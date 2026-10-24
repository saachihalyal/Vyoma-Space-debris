"""Reference bands for interpreting a numeric Pc, separate from geometry and ML."""

from __future__ import annotations

import math
import os
from typing import Any


POLICY_NAME = "NASA CARA published Pc reference bands"
POLICY_VERSION = "nasa-cara-pc-reference-v1"
ATTENTION_THRESHOLD = 1e-7
MITIGATION_THRESHOLD = 1e-4
REFERENCE_URL = "https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/"
ORION_RISK_POLICY_NAME = "ORION Physics Pc Risk Policy"
ORION_RISK_POLICY_VERSION = "orion-physics-pc-risk-v2"
DEFAULT_HIGH_PC_THRESHOLD = 1e-4
DEFAULT_MEDIUM_PC_THRESHOLD = 1e-7


def classify_orion_physics_pc(pc: Any, pc_channel: str, *, log10_pc: float | None = None) -> dict[str, Any]:
    """Score and classify a physics Pc channel under ORION's project policy.

    A log10 value preserves classifications for positive probabilities below
    binary64's float range. Numeric Pc=0 uses the mathematical Pc->0 limit and
    never substitutes a fabricated positive probability.
    """
    if pc_channel not in {"event_specific_foster_pc", "research_pc"}:
        return _orion_unavailable("SUPPORTED_PC_CHANNEL_REQUIRED", pc_channel)
    if pc is not None and (isinstance(pc, bool) or not isinstance(pc, (int, float)) or not math.isfinite(pc) or pc < 0.0 or pc > 1.0):
        return _orion_unavailable("VALID_NUMERIC_PC_REQUIRED", pc_channel)
    if log10_pc is not None and (
        isinstance(log10_pc, bool) or not isinstance(log10_pc, (int, float))
        or math.isnan(log10_pc) or log10_pc > 0.0
        or (not math.isfinite(log10_pc) and not (log10_pc == float("-inf") and pc == 0.0))
    ):
        return _orion_unavailable("VALID_LOG10_PC_REQUIRED", pc_channel)
    if pc is not None and log10_pc is not None:
        expected_log10 = float("-inf") if pc == 0 else math.log10(float(pc))
        if not math.isclose(float(log10_pc), expected_log10, rel_tol=0.0, abs_tol=1e-12):
            return _orion_unavailable("PC_LOG10_PC_MISMATCH", pc_channel)
    if log10_pc is None:
        if pc is None:
            return _orion_unavailable("VALID_NUMERIC_PC_REQUIRED", pc_channel)
        log10_value = float("-inf") if pc == 0 else math.log10(float(pc))
    else:
        log10_value = float(log10_pc)

    try:
        high_threshold = float(os.environ.get("ORION_RISK_HIGH_PC", str(DEFAULT_HIGH_PC_THRESHOLD)))
        score_floor = float(os.environ.get("ORION_RISK_SCORE_LOG10_FLOOR", "-12"))
        score_ceiling = float(os.environ.get("ORION_RISK_SCORE_LOG10_CEILING", "-2"))
        medium_threshold = float(os.environ.get("ORION_RISK_MEDIUM_PC", str(DEFAULT_MEDIUM_PC_THRESHOLD)))
        if not (math.isfinite(high_threshold) and math.isfinite(medium_threshold)
                and 0 < medium_threshold < high_threshold <= 1
                and math.isfinite(score_floor) and math.isfinite(score_ceiling) and score_floor < score_ceiling):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return _orion_unavailable("RISK_THRESHOLD_CONFIGURATION_INVALID", pc_channel)

    score = 0.0 if log10_value == float("-inf") else min(100.0, max(0.0, ((log10_value - score_floor) / (score_ceiling - score_floor)) * 100.0))
    high_log = math.log10(high_threshold)
    medium_log = math.log10(medium_threshold)
    risk_class = "High" if log10_value >= high_log else "Medium" if log10_value >= medium_log else "Low"
    return {
        "status": "classified",
        "risk_score": score,
        "risk_score_policy_name": ORION_RISK_POLICY_NAME,
        "risk_score_policy_version": ORION_RISK_POLICY_VERSION,
        "risk_score_pc_channel": pc_channel,
        "physics_risk_class": risk_class,
        "final_risk_class": risk_class,
        "classification_basis": f"{risk_class} from {pc_channel} under {ORION_RISK_POLICY_VERSION}; this physics class controls the displayed final class.",
        "log10_pc": log10_value if math.isfinite(log10_value) else None,
        "thresholds": {"high_pc_inclusive": high_threshold, "medium_pc_inclusive": medium_threshold},
        "score_window_log10_pc": {"floor": score_floor, "ceiling": score_ceiling},
        "boundary_policy": "Pc=0 is classified by the Pc->0 limit with score 0; no positive Pc is substituted." if pc == 0 else None,
        "limitations": [
            "Thresholds are ORION project policy, not universal safety standards.",
            "Risk score and class are derived from physics Pc only; AI and geometry priority remain separate.",
        ],
    }


def _orion_unavailable(reason_code: str, pc_channel: str) -> dict[str, Any]:
    return {
        "status": "unavailable", "risk_score": None, "risk_score_policy_name": ORION_RISK_POLICY_NAME,
        "risk_score_policy_version": ORION_RISK_POLICY_VERSION, "risk_score_pc_channel": pc_channel,
        "physics_risk_class": None, "final_risk_class": None, "classification_basis": None,
        "log10_pc": None, "thresholds": None, "boundary_policy": None,
        "reason_code": reason_code,
        "limitations": ["A valid Pc and threshold configuration are required for the physics risk policy."],
    }


def classify_probability_pc(pc: Any) -> dict[str, Any]:
    """Apply NASA-published attention/mitigation reference values, not action advice."""
    if isinstance(pc, bool) or not isinstance(pc, (int, float)) or not math.isfinite(pc) or not 0.0 < pc <= 1.0:
        return {
            "status": "unavailable",
            "category": None,
            "policy_name": POLICY_NAME,
            "policy_version": POLICY_VERSION,
            "reason_code": "VALID_NUMERIC_PC_REQUIRED",
            "explanation": "A probability-based category requires an available numeric Pc in (0, 1].",
        }
    if pc > MITIGATION_THRESHOLD:
        category = "ABOVE_NASA_MITIGATION_REFERENCE"
        explanation = "Pc exceeds NASA CARA's published 1e-4 mitigation reference; this comparison is not an action recommendation for this project."
    elif pc > ATTENTION_THRESHOLD:
        category = "ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE"
        explanation = "Pc is above NASA CARA's published 1e-7 attention reference and at or below its 1e-4 mitigation reference; this comparison is not an action recommendation for this project."
    else:
        category = "AT_OR_BELOW_NASA_ATTENTION_REFERENCE"
        explanation = "Pc is at or below NASA CARA's published 1e-7 attention reference; this comparison is not an operational risk decision."
    return {
        "status": "classified",
        "category": category,
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "pc": float(pc),
        "thresholds": {
            "attention_reference_exclusive": ATTENTION_THRESHOLD,
            "mitigation_reference_exclusive": MITIGATION_THRESHOLD,
        },
        "source_url": REFERENCE_URL,
        "explanation": explanation,
        "limitations": [
            "NASA describes these as CARA conjunction-assessment reference values; mission action thresholds depend on mission risk posture and mitigation capacity.",
            "This classification is based on Pc only; it does not include collision consequence, covariance realism, or data actionability.",
            "This is separate from ORION geometry review priority and the ESA ML log-risk estimate.",
        ],
    }
