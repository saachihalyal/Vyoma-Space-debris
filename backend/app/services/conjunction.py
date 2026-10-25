from __future__ import annotations

import hashlib
import math
import os
from decimal import Decimal, InvalidOperation
from decimal import localcontext
from datetime import datetime, timedelta, timezone
from typing import Any

from app.ai import DATASET_NAME, MODEL_NAME, MODEL_VERSION
from app.ai.maneuver_ranker import MODEL_NAME as MANEUVER_RANKER_NAME, MODEL_VERSION as MANEUVER_RANKER_VERSION, score_candidates
from app.models import (
    ComparisonResult,
    ConjunctionAssessmentEvent,
    ObjectSummary,
    PhysicsResult,
    Provenance,
    ReviewPriority,
    RiskCell,
    ScientificField,
    ScreeningProxyEvent,
    SpaceObject,
)
from app.services.risk import derived_provenance
from app.services.object_classification import pair_type_for
from app.services.automatic_research_pc import assess_automatic_research_pc, maneuver_baseline_covariances


SCREENING_METHOD = "same-shell catalog-pair heuristic screening proxy"
SCREENING_METHOD_VERSION = "1"
MANEUVER_POST_TCA_SEARCH_SECONDS = 1800.0
MANEUVER_SEARCH_SAMPLE_SECONDS = 5.0
MANEUVER_SEARCH_REFINEMENT_TOLERANCE_SECONDS = 0.01
MANEUVER_SEARCH_MAX_REFINEMENTS = 32
MANEUVER_BASELINE_MISS_TOLERANCE_KM = 0.1
MANEUVER_BASELINE_TCA_TOLERANCE_SECONDS = 5.0


def build_screening_proxies(
    objects: list[SpaceObject],
    risk_cells: list[RiskCell],
    *,
    limit: int = 80,
    horizon_hours: int = 48,
) -> list[ScreeningProxyEvent]:
    """Build heuristic candidate pairs only; this function does not assess conjunction geometry."""
    del horizon_hours  # Retained in the callable signature for API compatibility; no TCA is estimated.
    valid_objects = sorted(
        (obj for obj in objects if obj.provenance.validity_status == "valid"),
        key=lambda item: (item.id, item.provenance.input_hash or ""),
    )
    by_band: dict[str, list[SpaceObject]] = {}
    for obj in valid_objects:
        by_band.setdefault(obj.band, []).append(obj)

    candidates: dict[str, ScreeningProxyEvent] = {}
    used_pairs: set[tuple[str, str]] = set()
    candidate_cells = sorted(risk_cells, key=lambda cell: cell.heuristic_risk_score, reverse=True)[:40]
    for cell in candidate_cells:
        members = [
            obj
            for obj in by_band.get(cell.band, [])
            if abs(obj.altitude_km - cell.altitude_km) <= 650
            and abs(obj.inclination_deg - cell.inclination_deg) <= 18
        ]
        if len(members) < 2:
            members = sorted(
                by_band.get(cell.band, []),
                key=lambda item: (-item.heuristic_forecast_score, item.id),
            )[:8]
        members = sorted(
            members,
            key=lambda item: (
                abs(item.altitude_km - cell.altitude_km),
                abs(item.inclination_deg - cell.inclination_deg),
                -item.heuristic_risk_score,
                item.id,
                item.provenance.input_hash or "",
            ),
        )
        for offset in range(0, max(0, len(members) - 1), 2):
            a, b = members[offset], members[offset + 1]
            if _same_nonempty_catalog_id(a, b):
                continue
            pair_key = tuple(sorted((a.id, b.id)))
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            event = _event_from_pair(a, b, cell)
            candidates[event.id] = event

    # Preserve the existing same-band candidate-ranking fallback, but label it as
    # a screening proxy and carry no fabricated encounter state or Pc fields.
    if len(candidates) < min(limit, 24):
        ranked = sorted(valid_objects, key=lambda item: (item.band, -item.heuristic_forecast_score, item.altitude_km, item.id, item.provenance.input_hash or ""))
        for index in range(len(ranked) - 1):
            if len(candidates) >= min(limit, 40):
                break
            a, b = ranked[index], ranked[index + 1]
            if a.band != b.band:
                continue
            if _same_nonempty_catalog_id(a, b):
                continue
            pair_key = tuple(sorted((a.id, b.id)))
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            event = _event_from_pair(a, b, _cell_from_objects(a, b, index))
            candidates[event.id] = event

    events = sorted(candidates.values(), key=lambda item: (-item.risk_score, item.id))[:limit]
    _assign_relative_proxy_priority(events)
    return sorted(events, key=lambda item: (-item.priority_score, item.id))


def _same_nonempty_catalog_id(a: SpaceObject, b: SpaceObject) -> bool:
    """Reject self-pairs while retaining distinct records for deterministic ranking."""
    a_catalog_id = (a.provenance.catalog_id or "").strip() or (a.id or "").strip()
    b_catalog_id = (b.provenance.catalog_id or "").strip() or (b.id or "").strip()
    return bool(a_catalog_id and b_catalog_id and a_catalog_id == b_catalog_id)


def build_conjunctions(
    objects: list[SpaceObject],
    risk_cells: list[RiskCell],
    *,
    limit: int = 80,
    horizon_hours: int = 48,
) -> list[ScreeningProxyEvent]:
    """Deprecated compatibility alias; returns screening proxies only.

    The physical ``/api/conjunctions`` path is implemented by the independent
    trajectory-screening service and does not call this heuristic builder.
    """
    return build_screening_proxies(objects, risk_cells, limit=limit, horizon_hours=horizon_hours)


def build_smart_filter(events: list[ScreeningProxyEvent], total_objects: int) -> dict[str, Any]:
    by_class: dict[str, int] = {}
    for event in events:
        by_class[event.risk_level] = by_class.get(event.risk_level, 0) + 1

    retained = [event for event in events if event.risk_level in {"Medium", "High", "Critical"}]
    retained_ids = {event.id for event in retained}
    item_decisions = [
        {
            "event_id": event.id,
            "decision": "retain" if event.id in retained_ids else "exclude",
            "rule_ids": ["PROXY_RELATIVE_BAND_REVIEW"] if event.id in retained_ids else ["PROXY_RELATIVE_BAND_EXCLUSION"],
            "source": "HEURISTIC",
            "reason": (
                f"Relative proxy band {event.risk_level} is on the review list; bands are batch-relative, not physical severity."
                if event.id in retained_ids
                else f"Relative proxy band {event.risk_level} is outside the review list; this does not classify a physical conjunction as safe."
            ),
        }
        for event in events
    ]
    total = len(events)
    mean_risk_score = sum(event.risk_score for event in events) / total if total else None
    highest = events[0] if events else None
    return {
        "result_type": "heuristic_filter",
        "status": "available",
        "model_status": "not_applicable_to_proxy_events",
        "model_reason": "ESA inference requires complete event-level Stage 2A physics features; proxy pairs do not contain them.",
        "ml_supported_event_count": 0,
        "physics_only_event_count": 0,
        "heuristic_only_proxy_count": total,
        "unavailable_ml_prediction_count": 0,
        "raw_events": total,
        "objects_analyzed": total_objects,
        "after_filter": len(retained),
        "objects_removed": max(0, total - len(retained)),
        "item_decisions": item_decisions,
        "evaluation": {
            "candidate_count_before": total,
            "candidate_count_after": len(retained),
            "reduction_pct": None,
            "reduction_status": "not_measured",
            "retained_count": len(retained),
            "excluded_count": total - len(retained),
            "inconclusive_count": 0,
            "false_negative_count": None,
            "false_negative_status": "not_measured",
            "reference_labels": "No labeled proxy-pair safety subset is available.",
        },
        "rule_catalog": [
            {"rule_id": "PROXY_RELATIVE_BAND_REVIEW", "source": "HEURISTIC", "decision": "retain", "description": "Retain Critical, High, and Medium relative proxy bands for review."},
            {"rule_id": "PROXY_RELATIVE_BAND_EXCLUSION", "source": "HEURISTIC", "decision": "exclude", "description": "Exclude Low and Safe relative proxy bands from this proxy review list only; these are not physical safety labels."},
            {"rule_id": "CATALOG_VALIDITY_REQUIRED", "source": "HEURISTIC", "decision": "exclude", "description": "Proxy generation only accepts objects whose provenance validity status is valid."},
            {"rule_id": "RISK_CELL_TOP_40", "source": "HEURISTIC", "decision": "deprioritize", "description": "Proxy generation considers at most the 40 highest heuristic risk cells."},
            {"rule_id": "SHELL_ALTITUDE_WITHIN_650_KM", "source": "HEURISTIC", "decision": "deprioritize", "description": "Within a cell, candidate objects are limited to 650 km altitude difference."},
            {"rule_id": "SHELL_INCLINATION_WITHIN_18_DEG", "source": "HEURISTIC", "decision": "deprioritize", "description": "Within a cell, candidate objects are limited to 18 degrees inclination difference."},
            {"rule_id": "CELL_FALLBACK_TOP_8_FORECAST", "source": "HEURISTIC", "decision": "deprioritize", "description": "When fewer than two cell members remain, use up to eight same-band objects ranked by forecast heuristic."},
            {"rule_id": "ADJACENT_RANKED_PAIRING", "source": "HEURISTIC", "decision": "deprioritize", "description": "Sorted candidate objects are paired in adjacent positions."},
            {"rule_id": "SAME_CATALOG_ID_PAIR_REJECTION", "source": "HEURISTIC", "decision": "exclude", "description": "Reject pairs with identical nonempty catalog IDs."},
            {"rule_id": "DUPLICATE_PAIR_REJECTION", "source": "HEURISTIC", "decision": "exclude", "description": "Reject pairs already emitted from another cell or fallback pass."},
            {"rule_id": "SAME_BAND_FALLBACK_PAIR_SEARCH", "source": "HEURISTIC", "decision": "deprioritize", "description": "If fewer than 24 or the requested limit proxy candidates exist, search adjacent forecast-ranked same-band records."},
            {"rule_id": "PROXY_BATCH_LIMIT", "source": "HEURISTIC", "decision": "deprioritize", "description": "Cap the generated proxy review candidates at the requested limit."},
            {"rule_id": "ESA_LIVE_INFERENCE_NOT_A_FILTER", "source": "AI", "decision": "inconclusive", "description": "ESA inference is withheld when live feature semantics are unverified and is never used to remove a candidate."},
        ],
        "reduction_pct": None,
        "reduction_status": "not_measured",
        "reduction_reason": "No validated workload-reduction benchmark exists; these counts describe heuristic proxy pairs only.",
        "mean_heuristic_risk_score": round(mean_risk_score, 4) if mean_risk_score is not None else None,
        "by_class": by_class,
        "highest_priority_event": highest.model_dump(mode="json") if highest else None,
        "pipeline_stages": [
            {"name": "Catalog records", "count": total_objects, "kept_pct": 100 if total_objects else None},
            {"name": "Heuristic shell features", "count": total, "kept_pct": round(total / total_objects * 100, 1) if total_objects else None},
            {"name": "Candidate-pair screening proxy", "count": total, "kept_pct": 100 if total else None},
            {"name": "Heuristic triage", "count": total, "kept_pct": 100 if total else None},
            {"name": "Heuristic proxy review list", "count": len(retained), "kept_pct": None},
        ],
        "briefing": _mission_briefing(events, total_objects, retained),
        "provenance": {
            "source_type": "derived",
            "method": "deterministic heuristic threshold filter",
            "method_version": "1",
        },
    }


def optimize_maneuver(
    event: ScreeningProxyEvent | ConjunctionAssessmentEvent | dict[str, Any],
    *, lead_seconds: float = 300.0,
    burn_magnitudes_m_s: tuple[float, ...] = (0.01, 0.05),
    max_delta_v_m_s: float | None = None,
    initial_mass_kg: float | None = None,
    specific_impulse_s: float | None = None,
    refine_candidates: bool = True,
    rtn_direction: str = "all",
    covariance_scale: float = 1.0,
) -> dict[str, Any]:
    """Bounded exploratory two-body search and local delta-v refinement; not flight dynamics software."""
    event_id = event.id if isinstance(event, (ScreeningProxyEvent, ConjunctionAssessmentEvent)) else str(event.get("id", ""))
    is_physical = isinstance(event, ConjunctionAssessmentEvent) or (
        isinstance(event, dict) and event.get("result_kind") == "physics_assessment"
    )
    base = {
        "event_id": event_id,
        "result_type": "maneuver_assessment",
        "status": "unavailable",
        "reason_code": "MANEUVER_DYNAMICS_AND_CONTROL_MODEL_UNAVAILABLE" if is_physical else "PHYSICS_CONJUNCTION_ASSESSMENT_UNAVAILABLE",
        "reason": "No maneuver candidate was evaluated. This research simulation is not a validated burn-control or operational collision-avoidance system.",
        "method": None,
        "method_version": None,
        "physics_candidate_status": "not_evaluated",
        "ml_result": {"status": "unavailable", "reason_code": "MANEUVER_MODEL_NOT_EVALUATED", "model_name": None, "candidate_scores": {}},
        "comparison_result": {"status": "not_applicable", "reason_code": "NO_MANEUVER_CANDIDATES_TO_COMPARE"},
        "delta_v_m_s": None,
        "burn_direction": None,
        "burn_time_utc": None,
        "fuel_cost_kg": None,
        "fuel_status": "unavailable",
        "fuel_reason_code": "MASS_AND_PROPULSION_MODEL_REQUIRED",
        "fuel_reason": "Spacecraft mass and a documented propulsion model are unavailable.",
        "risk_reduction_pct": None,
        "probability_before": None,
        "probability_after": None,
        "probability_status": "unavailable",
        "probability_reason_code": "REAL_TLE_PRIOR_INPUTS_AND_VALID_CANDIDATE_TCA_REQUIRED",
        "probability_reason": "Comparable before/after research Pc requires valid candidate states and TLE epochs for the configured research covariance/HBR estimator.",
        "miss_distance_before_m": None,
        "miss_distance_after_m": None,
        "trajectory": None,
        "limitations": [
            "Before/after research Pc uses the same configured TLE-age covariance/HBR policy and scale; covariance is assigned at each calculated TCA rather than dynamically propagated, and burn-execution error is set to zero.",
            "When mass or specific impulse is omitted, fuel uses configurable default spacecraft assumptions and is labeled as an estimate.",
            "No operational recommendation or risk reduction is calculated.",
        ],
        "assessment_reason_codes": [],
    }
    physics_result = event.physics_result if isinstance(event, ConjunctionAssessmentEvent) else None
    reference_tca = physics_result.tca if physics_result else None
    reference_miss = physics_result.miss_distance if physics_result else None
    base.update({
        "stage2a_reference": {
            "event_id": event_id,
            "status": physics_result.status if physics_result else "unavailable",
            "source": "Stage 2A trajectory assessment",
            "propagator": (physics_result.provenance.propagator if physics_result and physics_result.provenance else None) or "SGP4",
            "method": physics_result.provenance.method if physics_result and physics_result.provenance else None,
            "method_version": physics_result.provenance.method_version if physics_result and physics_result.provenance else None,
            "tca": reference_tca.model_dump(mode="json") if reference_tca else {"status": "unavailable", "value": None, "reason_code": "STAGE2A_TCA_NOT_AVAILABLE"},
            "miss_distance": reference_miss.model_dump(mode="json") if reference_miss else {"status": "unavailable", "value": None, "reason_code": "STAGE2A_MISS_DISTANCE_NOT_AVAILABLE"},
            "notes": "Original Stage 2A SGP4 event metrics are the reference; they are not replaced by the two-body simulation.",
        },
        "zero_burn_baseline": {
            "event_id": event_id, "status": "not_evaluated", "method": "Earth two-body point-mass RK4",
            "propagator": "RK4", "reason_code": "ZERO_BURN_BASELINE_NOT_EVALUATED",
            "tca_utc": None, "miss_distance_km": None,
        },
        "physics_candidates": {
            "event_id": event_id, "status": "not_evaluated", "method": "Earth two-body point-mass RK4",
            "propagator": "RK4", "reason_code": "PHYSICS_CANDIDATES_NOT_EVALUATED", "candidates": [],
        },
        "surrogate_rank": {
            "event_id": event_id, "status": "unavailable", "model_name": MANEUVER_RANKER_NAME,
            "model_version": MANEUVER_RANKER_VERSION, "is_simulator_surrogate": True,
            "synthetic_training_labels": False, "physics_generated_training_labels": True, "ranking_used": False,
            "reason_code": "MANEUVER_MODEL_NOT_EVALUATED", "candidate_scores": {},
        },
    })
    if not is_physical or not isinstance(event, ConjunctionAssessmentEvent):
        base["ml_result"] = {"status": "not_applicable", "reason_code": "PHYSICAL_EVENT_REQUIRED", "model_name": None, "candidate_scores": {}}
        return base
    physics = event.physics_result
    pstate, sstate = physics.primary_state_at_tca, physics.secondary_state_at_tca
    if physics.event_id != event.id:
        base["reason_code"] = "PHYSICS_EVENT_IDENTITY_MISMATCH"
        base["reason"] = "PhysicsResult must identify the same event passed to the maneuver solver."
        return base
    if physics.status == "invalid":
        codes = list(physics.reason_codes or [])
        base["assessment_reason_codes"] = codes
        base["reason_code"] = codes[0] if codes else "PHYSICS_ASSESSMENT_INVALID"
        base["reason"] = "The selected physical event failed Stage 2A validation: " + (", ".join(codes) if codes else "no specific reason code was supplied") + ". No maneuver candidates were evaluated."
        return base
    if physics.status != "valid" or physics.tca_status != "valid" or not pstate or not sstate:
        missing = []
        if physics.tca_status != "valid" or not physics.tca or physics.tca.status != "available": missing.append("valid_tca")
        if not pstate: missing.append("primary_state_at_tca")
        if not sstate: missing.append("secondary_state_at_tca")
        base["assessment_reason_codes"] = missing
        base["reason_code"] = "VALID_INTERIOR_TCA_STATES_REQUIRED"
        base["reason"] = "Research simulation requires a valid interior TCA and both propagated state vectors. Missing or unavailable inputs: " + (", ".join(missing) or "valid_interior_tca") + ". Horizon-boundary minima are not eligible."
        return base
    expected_ids = (event.primary.id, event.secondary.id)
    physics_ids = (physics.object_primary_id, physics.object_secondary_id)
    state_ids = (pstate.get("object_id"), sstate.get("object_id"))
    event_pair_ids = (event.obj_a.id, event.obj_b.id)
    if (
        expected_ids[0] == expected_ids[1]
        or physics_ids != expected_ids
        or state_ids != expected_ids
        or event_pair_ids != expected_ids
    ):
        base["reason_code"] = "DISTINCT_OBJECT_STATE_IDENTITY_REQUIRED"
        base["reason"] = "PhysicsResult, TCA states, and event object references must match the same two distinct object IDs in primary/secondary order."
        return base
    state_information = physics.state_information or {}
    if (
        state_information.get("source_frame") != "TEME"
        or state_information.get("target_frame") != "TEME"
        or state_information.get("position_units") != "km"
        or state_information.get("velocity_units") != "km/s"
    ):
        base["reason_code"] = "TCA_STATE_FRAME_OR_UNITS_UNAVAILABLE"
        base["reason"] = "TCA state metadata must identify TEME position in km and velocity in km/s."
        return base
    epoch = physics.tca.value if physics.tca.status == "available" and physics.tca.units == "UTC" else None
    try:
        if not isinstance(epoch, str) or not epoch:
            raise ValueError
        tca_datetime = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
        if tca_datetime.tzinfo is None or tca_datetime.utcoffset() is None:
            raise ValueError
        state_datetimes = []
        for state in (pstate, sstate):
            state_epoch = state.get("epoch")
            if not isinstance(state_epoch, str) or not state_epoch:
                raise ValueError
            parsed_state_epoch = datetime.fromisoformat(state_epoch.replace("Z", "+00:00"))
            if parsed_state_epoch.tzinfo is None or parsed_state_epoch.utcoffset() is None:
                raise ValueError
            state_datetimes.append(parsed_state_epoch)
        epochs_match = all(value.astimezone(timezone.utc) == tca_datetime.astimezone(timezone.utc) for value in state_datetimes)
    except (TypeError, ValueError, OverflowError):
        epochs_match = False
        tca_datetime = None
    if not epochs_match or pstate.get("frame") != "TEME" or sstate.get("frame") != "TEME":
        base["reason_code"] = "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"
        base["reason"] = "TCA must be an available UTC timestamp, and both state epochs must identify that instant in the TEME frame."
        return base
    reference_miss_distance = None
    comparison_input_reason = None
    try:
        r1, v1 = _validated_state(pstate); r2, v2 = _validated_state(sstate)
        if math.dist(r1, r2) < 1e-8 and math.dist(v1, v2) < 1e-10:
            raise ValueError("coincident_duplicate_states")
        reference_state_separation = math.dist(r1, r2)
        miss_field = physics.miss_distance
        if miss_field.status != "available" or miss_field.units != "km":
            raise ValueError("REFERENCE_MISS_DISTANCE_STATUS_OR_UNITS_UNAVAILABLE")
        if isinstance(miss_field.value, bool) or not isinstance(miss_field.value, (int, float)):
            raise ValueError("REFERENCE_MISS_DISTANCE_INVALID")
        reference_miss_distance = float(miss_field.value)
        if not math.isfinite(reference_miss_distance) or reference_miss_distance < 0:
            raise ValueError("REFERENCE_MISS_DISTANCE_INVALID")
        if abs(reference_state_separation - reference_miss_distance) > 1e-5:
            raise ValueError("REFERENCE_MISS_DISTANCE_INCONSISTENT_WITH_TCA_STATES")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        base["reason_code"] = "invalid_or_non_finite_cartesian_state" if isinstance(exc, KeyError) else (str(exc) or "INVALID_TCA_STATE")
        base["reason"] = "Required TCA state or reference miss-distance inputs are missing, invalid, or inconsistent; no maneuver candidates were evaluated."
        return base

    try:
        magnitudes = tuple(burn_magnitudes_m_s)
    except TypeError:
        magnitudes = ()
    if max_delta_v_m_s is not None:
        if (isinstance(max_delta_v_m_s, bool) or not isinstance(max_delta_v_m_s, (int, float))
                or not math.isfinite(max_delta_v_m_s) or not 0 < max_delta_v_m_s <= 0.1):
            magnitudes = ()
        else:
            magnitudes = tuple(max_delta_v_m_s * fraction for fraction in (0.25, 0.5, 0.75, 1.0))
    fuel_parameters_valid = (
        initial_mass_kg is not None and specific_impulse_s is not None
        and not isinstance(initial_mass_kg, bool) and not isinstance(specific_impulse_s, bool)
        and isinstance(initial_mass_kg, (int, float)) and isinstance(specific_impulse_s, (int, float))
        and math.isfinite(initial_mass_kg) and math.isfinite(specific_impulse_s)
        and initial_mass_kg > 0 and 0 < specific_impulse_s <= 2000
    )
    if (initial_mass_kg is None) != (specific_impulse_s is None):
        base["reason_code"] = "MASS_AND_SPECIFIC_IMPULSE_MUST_BE_PAIRED"
        base["reason"] = "Supply both spacecraft mass and specific impulse, or omit both to use documented defaults."
        return base
    fuel_parameters_defaulted = initial_mass_kg is None
    if fuel_parameters_defaulted:
        try:
            initial_mass_kg = float(os.getenv("ORION_DEFAULT_SPACECRAFT_MASS_KG", "500"))
            specific_impulse_s = float(os.getenv("ORION_DEFAULT_SPECIFIC_IMPULSE_S", "220"))
        except (TypeError, ValueError, OverflowError):
            initial_mass_kg, specific_impulse_s = 500.0, 220.0
    fuel_parameters_valid = (
        isinstance(initial_mass_kg, (int, float)) and not isinstance(initial_mass_kg, bool)
        and isinstance(specific_impulse_s, (int, float)) and not isinstance(specific_impulse_s, bool)
        and math.isfinite(initial_mass_kg) and math.isfinite(specific_impulse_s)
        and initial_mass_kg > 0 and 0 < specific_impulse_s <= 2000
    )
    valid_lead = (
        isinstance(lead_seconds, (int, float))
        and not isinstance(lead_seconds, bool)
        and math.isfinite(lead_seconds)
        and 60 <= lead_seconds <= 10800
    )
    valid_magnitudes = bool(magnitudes) and len(magnitudes) <= 4 and all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value <= 0.1
        for value in magnitudes
    )
    if not valid_lead or not valid_magnitudes:
        base["reason_code"] = "MANEUVER_CONFIGURATION_OUT_OF_BOUNDS"
        base["reason"] = "Lead time must be 60 to 10800 s; one to four burn magnitudes must each be greater than 0 and at most 0.1 m/s."
        return base
    if (isinstance(covariance_scale, bool) or not isinstance(covariance_scale, (int, float))
            or not math.isfinite(covariance_scale) or not 0.5 <= covariance_scale <= 3.0):
        base["reason_code"] = "MANEUVER_COVARIANCE_SCALE_OUT_OF_BOUNDS"
        base["reason"] = "Covariance scale must be between 0.5 and 3.0, inclusive."
        return base
    burn_magnitudes_m_s = magnitudes
    mu, step = 398600.4418, MANEUVER_SEARCH_SAMPLE_SECONDS
    burn_epoch = tca_datetime.astimezone(timezone.utc) - timedelta(seconds=lead_seconds)
    try:
        p_burn = _rk4(r1, v1, -lead_seconds, step, mu)
        s_burn = _rk4(r2, v2, -lead_seconds, step, mu)
        secondary_tca_coarse = _rk4(s_burn[0], s_burn[1], lead_seconds, step, mu)
        secondary_tca_fine = _rk4(s_burn[0], s_burn[1], lead_seconds, step / 2, mu)
        secondary_convergence = math.dist(secondary_tca_coarse[0], secondary_tca_fine[0])
        radial = _unit(p_burn[0]); normal = _unit(_cross(p_burn[0], p_burn[1])); along = _unit(_cross(normal, radial))
        all_directions = [("radial +", radial), ("radial -", _scale(radial, -1)), ("along-track +", along), ("along-track -", _scale(along, -1)), ("cross-track +", normal), ("cross-track -", _scale(normal, -1))]
        direction_codes = {"radial_plus": "radial +", "radial_minus": "radial -", "along_track_plus": "along-track +", "along_track_minus": "along-track -", "cross_track_plus": "cross-track +", "cross_track_minus": "cross-track -"}
        if rtn_direction != "all" and rtn_direction not in direction_codes:
            raise ValueError("MANEUVER_RTN_DIRECTION_INVALID")
        directions = all_directions if rtn_direction == "all" else [item for item in all_directions if item[0] == direction_codes[rtn_direction]]
        candidates = [{"delta_v_m_s": 0.0, "direction": "zero-burn baseline", "burn_state": p_burn, "rtn_direction": (0.0, 0.0, 0.0)}]
        for magnitude in burn_magnitudes_m_s:
            for name, direction in directions:
                burn = _add(p_burn[1], _scale(direction, magnitude / 1000.0))
                candidates.append({"delta_v_m_s": magnitude, "direction": name, "burn_state": (p_burn[0], burn), "rtn_direction": direction})

        # The surrogate scores candidate inputs before physics outcomes are
        # attached. The independent two-body simulation below still runs for
        # every candidate and remains authoritative for its physical result.
        try:
            maneuver_ml = score_candidates(event, candidates, lead_seconds)
            if not isinstance(maneuver_ml, dict):
                raise TypeError("ranker returned a non-object result")
        except Exception:
            maneuver_ml = {
                "status": "unavailable", "reason_code": "MANEUVER_MODEL_INFERENCE_FAILED",
                "model_name": MANEUVER_RANKER_NAME, "model_version": MANEUVER_RANKER_VERSION,
                "score_name": "predicted log10 research-Pc reduction vs zero-burn baseline",
                "score_units": "log10 ratio; positive predicts reduction", "is_simulator_surrogate": True,
                "synthetic_training_labels": False, "physics_generated_training_labels": True, "ranking_used": False, "candidate_scores": {},
                "score_semantics": "No surrogate score is available; deterministic physics-confirmed candidate ranking remains active.",
            }

        # Start at the burn epoch and search through the original TCA plus a
        # fixed 30-minute post-TCA horizon. The 5 s grid is bounded (at most
        # 2521 samples for the validated 3-hour maximum lead); it is not a
        # claim about minima outside this simulator interval.
        search_end_elapsed = lead_seconds + MANEUVER_POST_TCA_SEARCH_SECONDS
        elapsed_samples = {0.0, float(lead_seconds), float(search_end_elapsed)}
        elapsed_samples.update(
            float(index) * step
            for index in range(1, math.ceil(search_end_elapsed / step))
            if index * step < search_end_elapsed
        )
        elapsed_samples = sorted(elapsed_samples)
        secondary_samples = _propagate_samples(s_burn, elapsed_samples, step, mu)
        def evaluate_candidate(candidate):
            primary_samples = _propagate_samples(candidate["burn_state"], elapsed_samples, step, mu)
            tca_index = elapsed_samples.index(float(lead_seconds))
            pr, pv = primary_samples[tca_index]
            cr, cv = _rk4(candidate["burn_state"][0], candidate["burn_state"][1], lead_seconds, step / 2, mu)
            convergence = max(math.dist(pr, cr), secondary_convergence)
            if not math.isfinite(convergence) or convergence > 0.001:
                raise ValueError("two_body_integration_not_converged")
            distances = [math.dist(p[0], s[0]) for p, s in zip(primary_samples, secondary_samples)]
            closest = _refine_sampled_minimum(
                elapsed_samples,
                distances,
                lambda elapsed, states=primary_samples, secondary=secondary_samples:
                    _distance_from_sampled_state(elapsed, elapsed_samples, states, secondary, step, mu),
            )
            tca_offset = closest["elapsed_seconds"] - lead_seconds
            is_search_boundary = closest["sample_index"] in {0, len(elapsed_samples) - 1}
            closest_index = max(0, min(len(elapsed_samples) - 1, closest["sample_index"]))
            offset = closest["elapsed_seconds"] - elapsed_samples[closest_index]
            refined_primary = primary_samples[closest_index] if abs(offset) < 1e-12 else _rk4(primary_samples[closest_index][0], primary_samples[closest_index][1], offset, step / 2, mu)
            refined_secondary = secondary_samples[closest_index] if abs(offset) < 1e-12 else _rk4(secondary_samples[closest_index][0], secondary_samples[closest_index][1], offset, step / 2, mu)
            relative_velocity = tuple(refined_secondary[1][axis] - refined_primary[1][axis] for axis in range(3))
            inertial_delta_v_km_s = tuple(candidate["burn_state"][1][axis] - p_burn[1][axis] for axis in range(3))
            inertial_delta_v_m_s = tuple(value * 1000.0 for value in inertial_delta_v_km_s)
            rtn_delta_v_m_s = tuple(sum(inertial_delta_v_m_s[axis] * basis[axis] for axis in range(3)) for basis in (radial, along, normal))
            closest_tca = (tca_datetime.astimezone(timezone.utc) + timedelta(seconds=tca_offset)).isoformat()
            sanity_displacement = 3.0 * (candidate["delta_v_m_s"] / 1000.0) * lead_seconds
            along_track_direction = "positive" if "along-track +" == candidate["direction"] else ("negative" if "along-track -" == candidate["direction"] else None)
            return {"delta_v_m_s": candidate["delta_v_m_s"], "direction": candidate["direction"], "delta_v_rtn_m_s": list(rtn_delta_v_m_s), "delta_v_inertial_teme_km_s": list(inertial_delta_v_km_s), "delta_v_units": "m/s", "inertial_delta_v_units": "km/s", "direction_frame": "RTN at maneuver epoch; inertial vector expressed in TEME", "maneuver_epoch_utc": burn_epoch.isoformat(), "lead_time_seconds": lead_seconds, "predicted_miss_distance_km": closest["distance_km"], "closest_approach_utc": closest_tca, "closest_approach_offset_from_original_tca_seconds": tca_offset, "relative_velocity_km_s": list(relative_velocity), "relative_speed_km_s": math.sqrt(sum(value * value for value in relative_velocity)), "primary_state_at_closest_approach": {"position_km": list(refined_primary[0]), "velocity_km_s": list(refined_primary[1]), "epoch": closest_tca}, "secondary_state_at_closest_approach": {"position_km": list(refined_secondary[0]), "velocity_km_s": list(refined_secondary[1]), "epoch": closest_tca}, "along_track_sanity_check": {"status": "approximation_only" if along_track_direction else "not_applicable", "estimated_displacement_m": (3.0 * candidate["delta_v_m_s"] * lead_seconds) if along_track_direction == "positive" else (-3.0 * candidate["delta_v_m_s"] * lead_seconds if along_track_direction == "negative" else None), "relation": "delta_s ~= 3 * delta_v * delta_t", "assumptions": "near-circular orbit and short lead time; first-order sanity estimate only, not used for candidate Pc or ranking"}, "change_from_zero_burn_km": None, "change_from_zero_burn_baseline_percent": None, "objective_status": "search_boundary_minimum" if is_search_boundary else "refined_local_minimum_within_bounded_search", "search_interval_start_utc": burn_epoch.isoformat(), "search_interval_end_utc": (burn_epoch + timedelta(seconds=search_end_elapsed)).isoformat(), "search_interval_seconds_from_burn": [0.0, search_end_elapsed], "search_sample_step_seconds": step, "search_sample_count": len(elapsed_samples), "refinement_evaluations": closest["refinement_evaluations"], "integration_state_convergence_km": convergence}

        result_rows = [evaluate_candidate(candidate) for candidate in candidates]
        baseline_miss = result_rows[0]["predicted_miss_distance_km"]
        for row in result_rows:
            row["change_from_zero_burn_km"] = row["predicted_miss_distance_km"] - baseline_miss
            row["change_from_zero_burn_baseline_percent"] = (100.0 * row["change_from_zero_burn_km"] / baseline_miss) if baseline_miss > 0 else None
            row["source_sgp4_miss_distance_km"] = reference_miss_distance
        pc_results = [_maneuver_research_pc(event, row, covariance_scale=covariance_scale) for row in result_rows]
        baseline_pc = pc_results[0]
        for row, pc_result in zip(result_rows, pc_results):
            row["research_pc_after"] = pc_result
            row["research_pc_reduction_log10"] = _pc_log10_reduction(baseline_pc, pc_result)
            row["absolute_research_pc_reduction_scientific"] = _pc_absolute_reduction(baseline_pc, pc_result)
            row["percentage_research_pc_reduction"] = _pc_percentage_reduction(baseline_pc, pc_result)

        # Refine the best coarse magnitude independently on each signed RTN axis.
        # Each objective call repropagates the modified Cartesian state and repeats
        # the bounded closest-approach search; no modified TLE is constructed.
        refinements = []
        for direction_name, direction_vector in (directions if refine_candidates else ()):
            directional = [row for row in result_rows if row["direction"] == direction_name and row["objective_status"] != "search_boundary_minimum"]
            if not directional:
                continue
            peak = max(directional, key=lambda row: row["predicted_miss_distance_km"])
            ordered_magnitudes = sorted({0.0, *burn_magnitudes_m_s})
            peak_index = min(range(1, len(ordered_magnitudes)), key=lambda i: abs(ordered_magnitudes[i] - peak["delta_v_m_s"]))
            lower = ordered_magnitudes[max(0, peak_index - 1)]
            upper = ordered_magnitudes[min(len(ordered_magnitudes) - 1, peak_index + 1)]
            if upper <= lower:
                continue
            ratio = (math.sqrt(5.0) - 1.0) / 2.0
            left, right = lower, upper
            x1, x2 = right - ratio * (right - left), left + ratio * (right - left)

            def candidate_at(delta_v, label):
                burn = _add(p_burn[1], _scale(direction_vector, delta_v / 1000.0))
                return evaluate_candidate({"delta_v_m_s": delta_v, "direction": direction_name, "burn_state": (p_burn[0], burn), "rtn_direction": direction_vector})

            c1, c2 = candidate_at(x1, "refined"), candidate_at(x2, "refined")
            for _ in range(4):
                if c1["predicted_miss_distance_km"] >= c2["predicted_miss_distance_km"]:
                    right, x2, c2 = x2, x1, c1
                    x1 = right - ratio * (right - left)
                    c1 = candidate_at(x1, "refined")
                else:
                    left, x1, c1 = x1, x2, c2
                    x2 = left + ratio * (right - left)
                    c2 = candidate_at(x2, "refined")
            refinements.extend([c1, c2])
        result_rows.extend(refinements)
        for row in result_rows:
            row["change_from_zero_burn_km"] = row["predicted_miss_distance_km"] - baseline_miss
            row["change_from_zero_burn_baseline_percent"] = (100.0 * row["change_from_zero_burn_km"] / baseline_miss) if baseline_miss > 0 else None
            row["source_sgp4_miss_distance_km"] = reference_miss_distance
            row["fuel"] = (_maneuver_fuel_estimate(row["delta_v_m_s"], initial_mass_kg, specific_impulse_s)
                           if fuel_parameters_valid else {"status": "unavailable", "reason_code": "INVALID_MASS_OR_SPECIFIC_IMPULSE"})
            if row["fuel"].get("status") == "estimated":
                row["fuel"]["assumption_status"] = "estimated_from_default_assumptions" if fuel_parameters_defaulted else "user_supplied_spacecraft_parameters"
        best_candidate = max(
            (row for row in result_rows[1:] if row["change_from_zero_burn_km"] > 0 and row["objective_status"] != "search_boundary_minimum"),
            key=lambda row: row["predicted_miss_distance_km"],
            default=None,
        )
        pc_ranked = [row for row in result_rows[1:] if isinstance(row.get("research_pc_reduction_log10"), (int, float))]
        best_pc_candidate = max(pc_ranked, key=lambda row: row["research_pc_reduction_log10"], default=None)
        pc_comparison_available = baseline_pc.get("status") == "available" and best_pc_candidate is not None
        if maneuver_ml.get("ranking_used") and not pc_comparison_available:
            maneuver_ml.update({
                "status": "fallback_physics_ranking", "ranking_used": False,
                "reason_code": "LIVE_RESEARCH_PC_CONFIRMATION_UNAVAILABLE",
                "score_semantics": "The trained score could not be confirmed against live physics research Pc; deterministic geometry/physics ordering is used.",
            })
        best_geometry_candidate = best_candidate
        best_candidate = best_pc_candidate or best_geometry_candidate
        for row in result_rows:
            row.pop("rtn_direction", None)
        candidate_scores = maneuver_ml.get("candidate_scores", {})
        if not isinstance(candidate_scores, dict):
            candidate_scores = None
        normalized_scores = {}
        if candidate_scores is not None:
            for key, value in candidate_scores.items():
                try:
                    normalized = float(value) if not isinstance(value, bool) else math.nan
                except (TypeError, ValueError, OverflowError):
                    normalized = math.nan
                if not math.isfinite(normalized):
                    candidate_scores = None
                    break
                normalized_scores[str(key)] = normalized
        if candidate_scores is None:
            candidate_scores = {}
            maneuver_ml.update({"status": "unavailable", "reason_code": "MANEUVER_MODEL_OUTPUT_INVALID", "candidate_scores": {}})
        else:
            candidate_scores = normalized_scores
        candidate_ranks = maneuver_ml.get("candidate_ranks", {})
        if not isinstance(candidate_ranks, dict):
            candidate_ranks = {}
        physics_order = sorted(
            (index for index, row in enumerate(result_rows) if index > 0 and row["objective_status"] != "search_boundary_minimum"),
            key=lambda index: (result_rows[index].get("research_pc_after", {}).get("log10_pc", math.inf), -result_rows[index]["predicted_miss_distance_km"], index),
        )
        physics_ranks = {index: rank for rank, index in enumerate(physics_order, 1)}
        for index, row in enumerate(result_rows):
            score = candidate_scores.get(str(index))
            model_rank = candidate_ranks.get(str(index)) if maneuver_ml.get("ranking_used") else None
            row["maneuver_ml_predicted_log10_pc_reduction"] = score if isinstance(score, (int, float)) and math.isfinite(score) else None
            row["maneuver_ml_rank"] = model_rank if isinstance(model_rank, int) and not isinstance(model_rank, bool) else None
            row["physics_research_pc_rank"] = physics_ranks.get(index)
            row["maneuver_ml_status"] = "research_only_rank_confirmed_by_physics" if row["maneuver_ml_rank"] is not None and row.get("research_pc_after", {}).get("status") == "available" else ("physics_fallback_rank" if row["physics_research_pc_rank"] is not None else "not_ranked")
        maneuver_ml["candidate_scores"] = {
            str(index): row["maneuver_ml_predicted_log10_pc_reduction"]
            for index, row in enumerate(result_rows)
            if row["maneuver_ml_predicted_log10_pc_reduction"] is not None
        }
        maneuver_ml["scored_candidate_count"] = len(maneuver_ml["candidate_scores"])
        if not maneuver_ml.get("candidate_scores") and maneuver_ml.get("status") == "research_only":
            maneuver_ml.update({"status": "fallback_physics_ranking", "ranking_used": False, "reason_code": "NO_MODEL_SCORED_CANDIDATES"})
        base["ml_result"] = maneuver_ml
        surrogate_rank = {
            **maneuver_ml,
            "event_id": event_id,
            "is_simulator_surrogate": True,
            "synthetic_training_labels": False,
            "physics_generated_training_labels": True,
            "ranking_used": bool(maneuver_ml.get("ranking_used")),
            "ordering_reason": maneuver_ml.get("score_semantics") or "Deterministic physics-confirmed candidate ordering is used when the surrogate is unavailable.",
        }
        base["surrogate_rank"] = surrogate_rank
        baseline_tca_offset = result_rows[0]["closest_approach_offset_from_original_tca_seconds"]
        miss_tolerance = (
            max(MANEUVER_BASELINE_MISS_TOLERANCE_KM, abs(reference_miss_distance) * 0.01)
            if reference_miss_distance is not None else None
        )
        miss_delta = baseline_miss - reference_miss_distance if reference_miss_distance is not None else None
        if comparison_input_reason:
            baseline_status = "unavailable"
        elif abs(miss_delta) > miss_tolerance or abs(baseline_tca_offset) > MANEUVER_BASELINE_TCA_TOLERANCE_SECONDS:
            baseline_status = "discrepancy"
        else:
            baseline_status = "within_comparison_tolerance"
        baseline_comparison = {
            "status": baseline_status,
            "reason_code": comparison_input_reason,
            "reference_source": "stored original Stage 2A SGP4 event",
            "reference_tca_utc": epoch,
            "reference_miss_distance_km": reference_miss_distance,
            "reference_state_separation_at_tca_km": reference_state_separation,
            "zero_burn_two_body_miss_distance_km": baseline_miss,
            "zero_burn_closest_approach_utc": result_rows[0]["closest_approach_utc"],
            "miss_distance_difference_km": miss_delta,
            "zero_burn_tca_offset_from_reference_seconds": baseline_tca_offset,
            "miss_distance_tolerance_km": miss_tolerance,
            "tca_offset_tolerance_seconds": MANEUVER_BASELINE_TCA_TOLERANCE_SECONDS,
            "interpretation": (
                "The stored Stage 2A SGP4 event is the reference and the zero-burn two-body result is the simulated baseline. "
                "This comparison is not an independent validation. "
                "Configured thresholds are diagnostic only, not scientifically validated tolerances. Candidate changes are relative "
                "to the simulated baseline and do not establish improvement over the original event."
            ),
        }
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        base["reason_code"] = str(exc) or "TWO_BODY_INTEGRATION_FAILED"
        base["reason"] = "Candidate propagation failed or did not provide sufficient valid samples for the bounded closest-approach search."
        return base
    # Existing thresholds are a diagnostic convention, not a validated
    # acceptance criterion. Keep the simulation available for inspection, but
    # qualify every result until a defensible comparison criterion exists.
    baseline_warning = True
    zero_burn_baseline = {
        "event_id": event_id,
        "status": "evaluated",
        "method": "Earth two-body point-mass RK4",
        "propagator": "RK4",
        "reason_code": None,
        "tca_utc": result_rows[0]["closest_approach_utc"],
        "miss_distance_km": result_rows[0]["predicted_miss_distance_km"],
        "candidate": result_rows[0],
    }
    stage2a_reference = {
        **base["stage2a_reference"],
        "status": physics.status,
        "propagator": (physics.provenance.propagator if physics.provenance else None) or "SGP4",
        "method": physics.provenance.method if physics.provenance else None,
        "method_version": physics.provenance.method_version if physics.provenance else None,
        "tca": physics.tca.model_dump(mode="json"),
        "miss_distance": physics.miss_distance.model_dump(mode="json"),
    }
    physics_candidates = {
        "event_id": event_id,
        "status": "evaluated",
        "method": "Earth two-body point-mass RK4",
        "propagator": "RK4",
        "reason_code": None,
        "candidates": result_rows[1:],
        "limitations": "Two-body simulator candidates; no J2, drag, third-body, covariance, execution error, attitude, or propulsion constraints.",
    }
    probability_before = {
        **baseline_pc, "event_id": event_id,
        "comparison_role": baseline_pc.get("comparison_role", "zero_burn_two_body_baseline"),
    }
    probability_after = ({
        **best_pc_candidate["research_pc_after"], "event_id": event_id,
        "comparison_role": "best_research_pc_reduction_candidate",
    } if best_pc_candidate else {
        "status": "unavailable", "pc": None, "event_id": event_id,
        "reason_code": baseline_pc.get("reason_code") or "NO_VALID_RESEARCH_PC_CANDIDATE",
        "meaning": "No candidate with a valid interior closest approach and comparable research Pc was available.",
    })
    return {
        **base,
        "status": "available_with_warning" if baseline_warning else "available",
        "reason_code": (
            "BASELINE_REFERENCE_COMPARISON_UNAVAILABLE" if baseline_status == "unavailable"
            else "ZERO_BURN_BASELINE_DISCREPANCY" if baseline_status == "discrepancy"
            else "BASELINE_COMPARISON_TOLERANCE_UNVALIDATED"
        ),
        "reason": (
            "Candidate sweep computed for research inspection, but the zero-burn baseline comparison is unavailable; candidates are not verified improvements to the original Stage 2A event."
            if baseline_status == "unavailable" else
            "Candidate sweep computed for research inspection, but the zero-burn two-body baseline disagrees with the original Stage 2A SGP4 event; candidates are not verified improvements to that event."
            if baseline_status == "discrepancy" else
            "Candidate sweep computed for research inspection; the comparison is within existing diagnostic thresholds, but those thresholds are not scientifically validated and candidates are not verified improvements to the original Stage 2A event."
        ),
        "method": f"Earth two-body point-mass RK4; mu=398600.4418 km^3/s^2; dt=5 s (convergence checked against 2.5 s); closest-approach search from burn epoch through {MANEUVER_POST_TCA_SEARCH_SECONDS:g} s after original TCA, maximum 5 s sample spacing with local-minimum refinement; burn lead {lead_seconds:g} s",
        "method_version": "research-2",
        "physics_candidate_status": "evaluated",
        "search_configuration": {
            "burn_lead_seconds": lead_seconds,
            "max_delta_v_m_s": max_delta_v_m_s if max_delta_v_m_s is not None else max(burn_magnitudes_m_s),
            "coarse_magnitudes_m_s": list(burn_magnitudes_m_s),
            "directions": [name for name, _ in directions],
            "rtn_direction_selection": rtn_direction,
            "refinement_method": "bounded golden-section maximization of miss distance on each signed RTN axis around the best coarse magnitude",
            "refinement_evaluations_per_axis_max": 6,
            "optimality_claim": "best valid candidate found in this bounded axis-aligned search; not globally optimal",
        },
        "best_candidate_status": ("best_research_pc_reduction_candidate_selected" if best_pc_candidate else ("improved_geometry_found" if best_candidate else "no_candidate_improved_separation_within_search_bounds")),
        "best_candidate": best_candidate,
        "best_geometry_candidate": best_geometry_candidate,
        "best_candidate_basis": "minimum prior-based research Pc among physics-evaluated candidates" if best_pc_candidate else "maximum simulated miss distance; research Pc unavailable",
        "best_pc_reduction_candidate": best_pc_candidate,
        "fuel": best_candidate["fuel"] if best_candidate else {"status": "unavailable", "reason_code": "NO_IMPROVING_CANDIDATE"},
        "fuel_cost_kg": (best_candidate["fuel"].get("propellant_consumption_kg") if best_candidate and best_candidate["fuel"].get("status") == "estimated" else None),
        "fuel_status": (best_candidate["fuel"].get("status") if best_candidate else "unavailable"),
        "fuel_reason_code": (best_candidate["fuel"].get("reason_code") if best_candidate else "NO_IMPROVING_CANDIDATE"),
        "stage2a_reference": stage2a_reference,
        "event_context": _maneuver_event_context(event),
        "zero_burn_baseline": zero_burn_baseline,
        "physics_candidates": physics_candidates,
        "surrogate_rank": surrogate_rank,
        "candidate_interpretation": "Candidate geometry changes are relative to the zero-burn two-body simulation. Baseline Pc at scale 1 reuses the selected event's Collision Analysis research-Pc record; candidate Pc uses the same configured TLE-age covariance policy, scale, and HBR selection. Covariance is assigned at each TCA rather than propagated; burn-execution error is zero and not modeled. Neither output is an operational maneuver recommendation.",
        "covariance_scale": float(covariance_scale),
        "percentage_reduction_policy": "Computed from exact before/after log10(Pc): 100 * (1 - 10^(after_log10_pc - before_log10_pc)); this remains defined for a negligible baseline. Absolute reduction is shown as < 1e-30 when below the documented Pc display floor.",
        "candidates": result_rows,
        "ml_result": maneuver_ml,
        "baseline_reference_comparison": baseline_comparison,
        "comparison_result": {"status": "available" if pc_comparison_available else "unavailable", "reason_code": None if pc_comparison_available else (baseline_pc.get("reason_code") or "RESEARCH_PC_COMPARISON_UNAVAILABLE"), "risk_reduction_pct": best_pc_candidate.get("percentage_research_pc_reduction") if pc_comparison_available else None},
        "assumptions": ["Bounded interval begins at burn epoch and ends 1800 s after original event TCA; no claim is made about minima outside it", "At most 721 coarse samples and 32 local-minimum refinements per trajectory; closest-approach golden-section refinement stops at 0.01 s", "TCA TEME Cartesian states are treated as inertial over the configured short propagation interval", "burn applied to primary only at TCA minus configured lead in the burn-epoch RTN frame", f"coarse magnitudes in m/s: {', '.join(f'{value:g}' for value in burn_magnitudes_m_s)}; candidate axis refinement is bounded by these samples", "no J2, drag, third-body, covariance, execution error, attitude, or propulsion constraints", "miss distance is simulated two-body geometry; no collision probability reduction or operational recommendation is inferred", "baseline comparison is a diagnostic against the stored SGP4 event, not independent validation", "fuel uses the ideal Tsiolkovsky equation only when user-supplied initial mass and specific impulse are both valid; it does not establish feasibility or remaining fuel"],
        "risk_reduction_pct": best_pc_candidate.get("percentage_research_pc_reduction") if pc_comparison_available else None,
        "probability_status": "available" if pc_comparison_available else "unavailable",
        "probability_reason_code": None if pc_comparison_available else (baseline_pc.get("reason_code") or "NO_VALID_RESEARCH_PC_CANDIDATE"),
        "probability_reason": None if pc_comparison_available else "Comparable prior-based research Pc was unavailable for the zero-burn baseline or all candidates.",
        "probability_before": probability_before,
        "probability_after": probability_after,
        "probability_comparison": {
            "status": "available" if pc_comparison_available else "unavailable",
            "reason_code": None if pc_comparison_available else (baseline_pc.get("reason_code") or "RESEARCH_PC_COMPARISON_UNAVAILABLE"),
            "risk_reduction_pct": best_pc_candidate.get("percentage_research_pc_reduction") if pc_comparison_available else None,
            "interpretation": "Comparison uses one consistent prior-based research Pc policy for the zero-burn and best evaluated candidate. It is an assumption-based estimate, not an observed or operationally validated Pc change.",
        },
    }


def _maneuver_research_pc(event: ConjunctionAssessmentEvent, candidate: dict[str, Any], *, covariance_scale: float = 1.0) -> dict[str, Any]:
    """Evaluate comparable prior-based research Pc at the candidate's own TCA."""
    if candidate.get("objective_status") == "search_boundary_minimum":
        return {"status": "unavailable", "pc": None, "reason_code": "CLOSEST_APPROACH_AT_SEARCH_BOUNDARY"}
    selected_research = event.automatic_research_pc_assessment
    if (candidate.get("delta_v_m_s") == 0 and covariance_scale == 1.0
            and selected_research is not None
            and selected_research.status == "prior_based_research_estimate"
            and isinstance(selected_research.log10_pc, (int, float))):
        return {
            "status": "available", "pc": selected_research.estimated_pc,
            "pc_scientific": selected_research.estimated_pc_scientific,
            "log10_pc": float(selected_research.log10_pc),
            "tca_utc": event.physics_result.tca.value,
            "miss_distance_km": event.physics_result.miss_distance.value,
            "method": selected_research.method_name,
            "method_version": selected_research.method_version,
            "covariance_method": selected_research.covariance_method,
            "hbr_method": selected_research.hbr_method,
            "hbr_km": selected_research.hbr_km,
            "provenance": selected_research.provenance,
            "assumptions": selected_research.assumptions,
            "covariance_assignment": "Exact selected-event Collision Analysis research-Pc record; TLE-age baseline policy, configured covariance scale 1.0, and selected-event HBR.",
            "comparison_role": "collision_analysis_research_pc_record",
        }
    try:
        selected_policy = (selected_research.covariance_policy_id if selected_research is not None
                           and selected_research.covariance_policy_id else "tle_age_baseline")
        fixed_covariances = None
        fixed_hbr_km = None
        if selected_research is not None and selected_research.status == "prior_based_research_estimate":
            fixed_covariances = maneuver_baseline_covariances(
                event.physics_result, event.primary, event.secondary,
                covariance_scale, selected_policy,
            )
            fixed_hbr_km = selected_research.hbr_km
        tca = candidate["closest_approach_utc"]
        p = candidate["primary_state_at_closest_approach"]
        s = candidate["secondary_state_at_closest_approach"]
        primary_state = {"object_id": event.primary.id, "epoch": tca, "frame": "TEME", "position_km": p["position_km"], "velocity_km_s": p["velocity_km_s"]}
        secondary_state = {"object_id": event.secondary.id, "epoch": tca, "frame": "TEME", "position_km": s["position_km"], "velocity_km_s": s["velocity_km_s"]}
        relative_position = [secondary_state["position_km"][i] - primary_state["position_km"][i] for i in range(3)]
        relative_velocity = [secondary_state["velocity_km_s"][i] - primary_state["velocity_km_s"][i] for i in range(3)]
        relative_speed = math.sqrt(sum(value * value for value in relative_velocity))
        physics = event.physics_result.model_copy(deep=True, update={
            "status": "valid", "tca_status": "valid",
            "tca": ScientificField(status="available", value=tca, units="UTC"),
            "miss_distance": ScientificField(status="available", value=candidate["predicted_miss_distance_km"], units="km"),
            "relative_position_at_tca": ScientificField(status="available", value=relative_position, units="km"),
            "relative_velocity_at_tca": ScientificField(status="available", value=relative_velocity, units="km/s"),
            "relative_speed_at_tca": ScientificField(status="available", value=relative_speed, units="km/s"),
            "primary_state_at_tca": primary_state, "secondary_state_at_tca": secondary_state,
            "object_primary_id": event.primary.id, "object_secondary_id": event.secondary.id,
        })
        research = assess_automatic_research_pc(
            physics, None, event.review_priority or ReviewPriority(), event.primary, event.secondary,
            covariance_scale=covariance_scale, covariance_policy=selected_policy,
            fixed_covariance_inputs=fixed_covariances, fixed_hbr_km=fixed_hbr_km,
        )
        scientific = research.estimated_pc_scientific
        if (research.status != "prior_based_research_estimate" or not isinstance(scientific, str)
                or not isinstance(research.log10_pc, (int, float)) or not math.isfinite(research.log10_pc)):
            return {"status": "unavailable", "pc": None, "reason_code": (research.reason_codes or ["RESEARCH_PC_NOT_ESTIMABLE"])[0], "tca_utc": tca}
        log10_pc = float(research.log10_pc)
        return {
            "status": "available", "pc": research.estimated_pc, "pc_scientific": scientific,
            "log10_pc": log10_pc, "tca_utc": tca,
            "miss_distance_km": candidate["predicted_miss_distance_km"],
            "method": research.method_name, "method_version": research.method_version,
            "covariance_method": research.covariance_method, "hbr_method": research.hbr_method,
            "hbr_km": research.hbr_km, "provenance": research.provenance,
            "assumptions": research.assumptions,
            "covariance_assignment": (f"Exact selected-event baseline TEME covariance matrix and HBR ({fixed_hbr_km:g} km) reused for every candidate; covariance matrix remains fixed while the mean relative state changes; scale {covariance_scale:g}."
                                      if fixed_covariances is not None and fixed_hbr_km is not None else
                                      f"Same {research.covariance_policy_id} policy and event-derived HBR selection at candidate TCA; no burn-execution covariance."),
        }
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return {"status": "unavailable", "pc": None, "reason_code": f"RESEARCH_PC_CANDIDATE_INVALID_{type(exc).__name__}"}


def _pc_log10_reduction(before: dict[str, Any], after: dict[str, Any]) -> float | None:
    if before.get("status") != "available" or after.get("status") != "available":
        return None
    return float(before["log10_pc"] - after["log10_pc"])


def _pc_absolute_reduction(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    if before.get("status") != "available" or after.get("status") != "available":
        return None
    try:
        with localcontext() as context:
            context.prec = 40
            baseline_log = Decimal(str(before["log10_pc"]))
            candidate_log = Decimal(str(after["log10_pc"]))
            value = (Decimal(10) ** baseline_log) - (Decimal(10) ** candidate_log)
        if abs(value) < Decimal("1e-30"):
            return "< 1e-30"
        return f"{value:.6E}"
    except (InvalidOperation, KeyError, TypeError, ValueError, OverflowError):
        return None


def _pc_percentage_reduction(before: dict[str, Any], after: dict[str, Any]) -> float | None:
    if before.get("status") != "available" or after.get("status") != "available":
        return None
    try:
        difference = float(after["log10_pc"]) - float(before["log10_pc"])
        ratio = math.pow(10.0, difference) if difference > -323.0 else 0.0
        result = 100.0 * (1.0 - ratio)
        return result if math.isfinite(result) else None
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def _maneuver_event_context(event: ConjunctionAssessmentEvent) -> dict[str, Any]:
    physics = event.physics_result
    pc = event.collision_probability
    event_pc_matches = bool(
        pc is not None and pc.status == "available" and pc.event_id == event.id
        and pc.object_1_id == event.primary.id and pc.object_2_id == event.secondary.id
        and pc.tca_utc == physics.tca.value and isinstance(pc.pc, (int, float))
        and not isinstance(pc.pc, bool) and math.isfinite(pc.pc) and 0 <= pc.pc <= 1
    )
    source_pc_matches = bool(
        pc is not None and pc.source_reported_event_id == event.id
        and isinstance(pc.source_reported_pc, (int, float)) and not isinstance(pc.source_reported_pc, bool)
        and math.isfinite(pc.source_reported_pc) and 0 <= pc.source_reported_pc <= 1
    )
    research = event.automatic_research_pc_assessment
    ai = event.ai_risk_assessment
    relative_velocity = physics.relative_velocity_at_tca
    return {
        "event_id": event.id,
        "object_ids": [event.primary.id, event.secondary.id],
        "tca_utc": physics.tca.value if physics.tca.status == "available" else None,
        "miss_distance_km": physics.miss_distance.value if physics.miss_distance.status == "available" else None,
        "relative_velocity_km_s": relative_velocity.value if relative_velocity.status == "available" else None,
        "relative_speed_km_s": physics.relative_speed_at_tca.value if physics.relative_speed_at_tca.status == "available" else None,
        "reference_frame": (physics.state_information or {}).get("source_frame"),
        "source_reported_pc": ({
            "status": "available", "pc": pc.source_reported_pc,
            "method": pc.source_reported_pc_method,
            "event_id": pc.source_reported_event_id,
            "provenance": pc.source_reported_pc_provenance,
        } if source_pc_matches and pc is not None else {"status": "unavailable", "pc": None}),
        "event_specific_foster_pc": ({
            "status": "available", "pc": pc.pc, "method": pc.method,
            "method_version": pc.method_version, "event_id": pc.event_id,
            "tca_utc": pc.tca_utc, "hbr_km": pc.hbr_km,
            "covariance_sources": [item.model_dump(mode="json") for item in pc.covariance_sources],
        } if event_pc_matches and pc is not None else {
            "status": "unavailable", "pc": None,
            "reason_code": "NO_EVENT_MATCHED_FOSTER_PC",
        }),
        "research_pc": ({
            "status": research.status, "estimated_pc": research.estimated_pc,
            "estimated_pc_scientific": research.estimated_pc_scientific,
            "method_name": research.method_name, "method_version": research.method_version,
            "quality_status": research.quality_status,
        } if research is not None else {"status": "unavailable"}),
        "ai_queue_index": ({
            "score": ai.score, "category": ai.category, "model_name": ai.model_name,
            "model_version": ai.model_version, "meaning": ai.target_definition,
        } if ai is not None else {"status": "unavailable"}),
        "uncertainty_provenance": {
            "covariance_status": "available_prior_based" if research is not None and research.status == "prior_based_research_estimate" else (pc.covariance_status if pc is not None else physics.covariance.status),
            "covariance_sources": [item.model_dump(mode="json") for item in pc.covariance_sources] if pc is not None else [],
            "hbr_km": pc.hbr_km if pc is not None else (research.hbr_km if research is not None else None),
            "hbr_source": pc.hbr_source if pc is not None else ("ESA_prior_assumed" if research is not None and research.status == "prior_based_research_estimate" else "unavailable"),
            "hbr_provenance": pc.hbr_provenance if pc is not None else (research.provenance if research is not None else None),
            "post_burn_covariance_propagation": "not_dynamically_propagated; the same configured TLE-age covariance/HBR policy and scale is assigned at each candidate TCA",
        },
        "data_quality_limitations": [
            "Candidate trajectories are Earth two-body RK4 simulations; they omit J2, drag, third-body effects, controls, and burn execution error.",
            "Research Pc uses the same configured TLE-age covariance/HBR policy and scale at each TCA; uncertainty is not dynamically propagated from TLE epoch.",
            "Source-reported Pc, event-specific Foster Pc, prior-based research Pc, and rule-based review priority remain separate evidence.",
            "This is a simulated candidate search, not an executed or operationally validated maneuver.",
        ],
    }


def _propagate_samples(initial_state, elapsed_samples, step, mu):
    if len(elapsed_samples) < 3 or elapsed_samples[0] != 0 or any(b <= a for a, b in zip(elapsed_samples, elapsed_samples[1:])):
        raise ValueError("insufficient_valid_propagation_samples")
    states = [initial_state]
    for before, after in zip(elapsed_samples, elapsed_samples[1:]):
        states.append(_rk4(states[-1][0], states[-1][1], after - before, step, mu))
    if not all(math.isfinite(value) for state in states for vector in state for value in vector):
        raise ValueError("invalid_non_finite_propagation_sample")
    return states


def _distance_from_sampled_state(elapsed, elapsed_samples, primary_samples, secondary_samples, step, mu):
    index = max(0, min(len(elapsed_samples) - 1, next((i for i, sample in enumerate(elapsed_samples) if sample > elapsed), len(elapsed_samples)) - 1))
    delta = elapsed - elapsed_samples[index]
    primary = primary_samples[index] if abs(delta) < 1e-12 else _rk4(primary_samples[index][0], primary_samples[index][1], delta, step / 2, mu)
    secondary = secondary_samples[index] if abs(delta) < 1e-12 else _rk4(secondary_samples[index][0], secondary_samples[index][1], delta, step / 2, mu)
    distance = math.dist(primary[0], secondary[0])
    if not math.isfinite(distance):
        raise ValueError("invalid_non_finite_refinement_sample")
    return distance


def _refine_sampled_minimum(times, distances, evaluate):
    if len(times) != len(distances) or len(times) < 3 or any(not math.isfinite(x) for x in distances):
        raise ValueError("insufficient_valid_propagation_samples")
    minimum_indices = [i for i, value in enumerate(distances) if (i == 0 or value <= distances[i - 1]) and (i == len(distances) - 1 or value <= distances[i + 1])]
    if not minimum_indices:
        raise ValueError("insufficient_valid_propagation_samples")
    if len(minimum_indices) > MANEUVER_SEARCH_MAX_REFINEMENTS:
        raise ValueError("too_many_local_minima_for_bounded_refinement")
    best = None
    for index in minimum_indices:
        # Interval endpoints cannot be refined without extrapolating beyond
        # the documented search bounds, so retain and flag them explicitly.
        if index in {0, len(times) - 1}:
            candidate = {"elapsed_seconds": times[index], "distance_km": distances[index], "sample_index": index, "refinement_evaluations": 0}
        else:
            left, right = times[index - 1], times[index + 1]
            ratio = (math.sqrt(5.0) - 1.0) / 2.0
            x1, x2 = right - ratio * (right - left), left + ratio * (right - left)
            f1, f2 = evaluate(x1), evaluate(x2)
            evaluations = 2
            for _ in range(80):
                if right - left <= MANEUVER_SEARCH_REFINEMENT_TOLERANCE_SECONDS:
                    break
                if f1 <= f2:
                    right, x2, f2 = x2, x1, f1
                    x1 = right - ratio * (right - left)
                    f1 = evaluate(x1)
                else:
                    left, x1, f1 = x1, x2, f2
                    x2 = left + ratio * (right - left)
                    f2 = evaluate(x2)
                evaluations += 1
            elapsed = (left + right) / 2
            candidate = {"elapsed_seconds": elapsed, "distance_km": evaluate(elapsed), "sample_index": index, "refinement_evaluations": evaluations + 1}
        if best is None or candidate["distance_km"] < best["distance_km"]:
            best = candidate
    return best


def _validated_state(state):
    r, v = state["position_km"], state["velocity_km_s"]
    if (
        len(r) != 3
        or len(v) != 3
        or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (*r, *v))
        or math.sqrt(sum(float(x) ** 2 for x in r)) < 6378
    ):
        raise ValueError("invalid_or_non_finite_cartesian_state")
    return tuple(map(float, r)), tuple(map(float, v))


def _gravity(r, mu):
    radius = math.sqrt(sum(x*x for x in r))
    if radius < 6378: raise ValueError("two_body_radius_below_earth_surface")
    return tuple(-mu*x/radius**3 for x in r)


def _maneuver_fuel_estimate(delta_v_m_s: float, initial_mass_kg: float | None, specific_impulse_s: float | None) -> dict[str, Any]:
    if (initial_mass_kg is None or specific_impulse_s is None
            or isinstance(initial_mass_kg, bool) or isinstance(specific_impulse_s, bool)
            or not isinstance(initial_mass_kg, (int, float)) or not isinstance(specific_impulse_s, (int, float))
            or not math.isfinite(initial_mass_kg) or not math.isfinite(specific_impulse_s)
            or initial_mass_kg <= 0 or specific_impulse_s <= 0):
        return {"status": "unavailable", "reason_code": "MASS_AND_PROPULSION_MODEL_REQUIRED"}
    # Ideal single-impulse rocket equation. The supplied initial mass is the
    # pre-burn mass; no tank, residual, efficiency, or thrust-arc model exists.
    propellant = initial_mass_kg * (1.0 - math.exp(-delta_v_m_s / (specific_impulse_s * 9.80665)))
    return {
        "status": "estimated",
        "propellant_consumption_kg": propellant,
        "initial_mass_kg": initial_mass_kg,
        "specific_impulse_s": specific_impulse_s,
        "standard_gravity_m_s2": 9.80665,
        "method": "ideal Tsiolkovsky rocket equation for one instantaneous impulse",
        "assumptions": ["No finite burn duration, propulsion efficiency, residual propellant, tank margin, or feasibility constraints are modeled."],
    }


def _rk4(r, v, duration, step, mu):
    n = max(1, math.ceil(abs(duration) / step)); h = duration / n
    r, v = tuple(r), tuple(v)
    for _ in range(n):
        a1 = _gravity(r, mu); k1r = v
        r2 = _add(r, _scale(k1r, h/2)); v2 = _add(v, _scale(a1, h/2)); a2 = _gravity(r2, mu); k2r = v2
        r3 = _add(r, _scale(k2r, h/2)); v3 = _add(v, _scale(a2, h/2)); a3 = _gravity(r3, mu); k3r = v3
        r4 = _add(r, _scale(k3r, h)); v4 = _add(v, _scale(a3, h)); a4 = _gravity(r4, mu); k4r = v4
        r = tuple(r[i] + h/6*(k1r[i]+2*k2r[i]+2*k3r[i]+v4[i]) for i in range(3))
        v = tuple(v[i] + h/6*(a1[i]+2*a2[i]+2*a3[i]+a4[i]) for i in range(3))
    return r, v


def _add(a,b): return tuple(x+y for x,y in zip(a,b))
def _scale(a,s): return tuple(x*s for x in a)
def _cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _unit(a):
    n=math.sqrt(sum(x*x for x in a))
    if n < 1e-12: raise ValueError("degenerate_rtn_basis")
    return tuple(x/n for x in a)


def _event_from_pair(a: SpaceObject, b: SpaceObject, cell: RiskCell) -> ScreeningProxyEvent:
    altitude_diff = abs(a.altitude_km - b.altitude_km)
    inclination_diff = abs(a.inclination_deg - b.inclination_deg)
    score = max(
        0.0,
        min(
            1.0,
            0.42 * ((a.heuristic_risk_score + b.heuristic_risk_score) / 2)
            + 0.38 * cell.heuristic_risk_score
            + 0.20 * ((a.heuristic_forecast_score + b.heuristic_forecast_score) / 2),
        ),
    )
    # Reassigned to a batch-relative rank after candidate generation.
    risk_level = "Low"
    priority = 0.0
    provenance = derived_provenance(
        [a, b],
        method=SCREENING_METHOD,
        method_version=SCREENING_METHOD_VERSION,
    )
    event_id = _stable_event_id(a, b)
    provenance.object_id = None
    provenance.input_hash = _pair_input_hash(a, b)
    physics_result = PhysicsResult(
        event_id=event_id,
        status="unavailable",
        applicability="candidate_pair_only",
        provenance=provenance.model_copy(deep=True),
        reason_codes=["screening_proxy_not_a_physical_event", "trajectory_assessment_not_attached"],
    )
    return ScreeningProxyEvent(
        id=event_id,
        primary=_object_summary(a),
        secondary=_object_summary(b),
        obj_a=_object_summary(a),
        obj_b=_object_summary(b),
        pair_type=_pair_type(a, b),
        risk_level=risk_level,
        risk_score=round(score, 4),
        priority_score=round(priority, 1),
        suggested_action=_suggested_action(risk_level),
        features={
            "altitude_difference_km": round(altitude_diff, 3),
            "inclination_difference_deg": round(inclination_diff, 3),
            "screening_band": cell.band,
            "heuristic_risk_scores": [a.heuristic_risk_score, b.heuristic_risk_score],
            "cell_heuristic_risk_score": cell.heuristic_risk_score,
            "score_semantics": "saturated deterministic orbital-shell heuristic; not physical conjunction probability",
            "class_semantics": "relative ranking within this generated proxy batch",
        },
        provenance=provenance,
        physics_result=physics_result,
        ml_result={
            "status": "unavailable",
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "training_dataset": DATASET_NAME,
            "features_imputed": False,
            "provenance": {"reason_code": "proxy_has_no_event_level_physics_features"},
            "reason_code": "PHYSICS_ASSESSMENT_FEATURES_REQUIRED",
        },
        comparison_result=ComparisonResult(
            status="not_applicable",
            reason_code="proxy_pairs_have_no_event_level_ml_or_physics_result",
        ),
    )


def _cell_from_objects(a: SpaceObject, b: SpaceObject, index: int) -> RiskCell:
    score = max(a.heuristic_forecast_score, b.heuristic_forecast_score)
    severity = "severe" if score > 0.72 else "elevated" if score > 0.52 else "moderate" if score > 0.33 else "low"
    return RiskCell(
        id=f"DERIVED-CELL-{a.id}-{b.id}-{index}",
        band=a.band,
        altitude_km=round((a.altitude_km + b.altitude_km) / 2, 2),
        inclination_deg=round((a.inclination_deg + b.inclination_deg) / 2, 2),
        raan_deg=round((a.orbit.raan_deg + b.orbit.raan_deg) / 2, 2),
        severity=severity,  # type: ignore[arg-type]
        heuristic_risk_score=round(score, 4),
        tracked_object_density_score=0.0,
        heuristic_untracked_pressure_score=0.0,
        heuristic_forecast_score=round((a.heuristic_forecast_score + b.heuristic_forecast_score) / 2, 4),
        heuristic_uncertainty_score=0.0,
        contributors=[a.name, b.name],
        explanation="Derived pair-ranking cell for heuristic screening only; not an encounter assessment.",
        provenance=derived_provenance([a, b], method=SCREENING_METHOD, method_version=SCREENING_METHOD_VERSION),
    )


def _object_summary(obj: SpaceObject) -> ObjectSummary:
    return ObjectSummary(
        id=obj.id,
        name=obj.name,
        category=obj.category,
        object_type=obj.object_type,
        source_classification=obj.source_classification,
        classification_source=obj.classification_source,
        band=obj.band,
        orbit_type=obj.orbit_type,
        altitude_km=obj.altitude_km,
        inclination_deg=obj.inclination_deg,
        velocity_kms=obj.velocity_kms,
        heuristic_risk_score=obj.heuristic_risk_score,
        heuristic_forecast_score=obj.heuristic_forecast_score,
        provenance=obj.provenance,
        heuristic_score_provenance=obj.heuristic_score_provenance,
    )


def _stable_event_id(a: SpaceObject, b: SpaceObject) -> str:
    return f"SP-{_pair_input_hash(a, b)[:20].upper()}"


def _pair_input_hash(a: SpaceObject, b: SpaceObject) -> str:
    pair_inputs = sorted(
        (
            (a.id, a.provenance.input_hash or a.id),
            (b.id, b.provenance.input_hash or b.id),
        )
    )
    canonical = "ORION-SCREENING-PROXY-V1|" + "|".join(f"{object_id}:{input_hash}" for object_id, input_hash in pair_inputs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assign_relative_proxy_priority(events: list[ScreeningProxyEvent]) -> None:
    """Use relative ranks because the upstream shell heuristics are saturated near 1."""
    total = len(events)
    for rank, event in enumerate(events):
        percentile = (rank + 1) / total if total else 1.0
        if percentile <= 0.05:
            level = "Critical"
        elif percentile <= 0.20:
            level = "High"
        elif percentile <= 0.50:
            level = "Medium"
        elif percentile <= 0.80:
            level = "Low"
        else:
            level = "Safe"
        event.risk_level = level
        event.priority_score = round(100 * (1 - rank / max(total, 1)), 1)
        event.suggested_action = _suggested_action(level)


def _pair_type(a: SpaceObject, b: SpaceObject) -> str:
    return pair_type_for(a.object_type, b.object_type)


def _suggested_action(risk_level: str) -> str:
    return {
        "Critical": "Analyst review of this heuristic screening proxy; no maneuver recommendation is available.",
        "High": "Review the heuristic screening proxy; no physical conjunction assessment is available.",
        "Medium": "Add to a review watchlist; refresh inputs before any operational decision.",
        "Low": "Continue catalog-level heuristic monitoring.",
        "Safe": "No screening action from this heuristic score.",
    }[risk_level]


def _mission_briefing(events: list[ScreeningProxyEvent], total_objects: int, retained: list[ScreeningProxyEvent]) -> str:
    if not events:
        return f"{total_objects:,} catalog objects analyzed. No heuristic screening proxy pairs were produced; physical conjunction assessment is unavailable."
    highest = events[0]
    return (
        f"{total_objects:,} catalog objects analyzed. {len(retained)} of {len(events)} heuristic screening proxy pairs "
        f"are on the review list. Highest heuristic score: {highest.primary.name} versus {highest.secondary.name} "
        f"({highest.risk_score:.3f}). No TCA, miss distance, covariance, Pc, or maneuver effect was calculated."
    )
