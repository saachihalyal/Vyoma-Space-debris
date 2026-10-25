from __future__ import annotations

import math
import random
from importlib.metadata import PackageNotFoundError, version as package_version
from datetime import datetime, timezone

import numpy as np
from sgp4.api import Satrec, WGS72, jday

from app.models import OrbitVisual, Provenance, SpaceObject, UnavailableCatalogObject
from app.services.tle_provider import TleRecord, _valid_tle_record, satellite_from_record
from app.services.object_classification import classify_object


EARTH_RADIUS_KM = 6378.137


def classify_band(altitude_km: float) -> str:
    if altitude_km < 2_000:
        return "LEO"
    if altitude_km < 30_000:
        return "MEO"
    if altitude_km < 45_000:
        return "GEO"
    return "HEO"


def category_from_record(record: TleRecord) -> str:
    return classify_object(
        object_type=record.object_type,
        source_classification=record.source_classification,
        source_group=record.source_group,
        name=record.name,
    ).category


def orbit_type_for(band: str, inclination_deg: float) -> str:
    if band == "GEO":
        return "Geostationary belt"
    if band == "MEO":
        return "Navigation/MEO shell"
    if inclination_deg > 80:
        return "Polar LEO"
    if inclination_deg > 45:
        return "High-inclination LEO"
    return "Low-inclination LEO"


def visual_radius_for_altitude(altitude_km: float) -> float:
    if altitude_km <= 2_000:
        return 2.22 + altitude_km / 1_850
    if altitude_km <= 30_000:
        return 3.55 + (altitude_km - 2_000) / 3_400
    return 11.75 + min(5.5, (altitude_km - 30_000) / 2_500)


def propagate_records(
    records: list[TleRecord], limit: int, now: datetime | None = None
) -> tuple[list[SpaceObject], str | None, list[UnavailableCatalogObject]]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6)
    objects: list[SpaceObject] = []
    unavailable: list[UnavailableCatalogObject] = []
    tle_epoch: str | None = None
    try:
        sgp4_version = package_version("sgp4")
    except PackageNotFoundError:  # pragma: no cover - package is required by the backend
        sgp4_version = "unknown"

    for index, record in enumerate(records[:limit]):
        catalog_id = record.catalog_id or ""
        object_id = catalog_id or f"UNVERIFIED-{record.input_hash[:12]}"
        source_type = record.source_type if record.source_type in {"live", "fallback", "synthetic"} else "unavailable"
        classification = classify_object(
            object_type=record.object_type,
            source_classification=record.source_classification,
            source_group=record.source_group,
            name=record.name,
        )
        provenance = Provenance(
            source=(f"CelesTrak GP/{record.source_format} group={record.source_group}" if source_type == "live" else f"{record.source_group} {record.source_format} input"),
            source_type=source_type,  # type: ignore[arg-type]
            source_timestamp=record.source_timestamp,
            element_epoch=record.element_epoch,
            propagation_epoch=now.isoformat(),
            reference_frame="TEME",
            units={"position": "km", "velocity": "km/s", "altitude": "km", "inclination": "deg"},
            catalog_id=catalog_id or None,
            object_id=object_id,
            input_hash=record.input_hash,
            propagator="python-sgp4 SGP4/SDP4",
            propagator_version=sgp4_version,
            propagator_configuration={"api": "Satrec.twoline2rv" if record.omm_fields is None else "sgp4.omm.initialize", "gravity_model": "WGS72", "position_output_frame": "TEME", "source_format": record.source_format},
            method=f"SGP4 {record.source_format} propagation",
            method_version=sgp4_version,
            validity_status="not_assessed",
            is_synthetic=source_type == "synthetic",
            is_fallback=source_type == "fallback",
        )
        provenance.source_record = {
            "source_group": record.source_group,
            "object_type": classification.object_type,
            "source_classification": classification.source_classification,
            "classification_source": classification.classification_source,
        }
        try:
            if not _valid_tle_record(record):
                raise ValueError(f"invalid {record.source_format} fields")
            if record.omm_fields is None:
                if len(record.line1) < 2 or not record.line1.startswith("1 ") or not record.line2.startswith("2 "):
                    raise ValueError("TLE lines must begin with line numbers 1 and 2")
                if record.line1[2:7] != record.line2[2:7]:
                    raise ValueError("TLE line catalog identifiers do not match")
            sat = satellite_from_record(record)
            provenance.source_record = {
                "source_url": record.source_url,
                "source_group": record.source_group,
                "object_type": classification.object_type,
                "source_classification": classification.source_classification,
                "classification_source": classification.classification_source,
                "retrieval_http_status": record.retrieval_http_status,
                "retrieval_timestamp": record.source_timestamp,
                "raw_response_hash": record.raw_response_hash,
                "raw_record_hash": record.raw_record_hash,
                "normalized_record_hash": record.normalized_record_hash,
                "source_format": record.source_format,
                "omm_fields": record.omm_fields,
                "normalized_line1": record.line1 or None,
                "normalized_line2": record.line2 or None,
                "original_line1": record.original_line1,
                "original_line2": record.original_line2,
                "parsed_catalog_id": catalog_id,
                "parsed_propagation_parameters": {
                    field: getattr(sat, field)
                    for field in ("epochyr", "epochdays", "ndot", "nddot", "bstar", "inclo", "nodeo", "ecco", "argpo", "mo", "no_kozai")
                },
            }
            error, position_km, velocity_kms = sat.sgp4(jd, fr)
            if error != 0:
                provenance.validity_status = "invalid"
                provenance.reason_code = f"sgp4_error_{error}"
                unavailable.append(
                    UnavailableCatalogObject(
                        id=object_id,
                        name=record.name,
                        category=classification.category, object_type=classification.object_type,
                        source_classification=classification.source_classification,
                        classification_source=classification.classification_source,
                        provenance=provenance,
                    )
                )
                continue
            position = np.asarray(position_km, dtype=float)
            velocity = np.asarray(velocity_kms, dtype=float)
            if position.shape != (3,) or velocity.shape != (3,):
                provenance.validity_status = "invalid"
                provenance.reason_code = "invalid_sgp4_state_dimensions"
                unavailable.append(
                    UnavailableCatalogObject(
                        id=object_id,
                        name=record.name,
                        category=classification.category, object_type=classification.object_type,
                        source_classification=classification.source_classification,
                        classification_source=classification.classification_source,
                        provenance=provenance,
                    )
                )
                continue
            if not np.isfinite(position).all() or not np.isfinite(velocity).all():
                provenance.validity_status = "invalid"
                provenance.reason_code = "non_finite_sgp4_state"
                unavailable.append(
                    UnavailableCatalogObject(
                        id=object_id,
                        name=record.name,
                        category=classification.category, object_type=classification.object_type,
                        source_classification=classification.source_classification,
                        classification_source=classification.classification_source,
                        provenance=provenance,
                    )
                )
                continue
            radius = float(np.linalg.norm(position))
            altitude = radius - EARTH_RADIUS_KM
            speed = float(np.linalg.norm(velocity))
            band = classify_band(altitude)
            inclination = math.degrees(float(sat.inclo))
            raan = math.degrees(float(sat.nodeo))
            eccentricity = float(sat.ecco)
            phase = math.atan2(float(position[2]), float(position[0]))
            angular_rate = max(0.003, min(0.08, abs(float(sat.no_kozai)) * 0.35))
            category = classification.category
            debris_pressure = estimate_heuristic_debris_pressure_score(altitude, inclination, category)
            risk_score = estimate_heuristic_risk_score(altitude, inclination, category, debris_pressure)
            forecast_score = min(1.0, risk_score * (1.18 if band == "LEO" else 1.08) + debris_pressure * 0.22)

            if tle_epoch is None:
                tle_epoch = record.element_epoch

            provenance.validity_status = "valid"

            objects.append(
                SpaceObject(
                    id=object_id,
                    name=record.name,
                    category=category,  # type: ignore[arg-type]
                    object_type=classification.object_type,
                    source_classification=classification.source_classification,
                    classification_source=classification.classification_source,
                    band=band,  # type: ignore[arg-type]
                    orbit_type=orbit_type_for(band, inclination),
                    altitude_km=round(altitude, 2),
                    inclination_deg=round(inclination, 3),
                    velocity_kms=round(speed, 4),
                    heuristic_risk_score=round(risk_score, 4),
                    heuristic_debris_pressure_score=round(debris_pressure, 4),
                    heuristic_forecast_score=round(forecast_score, 4),
                    position=[round(float(v), 3) for v in position],
                    velocity=[round(float(v), 6) for v in velocity],
                    orbit=OrbitVisual(
                        visual_radius=round(visual_radius_for_altitude(altitude), 4),
                        inclination_deg=round(inclination, 3),
                        raan_deg=round(raan, 3),
                        phase_rad=round(phase, 5),
                        angular_rate=round(angular_rate, 5),
                        eccentricity=round(eccentricity, 6),
                    ),
                    provenance=provenance,
                    heuristic_score_provenance=_heuristic_score_provenance(provenance),
                )
            )
        except Exception as exc:
            provenance.validity_status = "invalid"
            provenance.reason_code = "invalid_tle" if isinstance(exc, ValueError) else "sgp4_initialization_error"
            unavailable.append(
                UnavailableCatalogObject(
                    id=object_id,
                    name=record.name,
                    category=classification.category, object_type=classification.object_type,
                    source_classification=classification.source_classification,
                    classification_source=classification.classification_source,
                    provenance=provenance,
                )
            )
            continue

    return objects[:limit], tle_epoch, unavailable


def estimate_heuristic_debris_pressure_score(altitude_km: float, inclination_deg: float, category: str) -> float:
    """Legacy formula retained as a heuristic pressure score, not physical density."""
    leo_fragmentation = math.exp(-((altitude_km - 820) / 420) ** 2)
    sun_sync = math.exp(-((inclination_deg - 98) / 11) ** 2)
    geo_belt = math.exp(-((altitude_km - 35_786) / 1_800) ** 2)
    base = 0.08 + 0.42 * leo_fragmentation + 0.22 * sun_sync + 0.26 * geo_belt
    if category == "debris":
        base += 0.22
    return max(0.02, min(0.98, base))


def estimate_heuristic_risk_score(altitude_km: float, inclination_deg: float, category: str, debris_pressure_score: float) -> float:
    """Legacy formula retained as a heuristic risk score, not collision probability."""
    band_pressure = 0.45 * math.exp(-((altitude_km - 780) / 500) ** 2)
    crossing_pressure = 0.24 * math.exp(-((inclination_deg - 86) / 22) ** 2)
    category_pressure = 0.16 if category == "debris" else 0.06
    score = 0.04 + debris_pressure_score * 0.38 + band_pressure + crossing_pressure + category_pressure
    return max(0.01, min(0.99, score))


def build_synthetic_objects(count: int, offset: int = 0) -> list[SpaceObject]:
    rng = random.Random(77291 + offset)
    objects: list[SpaceObject] = []
    for i in range(max(0, count)):
        roll = rng.random()
        if roll < 0.72:
            band = "LEO"
            altitude = rng.choice([510, 630, 780, 920, 1_120, 1_420]) + rng.uniform(-95, 95)
            inclination = rng.choice([28.5, 51.6, 74.0, 82.5, 97.8]) + rng.uniform(-4, 4)
            speed = rng.uniform(7.2, 7.9)
        elif roll < 0.9:
            band = "MEO"
            altitude = rng.choice([20_200, 23_220, 26_600]) + rng.uniform(-650, 650)
            inclination = rng.choice([55, 63, 64.8]) + rng.uniform(-4, 4)
            speed = rng.uniform(3.2, 4.4)
        else:
            band = "GEO"
            altitude = 35_786 + rng.uniform(-520, 520)
            inclination = rng.uniform(0.0, 8.5)
            speed = rng.uniform(2.9, 3.2)

        simulated_category = "debris" if rng.random() < (0.36 if band == "LEO" else 0.18) else "active"
        demo_debris_pressure_score = estimate_heuristic_debris_pressure_score(altitude, inclination, simulated_category)
        demo_risk_score = estimate_heuristic_risk_score(altitude, inclination, simulated_category, demo_debris_pressure_score)
        radius = visual_radius_for_altitude(altitude)
        phase = rng.uniform(0, math.tau)
        raan = rng.uniform(0, 360)

        synthetic_provenance = Provenance(
            source="deterministic synthetic demo generator",
            source_type="synthetic",
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            reference_frame="synthetic visualization coordinates; not a propagated state",
            units={"position": "synthetic units", "velocity": "synthetic units"},
            object_id=f"SYN-{offset + i:05d}",
            method="seeded synthetic demo generation",
            method_version="1",
            validity_status="not_assessed",
            reason_code="synthetic_demo_state_not_physical",
            is_synthetic=True,
        )
        objects.append(
            SpaceObject(
                id=f"SYN-{offset + i:05d}",
                name=("[DEMO] DEBRIS FIELD " if simulated_category == "debris" else "[DEMO] SSA OBJECT ") + f"{offset + i:05d}",
                category="unknown",
                object_type="UNKNOWN",
                classification_source="classification_unavailable",
                band=band,  # type: ignore[arg-type]
                orbit_type=orbit_type_for(band, inclination),
                altitude_km=round(altitude, 2),
                inclination_deg=round(inclination, 3),
                velocity_kms=round(speed, 4),
                heuristic_risk_score=round(demo_risk_score, 4),
                heuristic_debris_pressure_score=round(demo_debris_pressure_score, 4),
                heuristic_forecast_score=round(min(1.0, demo_risk_score * rng.uniform(1.03, 1.22)), 4),
                position=[0.0, 0.0, 0.0],
                velocity=[0.0, 0.0, 0.0],
                orbit=OrbitVisual(
                    visual_radius=round(radius, 4),
                    inclination_deg=round(inclination, 3),
                    raan_deg=round(raan, 3),
                    phase_rad=round(phase, 5),
                    angular_rate=round(0.003 + 0.07 / max(1.0, radius), 5),
                    eccentricity=round(rng.uniform(0.0001, 0.012), 6),
                ),
                provenance=synthetic_provenance,
                heuristic_score_provenance=_heuristic_score_provenance(synthetic_provenance),
            )
        )
    return objects


def _heuristic_score_provenance(source_provenance: Provenance) -> Provenance:
    result = source_provenance.model_copy(deep=True)
    result.source = f"Heuristic scores derived from {source_provenance.source}"
    result.source_type = "derived"
    result.method = "legacy orbital shell heuristic formulas"
    result.method_version = "1"
    result.reason_code = "heuristic_score_not_collision_probability_or_physical_density"
    result.is_fallback = source_provenance.is_fallback
    result.is_synthetic = source_provenance.is_synthetic
    return result

