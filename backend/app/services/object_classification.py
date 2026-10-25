"""Catalog object types first, then explicit name patterns, then source group."""

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
    "STATION": ("station", "SPACE_STATION"),
    "SPACE STATION": ("station", "SPACE_STATION"),
    "SPACE_STATION": ("station", "SPACE_STATION"),
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
    name: str | None = None,
) -> ObjectClassification:
    """Use explicit catalog type, recognized name patterns, then group fallback.

    Category is a legacy derived field, so it is considered only after the
    catalog object type and raw source classification. Group-derived values
    are explicitly tagged so the UI can identify their weaker provenance.
    """
    # A specific rocket-body designation in the catalog name is stronger than
    # a broad or stale payload type supplied by a source group.
    named = _classify_name(name)
    if named is not None and named.object_type == "ROCKET_BODY":
        return named

    for raw, source in ((object_type, "catalog_object_type"), (source_classification, "source_classification")):
        if not isinstance(raw, str) or not raw.strip():
            continue
        mapped = _TYPE_MAP.get(raw.strip().upper())
        if mapped is not None:
            return ObjectClassification(mapped[0], mapped[1], source, raw.strip())

    inferred = _classify_name(name)
    if inferred is not None:
        return inferred

    mapped_category = _TYPE_MAP.get((category or "").strip().upper()) if isinstance(category, str) else None
    if mapped_category is not None:
        return ObjectClassification(mapped_category[0], mapped_category[1], "group_based_fallback", source_classification)

    group = (source_group or "").strip().lower().replace("-", "_")
    if group in {"stations", "visual", "weather", "gps_ops"}:
        return ObjectClassification("payload", "ACTIVE_SATELLITE", "group_based_fallback", source_classification)
    if group.endswith("_debris") or group == "debris":
        return ObjectClassification("debris", "SPACE_DEBRIS", "group_based_fallback", source_classification)
    return ObjectClassification("unknown", "UNKNOWN", "classification_unavailable", source_classification)


def _classify_name(name: str | None) -> ObjectClassification | None:
    if not isinstance(name, str) or not name.strip():
        return None
    upper = " ".join(name.upper().replace("_", " ").split())
    if "R/B" in upper or "ROCKET BODY" in upper:
        return ObjectClassification("rocket_body", "ROCKET_BODY", "name_pattern", name)
    if any(token in upper.split() for token in ("DEB", "DEBRIS", "FRAGMENT")):
        return ObjectClassification("debris", "SPACE_DEBRIS", "name_pattern", name)
    station_names = {
        "ISS", "ZARYA", "ZVEZDA", "NAUKA", "POISK", "RASSVET", "UNITY",
        "DESTINY", "HARMONY", "COLUMBUS", "KIBO", "QUEST", "TRANQUILITY",
        "CUPOLA", "PMM", "BISHOP", "PIRS", "PROGRESS", "SOYUZ",
    }
    if any(token in station_names for token in upper.replace("(", " ").replace(")", " ").split()):
        return ObjectClassification("station", "SPACE_STATION", "name_pattern", name)
    if "PAYLOAD" in upper:
        return ObjectClassification("payload", "ACTIVE_SATELLITE", "name_pattern", name)
    return None


def pair_type_for(primary_type: str | None, secondary_type: str | None) -> str:
    labels = {"ACTIVE_SATELLITE": "SATELLITE", "SPACE_DEBRIS": "DEBRIS", "ROCKET_BODY": "ROCKET BODY", "SPACE_STATION": "STATION", "UNKNOWN": "UNKNOWN"}
    order = {"SATELLITE": 0, "STATION": 1, "DEBRIS": 2, "ROCKET BODY": 3, "UNKNOWN": 4}
    first = labels.get(primary_type or "UNKNOWN", "UNKNOWN")
    second = labels.get(secondary_type or "UNKNOWN", "UNKNOWN")
    return " vs ".join(sorted((first, second), key=lambda label: order[label]))

