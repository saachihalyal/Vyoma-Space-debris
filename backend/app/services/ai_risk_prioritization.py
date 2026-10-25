"""Deterministic live conjunction prioritization, separate from Pc and ESA ML.

The score is a queue index only. It combines normalized miss-distance pressure
and relative speed. Thresholds/weights are versioned defaults and configurable
via environment; they are not trained/calibrated collision-risk cutoffs.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import os
from typing import Any

from app.models import AiRiskAssessment, ConjunctionAssessmentEvent, PhysicsResult


MODEL_VERSION = "1.0.0"
SPEED_REFERENCE_KM_S = 15.0  # explicit normalization reference, not a risk boundary


def assess_live_geometry(physics: PhysicsResult) -> AiRiskAssessment | None:
    """Create a deterministic numerical prioritization for usable encounter geometry."""
    if physics.status not in {"valid", "boundary"} or physics.tca_status not in {"valid", "boundary"}:
        return None
    miss = _finite_nonnegative(physics.miss_distance.value if physics.miss_distance.status == "available" else None)
    threshold = _finite_positive(physics.screening_threshold_km)
    speed = _finite_nonnegative(
        physics.relative_speed_at_tca.value
        if physics.relative_speed_at_tca.status == "available" else None
    )
    if miss is None or threshold is None or speed is None:
        return None

    proximity = 1.0 - min(miss / threshold, 1.0)
    speed_component = min(speed / SPEED_REFERENCE_KM_S, 1.0)
    proximity_weight = _configured_weight("ORION_AI_GEOMETRY_WEIGHT", 0.75)
    speed_weight = _configured_weight("ORION_AI_SPEED_WEIGHT", 0.25)
    total = proximity_weight + speed_weight
    if total <= 0:
        proximity_weight, speed_weight, total = 0.75, 0.25, 1.0
    score = (proximity_weight * proximity + speed_weight * speed_component) / total
    cutoffs = _category_cutoffs()
    if score >= cutoffs["critical"]:
        category = "Critical"
    elif score >= cutoffs["high"]:
        category = "High"
    elif score >= cutoffs["medium"]:
        category = "Medium"
    else:
        category = "Low"
    return AiRiskAssessment(
        score=score,
        category=category,
        feature_provenance={
            "source_event_id": physics.event_id,
            "miss_distance_km": miss,
            "screening_threshold_km": threshold,
            "relative_speed_km_s": speed,
            "proximity_component": proximity,
            "speed_component": speed_component,
            "speed_normalization_reference_km_s": SPEED_REFERENCE_KM_S,
            "weights": {"proximity": proximity_weight / total, "relative_speed": speed_weight / total},
            "source": "screening_pipeline PhysicsResult; propagated SGP4 TLE encounter geometry",
        },
        model_quality={
            "status": "deterministic_fallback_not_trained_or_calibrated",
            "validation_metrics": None,
            "limitations": [
                "Queue index is not a collision probability, Foster Pc, or calibrated event-risk probability.",
                "Relative speed reference is a normalization scale, not an empirically validated threshold.",
                "ESA log10-risk regressor is withheld because historical and live feature semantics are unverified.",
                *(["TCA is at a screening-horizon boundary; review separately from interior TCA solutions."] if physics.status == "boundary" or physics.tca_status == "boundary" else []),
            ],
        },
        explanation=(
            f"Normalized geometry/speed queue index: proximity {proximity:.3f} "
            f"(miss {miss:g} km / {threshold:g} km screen), relative-speed component "
            f"{speed_component:.3f} (reference {SPEED_REFERENCE_KM_S:g} km/s); "
            "deterministic fallback, not Pc or trained ESA prediction."
        ),
    )


def rank_screening_events(events: list[ConjunctionAssessmentEvent]) -> list[ConjunctionAssessmentEvent]:
    """Attach stable geometry, numeric-Pc-evidence, and final queue ranks."""
    eligible = [
        event for event in events
        if event.physics_result.status in {"valid", "boundary"} and event.ai_risk_assessment is not None
    ]
    geometry_order = sorted(eligible, key=lambda event: (
        _miss_fraction(event), event.id
    ))
    geometry_rank = {event.id: index + 1 for index, event in enumerate(geometry_order)}

    foster_values = {event.id: _foster_pc_decimal(event) for event in eligible}
    research_values = {event.id: _research_log10_pc_decimal(event) for event in eligible}
    foster_order = sorted((e for e in eligible if foster_values[e.id] is not None), key=lambda e: (-foster_values[e.id], e.id))  # type: ignore[operator]
    research_order = sorted(
        (e for e in eligible if research_values[e.id] is not None),
        key=lambda e: (-research_values[e.id], _research_miss_sigma(e), e.id),  # type: ignore[operator]
    )
    foster_rank = {event.id: index + 1 for index, event in enumerate(foster_order)}
    research_rank = {event.id: index + 1 for index, event in enumerate(research_order)}

    # A Pc percentile enters the final queue score only when every eligible
    # event has a value from the same provenance pathway. Foster and the
    # assumption-based ESA prior are not directly comparable.
    kinds = {"foster" for value in foster_values.values() if value is not None} | {
        "research_prior" for value in research_values.values() if value is not None
    }
    pc_order = foster_order if len(eligible) > 1 and kinds == {"foster"} and len(foster_order) == len(eligible) else (
        research_order if len(eligible) > 1 and kinds == {"research_prior"} and len(research_order) == len(eligible) else []
    )
    pc_rank = {event.id: index + 1 for index, event in enumerate(pc_order)}
    pc_signal = {event.id: (len(pc_order) - pc_rank[event.id] + 1) / len(pc_order) for event in pc_order} if pc_order else {}

    final_scores: dict[str, float] = {}
    for event in eligible:
        ai = event.ai_risk_assessment
        assert ai is not None
        geom = max(0.0, min(1.0, 1.0 - _miss_fraction(event)))
        if event.id in pc_signal:
            # Within-job percentile only; it does not rescale or calibrate Pc.
            final_scores[event.id] = 0.50 * ai.score + 0.30 * geom + 0.20 * pc_signal[event.id]
        else:
            final_scores[event.id] = (0.50 * ai.score + 0.30 * geom) / 0.80
    final_order = sorted(eligible, key=lambda event: (-final_scores[event.id], event.id))
    final_rank = {event.id: index + 1 for index, event in enumerate(final_order)}

    updated: list[ConjunctionAssessmentEvent] = []
    for event in events:
        assessment = event.ai_risk_assessment
        if assessment is None or event.id not in final_rank:
            updated.append(event)
            continue
        pc_basis = (
            "a within-screening-set percentile from event-specific Foster Pc"
            if event.id in pc_signal and event.id in foster_rank else
            "a within-screening-set percentile from the labeled ESA-prior research Pc"
            if event.id in pc_signal and event.id in research_rank else
            "Pc evidence has a separate source-specific rank and is excluded from the composite"
            if event.id in foster_rank or event.id in research_rank else
            "no numerical, event-bound Pc was available"
        )
        explanation = (
            "Final priority combines 50% deterministic rule-based review priority, 30% normalized geometry, "
            f"and 20% relative Pc percentile only in a multi-event result where every event has the same Pc provenance ({pc_basis}); "
            "otherwise review-priority and geometry weights are renormalized and Pc rankings remain separate. "
            "An ESA-prior Pc retains its unvalidated research-prior status and is not treated as operationally calibrated."
        )
        updated.append(event.model_copy(update={"ai_risk_assessment": assessment.model_copy(update={
            "geometry_rank": geometry_rank.get(event.id),
            "foster_pc_rank": foster_rank.get(event.id),
            "research_pc_rank": research_rank.get(event.id),
            "final_priority_rank": final_rank[event.id],
            "final_priority_score": final_scores[event.id],
            "ranking_explanation": explanation,
        })}))
    return updated


def _miss_fraction(event: ConjunctionAssessmentEvent) -> float:
    miss = _finite_nonnegative(event.physics_result.miss_distance.value)
    threshold = _finite_positive(event.physics_result.screening_threshold_km)
    return min(miss / threshold, 1.0) if miss is not None and threshold is not None else math.inf


def _foster_pc_decimal(event: ConjunctionAssessmentEvent) -> Decimal | None:
    result = event.collision_probability
    if (result is not None and result.status == "available" and result.event_id == event.id
            and result.pc is not None and math.isfinite(result.pc) and 0 <= result.pc <= 1):
        return Decimal(str(result.pc))
    return None


def _research_log10_pc_decimal(event: ConjunctionAssessmentEvent) -> Decimal | None:
    research = event.automatic_research_pc_assessment
    if (research is None or research.status != "prior_based_research_estimate"
            or event.physics_result.status != "valid" or event.physics_result.tca_status != "valid"):
        return None
    try:
        value = Decimal(str(research.log10_pc))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def _research_miss_sigma(event: ConjunctionAssessmentEvent) -> Decimal:
    research = event.automatic_research_pc_assessment
    try:
        value = Decimal(str(research.miss_sigma_ratio if research is not None else None))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("Infinity")
    return value if value.is_finite() and value >= 0 else Decimal("Infinity")


def _finite_nonnegative(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _finite_positive(value: Any) -> float | None:
    number = _finite_nonnegative(value)
    return number if number is not None and number > 0 else None


def _configured_weight(key: str, default: float) -> float:
    try:
        value = float(os.environ.get(key, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _category_cutoffs() -> dict[str, float]:
    try:
        critical = float(os.environ.get("ORION_AI_CRITICAL_SCORE", "0.80"))
        high = float(os.environ.get("ORION_AI_HIGH_SCORE", "0.60"))
        medium = float(os.environ.get("ORION_AI_MEDIUM_SCORE", "0.35"))
        if not (0 <= medium < high < critical <= 1) or not all(map(math.isfinite, (medium, high, critical))):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        medium, high, critical = 0.35, 0.60, 0.80
    return {"medium": medium, "high": high, "critical": critical}
