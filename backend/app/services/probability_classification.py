"""Reference bands for interpreting a numeric Pc, separate from geometry and ML."""

from __future__ import annotations

import math
from typing import Any


POLICY_NAME = "NASA CARA published Pc reference bands"
POLICY_VERSION = "nasa-cara-pc-reference-v1"
ATTENTION_THRESHOLD = 1e-7
MITIGATION_THRESHOLD = 1e-4
REFERENCE_URL = "https://www.nasa.gov/cara/step-2-close-approach-risk-assessment/"


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
