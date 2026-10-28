"""Versioned feature contract for physics-supervised collision surrogates."""

from __future__ import annotations

import math
from typing import Any

from app.models import ConjunctionAssessmentEvent


FEATURE_SCHEMA_VERSION = "orion-collision-features-v3"
OBJECT_CATEGORIES = ("active", "debris", "payload", "rocket_body", "unknown")
NUMERIC_FEATURES = (
    "miss_distance_km",
    "relative_speed_km_s",
    "primary_tle_age_days",
    "secondary_tle_age_days",
    "primary_altitude_km",
    "secondary_altitude_km",
    "primary_inclination_deg",
    "secondary_inclination_deg",
    "hbr_km",
    "covariance_scale",
    "hbr_scale",
    "miss_sigma_ratio",
    "miss_sigma_ratio_squared",
    "log10_hbr_area_to_covariance",
)
FEATURE_NAMES = NUMERIC_FEATURES + tuple(
    f"{prefix}_category_{category}"
    for prefix in ("primary", "secondary")
    for category in OBJECT_CATEGORIES
)
FEATURE_UNITS = {
    "miss_distance_km": "km",
    "relative_speed_km_s": "km/s",
    "primary_tle_age_days": "day at TCA",
    "secondary_tle_age_days": "day at TCA",
    "primary_altitude_km": "km",
    "secondary_altitude_km": "km",
    "primary_inclination_deg": "degree",
    "secondary_inclination_deg": "degree",
    "hbr_km": "km, assumed research HBR",
    "covariance_scale": "dimensionless assumed scenario multiplier",
    "hbr_scale": "dimensionless assumed scenario multiplier",
    "miss_sigma_ratio": "Mahalanobis distance in encounter-plane sigma units",
    "miss_sigma_ratio_squared": "squared Mahalanobis distance in encounter-plane sigma units",
    "log10_hbr_area_to_covariance": "log10(HBR^2 / (2 * sqrt(det(sigma2D))))",
    **{
        f"{prefix}_category_{category}": "one-hot object category"
        for prefix in ("primary", "secondary")
        for category in OBJECT_CATEGORIES
    },
}


def build_collision_features(
    event: ConjunctionAssessmentEvent,
    assessment: Any | None = None,
    *,
    allow_imputation: bool = False,
) -> dict[str, float] | None:
    """Build the declared feature contract; pipelines may impute absent numerics."""
    physics = event.physics_result
    research = assessment or event.automatic_research_pc_assessment
    if physics.status != "valid" or physics.tca_status != "valid" or research is None:
        return None
    if research.status != "prior_based_research_estimate" or research.hbr_km is None:
        return None

    metadata = research.provenance.get("object_metadata") or {}
    primary_metadata = metadata.get(event.primary.id) or {}
    secondary_metadata = metadata.get(event.secondary.id) or {}
    values: dict[str, float] = {
        "miss_distance_km": physics.miss_distance.value,
        "relative_speed_km_s": physics.relative_speed_at_tca.value,
        "primary_tle_age_days": primary_metadata.get("tle_age_days"),
        "secondary_tle_age_days": secondary_metadata.get("tle_age_days"),
        "primary_altitude_km": event.primary.altitude_km,
        "secondary_altitude_km": event.secondary.altitude_km,
        "primary_inclination_deg": event.primary.inclination_deg,
        "secondary_inclination_deg": event.secondary.inclination_deg,
        "hbr_km": research.hbr_km,
        "covariance_scale": research.provenance.get("scenario_covariance_scale", 1.0),
        "hbr_scale": research.provenance.get("scenario_hbr_scale", 1.0),
        "miss_sigma_ratio": research.miss_sigma_ratio,
        "miss_sigma_ratio_squared": (research.miss_sigma_ratio ** 2) if research.miss_sigma_ratio is not None else None,
        "log10_hbr_area_to_covariance": _log_hbr_covariance_ratio(research),
    }
    for prefix, obj in (("primary", event.primary), ("secondary", event.secondary)):
        for category in OBJECT_CATEGORIES:
            values[f"{prefix}_category_{category}"] = float(obj.category == category)
    invalid = [name for name, value in values.items()
               if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)]
    if invalid and not allow_imputation:
        return None
    return {name: float(values[name]) if name not in invalid else float("nan") for name in FEATURE_NAMES}


def missing_collision_features(features: dict[str, float] | None) -> list[str]:
    """Names that the validated pipeline's median imputer must supply."""
    if not isinstance(features, dict):
        return list(FEATURE_NAMES)
    return [name for name in FEATURE_NAMES if not isinstance(features.get(name), (int, float)) or not math.isfinite(features[name])]


def _log_hbr_covariance_ratio(research: Any) -> float | None:
    sigma_min = research.encounter_plane_sigma_min_km
    sigma_max = research.encounter_plane_sigma_max_km
    hbr = research.hbr_km
    if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0
               for value in (sigma_min, sigma_max, hbr)):
        return None
    return math.log10(hbr * hbr / (2.0 * sigma_min * sigma_max))
