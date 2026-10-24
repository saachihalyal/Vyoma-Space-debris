"""Classification from explicit catalog metadata; names are never evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectClassification:
    category: str
    object_type: str
    classification_source: str
    source_classification: str | None = None


_TYPE_MAP = {
    "PAYLOAD": ("payload", "ACTIVE_SATELLITE"),
    "ACTIVE": ("payload", "ACTIVE_SATELLITE"),
    "ACTIVE SATELLITE": ("payload", "ACTIVE_SATELLITE"),
    "ACTIVE_SATELLITE": ("payload", "ACTIVE_SATELLITE"),
    "SATELLITE": ("payload", "ACTIVE_SATELLITE"),
    "SPACECRAFT": ("payload", "ACTIVE_SATELLITE"),
    "DEBRIS": ("debris", "SPACE_DEBRIS"),
    "SPACE DEBRIS": ("debris", "SPACE_DEBRIS"),
    "SPACE_DEBRIS": ("debris", "SPACE_DEBRIS"),
    "FRAGMENT": ("debris", "SPACE_DEBRIS"),
    "ROCKET BODY": ("rocket_body", "ROCKET_BODY"),
    "ROCKET_BODY": ("rocket_body", "ROCKET_BODY"),
    "R/B": ("rocket_body", "ROCKET_BODY"),
    "UNKNOWN": ("unknown", "UNKNOWN"),
    "OTHER": ("unknown", "UNKNOWN"),
    "UNKNOWN / OTHER": ("unknown", "UNKNOWN"),
}


def classify_object(
    *,
    object_type: str | None = None,
    category: str | None = None,
    source_classification: str | None = None,
    source_group: str | None = None,
) -> ObjectClassification:
    """Prefer explicit source type; known curated groups are a limited fallback.

    If supplied metadata conflicts or is unsupported, preserve its raw value but
    report UNKNOWN. TLE display names and conjunction roles are not consulted.
    """
    supplied = [v.strip() for v in (source_classification, object_type, category) if isinstance(v, str) and v.strip()]
    mapped = [_TYPE_MAP.get(v.upper()) for v in supplied]
    mapped_known = [m for m in mapped if m is not None]
    if supplied:
        distinct = set(mapped_known)
        if len(distinct) == 1 and len(mapped_known) == len(supplied):
            category_value, type_value = mapped_known[0]
            return ObjectClassification(category_value, type_value, "source_metadata", source_classification or supplied[0])
        if len(distinct) > 1 or not mapped_known:
            return ObjectClassification("unknown", "UNKNOWN", "conflicting_or_unsupported_metadata", source_classification or "; ".join(supplied))

    group = (source_group or "").strip().lower().replace("-", "_")
    if group in {"stations", "visual", "weather", "gps_ops"}:
        return ObjectClassification("payload", "ACTIVE_SATELLITE", "celestrak_group", source_classification)
    if group.endswith("_debris") or group == "debris":
        return ObjectClassification("debris", "SPACE_DEBRIS", "celestrak_group", source_classification)
    return ObjectClassification("unknown", "UNKNOWN", "classification_unavailable", source_classification)


def pair_type_for(primary_type: str | None, secondary_type: str | None) -> str:
    labels = {"ACTIVE_SATELLITE": "SATELLITE", "SPACE_DEBRIS": "DEBRIS", "ROCKET_BODY": "ROCKET BODY", "UNKNOWN": "UNKNOWN"}
    order = {"SATELLITE": 0, "DEBRIS": 1, "ROCKET BODY": 2, "UNKNOWN": 3}
    first = labels.get(primary_type or "UNKNOWN", "UNKNOWN")
    second = labels.get(secondary_type or "UNKNOWN", "UNKNOWN")
    return " vs ".join(sorted((first, second), key=lambda label: order[label]))

