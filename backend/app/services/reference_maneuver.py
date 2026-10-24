"""Trajectory-only maneuver experiment for a traceable standalone reference CDM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Literal

from app.services.cdm_ingestion import CdmInputs
from app.services.conjunction import (
    MANEUVER_POST_TCA_SEARCH_SECONDS,
    MANEUVER_SEARCH_SAMPLE_SECONDS,
    _add,
    _cross,
    _distance_from_sampled_state,
    _propagate_samples,
    _refine_sampled_minimum,
    _rk4,
    _scale,
    _unit,
)
from app.services.event_pc_inputs import evaluate_cdm_reference


Direction = Literal["radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"]


def assess_reference_maneuver(
    cdm: CdmInputs,
    *,
    event_id: str,
    maneuvering_object_id: str,
    burn_lead_seconds: float,
    direction: Direction,
    delta_v_m_s: float,
) -> dict:
    """Propagate one explicitly specified impulsive burn; never infer post-burn Pc."""
    ids = [item.object_designator for item in cdm.inputs]
    if len(ids) != 2 or len(set(ids)) != 2 or maneuvering_object_id not in ids:
        raise ValueError("REFERENCE_MANEUVER_OBJECT_ID_INVALID")
    if not math.isfinite(burn_lead_seconds) or not 60 <= burn_lead_seconds <= 1800:
        raise ValueError("REFERENCE_MANEUVER_LEAD_OUT_OF_RANGE")
    if not math.isfinite(delta_v_m_s) or not 0 < delta_v_m_s <= 0.1:
        raise ValueError("REFERENCE_MANEUVER_DELTA_V_OUT_OF_RANGE")
    if direction not in {"radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"}:
        raise ValueError("REFERENCE_MANEUVER_DIRECTION_INVALID")
    tca = datetime.fromisoformat(cdm.tca_utc.replace("Z", "+00:00"))
    if tca.tzinfo is None or tca.utcoffset() is None:
        raise ValueError("REFERENCE_MANEUVER_TCA_INVALID")
    tca = tca.astimezone(timezone.utc)
    objects = {
        item.object_designator: ((tuple(item.position_km), tuple(item.velocity_km_s)))
        for item in cdm.inputs
    }
    first_id, second_id = ids
    first_tca, second_tca = objects[first_id], objects[second_id]
    mu = 398600.4418
    step = MANEUVER_SEARCH_SAMPLE_SECONDS
    first_burn = _rk4(first_tca[0], first_tca[1], -burn_lead_seconds, step, mu)
    second_burn = _rk4(second_tca[0], second_tca[1], -burn_lead_seconds, step, mu)
    selected_burn = first_burn if maneuvering_object_id == first_id else second_burn
    radial = _unit(selected_burn[0])
    normal = _unit(_cross(selected_burn[0], selected_burn[1]))
    along = _unit(_cross(normal, radial))
    axis = direction.removesuffix("+").removesuffix("-")
    sign = 1.0 if direction.endswith("+") else -1.0
    basis = {"radial": radial, "along_track": along, "cross_track": normal}
    delta_v_km_s = _scale(basis[axis], sign * delta_v_m_s / 1000.0)
    changed_state = (selected_burn[0], _add(selected_burn[1], delta_v_km_s))
    candidate_first = changed_state if maneuvering_object_id == first_id else first_burn
    candidate_second = changed_state if maneuvering_object_id == second_id else second_burn

    search_end = burn_lead_seconds + MANEUVER_POST_TCA_SEARCH_SECONDS
    elapsed = sorted({0.0, float(burn_lead_seconds), float(search_end), *(
        float(index * step) for index in range(1, math.ceil(search_end / step)) if index * step < search_end
    )})
    baseline_first = _propagate_samples(first_burn, elapsed, step, mu)
    baseline_second = _propagate_samples(second_burn, elapsed, step, mu)
    candidate_first_samples = _propagate_samples(candidate_first, elapsed, step, mu)
    candidate_second_samples = _propagate_samples(candidate_second, elapsed, step, mu)

    def closest(primary, secondary):
        distances = [math.dist(a[0], b[0]) for a, b in zip(primary, secondary)]
        return _refine_sampled_minimum(
            elapsed,
            distances,
            lambda value: _distance_from_sampled_state(value, elapsed, primary, secondary, step, mu),
        )

    def state_at(primary_samples, secondary_samples, result):
        index = result["sample_index"]
        offset = result["elapsed_seconds"] - elapsed[index]
        primary = primary_samples[index] if abs(offset) < 1e-12 else _rk4(
            primary_samples[index][0], primary_samples[index][1], offset, step / 2, mu,
        )
        secondary = secondary_samples[index] if abs(offset) < 1e-12 else _rk4(
            secondary_samples[index][0], secondary_samples[index][1], offset, step / 2, mu,
        )
        relative_velocity = tuple(secondary[1][axis] - primary[1][axis] for axis in range(3))
        return math.sqrt(sum(component * component for component in relative_velocity))

    baseline_min = closest(baseline_first, baseline_second)
    candidate_min = closest(candidate_first_samples, candidate_second_samples)
    baseline_relative_speed = state_at(baseline_first, baseline_second, baseline_min)
    candidate_relative_speed = state_at(candidate_first_samples, candidate_second_samples, candidate_min)
    miss_change = candidate_min["distance_km"] - baseline_min["distance_km"]
    miss_change_percent = (
        100.0 * miss_change / baseline_min["distance_km"]
        if baseline_min["distance_km"] > 0 else None
    )

    def closest_utc(result):
        return (tca - timedelta(seconds=burn_lead_seconds) + timedelta(seconds=result["elapsed_seconds"])).isoformat()

    original_pc = evaluate_cdm_reference(cdm, assume_independent_covariances=True)["collision_probability"]
    pc_before = {
        "status": original_pc.status,
        "pc": original_pc.pc,
        "event_id": event_id,
        "epoch_utc": cdm.tca_utc,
        "source": "ORION calculation from the original reference CDM at its supplied TCA",
        "assumptions": original_pc.assumptions,
        "reason_codes": original_pc.reason_codes,
    }
    return {
        "event_id": event_id,
        "result_type": "reference_cdm_maneuver_assessment",
        "status": "available_with_warning",
        "trajectory_status": "trajectory_only_research_simulation",
        "source": "Bundled NASA CARA public reference CDM; source not authenticated by ORION",
        "source_input_sha256": cdm.input_sha256,
        "message_id": cdm.message_id,
        "reference_frame": cdm.inputs[0].covariance.frame,
        "state_units": {"position": "km", "velocity": "km/s"},
        "tca_utc": cdm.tca_utc,
        "covariance": {
            "status": "available",
            "frame": cdm.inputs[0].covariance.frame,
            "epoch_utc": cdm.inputs[0].covariance.epoch,
            "units": "km^2 position covariance at supplied TCA",
            "sources": [item.covariance.source for item in cdm.inputs],
            "cross_covariance": "not supplied; independent object covariance assumption explicitly used only for original reference Pc",
        },
        "hard_body_radius": {
            "value": cdm.hbr.value_km,
            "units": "km combined radius",
            "source_type": cdm.hbr.source_type,
            "description": cdm.hbr.description,
        },
        "source_reported_pc": cdm.source_pc,
        "source_reported_pc_method": cdm.source_pc_method,
        "objects": [{"id": item.object_designator, "name": item.object_name} for item in cdm.inputs],
        "maneuver": {
            "object_id": maneuvering_object_id,
            "burn_time_utc": (tca - timedelta(seconds=burn_lead_seconds)).isoformat(),
            "lead_before_reference_tca_seconds": burn_lead_seconds,
            "direction": direction,
            "direction_frame": "RTN at estimated burn epoch",
            "delta_v_m_s": delta_v_m_s,
            "delta_v_units": "m/s",
            "delta_v_inertial_km_s": list(delta_v_km_s),
        },
        "original_reference_geometry": {
            "tca_utc": cdm.tca_utc,
            "miss_distance_km": cdm.source_miss_distance_km,
            "source": "Values reported in the CDM; miss distance may be rounded",
        },
        "zero_burn_two_body_baseline": {
            "tca_utc": closest_utc(baseline_min),
            "miss_distance_km": baseline_min["distance_km"],
            "relative_velocity_km_s": baseline_relative_speed,
            "method": "Earth point-mass two-body RK4",
        },
        "candidate_two_body_geometry": {
            "tca_utc": closest_utc(candidate_min),
            "miss_distance_km": candidate_min["distance_km"],
            "relative_velocity_km_s": candidate_relative_speed,
            "change_from_zero_burn_baseline_km": miss_change,
            "change_from_zero_burn_baseline_percent": miss_change_percent,
            "percentage_change_status": "available" if miss_change_percent is not None else "unavailable_zero_baseline_miss_distance",
            "objective_status": "bounded_local_minimum_or_search_boundary",
        },
        "probability_before": pc_before,
        "probability_after": {
            "status": "unavailable",
            "pc": None,
            "reason_code": "POST_MANEUVER_COVARIANCE_PROPAGATION_UNAVAILABLE",
            "reason": "The CDM covariance is supplied at the original TCA. No validated covariance propagation through the burn to the candidate TCA is implemented.",
        },
        "probability_change": {
            "status": "unavailable",
            "value": None,
            "reason_code": "POST_MANEUVER_COVARIANCE_PROPAGATION_UNAVAILABLE",
        },
        "fuel": {"status": "unavailable", "reason_code": "MASS_AND_PROPULSION_MODEL_REQUIRED"},
        "assumptions": [
            "Original TCA states are backward-propagated to the requested burn epoch with a two-body point-mass model.",
            "The impulse is applied instantaneously in the selected object's RTN frame at that estimated burn epoch.",
            "Both objects are propagated with two-body point-mass RK4; search is bounded from burn epoch through 1800 s after original TCA.",
            "Original reference Pc uses the explicit independence assumption and is not a post-maneuver Pc estimate.",
        ],
        "limitations": [
            "Trajectory outputs are exploratory and do not establish a safe or effective maneuver.",
            "No J2, drag, third-body effects, state uncertainty, execution error, attitude, or control constraints are modeled.",
            "No post-maneuver covariance propagation is performed; Pc change is unavailable.",
            "Fuel use and maneuver feasibility are unavailable without spacecraft mass and propulsion data.",
        ],
    }
