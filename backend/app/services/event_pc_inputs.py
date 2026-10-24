"""Bind imported or explicitly assumed uncertainty inputs to one Stage 2A event."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.models import ConjunctionAssessmentEvent, PhysicsResult
from app.services.cdm_ingestion import CdmInputs
from app.services.collision_probability import (
    CovarianceInput,
    HardBodyRadiusInput,
    calculate_foster_2d,
)


def apply_cdm_inputs(
    event: ConjunctionAssessmentEvent,
    cdm: CdmInputs,
    *,
    assume_independent_covariances: bool,
) -> ConjunctionAssessmentEvent:
    physics = _require_supported_event(event)
    object_ids = {event.primary.id, event.secondary.id}
    imported_ids = {item.object_designator for item in cdm.inputs}
    if imported_ids != object_ids:
        raise ValueError("CDM_OBJECT_ID_MISMATCH")
    event_tca = _utc(physics.tca.value)
    if event_tca != _utc(cdm.tca_utc):
        raise ValueError("CDM_TCA_MISMATCH")
    frames = {item.covariance.frame for item in cdm.inputs}
    if len(frames) != 1:
        raise ValueError("CDM_FRAME_MISMATCH")
    event_frame = (physics.state_information or {}).get("source_frame")
    if frames != {event_frame}:
        raise ValueError("CDM_FRAME_MISMATCH")
    if any(_utc(item.covariance.epoch) != event_tca for item in cdm.inputs):
        raise ValueError("CDM_COVARIANCE_EPOCH_MISMATCH")
    by_id = {item.object_designator: item.covariance for item in cdm.inputs}
    result = _calculate(
        event,
        by_id[event.primary.id],
        by_id[event.secondary.id],
        cdm.hbr,
        assume_independent_covariances=assume_independent_covariances,
        state_override={item.object_designator: item for item in cdm.inputs},
    )
    return _with_source_probability(event, result, cdm)


def evaluate_cdm_reference(cdm: CdmInputs, *, assume_independent_covariances: bool) -> dict[str, Any]:
    """Calculate Pc directly from one CDM, keeping its event separate from TLE events."""
    first, second = cdm.inputs
    if first.covariance.frame != second.covariance.frame:
        raise ValueError("CDM_FRAME_MISMATCH")
    result = calculate_foster_2d(
        event_id=f"CDM-{cdm.input_sha256[:24]}",
        object_1_id=first.object_designator,
        object_2_id=second.object_designator,
        tca_utc=cdm.tca_utc,
        position_1_km=first.position_km,
        velocity_1_km_s=first.velocity_km_s,
        position_2_km=second.position_km,
        velocity_2_km_s=second.velocity_km_s,
        state_frame=first.covariance.frame,
        tca_status="valid",
        covariance_1=first.covariance,
        covariance_2=second.covariance,
        hbr=cdm.hbr,
        assume_independent_covariances=assume_independent_covariances,
    )
    warnings = [warning for warning in result.warnings if "TLE-only propagation" not in warning]
    warnings.append("CDM covariance realism and Foster 2D applicability were not independently validated by ORION.")
    warnings.append("ORION used the states supplied in this CDM at its declared TCA; no independent state propagation or TCA refinement was performed.")
    return {
        "event_id": result.event_id,
        "source_format": cdm.source_format,
        "object_1": {"id": first.object_designator, "name": first.object_name},
        "object_2": {"id": second.object_designator, "name": second.object_name},
        "object_hbr_inputs_km": {
            first.object_designator: first.object_hbr_km,
            second.object_designator: second.object_hbr_km,
        },
        "tca_utc": cdm.tca_utc,
        "reference_frame": first.covariance.frame,
        "input_sha256": cdm.input_sha256,
        "message_id": cdm.message_id,
        "originator_declared": cdm.originator,
        "source_authenticated": False,
        "source_reported_pc": cdm.source_pc,
        "source_reported_pc_method": cdm.source_pc_method,
        "source_reported_miss_distance_km": cdm.source_miss_distance_km,
        "collision_probability": result.model_copy(update={
            "warnings": warnings + [
                "This is a standalone historical/reference CDM result and is not attached to any live TLE screening event.",
                "The user-declared CDM originator and input provenance were not authenticated by ORION.",
            ]
        }),
    }


def apply_scenario_inputs(
    event: ConjunctionAssessmentEvent,
    *,
    covariance_primary_km2: list[list[float]],
    covariance_secondary_km2: list[list[float]],
    hbr_km: float,
    assumptions: str,
    assume_independent_covariances: bool,
) -> ConjunctionAssessmentEvent:
    physics = _require_supported_event(event)
    tca = _utc(physics.tca.value).isoformat()
    frame = (physics.state_information or {}).get("source_frame")
    if not frame:
        raise ValueError("EVENT_REFERENCE_FRAME_UNAVAILABLE")
    scenario_payload = {
        "event_id": event.id,
        "tca": tca,
        "frame": frame,
        "covariance_primary_km2": covariance_primary_km2,
        "covariance_secondary_km2": covariance_secondary_km2,
        "hbr_km": hbr_km,
        "assumptions": assumptions.strip(),
        "assume_independent_covariances": assume_independent_covariances,
    }
    digest = hashlib.sha256(json.dumps(scenario_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    scenario_source = "User-entered research scenario parameters; not observed covariance or object dimensions"
    covariance_1 = CovarianceInput(
        object_id=event.primary.id,
        frame=frame,
        epoch=tca,
        matrix=covariance_primary_km2,
        units={"position": "km^2"},
        source=scenario_source,
        source_type="synthetic",
        source_timestamp=now,
        input_hash=digest,
        is_synthetic=True,
    )
    covariance_2 = CovarianceInput(
        object_id=event.secondary.id,
        frame=frame,
        epoch=tca,
        matrix=covariance_secondary_km2,
        units={"position": "km^2"},
        source=scenario_source,
        source_type="synthetic",
        source_timestamp=now,
        input_hash=digest,
        is_synthetic=True,
    )
    hbr = HardBodyRadiusInput(
        value_km=hbr_km,
        source="synthetic",
        source_type="synthetic",
        description="Explicit user-entered combined HBR scenario; not measured object dimensions.",
        source_timestamp=now,
        input_hash=digest,
        is_synthetic=True,
    )
    result = _calculate(
        event,
        covariance_1,
        covariance_2,
        hbr,
        assume_independent_covariances=assume_independent_covariances,
    )
    scenario_assumptions = [
        "RESEARCH SCENARIO ONLY: covariance and HBR are user-entered assumptions, not observations.",
        f"Position covariance matrices are in km^2, in {frame}, bound to event TCA {tca}.",
        f"Combined HBR is user-assumed as {hbr_km} km.",
        "Independent object covariance is explicitly assumed." if assume_independent_covariances else "Object covariance independence was not asserted; Foster Pc remains unsupported.",
        assumptions.strip(),
    ]
    return event.model_copy(update={
        "scenario_collision_probability": result,
        "scenario_inputs": {
            "covariance_primary_km2": covariance_primary_km2,
            "covariance_secondary_km2": covariance_secondary_km2,
            "hbr_km": hbr_km,
            "frame": frame,
            "tca_utc": tca,
            "assume_independent_covariances": assume_independent_covariances,
            "declared_assumptions": assumptions.strip(),
            "sensitivity_status": "not_calculated_no_input_uncertainty_ranges",
        },
        "scenario_assumptions": scenario_assumptions,
    })


def _require_supported_event(event: ConjunctionAssessmentEvent) -> PhysicsResult:
    if event.result_kind != "physics_assessment":
        raise ValueError("PHYSICAL_EVENT_REQUIRED")
    physics = event.physics_result
    if physics.status != "valid" or physics.tca_status != "valid":
        raise ValueError("VALID_INTERIOR_TCA_REQUIRED")
    if physics.tca.status != "available" or not physics.tca.value:
        raise ValueError("EVENT_TCA_UNAVAILABLE")
    if not physics.primary_state_at_tca or not physics.secondary_state_at_tca:
        raise ValueError("EVENT_TCA_STATES_UNAVAILABLE")
    if physics.event_id != event.id:
        raise ValueError("PHYSICS_EVENT_IDENTITY_MISMATCH")
    expected_ids = (event.primary.id, event.secondary.id)
    if (
        expected_ids[0] == expected_ids[1]
        or (physics.object_primary_id, physics.object_secondary_id) != expected_ids
        or (event.obj_a.id, event.obj_b.id) != expected_ids
    ):
        raise ValueError("EVENT_OBJECT_IDENTITY_MISMATCH")
    if physics.tca.units != "UTC":
        raise ValueError("EVENT_TCA_UNITS_INVALID")
    event_tca = _utc(physics.tca.value)
    state_information = physics.state_information or {}
    frame = state_information.get("source_frame")
    if (
        not frame
        or state_information.get("target_frame", frame) != frame
        or state_information.get("position_units") != "km"
        or state_information.get("velocity_units") != "km/s"
    ):
        raise ValueError("EVENT_TCA_STATE_FRAME_OR_UNITS_INVALID")

    states = (physics.primary_state_at_tca, physics.secondary_state_at_tca)
    vectors: list[tuple[list[float], list[float]]] = []
    for state, expected_id in zip(states, expected_ids):
        if state.get("object_id") != expected_id:
            raise ValueError("EVENT_TCA_STATE_OBJECT_ID_MISMATCH")
        if state.get("frame") != frame:
            raise ValueError("EVENT_TCA_STATE_FRAME_MISMATCH")
        if _utc(state.get("epoch")) != event_tca:
            raise ValueError("EVENT_TCA_STATE_EPOCH_MISMATCH")
        position = state.get("position_km")
        velocity = state.get("velocity_km_s")
        if any(
            not isinstance(vector, (list, tuple))
            or len(vector) != 3
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector)
            for vector in (position, velocity)
        ):
            raise ValueError("EVENT_TCA_STATE_INVALID")
        vectors.append((position, velocity))

    separation = math.sqrt(sum((vectors[1][0][i] - vectors[0][0][i]) ** 2 for i in range(3)))
    miss = physics.miss_distance
    if miss.status != "available" or miss.units != "km":
        raise ValueError("EVENT_MISS_DISTANCE_UNAVAILABLE")
    if isinstance(miss.value, bool) or not isinstance(miss.value, (int, float)) or not math.isfinite(miss.value) or miss.value < 0:
        raise ValueError("EVENT_MISS_DISTANCE_INVALID")
    if abs(separation - miss.value) > 1e-5:
        raise ValueError("EVENT_MISS_DISTANCE_INCONSISTENT_WITH_TCA_STATES")
    return physics


def _calculate(
    event: ConjunctionAssessmentEvent,
    covariance_1: CovarianceInput,
    covariance_2: CovarianceInput,
    hbr: HardBodyRadiusInput,
    *,
    assume_independent_covariances: bool,
    state_override: dict[str, Any] | None = None,
):
    physics = event.physics_result
    primary_state = physics.primary_state_at_tca or {}
    secondary_state = physics.secondary_state_at_tca or {}
    state_frame = (physics.state_information or {}).get("source_frame")
    if state_override:
        primary_input = state_override[event.primary.id]
        secondary_input = state_override[event.secondary.id]
        primary_position = primary_input.position_km
        primary_velocity = primary_input.velocity_km_s
        secondary_position = secondary_input.position_km
        secondary_velocity = secondary_input.velocity_km_s
        state_frame = primary_input.covariance.frame
    else:
        primary_position = primary_state.get("position_km")
        primary_velocity = primary_state.get("velocity_km_s")
        secondary_position = secondary_state.get("position_km")
        secondary_velocity = secondary_state.get("velocity_km_s")
    result = calculate_foster_2d(
        event_id=event.id,
        object_1_id=event.primary.id,
        object_2_id=event.secondary.id,
        tca_utc=str(physics.tca.value),
        position_1_km=primary_position,
        velocity_1_km_s=primary_velocity,
        position_2_km=secondary_position,
        velocity_2_km_s=secondary_velocity,
        state_frame=state_frame,
        tca_status=physics.tca_status,
        covariance_1=covariance_1,
        covariance_2=covariance_2,
        hbr=hbr,
        assume_independent_covariances=assume_independent_covariances,
    )
    if covariance_1.source_type == "user_supplied" or covariance_2.source_type == "user_supplied":
        result = result.model_copy(update={
            "warnings": result.warnings + [
                "Imported CDM source label and originator are user-declared and were not authenticated by ORION.",
                "Pc mean encounter state and covariance are from the imported CDM; the Stage 2A TLE state remains a separate assessment.",
            ],
        })
    return result


def _with_source_probability(event: ConjunctionAssessmentEvent, result: Any, cdm: CdmInputs) -> ConjunctionAssessmentEvent:
    source_probability = cdm.source_pc
    result = result.model_copy(update={
        "source_reported_pc": source_probability,
        "source_reported_pc_method": cdm.source_pc_method,
        "source_reported_event_id": event.id if source_probability is not None else None,
        "source_reported_pc_provenance": ({
            "source_type": "user_supplied",
            "source": cdm.inputs[0].covariance.source,
            "input_sha256": cdm.input_sha256,
            "authenticated": False,
        } if source_probability is not None else None),
    })
    return event.model_copy(update={"collision_probability": result})


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("EVENT_TCA_UNAVAILABLE")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("EVENT_TCA_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("EVENT_TCA_INVALID")
    return parsed.astimezone(timezone.utc)
