from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from app.models import ForecastFrame, ForecastResponse, Provenance, RiskCell, SpaceObject


RISK_LEVELS = [
    (0.33, "low"),
    (0.52, "moderate"),
    (0.72, "elevated"),
    (1.01, "severe"),
]
METHOD = "deterministic weighted-logistic orbital-shell heuristic"
METHOD_VERSION = "1"


def risk_level(value: float) -> str:
    for threshold, label in RISK_LEVELS:
        if value < threshold:
            return label
    return "severe"


def build_risk_cells(objects: list[SpaceObject], forecast_hours: int = 0) -> list[RiskCell]:
    buckets: dict[tuple[str, int, int], list[SpaceObject]] = defaultdict(list)
    for obj in objects:
        altitude_bin = int(round(obj.altitude_km / 400.0) * 400)
        inclination_bin = int(round(obj.inclination_deg / 15.0) * 15)
        buckets[(obj.band, altitude_bin, inclination_bin)].append(obj)

    cells: list[RiskCell] = []
    for index, ((band, altitude_bin, inclination_bin), members) in enumerate(buckets.items()):
        if len(members) < 3 and band != "GEO":
            continue

        tracked_density = min(1.0, len(members) / (34 if band == "LEO" else 18))
        debris_ratio = sum(1 for obj in members if obj.category == "debris") / max(1, len(members))
        mean_risk = float(np.mean([obj.heuristic_risk_score for obj in members]))
        untracked_pressure = min(1.0, 0.18 + debris_ratio * 0.46 + tracked_density * 0.28)
        altitude_pressure = orbital_pressure(float(altitude_bin), band)
        forecast_score = forecast_growth(float(altitude_bin), float(inclination_bin), debris_ratio, forecast_hours)
        risk_score = score_heuristic_risk(
            density=tracked_density,
            debris_ratio=debris_ratio,
            mean_risk=mean_risk,
            untracked_pressure=untracked_pressure,
            altitude_pressure=altitude_pressure,
            forecast_score=forecast_score,
        )
        uncertainty_score = min(0.95, 0.16 + untracked_pressure * 0.55 + forecast_hours / 420)

        contributors = sorted(members, key=lambda obj: obj.heuristic_risk_score, reverse=True)[:4]
        explanation = build_explanation(band, altitude_bin, inclination_bin, debris_ratio, tracked_density, forecast_score)
        cells.append(
            RiskCell(
                id=f"RISK-{band}-{altitude_bin}-{inclination_bin}-{index}",
                band=band,  # type: ignore[arg-type]
                altitude_km=float(altitude_bin),
                inclination_deg=float(inclination_bin),
                raan_deg=round((index * 47 + altitude_bin * 0.03) % 360, 3),
                severity=risk_level(risk_score),  # type: ignore[arg-type]
                heuristic_risk_score=round(risk_score, 4),
                tracked_object_density_score=round(tracked_density, 4),
                heuristic_untracked_pressure_score=round(untracked_pressure, 4),
                heuristic_forecast_score=round(forecast_score, 4),
                heuristic_uncertainty_score=round(uncertainty_score, 4),
                contributors=[obj.name for obj in contributors],
                explanation=explanation,
                provenance=derived_provenance(members, method=METHOD, method_version=METHOD_VERSION),
            )
        )

    cells.sort(key=lambda cell: cell.heuristic_risk_score, reverse=True)
    return cells[:48]


def score_heuristic_risk(
    *,
    density: float,
    debris_ratio: float,
    mean_risk: float,
    untracked_pressure: float,
    altitude_pressure: float,
    forecast_score: float,
) -> float:
    """Fixed weighted-logistic score. It is deterministic arithmetic, not an ML model or probability."""
    raw = (
        density * 1.45
        + debris_ratio * 1.08
        + mean_risk * 1.62
        + untracked_pressure * 0.86
        + altitude_pressure * 0.94
        + forecast_score * 0.74
        - 1.52
    )
    value = 1.0 / (1.0 + math.exp(-raw))
    return float(max(0.03, min(0.99, value)))


def orbital_pressure(altitude_km: float, band: str) -> float:
    leo = math.exp(-((altitude_km - 850) / 520) ** 2)
    geo = math.exp(-((altitude_km - 35_800) / 1_400) ** 2)
    meo = math.exp(-((altitude_km - 20_400) / 2_600) ** 2)
    band_weight = {"LEO": 1.0, "MEO": 0.62, "GEO": 0.72, "HEO": 0.42}.get(band, 0.5)
    return min(1.0, band_weight * max(leo, geo, meo))


def forecast_growth(altitude_km: float, inclination_deg: float, debris_ratio: float, forecast_hours: int) -> float:
    if forecast_hours <= 0:
        return 0.0
    temporal = min(1.0, forecast_hours / 168)
    congestion_wave = 0.5 + 0.5 * math.sin(forecast_hours / 18 + altitude_km / 950 + inclination_deg / 19)
    fragmentation_memory = math.exp(-((altitude_km - 850) / 620) ** 2) * (0.3 + debris_ratio)
    return min(1.0, temporal * (0.26 + 0.38 * congestion_wave + 0.42 * fragmentation_memory))


def build_explanation(
    band: str,
    altitude_bin: int,
    inclination_bin: int,
    debris_ratio: float,
    density: float,
    forecast_score: float,
) -> str:
    drivers: list[str] = []
    if density > 0.55:
        drivers.append("tracked-object concentration score")
    if debris_ratio > 0.28:
        drivers.append("debris share in the tracked sample")
    if forecast_score > 0.35:
        drivers.append("heuristic forecast score")
    if not drivers:
        drivers.append("the weighted orbital-shell score")
    driver_text = ", ".join(drivers)
    return (
        f"{band} heuristic risk index near {altitude_bin:,} km and {inclination_bin} deg inclination "
        f"is influenced by {driver_text}. This is not a physical debris density, collision probability, "
        "or covariance-derived uncertainty."
    )


def derived_provenance(objects: list[SpaceObject], *, method: str, method_version: str) -> Provenance:
    if not objects:
        return Provenance(
            source="No valid catalog inputs",
            source_type="unavailable",
            method=method,
            method_version=method_version,
            validity_status="unavailable",
            reason_code="no_valid_input_objects",
        )
    types = {obj.provenance.source_type for obj in objects}
    if types == {"live"}:
        parent_source = "live CelesTrak catalog inputs"
    elif types == {"fallback"}:
        parent_source = "bundled fallback TLE inputs"
    elif types == {"synthetic"}:
        parent_source = "synthetic demo inputs"
    else:
        parent_source = "mixed catalog inputs"
    parent_hashes = sorted(obj.provenance.input_hash or obj.id for obj in objects)
    input_hash = hashlib.sha256(json.dumps(parent_hashes, separators=(",", ":")).encode()).hexdigest()
    return Provenance(
        source=f"Derived from {parent_source}",
        source_type="derived",
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        input_hash=input_hash,
        method=method,
        method_version=method_version,
        validity_status="valid",
        is_synthetic="synthetic" in types,
        is_fallback="fallback" in types,
    )


def build_forecast(objects: list[SpaceObject], horizon_hours: int = 168, steps: int = 8) -> ForecastResponse:
    horizon_hours = max(1, min(336, horizon_hours))
    steps = max(2, min(24, steps))
    frames: list[ForecastFrame] = []

    for step in range(steps):
        hour = round(step * horizon_hours / (steps - 1))
        cells = build_risk_cells(objects, forecast_hours=hour)
        global_heuristic_risk_score = float(np.mean([cell.heuristic_risk_score for cell in cells[:12]])) if cells else None
        tracked_object_density_score = min(1.0, len(objects) / 1_200)
        frames.append(
            ForecastFrame(
                hour=hour,
                global_heuristic_risk_score=(
                    round(global_heuristic_risk_score, 4) if global_heuristic_risk_score is not None else None
                ),
                tracked_object_density_score=round(tracked_object_density_score, 4),
                cells=cells[:28],
                provenance=derived_provenance(objects, method="heuristic shell-score extrapolation", method_version="1"),
            )
        )

    return ForecastResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        horizon_hours=horizon_hours,
        frames=frames,
        provenance=derived_provenance(objects, method="heuristic shell-score extrapolation", method_version="1"),
    )
