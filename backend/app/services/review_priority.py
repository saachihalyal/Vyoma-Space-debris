"""Versioned internal geometry-only review triage.

Categories are an ORION queueing policy based on a valid event's miss
distance relative to its configured screening threshold. They are not
collision-risk classes, probabilities, or NASA/ESA operational thresholds.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.models import PhysicsResult, ReviewPriority


@dataclass(frozen=True)
class ReviewPriorityPolicy:
    version: str = "orion-geometry-review-v1"
    critical_max_fraction: float = 0.05
    high_max_fraction: float = 0.20
    medium_max_fraction: float = 0.60

    def validate(self) -> None:
        limits = (self.critical_max_fraction, self.high_max_fraction, self.medium_max_fraction)
        if (not all(math.isfinite(value) for value in limits)
                or not 0 < limits[0] < limits[1] < limits[2] <= 1):
            raise ValueError("REVIEW_PRIORITY_POLICY_CONFIGURATION_INVALID")


def configured_policy(environ: dict[str, str] | None = None) -> ReviewPriorityPolicy:
    values = os.environ if environ is None else environ
    policy = ReviewPriorityPolicy(
        version=values.get("ORION_REVIEW_POLICY_VERSION", "orion-geometry-review-v1"),
        critical_max_fraction=float(values.get("ORION_REVIEW_CRITICAL_MAX_FRACTION", "0.05")),
        high_max_fraction=float(values.get("ORION_REVIEW_HIGH_MAX_FRACTION", "0.20")),
        medium_max_fraction=float(values.get("ORION_REVIEW_MEDIUM_MAX_FRACTION", "0.60")),
    )
    policy.validate()
    return policy


def policy_status() -> dict[str, Any]:
    try:
        policy = configured_policy()
    except (TypeError, ValueError, OverflowError):
        return {"status": "unavailable", "reason_code": "REVIEW_PRIORITY_POLICY_CONFIGURATION_INVALID"}
    return {
        "status": "available",
        "policy_name": "ORION Geometry-only Review Priority",
        "policy_version": policy.version,
        "thresholds": {
            "critical_max_miss_distance_fraction": policy.critical_max_fraction,
            "high_max_miss_distance_fraction": policy.high_max_fraction,
            "medium_max_miss_distance_fraction": policy.medium_max_fraction,
        },
        "signals_used": ["valid_miss_distance_km", "event_screening_threshold_km"],
        "signals_excluded": ["physical_pc", "esa_ml_output", "relative_speed", "object_type"],
    }


def classify_review_priority(
    physics: PhysicsResult,
    *,
    policy: ReviewPriorityPolicy | None = None,
    ml_status: str | None = None,
    pc_status: str | None = None,
) -> ReviewPriority:
    """Classify only valid geometry; ML and Pc are explicitly excluded inputs."""
    try:
        active_policy = policy or configured_policy()
        active_policy.validate()
    except (TypeError, ValueError, OverflowError):
        return _unavailable("REVIEW_PRIORITY_POLICY_CONFIGURATION_INVALID", "Review priority is unclassified because the configured ORION policy is invalid.")

    if physics.status == "invalid" or physics.tca_status == "invalid":
        reasons = physics.reason_codes or ["PHYSICS_ASSESSMENT_INVALID"]
        return ReviewPriority(
            category="REVIEW_REQUIRED", status="review_required", policy_version=active_policy.version,
            evidence=list(reasons), reason_codes=list(reasons),
            input_signals={"physics_status": physics.status, "tca_status": physics.tca_status,
                           "ml_status": ml_status or "unavailable", "pc_status": pc_status or "unavailable"},
            limitations=["Invalid trajectory assessments are never assigned a geometry priority."],
            explanation="Review required: the selected trajectory assessment is invalid (" + ", ".join(reasons) + ").",
        )
    if physics.status != "valid" or physics.tca_status != "valid":
        reason = "INTERIOR_VALID_TCA_REQUIRED"
        return ReviewPriority(
            category="REVIEW_REQUIRED", status="review_required", policy_version=active_policy.version,
            evidence=[physics.status, physics.tca_status], reason_codes=[reason],
            limitations=["Boundary and non-valid trajectory solutions are not assigned a geometry priority."],
            explanation="Review required: an interior, valid TCA assessment is required for this triage policy.",
        )

    tca_text = _format_time(physics.tca.value) if physics.tca.status == "available" else "unavailable"
    miss = _available_number(physics.miss_distance.value, physics.miss_distance.status)
    threshold = physics.screening_threshold_km
    if tca_text == "unavailable" or miss is None or threshold is None or not math.isfinite(threshold) or threshold <= 0:
        missing = []
        if tca_text == "unavailable": missing.append("VALID_TCA_REQUIRED")
        if miss is None: missing.append("VALID_MISS_DISTANCE_REQUIRED")
        if threshold is None or not math.isfinite(threshold) or threshold <= 0: missing.append("POSITIVE_SCREENING_THRESHOLD_REQUIRED")
        return _unavailable(";".join(missing), "Review priority is unclassified because " + ", ".join(missing).lower().replace("_", " ") + ".", active_policy.version)

    fraction = miss / threshold
    if fraction <= active_policy.critical_max_fraction:
        category = "CRITICAL"
        applied = f"miss_distance / screening_threshold <= {active_policy.critical_max_fraction:g}"
    elif fraction <= active_policy.high_max_fraction:
        category = "HIGH"
        applied = f"miss_distance / screening_threshold <= {active_policy.high_max_fraction:g}"
    elif fraction <= active_policy.medium_max_fraction:
        category = "MEDIUM"
        applied = f"miss_distance / screening_threshold <= {active_policy.medium_max_fraction:g}"
    else:
        category = "LOW"
        applied = f"miss_distance / screening_threshold > {active_policy.medium_max_fraction:g}"
    band_number = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}[category]
    evidence = [
        f"Miss distance {miss:g} km against configured screening threshold {threshold:g} km (fraction {fraction:.6g}).",
        f"TCA {tca_text}.",
    ]
    return ReviewPriority(
        category=category, status="classified", policy_version=active_policy.version,
        criteria={
            "miss_distance_fraction": fraction,
            "applied_rule": applied,
            "critical_max_fraction": active_policy.critical_max_fraction,
            "high_max_fraction": active_policy.high_max_fraction,
            "medium_max_fraction": active_policy.medium_max_fraction,
            "screening_threshold_km": threshold,
        },
        input_signals={
            "miss_distance_km": miss,
            "screening_threshold_km": threshold,
            "tca_utc": physics.tca.value,
            "physics_status": physics.status,
            "ml_status": ml_status or "unavailable",
            "pc_status": pc_status or "unavailable",
            "ml_signal_used": False,
            "pc_signal_used": False,
        },
        evidence=evidence,
        limitations=[
            "This geometry-only ORION internal review queue is not a physical collision-risk classification or Pc estimate.",
            "TCA, relative speed, object type, physical Pc, and ML output do not change this category; ML and Pc are reported separately.",
        ],
        explanation=(f"Geometry review band {band_number} under {active_policy.version}: "
                     f"miss distance is {fraction:.3%} of the configured screening threshold; TCA is {tca_text}. "
                     "This is geometry-only triage, not a collision probability or operational risk label."),
    )


def _available_number(value: Any, status: str) -> float | None:
    if status != "available" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _format_time(value: Any) -> str:
    if not isinstance(value, str):
        return "unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return "unavailable"
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return "unavailable"


def _unavailable(reason_code: str, explanation: str, version: str = "orion-geometry-review-v1") -> ReviewPriority:
    return ReviewPriority(
        category="UNCLASSIFIED", status="unclassified", policy_version=version,
        reason_codes=reason_code.split(";"), explanation=explanation,
        limitations=["Required valid assessment evidence is missing or the review policy configuration is invalid."],
    )
