"""Offline-trained surrogate ranking for the existing maneuver simulator.

The target is the existing simulator's candidate closest-approach miss distance,
not collision probability, safety, or a real maneuver outcome.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


MODEL_NAME = "ORION simulated two-body maneuver miss-distance ranker"
MODEL_VERSION = "1.0.0"
FEATURE_SCHEMA_VERSION = "1.0.0"
FEATURES = (
    "primary_x_tca_km", "primary_y_tca_km", "primary_z_tca_km",
    "primary_vx_tca_km_s", "primary_vy_tca_km_s", "primary_vz_tca_km_s",
    "relative_x_tca_km", "relative_y_tca_km", "relative_z_tca_km",
    "relative_vx_tca_km_s", "relative_vy_tca_km_s", "relative_vz_tca_km_s",
    "delta_v_m_s", "lead_time_seconds",
    "direction_radial_plus", "direction_radial_minus",
    "direction_along_track_plus", "direction_along_track_minus",
    "direction_cross_track_plus", "direction_cross_track_minus",
)
DIRECTION_INDEX = {
    "radial +": 0, "radial -": 1, "along-track +": 2,
    "along-track -": 3, "cross-track +": 4, "cross-track -": 5,
}
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "maneuver_miss_ranker.joblib"
METADATA_PATH = ARTIFACT_DIR / "maneuver_miss_ranker.metadata.json"


def feature_vector(event: Any, candidate: dict[str, Any], lead_seconds: float) -> list[float]:
    """Extract candidate inputs after strict event/state/candidate validation."""
    physics = getattr(event, "physics_result", None)
    if physics is None or getattr(physics, "event_id", None) != getattr(event, "id", None):
        raise ValueError("MANEUVER_EVENT_IDENTITY_MISMATCH")
    if getattr(physics, "status", None) != "valid" or getattr(physics, "tca_status", None) != "valid":
        raise ValueError("MANEUVER_PHYSICS_STATE_UNAVAILABLE")
    tca = getattr(physics, "tca", None)
    if getattr(tca, "status", None) != "available" or getattr(tca, "units", None) != "UTC":
        raise ValueError("MANEUVER_TCA_UNAVAILABLE")
    state_info = physics.state_information or {}
    if (state_info.get("source_frame") != "TEME" or state_info.get("target_frame") != "TEME"
            or state_info.get("position_units") != "km" or state_info.get("velocity_units") != "km/s"):
        raise ValueError("MANEUVER_STATE_FRAME_OR_UNITS_INVALID")
    primary = physics.primary_state_at_tca
    secondary = physics.secondary_state_at_tca
    expected = (getattr(getattr(event, "primary", None), "id", None), getattr(getattr(event, "secondary", None), "id", None))
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        raise ValueError("MANEUVER_TCA_STATE_MISSING")
    if (primary.get("object_id"), secondary.get("object_id")) != expected or expected[0] == expected[1]:
        raise ValueError("MANEUVER_STATE_OBJECT_IDENTITY_MISMATCH")
    if any(state.get("frame") != "TEME" or not _same_utc_instant(state.get("epoch"), tca.value) for state in (primary, secondary)):
        raise ValueError("MANEUVER_STATE_EPOCH_OR_FRAME_MISMATCH")
    try:
        pr = np.asarray(primary["position_km"], dtype=float)
        pv = np.asarray(primary["velocity_km_s"], dtype=float)
        sr = np.asarray(secondary["position_km"], dtype=float)
        sv = np.asarray(secondary["velocity_km_s"], dtype=float)
        dv = float(candidate["delta_v_m_s"])
        lead = float(lead_seconds)
        direction = candidate["direction"]
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        raise ValueError("MANEUVER_FEATURES_MALFORMED") from exc
    if any(x.shape != (3,) or not np.isfinite(x).all() for x in (pr, pv, sr, sv)):
        raise ValueError("MANEUVER_STATE_VECTOR_INVALID")
    if not math.isfinite(dv) or dv <= 0 or not math.isfinite(lead) or not 60 <= lead <= 1800:
        raise ValueError("MANEUVER_CANDIDATE_CONFIGURATION_INVALID")
    if direction not in DIRECTION_INDEX:
        raise ValueError("MANEUVER_DIRECTION_UNSUPPORTED")
    one_hot = [0.0] * len(DIRECTION_INDEX)
    one_hot[DIRECTION_INDEX[direction]] = 1.0
    row = [*pr.tolist(), *pv.tolist(), *(sr - pr).tolist(), *(sv - pv).tolist(), dv, lead, *one_hot]
    if len(row) != len(FEATURES) or not all(math.isfinite(x) for x in row):
        raise ValueError("MANEUVER_FEATURES_NON_FINITE")
    return row


def score_candidates(event: Any, candidates: list[dict[str, Any]], lead_seconds: float) -> dict[str, Any]:
    """Return predicted simulator miss distance for each nonzero candidate."""
    provenance = {"source_event_id": getattr(event, "id", None), "target": "existing two-body simulator candidate miss distance", "target_units": "km"}
    model, metadata, failure = _load_model()
    if failure:
        return _unavailable(failure, provenance)
    inputs: list[list[float]] = []
    indexes: list[int] = []
    try:
        for index, candidate in enumerate(candidates):
            if candidate.get("delta_v_m_s") == 0:
                continue
            inputs.append(feature_vector(event, candidate, lead_seconds))
            indexes.append(index)
        if not inputs:
            return _unavailable("NO_NONZERO_CANDIDATES", provenance, metadata)
        predictions = np.asarray(model["estimator"].predict(np.asarray(inputs, dtype=float)), dtype=float)
        if predictions.shape != (len(indexes),) or not np.isfinite(predictions).all() or (predictions < 0).any():
            return _unavailable("MANEUVER_MODEL_OUTPUT_INVALID", provenance, metadata)
        test_metrics = metadata.get("test_metrics") or {}
        baseline_metrics = metadata.get("baseline", {}).get("test_metrics") or {}
        return {
            "status": "research_only",
            "is_simulator_surrogate": True,
            "synthetic_training_labels": True,
            "ranking_used": False,
            "reason_code": "HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE",
            "model_name": metadata["model_name"],
            "model_version": metadata["model_version"],
            "score_name": "predicted two-body simulated closest-approach miss distance",
            "score_units": "km",
            "score_semantics": "Diagnostic estimate of the training simulator's miss-distance output only. It is not used to rank candidates because held-out selection performance did not outperform the minimum-delta-v baseline; it is not a collision probability, safety assessment, or verified improvement.",
            "feature_schema_version": metadata["feature_schema_version"],
            "artifact_sha256": metadata["artifact_sha256"],
            "provenance": provenance,
            "candidate_scores": {str(indexes[i]): float(predictions[i]) for i in range(len(indexes))},
            "evaluation_summary": {
                "held_out_scenario_count": test_metrics.get("scenario_count"),
                "held_out_candidate_count": test_metrics.get("candidate_count"),
                "mean_within_scenario_spearman": test_metrics.get("mean_within_scenario_spearman"),
                "top1_agreement_with_simulator_best": test_metrics.get("top1_agreement_with_simulator_best"),
                "model_mean_regret_km": test_metrics.get("mean_selected_simulator_miss_regret_vs_best_km"),
                "minimum_delta_v_baseline_mean_regret_km": baseline_metrics.get("mean_selected_simulator_miss_regret_vs_best_km"),
                "source": "held-out synthetic scenarios; labels generated by the same two-body simulator",
            },
            "limitations": metadata["limitations"],
        }
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return _unavailable(str(exc) or "MANEUVER_FEATURE_VALIDATION_FAILED", provenance, metadata)
    except Exception:
        return _unavailable("MANEUVER_MODEL_INFERENCE_FAILED", provenance, metadata)


def _unavailable(reason: str, provenance: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "is_simulator_surrogate": True,
        "synthetic_training_labels": True,
        "ranking_used": False,
        "reason_code": reason,
        "model_name": (metadata or {}).get("model_name", MODEL_NAME),
        "model_version": (metadata or {}).get("model_version"),
        "score_name": "predicted two-body simulated closest-approach miss distance",
        "score_units": "km",
        "score_semantics": "No model score is available; physics candidate evaluation remains separate.",
        "provenance": provenance,
        "candidate_scores": {},
    }


def _same_utc_instant(left: Any, right: Any) -> bool:
    try:
        parsed = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (left, right)]
        if any(value.tzinfo is None or value.utcoffset() is None for value in parsed):
            return False
        return parsed[0].astimezone(timezone.utc) == parsed[1].astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


@lru_cache(maxsize=1)
def _load_model():
    if not ARTIFACT_PATH.is_file() or not METADATA_PATH.is_file():
        return None, None, "MANEUVER_MODEL_ARTIFACT_UNAVAILABLE"
    try:
        import joblib
        import sklearn
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        digest = hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest()
        if digest != metadata.get("artifact_sha256"):
            return None, None, "MANEUVER_MODEL_ARTIFACT_HASH_MISMATCH"
        if sklearn.__version__ != metadata.get("scikit_learn_version"):
            return None, None, "MANEUVER_MODEL_RUNTIME_VERSION_MISMATCH"
        model = joblib.load(ARTIFACT_PATH)
        if model.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or model.get("feature_names") != list(FEATURES):
            return None, None, "MANEUVER_MODEL_FEATURE_SCHEMA_MISMATCH"
        if model.get("model_version") != metadata.get("model_version"):
            return None, None, "MANEUVER_MODEL_VERSION_MISMATCH"
        return model, metadata, None
    except ImportError:
        return None, None, "MANEUVER_MODEL_RUNTIME_UNAVAILABLE"
    except Exception:
        return None, None, "MANEUVER_MODEL_ARTIFACT_INVALID"

