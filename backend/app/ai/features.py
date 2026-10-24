"""ESA-compatible feature schema and Stage 2A TEME-to-instantaneous-RTN adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np

from app.ai import FEATURE_SCHEMA_VERSION
from app.ai.eligibility import LIVE_TIME_TO_TCA_INVALID_REASON
from app.models import PhysicsResult


FEATURE_UNITS = {
    "time_to_tca_days": "day",
    "miss_distance_m": "m",
    "relative_speed_m_s": "m/s",
    "relative_position_r_m": "m",
    "relative_position_t_m": "m",
    "relative_position_n_m": "m",
    "relative_velocity_r_m_s": "m/s",
    "relative_velocity_t_m_s": "m/s",
    "relative_velocity_n_m_s": "m/s",
}
FEATURE_NAMES = tuple(FEATURE_UNITS)


@dataclass(frozen=True)
class FeatureBuild:
    values: dict[str, float] | None
    availability: dict[str, bool]
    reason_code: str | None = None
    frame: str | None = None


def extract_live_features(physics: PhysicsResult) -> FeatureBuild:
    """Build the nine learned features from an existing Stage 2A result.

    Position/velocity are projected from the Stage 2A TEME components onto the
    primary object's instantaneous RTN basis at TCA. This function never calls
    a propagator and never substitutes catalog or heuristic values.
    """
    availability = {name: False for name in FEATURE_NAMES}
    if physics.status not in {"valid", "boundary"} or physics.tca_status not in {"valid", "boundary"}:
        return FeatureBuild(None, availability, "PHYSICS_ENCOUNTER_UNAVAILABLE")

    if not isinstance(physics.state_information, dict) or physics.state_information.get("source_frame") != "TEME":
        return FeatureBuild(None, availability, "PHYSICS_FRAME_UNAVAILABLE")
    primary_state = physics.primary_state_at_tca
    if not isinstance(primary_state, dict) or primary_state.get("frame") != "TEME":
        return FeatureBuild(None, availability, "PRIMARY_TCA_STATE_UNAVAILABLE")

    tca = _parse_utc(physics.tca.value if physics.tca.status == "available" else None)
    horizon_start = _parse_utc(physics.screening_horizon_start)
    state_epoch = _parse_utc(primary_state.get("epoch"))
    if tca is None or horizon_start is None or state_epoch is None or tca != state_epoch:
        return FeatureBuild(None, availability, LIVE_TIME_TO_TCA_INVALID_REASON)
    time_to_tca_days = (tca - horizon_start).total_seconds() / 86400.0
    if not math.isfinite(time_to_tca_days) or time_to_tca_days < 0.0:
        return FeatureBuild(None, availability, LIVE_TIME_TO_TCA_INVALID_REASON)

    primary_position = _vector(primary_state.get("position_km"))
    primary_velocity = _vector(primary_state.get("velocity_km_s"))
    relative_position = _field_vector(physics.relative_position_at_tca, "km")
    relative_velocity = _field_vector(physics.relative_velocity_at_tca, "km/s")
    miss_distance = _field_scalar(physics.miss_distance, "km")
    relative_speed = _field_scalar(physics.relative_speed_at_tca, "km/s")
    availability.update({
        "time_to_tca_days": True,
        "miss_distance_m": miss_distance is not None,
        "relative_speed_m_s": relative_speed is not None,
        "relative_position_r_m": relative_position is not None,
        "relative_position_t_m": relative_position is not None,
        "relative_position_n_m": relative_position is not None,
        "relative_velocity_r_m_s": relative_velocity is not None,
        "relative_velocity_t_m_s": relative_velocity is not None,
        "relative_velocity_n_m_s": relative_velocity is not None,
    })
    if any(value is None for value in (primary_position, primary_velocity, relative_position, relative_velocity, miss_distance, relative_speed)):
        return FeatureBuild(None, availability, "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE", "TEME")

    r = np.asarray(primary_position, dtype=float)
    v = np.asarray(primary_velocity, dtype=float)
    rel_r = np.asarray(relative_position, dtype=float)
    rel_v = np.asarray(relative_velocity, dtype=float)
    r_norm = float(np.linalg.norm(r))
    v_norm = float(np.linalg.norm(v))
    h = np.cross(r, v)
    h_norm = float(np.linalg.norm(h))
    if not all(math.isfinite(value) for value in (r_norm, v_norm, h_norm)) or r_norm <= 0.0 or v_norm <= 0.0:
        return FeatureBuild(None, availability, "DEGENERATE_RTN_BASIS", "TEME")
    if h_norm <= 1e-12 * r_norm * v_norm:
        return FeatureBuild(None, availability, "DEGENERATE_RTN_BASIS", "TEME")

    r_hat = r / r_norm
    n_hat = h / h_norm
    t_hat = np.cross(n_hat, r_hat)
    t_norm = float(np.linalg.norm(t_hat))
    if not math.isfinite(t_norm) or t_norm <= 1e-12:
        return FeatureBuild(None, availability, "DEGENERATE_RTN_BASIS", "TEME")
    t_hat /= t_norm

    expected_miss = float(miss_distance)
    projected_miss = float(np.linalg.norm(rel_r))
    expected_speed = float(relative_speed)
    projected_speed = float(np.linalg.norm(rel_v))
    if (
        abs(projected_miss - expected_miss) > max(1e-8, expected_miss * 1e-8)
        or abs(projected_speed - expected_speed) > max(1e-9, expected_speed * 1e-8)
    ):
        return FeatureBuild(None, availability, "INCONSISTENT_PHYSICS_STATE", "TEME")

    position_rtn_m = 1000.0 * np.array([np.dot(rel_r, axis) for axis in (r_hat, t_hat, n_hat)])
    velocity_rtn_m_s = 1000.0 * np.array([np.dot(rel_v, axis) for axis in (r_hat, t_hat, n_hat)])
    values = {
        "time_to_tca_days": float(time_to_tca_days),
        "miss_distance_m": expected_miss * 1000.0,
        "relative_speed_m_s": expected_speed * 1000.0,
        "relative_position_r_m": float(position_rtn_m[0]),
        "relative_position_t_m": float(position_rtn_m[1]),
        "relative_position_n_m": float(position_rtn_m[2]),
        "relative_velocity_r_m_s": float(velocity_rtn_m_s[0]),
        "relative_velocity_t_m_s": float(velocity_rtn_m_s[1]),
        "relative_velocity_n_m_s": float(velocity_rtn_m_s[2]),
    }
    if set(values) != set(FEATURE_NAMES) or not all(math.isfinite(value) for value in values.values()):
        return FeatureBuild(None, availability, "NON_FINITE_PHYSICS_FEATURE", "TEME")
    return FeatureBuild(values, {name: True for name in FEATURE_NAMES}, frame="instantaneous primary RTN at TCA")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _vector(value: Any) -> tuple[float, float, float] | None:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if array.shape != (3,) or not np.isfinite(array).all():
        return None
    return tuple(float(component) for component in array)


def _field_scalar(field: Any, expected_units: str) -> float | None:
    if getattr(field, "status", None) != "available" or getattr(field, "units", None) != expected_units:
        return None
    try:
        value = float(field.value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0.0 else None


def _field_vector(field: Any, expected_units: str) -> tuple[float, float, float] | None:
    if getattr(field, "status", None) != "available" or getattr(field, "units", None) != expected_units:
        return None
    return _vector(field.value)
