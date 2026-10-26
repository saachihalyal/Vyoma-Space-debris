from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import os
import subprocess
from functools import partial
import json
import logging
from pathlib import Path
import re
import time
import asyncio
import copy
import hashlib
import io
import threading
import uuid
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.ai.inference import model_status
from app.ai.anomaly import model_status as orbital_anomaly_model_status
from app.ai.collision_models import assess_collision_ai, collision_model_status
from app.ai.smart_filter import evaluate_physical_smart_filter, filter_policy, smart_filter_model_status
from app.models import (
    CatalogSnapshot,
    CdmImportRequest,
    ConjunctionAssessmentEvent,
    ManeuverAssessmentResponse,
    ReferenceManeuverRequest,
    ResearchPcScenarioRequest,
    Provenance,
    ScenarioPcRequest,
    SnapshotStats,
    SourceSummary,
)
from app.services.cdm_ingestion import parse_cdm_input
from app.services.conjunction import build_screening_proxies, build_smart_filter, optimize_maneuver
from app.services.event_pc_inputs import apply_cdm_inputs, apply_scenario_inputs, evaluate_cdm_reference
from app.services.automatic_research_pc import METHOD_VERSION as RESEARCH_PC_METHOD_VERSION, assess_automatic_research_pc
from app.services.ai_risk_prioritization import assess_live_geometry, rank_screening_events
from app.services.probability_classification import POLICY_VERSION as PC_CLASSIFICATION_POLICY_VERSION
from app.services.probability_classification import ORION_RISK_POLICY_VERSION, classify_orion_physics_pc
from app.services.orbit import propagate_records
from app.services.review_priority import policy_status
from app.services.reports import conjunctions_csv, event_report_csv, event_report_payload, event_report_pdf, mission_report_pdf, reference_cdm_report_pdf, reference_maneuver_report_pdf
from app.services.reference_maneuver import assess_reference_maneuver
from app.services.risk import build_forecast, build_risk_cells, derived_provenance
from app.services.tle_provider import CELESTRAK_CACHE_PATH, TleProvider, TleRecord
from app.services.trajectory_screening import (
    DEFAULT_HORIZON_HOURS,
    DEFAULT_SAMPLE_STEP_SECONDS,
    DEFAULT_SCREENING_THRESHOLD_KM,
    MAX_CANDIDATE_MINIMA,
    MAX_CANDIDATE_PAIRS,
    MAX_LOCAL_MINIMA_PER_PAIR,
    MAX_RELATIVE_SPEED_BOUND_KM_S,
    MAX_SAMPLE_EPOCHS,
    METHOD_VERSION,
    ScreeningRun,
    TCA_MAX_ITERATIONS,
    TCA_NEIGHBOR_CHECK_SECONDS,
    TCA_TIME_TOLERANCE_SECONDS,
    _sgp4_version,
    screen_tle_records,
)


app = FastAPI(
    title="ORION SSA Research API",
    description="Catalog ingestion, WGS-72 SGP4 trajectory screening, independent ESA-trained log10-risk ML estimates, and heuristic proxies.",
    version="1.3.0",
)

@app.get("/api/version")
async def version() -> dict:
    """Build identity used to detect stale frontend/backend development servers."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = os.getenv("ORION_COMMIT", "unknown")
    artifact_dir = Path(__file__).resolve().parent / "ai" / "artifacts"
    versions = {}
    for metadata_path in sorted(artifact_dir.glob("*.metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            versions[metadata_path.name.removesuffix(".metadata.json")] = metadata.get("model_version", metadata.get("version", "unknown"))
        except (OSError, ValueError):
            versions[metadata_path.name.removesuffix(".metadata.json")] = "invalid-metadata"
    return {"commit": commit, "build_time": os.getenv("ORION_BUILD_TIME", "development"), "model_artifact_versions": versions}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1_000)
logger = logging.getLogger(__name__)

SCREENING_RESULT_TTL_SECONDS = 30.0
SCREENING_JOB_TTL_SECONDS = 3_600.0
ASSESSMENT_PAGE_SIZE_DEFAULT = 120
ASSESSMENT_PAGE_SIZE_MAX = 200
ASSESSMENT_RESULT_TTL_SECONDS = 3_600.0
_screening_registry_lock = threading.Lock()
_screening_inflight: dict[str, asyncio.Task] = {}
_screening_cache: dict[str, tuple[float, tuple]] = {}
_screening_jobs: dict[str, dict] = {}
_assessment_results: dict[str, dict] = {}
_assessment_results_lock = threading.Lock()
_smart_filter_results: dict[str, dict] = {}
_smart_filter_results_lock = threading.Lock()
SCREENING_EXPORT_ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "exports"
NASA_CARA_PC_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "nasa_cara_pc_reference.cdm"
NASA_CARA_PC_REFERENCE_URL = "https://github.com/nasa/CARA_Analysis_Tools/blob/master/DataFiles/PcTestCaseCDMs/000020580_conj_000002017_20230613_001923_20230608_063715.cdm"

tle_provider = TleProvider(retry_state_path=CELESTRAK_CACHE_PATH)


async def build_snapshot(
    limit: int = 850,
    forecast_hours: int = 0,
    *,
    records: list[TleRecord] | None = None,
    source_state: dict | None = None,
    now: datetime | None = None,
    performance: dict | None = None,
) -> CatalogSnapshot:
    if records is None:
        if hasattr(tle_provider, "get_catalog_with_state"):
            records, accepted_source_state = await tle_provider.get_catalog_with_state(limit=limit)
        else:  # Compatibility for injected providers used by integrations and tests.
            records = await tle_provider.get_catalog(limit=limit)
            provider_type = getattr(tle_provider, "source_type", "unavailable")
            accepted_source_state = {
                "status": provider_type if provider_type in {"live", "fallback"} else "unavailable",
                "source": getattr(tle_provider, "source", "Source unavailable"),
                "last_success_at": None,
                "last_error_code": None,
            }
        source_state = accepted_source_state
    source_state = source_state or tle_provider.source_state
    propagation_started = time.perf_counter()
    objects, tle_epoch, unavailable_objects = propagate_records(records, limit=limit, now=now)
    if performance is not None:
        performance["snapshot_propagation_seconds"] = time.perf_counter() - propagation_started
    risk_cells = build_risk_cells(objects, forecast_hours=forecast_hours)
    source_summary = summarize_sources(objects, unavailable_objects)

    global_risk = float(np.mean([cell.heuristic_risk_score for cell in risk_cells[:12]])) if risk_cells else None
    active = sum(1 for obj in objects if obj.category in {"active", "payload"})
    debris = sum(1 for obj in objects if obj.category == "debris")
    unknown = sum(1 for obj in objects if obj.category == "unknown")
    stats = SnapshotStats(
        tracked_objects=len(objects),
        active_satellites=active,
        debris_objects=debris,
        unknown_objects=unknown,
        leo=sum(1 for obj in objects if obj.band == "LEO"),
        meo=sum(1 for obj in objects if obj.band == "MEO"),
        geo=sum(1 for obj in objects if obj.band == "GEO"),
        global_heuristic_risk_score=round(global_risk, 4) if global_risk is not None else None,
        heuristic_forecast_trend_score=(
            round(float(np.mean([cell.heuristic_forecast_score for cell in risk_cells[:16]])), 4)
            if risk_cells else None
        ),
        data_latency_seconds=round(tle_provider.latency_seconds, 2),
        unavailable_objects=len(unavailable_objects),
        provenance=derived_provenance(objects, method="catalog summary statistics", method_version="1"),
    )

    return CatalogSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=source_state["source"],
        source_state=source_state,
        source_summary=source_summary,
        tle_epoch=tle_epoch,
        stats=stats,
        objects=objects,
        unavailable_objects=unavailable_objects,
        risk_cells=risk_cells,
    )


def summarize_sources(objects: list, unavailable_objects: list) -> SourceSummary:
    provenance_items = [obj.provenance for obj in objects] + [obj.provenance for obj in unavailable_objects]
    counts = Counter(item.source_type for item in provenance_items)
    types = set(counts)
    if not types:
        status = "unavailable"
    elif types == {"live"}:
        status = "all_live"
    elif types == {"fallback"}:
        status = "fallback"
    elif types == {"synthetic"}:
        status = "synthetic_demo"
    elif "live" in types and "synthetic" in types:
        status = "mixed_live_synthetic"
    elif "live" in types and "fallback" in types:
        status = "mixed_live_fallback"
    elif "synthetic" in types:
        status = "synthetic_demo"
    elif "fallback" in types:
        status = "fallback"
    else:
        status = "unavailable"
    return SourceSummary(
        status=status,
        counts_by_source_type=dict(counts),
        object_count=len(objects),
        unavailable_count=len(unavailable_objects),
    )


async def build_event_context(limit: int = 850, forecast_hours: int = 24):
    """Return the Stage 1 heuristic proxy context for analytics/filter pages."""
    snapshot = await build_snapshot(limit=limit, forecast_hours=forecast_hours)
    events = build_screening_proxies(snapshot.objects, snapshot.risk_cells, limit=120)
    return snapshot, events


async def build_trajectory_context(
    *,
    limit: int = 900,
    horizon_hours: float = DEFAULT_HORIZON_HOURS,
    sample_step_seconds: int = DEFAULT_SAMPLE_STEP_SECONDS,
    screening_threshold_km: float = DEFAULT_SCREENING_THRESHOLD_KM,
    start_utc: datetime | None = None,
):
    if hasattr(tle_provider, "get_catalog_with_state"):
        records, source_state = await tle_provider.get_catalog_with_state(limit=limit)
    else:  # Compatibility for injected providers used by integrations and tests.
        records = await tle_provider.get_catalog(limit=limit)
        provider_type = getattr(tle_provider, "source_type", "unavailable")
        source_state = getattr(tle_provider, "source_state", {
            "status": provider_type if provider_type in {"live", "fallback"} else "unavailable",
            "source": getattr(tle_provider, "source", "Source unavailable"),
            "last_success_at": None,
            "last_error_code": None,
        })
    screening_start = start_utc or datetime.now(timezone.utc)
    if screening_start.tzinfo is None or screening_start.utcoffset() is None:
        raise ValueError("start_utc must include an explicit UTC offset")
    screening_start = screening_start.astimezone(timezone.utc)
    catalog_identity = {
        "source_state": source_state,
        "records": sorted(
            (record.input_hash, record.source_type, record.source_group, record.source_timestamp, record.element_epoch)
            for record in records
        ),
    }
    cache_material = {
        "catalog_identity": catalog_identity,
        "catalog_limit": limit,
        "screening_start_utc": screening_start.isoformat(),
        "horizon_hours": horizon_hours,
        "sample_step_seconds": sample_step_seconds,
        "screening_threshold_km": screening_threshold_km,
        "max_candidate_pairs": MAX_CANDIDATE_PAIRS,
        "max_candidate_minima": MAX_CANDIDATE_MINIMA,
        "max_local_minima_per_pair": MAX_LOCAL_MINIMA_PER_PAIR,
        "max_sample_epochs": MAX_SAMPLE_EPOCHS,
        "max_relative_speed_bound_km_s": MAX_RELATIVE_SPEED_BOUND_KM_S,
        "tca_max_iterations": TCA_MAX_ITERATIONS,
        "tca_neighbor_check_seconds": TCA_NEIGHBOR_CHECK_SECONDS,
        "tca_time_tolerance_seconds": TCA_TIME_TOLERANCE_SECONDS,
        "screening_method_version": METHOD_VERSION,
        "propagator_version": _sgp4_version(),
        "ml_model_identity": model_status(),
        "orbital_anomaly_model_identity": orbital_anomaly_model_status(),
        "gravity_model": "WGS72",
    }
    cache_key = hashlib.sha256(json.dumps(cache_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    now = time.monotonic()
    with _screening_registry_lock:
        for stale_key, (expires_at, _) in list(_screening_cache.items()):
            if expires_at <= now:
                _screening_cache.pop(stale_key, None)
        cached = _screening_cache.get(cache_key)
        if cached:
            return copy.deepcopy(cached[1])
        task = _screening_inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(_build_trajectory_context_uncached(
                cache_key, records, source_state, limit, screening_start,
                horizon_hours, sample_step_seconds, screening_threshold_km,
            ))
            _screening_inflight[cache_key] = task
    return copy.deepcopy(await asyncio.shield(task))


async def _build_trajectory_context_uncached(
    cache_key: str,
    records: list[TleRecord],
    source_state: dict,
    limit: int,
    screening_start: datetime,
    horizon_hours: float,
    sample_step_seconds: int,
    screening_threshold_km: float,
):
    snapshot_performance: dict[str, float] = {}
    try:
        snapshot_started = time.perf_counter()
        snapshot = await build_snapshot(
            limit=limit, forecast_hours=0, records=records, source_state=source_state,
            now=screening_start, performance=snapshot_performance,
        )
        snapshot_build_seconds = time.perf_counter() - snapshot_started
        if source_state.get("status") == "fallback" or snapshot.source_summary.status == "fallback":
            run = ScreeningRun(events=[], summary={
                "status": "unavailable",
                "completion_status": "failed",
                "reason_code": "FALLBACK_CATALOG_NOT_SCREENED",
                "partial_reasons": [],
                "performance": {},
                "method": "WGS-72 SGP4/SDP4 trajectory screening",
                "method_version": METHOD_VERSION,
            })
        else:
            run = await run_in_threadpool(partial(
                screen_tle_records, records, snapshot.objects,
                start_utc=screening_start, horizon_hours=horizon_hours,
                sample_step_seconds=sample_step_seconds,
                screening_threshold_km=screening_threshold_km,
                unavailable_objects=snapshot.unavailable_objects,
            ))
        run.summary.setdefault("performance", {}).update(snapshot_performance)
        run.summary.update({
            "objects_requested": limit,
            "effective_catalog_limit": limit,
            "catalog_records_received": len(records),
            "objects_used": run.summary.get("valid_track_count", 0),
            "requested_horizon_hours": horizon_hours,
            "effective_horizon_hours": horizon_hours,
            "requested_sample_step_seconds": sample_step_seconds,
            "effective_sample_step_seconds": sample_step_seconds,
            "requested_screening_threshold_km": screening_threshold_km,
            "effective_screening_threshold_km": screening_threshold_km,
        })
        run.summary["performance"]["snapshot_build_seconds"] = snapshot_build_seconds
        run.summary["completion_status"] = (
            "failed" if run.summary.get("status") == "unavailable"
            else "partial" if run.summary.get("status") == "partial"
            else "complete"
        )
        result = (snapshot, run)
        with _screening_registry_lock:
            _screening_cache[cache_key] = (time.monotonic() + SCREENING_RESULT_TTL_SECONDS, result)
        return result
    finally:
        with _screening_registry_lock:
            if _screening_inflight.get(cache_key) is asyncio.current_task():
                _screening_inflight.pop(cache_key, None)


def event_dicts(events) -> list[dict]:
    return [event.model_dump(mode="json") for event in events]


def _screening_result_status(screening_status: str, events: list, response_truncated: bool) -> str:
    if screening_status == "unavailable":
        return "unavailable"
    if screening_status == "partial" or response_truncated:
        return "partial"
    if any(
        getattr(event, "result_kind", None) == "physics_assessment"
        and getattr(getattr(event, "physics_result", None), "status", None) == "valid"
        and getattr(getattr(event, "provenance", None), "validity_status", None) == "valid"
        and not getattr(getattr(event, "provenance", None), "is_synthetic", True)
        and getattr(getattr(event, "provenance", None), "source_type", None) != "synthetic"
        for event in events
    ):
        return "valid_non_empty"
    return "valid_empty"


@app.get("/api/health")
async def health() -> dict:
    snapshot = await build_snapshot(limit=250, forecast_hours=0)
    ml_status = model_status()
    return {
        "success": True,
        "status": "online",
        "backend_status": "operational",
        "ai_status": ml_status["status"],
        "ai_reason": ml_status["reason_code"],
        "ml_model": ml_status,
        "orbital_anomaly_model": orbital_anomaly_model_status(),
        "collision_models": collision_model_status(),
        "smart_filter_model": smart_filter_model_status(),
        "database_status": "in_memory_tle_cache; no persistent database configured",
        "gpu_status": "not_used",
        "dataset_loaded": bool(snapshot.objects),
        "dataset_source": snapshot.source,
        "source_state": snapshot.source_state,
        "source_summary": snapshot.source_summary.model_dump(),
        "objects_tracked": snapshot.stats.tracked_objects,
        "unavailable_objects": snapshot.stats.unavailable_objects,
        "risk_cells": len(snapshot.risk_cells),
        "physics_conjunction_assessment": "stage_2a_trajectory_screening_configured; request-specific status is returned by /api/conjunctions",
        "screening_readiness": "configured; screening runs require an explicit request",
        "physical_pc_availability": "input_dependent; live catalog covariance and hard-body radius are not provided",
        "review_priority_policy": policy_status(),
        "version": app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/api/catalog",
    response_model=CatalogSnapshot,
    response_model_exclude={
        "objects": {"__all__": {"velocity": True, "provenance": {"source_record": True}, "heuristic_score_provenance": {"source_record": True}}},
        "unavailable_objects": {"__all__": {"provenance": {"source_record": True}}},
    },
)
async def catalog(limit: int = Query(850, ge=25, le=2_000), forecast_hours: int = Query(0, ge=0, le=336)) -> CatalogSnapshot:
    return await build_snapshot(limit=limit, forecast_hours=forecast_hours)


@app.get("/api/collision-models")
async def get_collision_model_status() -> dict:
    """Expose validated offline artifact versions, metrics, schema, and provenance."""
    return collision_model_status()


@app.get("/api/forecast")
async def forecast(
    horizon_hours: int = Query(168, ge=1, le=336),
    steps: int = Query(9, ge=2, le=24),
    limit: int = Query(850, ge=25, le=2_000),
):
    records = await tle_provider.get_catalog(limit=limit)
    objects, _, unavailable_objects = propagate_records(records, limit=limit)
    response = build_forecast(objects, horizon_hours=horizon_hours, steps=steps)
    return {
        **response.model_dump(mode="json"),
        "source_summary": summarize_sources(objects, unavailable_objects).model_dump(),
        "unavailable_objects": len(unavailable_objects),
    }


@app.get("/api/system-health")
async def system_health() -> dict:
    snapshot, events = await build_event_context(limit=650, forecast_hours=24)
    ml_status = model_status()
    high_priority = sum(1 for event in events if event.risk_level in {"High", "Critical"})
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "backend": "operational",
            "dataset_loaded": bool(snapshot.objects),
            "dataset_source": snapshot.source,
            "source_state": snapshot.source_state,
            "source_summary": snapshot.source_summary.model_dump(),
            "objects_tracked": snapshot.stats.tracked_objects,
            "active_satellites": snapshot.stats.active_satellites,
            "debris_objects": snapshot.stats.debris_objects,
            "screening_proxy_pairs": len(events),
            "high_priority_screening_proxies": high_priority,
            "conjunction_assessment_status": "stage_2a_trajectory_screening_configured; request-specific status is returned by /api/conjunctions",
            "screening_readiness": "configured; screening runs require an explicit request",
            "physical_pc_availability": "input_dependent; live catalog covariance and hard-body radius are not provided",
            "review_priority_policy": policy_status(),
            "ai_status": ml_status["status"],
            "ai_reason": ml_status["reason_code"],
            "ml_model": ml_status,
            "orbital_anomaly_model": orbital_anomaly_model_status(),
            "collision_models": collision_model_status(),
            "smart_filter_model": smart_filter_model_status(),
            "gpu_status": "not_used",
            "database_status": "no_persistent_database_configured",
            "version": app.version,
        },
        "message": "System health reflects currently configured capabilities.",
    }


@app.get("/api/objects")
async def objects(
    q: str | None = None,
    band: str | None = None,
    category: str | None = None,
    limit: int = Query(500, ge=25, le=2_000),
) -> dict:
    snapshot = await build_snapshot(limit=limit, forecast_hours=0)
    result = snapshot.objects
    if band:
        result = [obj for obj in result if obj.band.lower() == band.lower()]
    if category:
        result = [obj for obj in result if obj.category.lower() == category.lower()]
    if q:
        query = q.lower()
        result = [obj for obj in result if query in obj.name.lower() or query in obj.id.lower()]
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "objects": [obj.model_dump(mode="json") for obj in result[:limit]],
            "unavailable_objects": [obj.model_dump(mode="json") for obj in snapshot.unavailable_objects],
            "metadata": snapshot.stats.model_dump(mode="json"),
            "source": snapshot.source,
            "source_summary": snapshot.source_summary.model_dump(),
        },
        "message": "Propagated objects and unavailable propagation records returned.",
    }


@app.get("/api/analytics")
async def analytics(limit: int = Query(850, ge=25, le=2_000)) -> dict:
    snapshot, events = await build_event_context(limit=limit, forecast_hours=24)
    risk_distribution: dict[str, int] = {}
    band_distribution = {"LEO": 0, "MEO": 0, "GEO": 0, "HEO": 0}
    altitude_distribution: dict[str, int] = {}
    for obj in snapshot.objects:
        band_distribution[obj.band] = band_distribution.get(obj.band, 0) + 1
        altitude_key = f"{int(obj.altitude_km // 1000) * 1000}-{int(obj.altitude_km // 1000 + 1) * 1000}"
        altitude_distribution[altitude_key] = altitude_distribution.get(altitude_key, 0) + 1
    for event in events:
        risk_distribution[event.risk_level] = risk_distribution.get(event.risk_level, 0) + 1
    mean_event_risk = float(np.mean([event.risk_score for event in events])) if events else None
    forecast_payload = build_forecast(snapshot.objects, horizon_hours=168, steps=8)
    payload = {
        "total_objects": snapshot.stats.tracked_objects,
        "unavailable_objects": snapshot.stats.unavailable_objects,
        "active_satellites": snapshot.stats.active_satellites,
        "debris_objects": snapshot.stats.debris_objects,
        "total_screening_proxy_pairs": len(events),
        "high_priority_screening_proxies": sum(1 for event in events if event.risk_level in {"High", "Critical"}),
        "mean_heuristic_risk_score": round(mean_event_risk, 4) if mean_event_risk is not None else None,
        "global_heuristic_risk_score": snapshot.stats.global_heuristic_risk_score,
        "heuristic_forecast_trend_score": snapshot.stats.heuristic_forecast_trend_score,
        "smart_filter_reduction_pct": build_smart_filter(events, snapshot.stats.tracked_objects)["reduction_pct"],
        "risk_distribution": risk_distribution,
        "band_distribution": band_distribution,
        "altitude_distribution": altitude_distribution,
        "risk_timeline": [
            {"hour": frame.hour, "global_heuristic_risk_score": frame.global_heuristic_risk_score,
             "tracked_object_density_score": frame.tracked_object_density_score,
             "provenance": frame.provenance.model_dump(mode="json")}
            for frame in forecast_payload.frames
        ],
        "source_summary": snapshot.source_summary.model_dump(),
        "provenance": snapshot.stats.provenance.model_dump(mode="json"),
    }
    return {"success": True, "timestamp": datetime.now(timezone.utc).isoformat(), "data": payload}


@app.get("/api/conjunctions")
async def conjunctions(
    limit: int = Query(100, ge=1, le=400),
    min_pc: float | None = None,
    risk: str | None = None,
    horizon_hours: float = Query(DEFAULT_HORIZON_HOURS, ge=0.01, le=72),
    sample_step_seconds: int = Query(DEFAULT_SAMPLE_STEP_SECONDS, ge=10, le=300),
    screening_threshold_km: float = Query(DEFAULT_SCREENING_THRESHOLD_KM, gt=0, le=1_000),
    start_utc: datetime | None = None,
) -> dict:
    request_started = time.perf_counter()
    if min_pc is not None:
        raise HTTPException(status_code=422, detail="Pc filtering is not configured on this endpoint.")
    if start_utc is not None and (start_utc.tzinfo is None or start_utc.utcoffset() is None):
        raise HTTPException(status_code=422, detail="start_utc must include an explicit UTC offset.")
    if risk is not None:
        raise HTTPException(status_code=422, detail="Risk classes are heuristic proxy outputs; query /api/screening-proxies for that filter.")
    try:
        snapshot, run = await build_trajectory_context(
            limit=limit,
            horizon_hours=horizon_hours,
            sample_step_seconds=sample_step_seconds,
            screening_threshold_km=screening_threshold_km,
            start_utc=start_utc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Trajectory screening execution failed")
        return JSONResponse(status_code=500, content={
            "success": False,
            "result_kind": "physics_assessment",
            "result_status": "error",
            "completion_status": "failed",
            "physics_assessment_status": "unavailable",
            "data": [],
            "reason_code": "SCREENING_EXECUTION_FAILED",
            "message": "Trajectory screening failed before a complete or partial result was produced.",
        })
    assessments = run.events
    # `limit` controls catalog objects only. Assessment rows are a separate,
    # persisted result set and must never be discarded at this boundary.
    returned_assessments = assessments
    assessment_records_truncated = False
    screening_summary = dict(run.summary)
    screening_summary.update({
        "catalog_record_limit": limit,
        "assessment_record_limit": None,
        "assessment_record_count": len(assessments),
        "returned_assessment_record_count": len(returned_assessments),
        "assessment_records_truncated": assessment_records_truncated,
        # Keep the propagation/screening computation outcome distinct from the
        # completeness of this capped response payload.
        "computation_status": run.summary["status"],
        "screening_execution_status": run.summary.get("completion_status", {
            "valid": "complete", "partial": "partial", "unavailable": "failed",
        }.get(run.summary.get("status"), "failed")),
        "valid_assessment_record_count": sum(getattr(getattr(event, "physics_result", None), "status", "unavailable") == "valid" for event in assessments),
        "invalid_assessment_record_count": sum(getattr(getattr(event, "physics_result", None), "status", "valid") == "invalid" for event in assessments),
        "valid_close_approach_count": sum(getattr(getattr(event, "physics_result", None), "status", "valid") in {"valid", "boundary"} for event in assessments),
        "pc_unavailable_assessment_count": sum(getattr(getattr(event, "collision_probability", None), "status", "unavailable") != "available" for event in assessments),
        "review_priority_counts": {
            category: sum(getattr(getattr(event, "review_priority", None), "category", "UNCLASSIFIED") == category for event in assessments)
            for category in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "REVIEW_REQUIRED", "UNCLASSIFIED")
        },
        "total_records_available": len(assessments),
        "records_returned": len(returned_assessments),
        "has_more_records": False,
        "response_page_partial": False,
    })
    if assessment_records_truncated:
        screening_summary["status"] = "partial"
        screening_summary["screening_status"] = "partial"
        screening_summary["coverage_status"] = "partial"
        screening_summary["completion_status"] = "partial"
        screening_summary["assessment_response_limit_reached"] = True
        screening_summary["partial_reasons"] = list(screening_summary.get("partial_reasons") or []) + ["assessment_response_limit_reached"]
        reason_codes = [code for code in (screening_summary.get("reason_code") or "").split(";") if code]
        if "assessment_response_limit_reached" not in reason_codes:
            reason_codes.append("assessment_response_limit_reached")
        screening_summary["reason_code"] = ";".join(reason_codes)
    else:
        screening_summary["assessment_response_limit_reached"] = False
    ml_model = model_status()
    result_status = _screening_result_status(run.summary["status"], assessments, assessment_records_truncated)
    message = {
        "valid_non_empty": "Trajectory-derived close approaches returned within the configured screening horizon.",
        "valid_empty": "Screening completed; no qualifying close approaches were found within the configured horizon and threshold.",
        "partial": "Partial trajectory screening completed; see screening metadata for propagation or resource-limit exclusions.",
        "unavailable": "Trajectory screening was unavailable because no usable TLE tracks were available.",
    }[result_status]
    if getattr(snapshot.source_summary, "status", None) == "fallback":
        message = "Live catalog acquisition failed; bundled fallback data was not used for physical screening."
    if assessment_records_truncated:
        message = "Partial trajectory assessment response; the screening result contains more assessment records than this response returned. See screening metadata for counts and limits."
    response_started = time.perf_counter()
    response_data = event_dicts(returned_assessments)
    serialization_seconds = time.perf_counter() - response_started
    response = {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result_status": result_status,
        "completion_status": "partial" if assessment_records_truncated else run.summary.get("completion_status", "failed"),
        "result_kind": "physics_assessment",
        "physics_assessment_status": screening_summary["status"],
        "ml_status": ml_model["status"],
        "ml_model": ml_model,
        "ml_available_event_count": sum(event.ml_result.status == "available" for event in assessments),
        "ml_threshold_flag_at_minus_6_event_count": sum(
            event.ml_result.status == "available" and bool(event.ml_result.prediction and event.ml_result.prediction.threshold_flag_at_minus_6)
            for event in assessments
        ),
        # Deprecated response alias retained for existing clients.
        "ml_high_risk_event_count": sum(
            event.ml_result.status == "available" and bool(event.ml_result.prediction and event.ml_result.prediction.threshold_flag_at_minus_6)
            for event in assessments
        ),
        "source_summary": snapshot.source_summary.model_dump(),
        "source_state": snapshot.source_state,
        "screening": {key: value for key, value in screening_summary.items() if key != "performance"},
        "provenance": {
            "source_summary": snapshot.source_summary.model_dump(),
            "source_state": snapshot.source_state,
            "catalog_input_hash": snapshot.stats.provenance.input_hash,
            "tle_epoch": snapshot.tle_epoch,
            "screening_method": run.summary.get("method"),
            "screening_method_version": run.summary.get("method_version"),
        },
        "data": response_data,
        "message": message,
    }
    run.summary.setdefault("performance", {})["api_request_total_seconds"] = time.perf_counter() - request_started
    run.summary["performance"]["response_event_serialization_seconds"] = serialization_seconds
    response["performance"] = {
        "diagnostic_scope": "aggregate timings; no per-object or per-epoch records",
        **run.summary["performance"],
    }
    return response


async def _execute_screening_job(job_id: str, *, limit: int, horizon_hours: float, sample_step_seconds: int,
                                 screening_threshold_km: float, start_utc: datetime) -> None:
    job = _screening_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now(timezone.utc).isoformat()
    job["progress"] = {
        "stage": "trajectory_screening",
        "percent": None,
        "message": "Screening is running. The propagator does not expose a truthful percentage until it completes.",
    }
    try:
        result = await conjunctions(
            limit=limit,
            min_pc=None,
            risk=None,
            horizon_hours=horizon_hours,
            sample_step_seconds=sample_step_seconds,
            screening_threshold_km=screening_threshold_km,
            start_utc=start_utc,
        )
        if isinstance(result, JSONResponse):
            result = json.loads(result.body)
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            for record in result["data"]:
                if isinstance(record, dict) and record.get("result_kind") == "physics_assessment":
                    record["screening_job_id"] = job_id
        job["result"] = result
        completion = result.get("completion_status", "failed")
        job["status"] = completion if completion in {"complete", "partial", "failed"} else "failed"
        job["progress"] = {
            "stage": "complete" if job["status"] == "complete" else job["status"],
            "percent": 100 if job["status"] in {"complete", "partial"} else None,
            "message": result.get("message", "Screening finished."),
        }
    except ValidationError as exc:
        logger.exception("Trajectory screening job %s failed", job_id)
        job["status"] = "failed"
        job["progress"] = {"stage": "failed", "percent": None, "message": "Screening failed before a result was produced."}
        job["result"] = {
            "success": False,
            "result_kind": "physics_assessment",
            "result_status": "error",
            "completion_status": "failed",
            "physics_assessment_status": "unavailable",
            "data": [],
            "reason_code": "SCREENING_EXECUTION_FAILED",
            "message": "Screening failed before a complete or partial result was produced.",
        }
        job["error_type"] = type(exc).__name__
    except Exception:
        logger.exception("Trajectory screening job %s failed unexpectedly", job_id)
        job["status"] = "failed"
        job["progress"] = {
            "stage": "failed",
            "percent": None,
            "message": "Screening failed unexpectedly before a result was produced.",
        }
        job["result"] = {
            "success": False,
            "result_kind": "physics_assessment",
            "result_status": "error",
            "completion_status": "failed",
            "physics_assessment_status": "unavailable",
            "data": [],
            "reason_code": "SCREENING_EXECUTION_FAILED",
            "message": "Screening execution failed before a complete or partial result was produced.",
        }
        job["error_code"] = "SCREENING_EXECUTION_FAILED"
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


@app.post("/api/conjunction-jobs", status_code=202)
async def create_conjunction_job(
    limit: int = Query(100, ge=1, le=400),
    horizon_hours: float = Query(DEFAULT_HORIZON_HOURS, ge=0.01, le=72),
    sample_step_seconds: int = Query(DEFAULT_SAMPLE_STEP_SECONDS, ge=10, le=300),
    screening_threshold_km: float = Query(DEFAULT_SCREENING_THRESHOLD_KM, gt=0, le=1_000),
    start_utc: datetime | None = None,
) -> dict:
    if start_utc is not None and (start_utc.tzinfo is None or start_utc.utcoffset() is None):
        raise HTTPException(status_code=422, detail="start_utc must include an explicit UTC offset.")
    start = (start_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_monotonic = time.monotonic()
    for old_id, old_job in list(_screening_jobs.items()):
        if old_job.get("status") in {"complete", "partial", "failed"} and now_monotonic - old_job.get("created_monotonic", now_monotonic) > SCREENING_JOB_TTL_SECONDS:
            _screening_jobs.pop(old_id, None)
    job_id = uuid.uuid4().hex
    _screening_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_monotonic": now_monotonic,
        "started_at": None,
        "finished_at": None,
        "progress": {"stage": "queued", "percent": 0, "message": "Screening job accepted."},
        "result": None,
        "configuration": {
            "limit": limit,
            "requested_limit": limit,
            "effective_catalog_limit": limit,
            "horizon_hours": horizon_hours,
            "requested_horizon_hours": horizon_hours,
            "effective_horizon_hours": horizon_hours,
            "sample_step_seconds": sample_step_seconds,
            "requested_sample_step_seconds": sample_step_seconds,
            "effective_sample_step_seconds": sample_step_seconds,
            "screening_threshold_km": screening_threshold_km,
            "requested_screening_threshold_km": screening_threshold_km,
            "effective_screening_threshold_km": screening_threshold_km,
            "start_utc": start.isoformat(),
        },
    }
    _screening_jobs[job_id]["task"] = asyncio.create_task(_execute_screening_job(
        job_id, limit=limit, horizon_hours=horizon_hours, sample_step_seconds=sample_step_seconds,
        screening_threshold_km=screening_threshold_km, start_utc=start,
    ))
    return {key: value for key, value in _screening_jobs[job_id].items() if key not in {"task", "result", "created_monotonic"}}


def _validate_archived_screening_job(job_id: str, archived: object) -> dict:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", job_id):
        raise HTTPException(status_code=422, detail="Screening job ID must be a 32-character hexadecimal ID.")
    if not isinstance(archived, dict):
        raise HTTPException(status_code=409, detail="Archived screening job must be a JSON object.")
    if archived.get("job_id") != job_id:
        raise HTTPException(status_code=409, detail="Archived screening job ID does not match the requested ID.")
    status = archived.get("status")
    if status not in {"complete", "partial"}:
        raise HTTPException(status_code=409, detail="Only complete or partial archived screening jobs can be restored.")
    result = archived.get("result")
    configuration = archived.get("configuration")
    summary = result.get("screening") if isinstance(result, dict) else None
    records = result.get("data") if isinstance(result, dict) else None
    if not isinstance(configuration, dict) or not isinstance(result, dict) or not isinstance(summary, dict):
        raise HTTPException(status_code=409, detail="Archived screening job is missing its configuration, result, or screening summary.")
    if result.get("result_kind") != "physics_assessment" or not isinstance(records, list):
        raise HTTPException(status_code=409, detail="Archived screening job does not contain a physical assessment record list.")
    if result.get("completion_status") != status or summary.get("completion_status") != status:
        raise HTTPException(status_code=409, detail="Archived screening job has inconsistent completion status metadata.")
    source_summary = result.get("source_summary")
    if not isinstance(source_summary, dict):
        raise HTTPException(status_code=409, detail="Archived screening job is missing its source summary.")
    if not isinstance(archived.get("progress"), dict):
        raise HTTPException(status_code=409, detail="Archived screening job has invalid progress metadata.")
    try:
        limit = configuration["limit"]
        horizon = configuration["horizon_hours"]
        sample_step = configuration["sample_step_seconds"]
        threshold = configuration["screening_threshold_km"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError
        if isinstance(horizon, bool) or not isinstance(horizon, (int, float)) or not 0.01 <= horizon <= 72:
            raise ValueError
        if isinstance(sample_step, bool) or not isinstance(sample_step, int) or not 10 <= sample_step <= 300:
            raise ValueError
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1_000:
            raise ValueError
        for key in ("created_at", "started_at", "finished_at", "start_utc"):
            value = configuration.get(key) if key == "start_utc" else archived.get(key)
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=409, detail="Archived screening job has invalid configuration or timestamp metadata.") from None
    record_ids: set[str] = set()
    for record in records:
        if (not isinstance(record, dict)
                or not isinstance(record.get("id"), str)
                or not record["id"]
                or record.get("result_kind") != "physics_assessment"
                or not isinstance(record.get("physics_result"), dict)):
            raise HTTPException(status_code=409, detail="Archived screening job contains a malformed assessment record.")
        if record["id"] in record_ids:
            raise HTTPException(status_code=409, detail="Archived screening job contains duplicate event identities.")
        record_ids.add(record["id"])
    return archived


def _backfill_archived_research_pc(result: dict) -> None:
    """Attach the current assumption-based estimate to legacy saved events.

    Screening exports created before automatic research Pc was added remain
    immutable on disk. On restore, valid interior-TCA events can be assessed
    from their archived event-matched states and object provenance.
    """
    records = result.get("data")
    if not isinstance(records, list):
        return
    validated_events = []
    records_by_id = {}
    missing_ai_assessment = False
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            event = ConjunctionAssessmentEvent.model_validate(record)
        except ValidationError:
            logger.warning("Skipping research Pc backfill for malformed archived event %s", record.get("id"))
            continue
        foster = event.collision_probability
        foster_risk = (record.get("collision_probability") or {}).get("risk_assessment")
        foster_risk_current = (isinstance(foster_risk, dict)
                               and foster_risk.get("risk_score_policy_version") == ORION_RISK_POLICY_VERSION
                               and foster_risk.get("status") == "classified")
        if (foster is not None and foster.status == "available" and foster.event_id == event.id
                and foster.pc is not None and not foster_risk_current):
            risk = classify_orion_physics_pc(foster.pc, "event_specific_foster_pc")
            updated_foster = foster.model_copy(update={"risk_assessment": risk})
            record["collision_probability"] = updated_foster.model_dump(mode="json")
            event = event.model_copy(update={"collision_probability": updated_foster})
        saved_research = record.get("automatic_research_pc_assessment") or {}
        saved_research_risk = saved_research.get("risk_assessment") or {}
        research_policy_current = (
            saved_research.get("method_version") == RESEARCH_PC_METHOD_VERSION
            and saved_research_risk.get("risk_score_policy_version") == ORION_RISK_POLICY_VERSION
            and saved_research_risk.get("status") == "classified"
        )
        if (not research_policy_current
                and event.physics_result.status == "valid" and event.physics_result.tca_status == "valid"):
            assessment = assess_automatic_research_pc(
                event.physics_result,
                event.collision_probability,
                event.review_priority,
                primary=event.primary,
                secondary=event.secondary,
            )
            record["automatic_research_pc_assessment"] = assessment.model_dump(mode="json")
            event = event.model_copy(update={"automatic_research_pc_assessment": assessment})
        collision_ai = assess_collision_ai(event)
        event = event.model_copy(update={"collision_ai_assessment": collision_ai})
        record["collision_ai_assessment"] = collision_ai.model_dump(mode="json")
        if event.ai_risk_assessment is None:
            ai_assessment = assess_live_geometry(event.physics_result)
            if ai_assessment is not None:
                event = event.model_copy(update={"ai_risk_assessment": ai_assessment})
                records_by_id[event.id] = record
                missing_ai_assessment = True
        validated_events.append(event)

    if missing_ai_assessment:
        for event in rank_screening_events(validated_events):
            record = records_by_id.get(event.id)
            if record is not None and event.ai_risk_assessment is not None:
                record["ai_risk_assessment"] = event.ai_risk_assessment.model_dump(mode="json")


def _load_archived_screening_job(job_id: str) -> dict:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", job_id):
        raise HTTPException(status_code=422, detail="Screening job ID must be a 32-character hexadecimal ID.")
    archive_path = SCREENING_EXPORT_ARCHIVE_DIR / f"screening-job-{job_id}.json"
    if not archive_path.is_file():
        demo_path = SCREENING_EXPORT_ARCHIVE_DIR / "demo" / archive_path.name
        if demo_path.is_file():
            archive_path = demo_path
    try:
        archived = json.loads(archive_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No archived screening job exists for this ID.") from None
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=409, detail="Archived screening job JSON is unreadable or malformed.") from None
    return _validate_archived_screening_job(job_id, archived)


@app.post("/api/conjunction-jobs/{job_id}/restore")
async def restore_archived_screening_job(job_id: str) -> dict:
    archived = _load_archived_screening_job(job_id)
    with _screening_registry_lock:
        existing = _screening_jobs.get(job_id)
        if existing is not None:
            if existing.get("restored_from_archive"):
                return copy.deepcopy(existing)
            raise HTTPException(status_code=409, detail="A live screening job with this ID is already in the registry; it was left unchanged.")
        restored = copy.deepcopy(archived)
        _backfill_archived_research_pc(restored["result"])
        restored["restored_from_archive"] = True
        restored["archived"] = True
        _screening_jobs[job_id] = restored
    return copy.deepcopy(restored)


def _screening_job_for_smart_filter(job_id: str) -> dict:
    job = _screening_jobs.get(job_id)
    if job is None:
        archived = _load_archived_screening_job(job_id)
        job = copy.deepcopy(archived)
        _backfill_archived_research_pc(job["result"])
        job["restored_from_archive"] = True
        job["archived"] = True
    if job.get("status") not in {"complete", "partial"} or not isinstance(job.get("result"), dict):
        raise HTTPException(status_code=409, detail="Smart Filter requires a completed or partial physical screening job.")
    # Runtime asyncio task handles are process-local and cannot be deep-copied.
    # The smart-filter consumer only needs the terminal data snapshot.
    return copy.deepcopy({key: value for key, value in job.items() if key != "task"})


@app.get("/api/conjunction-jobs/{job_id}/smart-filter")
async def evaluate_screening_job_smart_filter(job_id: str) -> dict:
    policy = filter_policy()
    cache_key = f"{job_id}|{policy['significant_pc_threshold']}|{policy['safety_miss_distance_threshold_km']}"
    with _smart_filter_results_lock:
        cached = _smart_filter_results.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    job = _screening_job_for_smart_filter(job_id)
    records = job["result"].get("data") or []
    events: list[ConjunctionAssessmentEvent] = []
    unparsed: list[dict] = []
    for record in records:
        try:
            events.append(ConjunctionAssessmentEvent.model_validate(record))
        except ValidationError:
            unparsed.append({
                "event_id": record.get("id") if isinstance(record, dict) else None,
                "object_ids": [], "object_names": [], "tca_utc": None, "miss_distance_km": None,
                "relative_speed_km_s": None, "decision": "retain",
                "reason": "SAFETY_GUARD_INVALID_OR_UNCERTAIN_RECORD",
                "reason_code": "SAFETY_GUARD_INVALID_OR_UNCERTAIN_RECORD",
                "decision_source": "safety_guard",
                "model_status": "unavailable", "model_prediction": None, "confidence": None,
                "confidence_definition": policy["confidence_definition"], "safety_guard_retained": True,
                "safety_guard_reasons": ["SAFETY_GUARD_INVALID_OR_UNCERTAIN_RECORD"],
                "scenario_count_calculated": 0, "scenario_count_required": policy["scenario_count"],
                "maximum_scenario_log10_pc": None, "maximum_scenario_pc_scientific": None,
                "scenario_errors": {}, "model_name": None, "model_version": None,
            })
    result = await run_in_threadpool(evaluate_physical_smart_filter, events)
    if unparsed:
        result["decisions"].extend(unparsed)
        result["evaluation"]["before_count"] += len(unparsed)
        result["evaluation"]["kept_count"] += len(unparsed)
        result["evaluation"]["safety_guard_retained_count"] += len(unparsed)
    payload = {
        **result,
        "screening_job_id": job_id,
        "screening_job_archived": bool(job.get("archived") or job.get("restored_from_archive")),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with _smart_filter_results_lock:
        _smart_filter_results[cache_key] = copy.deepcopy(payload)
    return payload


@app.get("/api/conjunction-jobs/{job_id}/smart-filter.csv")
async def export_screening_job_smart_filter_csv(job_id: str) -> Response:
    result = await evaluate_screening_job_smart_filter(job_id)
    stream = io.StringIO(newline="")
    columns = [
        "event_id", "object_ids", "object_names", "tca_utc", "miss_distance_km",
        "relative_speed_km_s", "decision", "reason", "model_status", "model_prediction",
        "decision_source", "confidence", "safety_guard_retained", "safety_guard_reasons",
        "scenario_count_calculated", "scenario_count_required", "maximum_scenario_pc_scientific",
    ]
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in result["decisions"]:
        writer.writerow({**row, "object_ids": "|".join(row.get("object_ids") or []),
                         "object_names": "|".join(row.get("object_names") or []),
                         "safety_guard_reasons": "|".join(row.get("safety_guard_reasons") or [])})
    content = stream.getvalue()
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{job_id}-smart-filter.csv"'})


@app.get("/api/conjunction-jobs/{job_id}")
async def get_conjunction_job(job_id: str) -> dict:
    job = _screening_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Screening job not found in this backend process.")
    payload = {key: value for key, value in job.items() if key not in {"task", "result", "created_monotonic"}}
    payload["completion_status"] = job["status"] if job["status"] in {"complete", "partial", "failed"} else None
    if job["result"] is not None:
        result = copy.deepcopy(job["result"])
        records = result.get("data") or []
        page_size = ASSESSMENT_PAGE_SIZE_DEFAULT
        result["data"] = records[:page_size]
        total = len(records)
        result_summary = result.setdefault("screening", {})
        result_summary["total_records_available"] = total
        result_summary["records_returned"] = len(result["data"])
        result_summary["has_more_records"] = total > page_size
        result_summary["response_page_partial"] = total > page_size
        result_summary["returned_assessment_record_count"] = len(result["data"])
        result_summary["assessment_records_truncated"] = total > page_size
        result["assessment_pagination"] = {
            "page": 1, "page_size": page_size, "total_records": total,
            "returned_records": len(result["data"]), "has_more": total > page_size,
            "next_page": 2 if total > page_size else None,
            "retrieval_url": f"/api/conjunction-jobs/{job_id}/assessments?page={{page}}&page_size={{page_size}}",
        }
        payload["result"] = result
    return payload


@app.get("/api/conjunction-jobs/{job_id}/assessments")
async def get_conjunction_job_assessments(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(ASSESSMENT_PAGE_SIZE_DEFAULT, ge=1, le=ASSESSMENT_PAGE_SIZE_MAX),
) -> dict:
    job = _screening_jobs.get(job_id)
    if not job or job.get("status") not in {"complete", "partial"} or not job.get("result"):
        raise HTTPException(status_code=404, detail="Completed screening job was not found or has expired.")
    records = job["result"].get("data")
    if not isinstance(records, list):
        raise HTTPException(status_code=409, detail="The screening job has no assessment record list.")
    total = len(records)
    offset = (page - 1) * page_size
    rows = records[offset:offset + page_size]
    return {
        "job_id": job_id, "page": page, "page_size": page_size,
        "total_records": total, "returned_records": len(rows),
        "has_more": offset + len(rows) < total,
        "next_page": page + 1 if offset + len(rows) < total else None,
        "data": rows,
    }


def _completed_job_event(job_id: str, event_id: str, *, allow_archived_read: bool = False) -> tuple[dict, int, ConjunctionAssessmentEvent]:
    job = _screening_jobs.get(job_id)
    if job is None and allow_archived_read:
        job = _screening_job_for_export(job_id)
        if job is not None:
            _backfill_archived_research_pc(job.get("result") or {})
    if not job or job.get("status") not in {"complete", "partial"} or not job.get("result"):
        raise HTTPException(status_code=404, detail="Completed screening job was not found or has expired.")
    if job.get("restored_from_archive") and not allow_archived_read:
        raise HTTPException(status_code=409, detail="Archived screening results are read-only; restore a live job to submit new assessment inputs.")
    data = job["result"].get("data")
    if not isinstance(data, list):
        raise HTTPException(status_code=409, detail="The selected screening job has no event result list.")
    index = next((index for index, item in enumerate(data) if isinstance(item, dict) and item.get("id") == event_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="The selected event is not part of this completed screening job.")
    try:
        event = ConjunctionAssessmentEvent.model_validate(data[index])
    except Exception as exc:
        raise HTTPException(status_code=409, detail="The selected stored result is not a valid physical event.") from exc
    if event.result_kind != "physics_assessment":
        raise HTTPException(status_code=422, detail="Collision probability inputs require a Stage 2A physical event.")
    if event.screening_job_id is not None and event.screening_job_id != job_id:
        raise _identity_http_error(409, "EVENT_JOB_MISMATCH", "The selected event belongs to a different screening job.")
    return job, index, event


def _identity_http_error(status_code: int, reason_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"reason_code": reason_code, "message": message})


def _pc_input_http_error(exc: ValueError) -> HTTPException:
    reason_code = str(exc).strip().split(":", 1)[0] or "PC_INPUT_INVALID"
    message = reason_code.replace("_", " ").capitalize()
    return HTTPException(status_code=422, detail={"reason_code": reason_code, "message": message})


def _event_tca_identity(event: ConjunctionAssessmentEvent) -> tuple[object, ...]:
    field = event.physics_result.tca
    raw_value = field.value if field else None
    if isinstance(raw_value, str):
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            normalized = parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else ("invalid", raw_value)
        except ValueError:
            normalized = ("invalid", raw_value)
    else:
        normalized = raw_value
    return (event.physics_result.tca_status, field.status if field else None, field.units if field else None, normalized)


def _event_identity_matches(stored: ConjunctionAssessmentEvent, supplied: ConjunctionAssessmentEvent) -> bool:
    """Compare stable event identity while ignoring client-supplied state vectors."""
    object_ids = lambda event: (
        event.primary.id, event.secondary.id, event.obj_a.id, event.obj_b.id,
    )
    return (
        stored.id == supplied.id
        and stored.screening_job_id == supplied.screening_job_id
        and object_ids(stored) == object_ids(supplied)
        and stored.result_kind == supplied.result_kind
        and stored.physics_result.event_id == supplied.physics_result.event_id
        and stored.physics_result.status == supplied.physics_result.status
        and _event_tca_identity(stored) == _event_tca_identity(supplied)
        and stored.provenance.model_dump(mode="json") == supplied.provenance.model_dump(mode="json")
        and stored.primary.provenance.model_dump(mode="json") == supplied.primary.provenance.model_dump(mode="json")
        and stored.secondary.provenance.model_dump(mode="json") == supplied.secondary.provenance.model_dump(mode="json")
    )


def _require_usable_physical_event(event: ConjunctionAssessmentEvent) -> None:
    if event.result_kind != "physics_assessment" or event.provenance.is_synthetic or event.provenance.source_type == "synthetic":
        raise _identity_http_error(422, "DEMO_OR_PROXY_EVENT", "Demo, proxy, and synthetic events cannot be used as physical conjunctions.")
    if event.physics_result.status != "valid" or event.provenance.validity_status != "valid":
        raise _identity_http_error(422, "EVENT_NOT_PHYSICALLY_VALID", "The stored event does not have valid physical trajectory status.")


def _stored_physical_event_for_report(job_id: str, event_id: str) -> tuple[dict, ConjunctionAssessmentEvent]:
    job = _screening_jobs.get(job_id)
    if not job:
        raise _identity_http_error(404, "JOB_NOT_FOUND", "The selected screening job was not found or has expired.")
    if job.get("status") not in {"complete", "partial"} or not isinstance(job.get("result"), dict):
        code = "JOB_FAILED" if job.get("status") == "failed" else "JOB_NOT_TERMINAL"
        raise _identity_http_error(409, code, "Event reports require a completed or partial screening job.")
    records = job["result"].get("data")
    if not isinstance(records, list):
        raise _identity_http_error(409, "JOB_RESULT_UNAVAILABLE", "The selected screening job has no event result list.")
    record = next((item for item in records if isinstance(item, dict) and item.get("id") == event_id), None)
    if record is None:
        raise _identity_http_error(404, "EVENT_NOT_FOUND", "The selected event is not part of this screening job.")
    if record.get("result_kind") != "physics_assessment":
        raise _identity_http_error(422, "DEMO_OR_PROXY_EVENT", "Proxy and nonphysical events cannot be reported as physical conjunctions.")
    try:
        event = ConjunctionAssessmentEvent.model_validate(record)
    except Exception as exc:
        raise _identity_http_error(409, "STORED_EVENT_INVALID", "The stored event is invalid and cannot be reported as a physical conjunction.") from exc
    if event.id != event_id or event.physics_result.event_id != event_id:
        raise _identity_http_error(409, "STORED_EVENT_IDENTITY_MISMATCH", "The stored event identity is inconsistent with the report request.")
    _require_usable_physical_event(event)
    if event.screening_job_id is not None and event.screening_job_id != job_id:
        raise _identity_http_error(409, "EVENT_JOB_MISMATCH", "The stored event belongs to a different screening job.")
    return job, event


def _maneuver_result_for_report(job: dict, job_id: str, event_id: str) -> dict:
    unavailable_reason = "JOB_INCOMPLETE" if job.get("status") == "partial" else "MANEUVER_ASSESSMENT_NOT_AVAILABLE"
    result = (job.get("maneuver_results") or {}).get(event_id)
    if result is None:
        return {
            "event_id": event_id, "screening_job_id": job_id, "status": "unavailable",
            "reason_code": unavailable_reason,
            "reason": "No maneuver simulation result is stored for this event and screening job.",
        }
    if not isinstance(result, dict) or result.get("event_id") != event_id or result.get("screening_job_id") != job_id:
        return {
            "event_id": event_id, "screening_job_id": job_id, "status": "unavailable",
            "reason_code": "MANEUVER_RESULT_IDENTITY_MISMATCH",
            "reason": "Stored maneuver result identity does not match this event and screening job.",
        }
    for block_name in ("stage2a_reference", "zero_burn_baseline", "physics_candidates", "surrogate_rank"):
        block = result.get(block_name)
        if isinstance(block, dict) and (block.get("event_id") != event_id or block.get("screening_job_id") != job_id):
            return {
                "event_id": event_id, "screening_job_id": job_id, "status": "unavailable",
                "reason_code": "MANEUVER_RESULT_IDENTITY_MISMATCH",
                "reason": f"Stored {block_name} maneuver block identity does not match this event and screening job.",
            }
    candidate_block = result.get("physics_candidates") or {}
    if not isinstance(candidate_block, dict):
        return {
            "event_id": event_id, "screening_job_id": job_id, "status": "unavailable",
            "reason_code": "MANEUVER_RESULT_IDENTITY_MISMATCH",
            "reason": "Stored maneuver candidate block is malformed.",
        }
    candidates = candidate_block.get("candidates", [])
    if any(not isinstance(item, dict) or item.get("event_id") != event_id or item.get("screening_job_id") != job_id for item in candidates):
        return {
            "event_id": event_id, "screening_job_id": job_id, "status": "unavailable",
            "reason_code": "MANEUVER_RESULT_IDENTITY_MISMATCH",
            "reason": "Stored maneuver candidate identity does not match this event and screening job.",
        }
    return result


@app.post("/api/conjunction-jobs/{job_id}/events/{event_id}/cdm")
async def import_event_cdm(job_id: str, event_id: str, request: CdmImportRequest) -> dict:
    job, index, event = _completed_job_event(job_id, event_id)
    try:
        cdm = parse_cdm_input(request.cdm_xml, source_label=request.source_label)
        updated = apply_cdm_inputs(
            event,
            cdm,
            assume_independent_covariances=request.assume_independent_covariances,
        )
    except ValueError as exc:
        raise _pc_input_http_error(exc) from exc
    stored = updated.model_dump(mode="json")
    job["result"]["data"][index] = stored
    return {
        "success": True,
        "result_kind": "physics_assessment",
        "job_id": job_id,
        "data": stored,
        "input_provenance": {
            "source_type": "user_supplied",
            "source_format": cdm.source_format,
            "input_sha256": cdm.input_sha256,
            "originator": cdm.originator,
            "created_utc": cdm.created_utc,
            "source_authenticated": False,
            "object_hbr_inputs_km": {
                item.object_designator: item.object_hbr_km for item in cdm.inputs
            },
        },
    }


@app.post("/api/collision-probability/cdm")
async def calculate_reference_cdm_pc(request: CdmImportRequest) -> dict:
    """Evaluate a supplied historical/reference CDM without binding it to a TLE job."""
    try:
        cdm = parse_cdm_input(request.cdm_xml, source_label=request.source_label)
        data = evaluate_cdm_reference(
            cdm,
            assume_independent_covariances=request.assume_independent_covariances,
        )
    except ValueError as exc:
        raise _pc_input_http_error(exc) from exc
    return {
        "success": True,
        "result_kind": "standalone_cdm_reference_assessment",
        "input_provenance": {
            "source_type": "user_supplied",
            "source_format": cdm.source_format,
            "input_sha256": cdm.input_sha256,
            "originator": cdm.originator,
            "created_utc": cdm.created_utc,
            "source_authenticated": False,
        },
        "data": data,
        "message": "This CDM assessment remains separate from live TLE screening events.",
    }


@app.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d")
async def calculate_nasa_cara_reference_case() -> dict:
    """Run the bundled, traceable NASA CARA Foster 2D numerical CDM case."""
    try:
        raw_cdm = NASA_CARA_PC_REFERENCE_PATH.read_text(encoding="utf-8")
        cdm = parse_cdm_input(raw_cdm, source_label="Bundled NASA CARA public Foster 2D reference CDM")
        # The published source Pc is a Foster-1992 value from the same two
        # object covariances. Reproduce the documented independent covariance
        # sum explicitly; the resulting assumption is retained in the output.
        data = evaluate_cdm_reference(cdm, assume_independent_covariances=True)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail={
            "reason_code": "NASA_CARA_REFERENCE_CASE_UNAVAILABLE",
            "message": "The bundled NASA CARA reference case could not be loaded or validated.",
        }) from exc
    pc_result = data["collision_probability"]
    source_pc = cdm.source_pc
    computed_pc = pc_result.pc
    tolerance = 5e-9  # Half-step represented by the CDM's published 1.862e-05 value.
    absolute_difference = abs(computed_pc - source_pc) if computed_pc is not None and source_pc is not None else None
    data["reference_case"] = {
        "name": "NASA CARA PcTestCaseCDMs Foster 2D case",
        "source_url": NASA_CARA_PC_REFERENCE_URL,
        "source_sha256": cdm.input_sha256,
        "source_license_note": "Distributed in NASA CARA Analysis Tools; the repository lists NASA Open Source Software Agreements. No separate data-specific license statement was found.",
        "expected_pc": source_pc,
        "expected_pc_method": cdm.source_pc_method,
        "computed_pc": computed_pc,
        "absolute_difference": absolute_difference,
        "comparison_tolerance": tolerance,
        "within_tolerance": absolute_difference is not None and absolute_difference <= tolerance,
        "tolerance_basis": "The source CDM reports Pc as 1.862e-05 (four significant digits); tolerance is half a unit in its final printed digit.",
        "independence_assumption": "Explicitly authorized for this Foster 2D reference reproduction; ORION adds the two supplied object position covariances.",
        "live_event_binding": "none; this historical reference event is standalone and never attached to a TLE screening event",
        "classification_policy_version": PC_CLASSIFICATION_POLICY_VERSION,
    }
    return {
        "success": True,
        "result_kind": "standalone_nasa_cara_reference_assessment",
        "input_provenance": {
            "source_type": "bundled_public_reference_fixture",
            "source_format": cdm.source_format,
            "input_sha256": cdm.input_sha256,
            "originator": cdm.originator,
            "created_utc": cdm.created_utc,
            "source_authenticated": False,
            "source_url": NASA_CARA_PC_REFERENCE_URL,
        },
        "data": data,
        "message": "Historical NASA CARA reference calculation; isolated from live TLE screening events.",
    }


@app.post("/api/conjunction-jobs/{job_id}/events/{event_id}/scenario-pc")
async def calculate_event_scenario_pc(job_id: str, event_id: str, request: ScenarioPcRequest) -> dict:
    job, index, event = _completed_job_event(job_id, event_id)
    try:
        updated = apply_scenario_inputs(
            event,
            covariance_primary_km2=request.covariance_primary_km2,
            covariance_secondary_km2=request.covariance_secondary_km2,
            hbr_km=request.hbr_km,
            assumptions=request.assumptions,
            assume_independent_covariances=request.assume_independent_covariances,
        )
    except ValueError as exc:
        raise _pc_input_http_error(exc) from exc
    stored = updated.model_dump(mode="json")
    job["result"]["data"][index] = stored
    return {
        "success": True,
        "result_kind": "research_scenario",
        "job_id": job_id,
        "data": stored,
        "message": "Scenario output uses explicit user-entered assumptions and is separate from source-supported physical Pc.",
    }


@app.post("/api/conjunction-jobs/{job_id}/events/{event_id}/research-pc-scenario")
async def calculate_research_pc_scenario(job_id: str, event_id: str, request: ResearchPcScenarioRequest) -> dict:
    _, _, event = _completed_job_event(job_id, event_id, allow_archived_read=True)
    assessment = assess_automatic_research_pc(
        event.physics_result, event.collision_probability, event.review_priority,
        primary=event.primary, secondary=event.secondary,
        covariance_policy=request.covariance_policy,
        covariance_scale=request.covariance_scale, hbr_scale=request.hbr_scale,
    )
    return {
        "success": assessment.status in {"prior_based_research_estimate", "event_specific_foster_available"},
        "job_id": job_id, "event_id": event_id,
        "result_kind": "research_pc_scenario", "data": assessment.model_dump(mode="json"),
    }


@app.get("/api/screening-proxies")
async def screening_proxies(limit: int = Query(100, ge=1, le=200), risk: str | None = None) -> dict:
    snapshot, events = await build_event_context(limit=900, forecast_hours=24)
    if risk is not None:
        events = [event for event in events if event.risk_level.lower() == risk.lower()]
    selected = events[:limit]
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result_status": "non_empty" if selected else "empty",
        "result_kind": "screening_proxy",
        "physics_assessment_status": "not_assessed",
        "ml_status": "unavailable",
        "source_summary": snapshot.source_summary.model_dump(),
        "data": [event.model_dump(mode="json", exclude={
            "obj_a": True, "obj_b": True, "features": True, "physics_result": True, "ml_result": True, "comparison_result": True,
            "provenance": {"source_record": True},
            "primary": {"provenance": {"source_record": True}},
            "secondary": {"provenance": {"source_record": True}},
        }) for event in selected],
        "message": "Deterministic catalog heuristic proxies; no trajectory-based close-approach assessment is implied.",
    }


@app.get("/api/conjunctions/{event_id}")
async def conjunction_detail(event_id: str) -> dict:
    if event_id.startswith("SP-"):
        snapshot, events = await build_event_context(limit=900, forecast_hours=24)
        event = next((item for item in events if item.id == event_id), None)
        if not event:
            raise HTTPException(status_code=404, detail="Screening proxy event not found.")
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result_kind": "screening_proxy",
            "physics_assessment_status": "not_assessed",
            "source_summary": snapshot.source_summary.model_dump(),
            "data": event.model_dump(mode="json"),
        }
    snapshot, run = await build_trajectory_context(limit=900)
    events = run.events
    event = next((item for item in events if item.id == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="Trajectory assessment not found in the current screening run.")
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result_kind": "physics_assessment",
        "physics_assessment_status": event.physics_result.status,
        "source_summary": snapshot.source_summary.model_dump(),
        "data": event.model_dump(mode="json"),
    }


def _reference_maneuver_result(request: ReferenceManeuverRequest) -> dict:
    try:
        raw_cdm = NASA_CARA_PC_REFERENCE_PATH.read_text(encoding="utf-8")
        cdm = parse_cdm_input(raw_cdm, source_label="Bundled NASA CARA public Foster 2D reference CDM")
        expected_event_id = f"CDM-{cdm.input_sha256[:24]}"
        if request.event_id != expected_event_id:
            raise HTTPException(status_code=404, detail={"reason_code": "REFERENCE_EVENT_NOT_FOUND", "message": "The requested event ID does not identify the bundled reference CDM."})
        return assess_reference_maneuver(
            cdm,
            event_id=expected_event_id,
            maneuvering_object_id=request.maneuvering_object_id,
            burn_lead_seconds=request.burn_lead_seconds,
            direction=request.direction,
            delta_v_m_s=request.delta_v_m_s,
        )
    except ValueError as exc:
        raise _pc_input_http_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail={"reason_code": "NASA_CARA_REFERENCE_CASE_UNAVAILABLE", "message": "The bundled NASA CARA reference case could not be loaded."}) from exc


@app.post("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver")
async def calculate_reference_maneuver(request: ReferenceManeuverRequest) -> dict:
    data = _reference_maneuver_result(request)
    return {
        "success": True,
        "result_kind": "standalone_reference_cdm_maneuver_assessment",
        "input_provenance": {
            "source_type": "bundled_public_reference_fixture",
            "source_format": "CCSDS CDM KVN",
            "input_sha256": data["source_input_sha256"],
            "source_authenticated": False,
            "live_screening_binding": "none",
        },
        "data": data,
        "message": "Trajectory-only reference-CDM maneuver experiment; post-maneuver Pc is unavailable without covariance propagation.",
    }


@app.get("/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver-report.pdf")
async def reference_maneuver_report(
    event_id: str,
    maneuvering_object_id: str,
    burn_lead_seconds: float = Query(..., ge=60, le=10800),
    direction: Literal["radial+", "radial-", "along_track+", "along_track-", "cross_track+", "cross_track-"] = Query(...),
    delta_v_m_s: float = Query(..., gt=0, le=0.1),
) -> StreamingResponse:
    request = ReferenceManeuverRequest(
        event_id=event_id,
        maneuvering_object_id=maneuvering_object_id,
        burn_lead_seconds=burn_lead_seconds,
        direction=direction,
        delta_v_m_s=delta_v_m_s,
    )
    data = _reference_maneuver_result(request)
    pdf = reference_maneuver_report_pdf(data)
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{event_id}-reference-maneuver-assessment.pdf"'},
    )


@app.get("/api/collision-probability/reference-cases/nasa-cara-foster-2d/assessment.pdf")
async def nasa_cara_reference_assessment_pdf() -> StreamingResponse:
    payload = await calculate_nasa_cara_reference_case()
    pdf = reference_cdm_report_pdf({**payload["data"], "source_label": "Bundled public NASA CARA reference CDM"})
    return StreamingResponse(iter([pdf]), media_type="application/pdf", headers={
        "Content-Disposition": 'attachment; filename="vyoma-reference-collision-assessment.pdf"',
    })


@app.post("/api/conjunctions/{event_id}/maneuver", response_model=ManeuverAssessmentResponse, response_model_exclude_unset=True)
async def maneuver(
    event_id: str,
    event: ConjunctionAssessmentEvent,
    screening_job_id: str,
    lead_seconds: float = Query(300, ge=60, le=10800),
    burn_magnitudes_m_s: str = Query("0.01,0.05"),
    rtn_direction: Literal["all", "radial_plus", "radial_minus", "along_track_plus", "along_track_minus", "cross_track_plus", "cross_track_minus"] = Query("all"),
    max_delta_v_m_s: float | None = Query(None, gt=0, le=0.1),
    initial_mass_kg: float | None = Query(None, gt=0),
    specific_impulse_s: float | None = Query(None, gt=0, le=2000),
    covariance_scale: float = Query(1.0, ge=0.5, le=3.0),
) -> ManeuverAssessmentResponse:
    # Maneuver evaluation must use the exact completed screening event selected
    # in the UI. Re-running the catalog screen here could select a different
    # event (or repeat minutes of expensive work) and lose its state vectors.
    if event.id != event_id:
        raise _identity_http_error(422, "EVENT_ID_MISMATCH", "Path event ID must match the supplied trajectory event.")
    job = _screening_jobs.get(screening_job_id)
    if not job:
        raise _identity_http_error(404, "JOB_NOT_FOUND", "The requested screening job was not found or has expired.")
    if job.get("status") == "failed":
        raise _identity_http_error(409, "JOB_FAILED", "A failed screening job cannot be used for maneuver assessment.")
    if job.get("status") in {"queued", "running"}:
        raise _identity_http_error(409, "JOB_NOT_TERMINAL", "Maneuver assessment requires a terminal screening job.")
    if job.get("status") not in {"complete", "partial"} or not job.get("result"):
        raise _identity_http_error(409, "JOB_UNAVAILABLE", "The screening job is unavailable for maneuver assessment.")
    stored_event = next((item for item in job["result"].get("data", []) if item.get("id") == event_id), None)
    if not stored_event:
        raise _identity_http_error(404, "EVENT_NOT_FOUND", "The selected event is not part of this screening job.")
    if stored_event.get("screening_job_id") is not None and stored_event.get("screening_job_id") != screening_job_id:
        raise _identity_http_error(409, "EVENT_JOB_MISMATCH", "The selected event belongs to a different screening job.")
    def discard_previous_assessment() -> None:
        previous = job.get("maneuver_results")
        if isinstance(previous, dict):
            previous.pop(event_id, None)

    if stored_event.get("result_kind") != "physics_assessment":
        discard_previous_assessment()
        raise _identity_http_error(422, "DEMO_OR_PROXY_EVENT", "Maneuver evaluation rejects heuristic proxy and nonphysical events.")
    try:
        authoritative_event = ConjunctionAssessmentEvent.model_validate(stored_event)
    except Exception as exc:
        discard_previous_assessment()
        raise _identity_http_error(409, "STORED_EVENT_INVALID", "The event stored in this screening job is invalid and cannot be simulated.") from exc
    if authoritative_event.id != event_id or authoritative_event.physics_result.event_id != event_id:
        discard_previous_assessment()
        raise _identity_http_error(409, "STORED_EVENT_IDENTITY_MISMATCH", "The stored trajectory event identity is inconsistent with the selected event.")
    if not _event_identity_matches(authoritative_event, event):
        discard_previous_assessment()
        raise _identity_http_error(409, "EVENT_IDENTITY_MISMATCH", "Submitted object IDs, source provenance, or physical-validity metadata do not match the stored event.")
    _require_usable_physical_event(authoritative_event)
    try:
        magnitudes = tuple(float(value.strip()) for value in burn_magnitudes_m_s.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="burn_magnitudes_m_s must be comma-separated numeric values.") from exc
    if not magnitudes or len(magnitudes) > 4 or any(not np.isfinite(value) or value <= 0 or value > 0.1 for value in magnitudes):
        raise HTTPException(status_code=422, detail="Provide one to four burn magnitudes in the range (0, 0.1] m/s.")
    if (initial_mass_kg is None) != (specific_impulse_s is None):
        raise HTTPException(status_code=422, detail="initial_mass_kg and specific_impulse_s must be supplied together for a fuel estimate.")
    maneuver_result = optimize_maneuver(
        authoritative_event,
        lead_seconds=lead_seconds,
        burn_magnitudes_m_s=magnitudes,
        max_delta_v_m_s=max_delta_v_m_s,
        initial_mass_kg=initial_mass_kg,
        specific_impulse_s=specific_impulse_s,
        rtn_direction=rtn_direction,
        covariance_scale=covariance_scale,
    )
    if not isinstance(maneuver_result, dict) or maneuver_result.get("event_id") != event_id:
        discard_previous_assessment()
        raise _identity_http_error(409, "MANEUVER_RESULT_IDENTITY_MISMATCH", "Maneuver result identity does not match the selected event and screening job.")
    maneuver_result["screening_job_id"] = screening_job_id
    maneuver_result["screening_job_status"] = job.get("status")
    maneuver_result["screening_job_archived"] = bool(job.get("restored_from_archive"))
    if job.get("status") == "partial":
        maneuver_result.setdefault("limitations", []).append(
            "The originating screening job was partial; this maneuver assessment applies only to the selected event and does not imply complete catalog screening."
        )
        if maneuver_result.get("status") == "available":
            maneuver_result["status"] = "available_with_warning"
    for block_name in ("stage2a_reference", "zero_burn_baseline", "physics_candidates", "surrogate_rank"):
        block = maneuver_result.get(block_name)
        if isinstance(block, dict):
            block["event_id"] = event_id
            block["screening_job_id"] = screening_job_id
            if block_name == "physics_candidates":
                for candidate in block.get("candidates", []):
                    if isinstance(candidate, dict):
                        candidate["event_id"] = event_id
                        candidate["screening_job_id"] = screening_job_id
    ml_result = maneuver_result.get("ml_result")
    if isinstance(ml_result, dict):
        provenance = ml_result.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance.update({"source_event_id": event_id, "screening_job_id": screening_job_id})
    if maneuver_result.get("status") in {"available", "available_with_warning"}:
        job.setdefault("maneuver_results", {})[event_id] = maneuver_result
    else:
        discard_previous_assessment()
    return ManeuverAssessmentResponse(
        success=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
        screening_job_id=screening_job_id,
        data=maneuver_result,
        message="Returns an exploratory two-body candidate sweep when event states pass validation; never uses ESA event-risk inference for maneuvers.",
    )


@app.post("/api/maneuver/user-upload", response_model=ManeuverAssessmentResponse, response_model_exclude_unset=True)
async def maneuver_user_upload(
    request: Request,
    lead_seconds: float = Query(300, ge=60, le=10800),
    burn_magnitude_m_s: float = Query(0.01, gt=0, le=0.1),
    rtn_direction: Literal["all", "radial_plus", "radial_minus", "along_track_plus", "along_track_minus", "cross_track_plus", "cross_track_minus"] = Query("all"),
    initial_mass_kg: float | None = Query(None, gt=0),
    specific_impulse_s: float | None = Query(None, gt=0, le=2000),
) -> ManeuverAssessmentResponse:
    """Run the research maneuver workflow from a validated event JSON or CSV wrapper.

    CSV format: one row with a single `event_json` column containing the canonical
    ConjunctionAssessmentEvent JSON. This keeps nested state vectors unambiguous.
    """
    if (initial_mass_kg is None) != (specific_impulse_s is None):
        raise HTTPException(status_code=422, detail={"reason_code": "MASS_AND_ISP_MUST_BE_PAIRED", "message": "Supply both spacecraft mass and specific impulse, or leave both blank to use configured defaults."})
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail={"reason_code": "UPLOAD_TOO_LARGE", "message": "Maneuver event upload is limited to 2 MB."})
    content_type = request.headers.get("content-type", "").lower()
    try:
        if "json" in content_type:
            payload = json.loads(raw)
        elif "csv" in content_type or raw[:256].decode("utf-8-sig", errors="ignore").lstrip().startswith("event_json"):
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if len(rows) != 1 or not rows[0].get("event_json"):
                raise ValueError("CSV must contain exactly one row with an event_json column.")
            payload = json.loads(rows[0]["event_json"])
        else:
            raise HTTPException(status_code=415, detail={"reason_code": "UNSUPPORTED_UPLOAD_FORMAT", "message": "Upload a JSON event or a CSV with one event_json column."})
        event = ConjunctionAssessmentEvent.model_validate(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"reason_code": "INVALID_MANEUVER_UPLOAD", "message": "The uploaded event does not match the required ORION event schema."}) from exc
    if event.provenance.source_type != "user_supplied" or event.provenance.is_synthetic:
        raise HTTPException(status_code=422, detail={"reason_code": "UPLOAD_PROVENANCE_REQUIRED", "message": "Uploaded events must identify user_supplied provenance and must not be synthetic."})
    physics = event.physics_result
    tca = physics.tca.value if physics.tca else None
    states = (physics.primary_state_at_tca, physics.secondary_state_at_tca)
    try:
        tca_epoch = datetime.fromisoformat(str(tca).replace("Z", "+00:00")).astimezone(timezone.utc)
        state_epochs_match = all(
            datetime.fromisoformat(str(state.get("epoch")).replace("Z", "+00:00")).astimezone(timezone.utc) == tca_epoch
            for state in states if isinstance(state, dict)
        )
    except (TypeError, ValueError):
        state_epochs_match = False
    if (physics.status != "valid" or physics.tca_status != "valid" or not tca
            or not physics.state_information
            or physics.state_information.get("source_frame") != "TEME"
            or physics.state_information.get("position_units") != "km"
            or physics.state_information.get("velocity_units") != "km/s"
            or not state_epochs_match
            or any(not isinstance(state, dict) or not state.get("epoch") or state.get("frame") != "TEME"
                   or state.get("object_id") not in {None, summary.id}
                   or state.get("position_km") is None or state.get("velocity_km_s") is None
                   for state, summary in zip(states, (event.primary, event.secondary)))
            or not event.primary.provenance.element_epoch or not event.secondary.provenance.element_epoch):
        raise HTTPException(status_code=422, detail={"reason_code": "MANDATORY_STATE_OR_EPOCH_MISSING", "message": "Both finite TEME position/velocity states in km and km/s, matching TCA epochs, and each object's TLE element epoch are required."})
    _require_usable_physical_event(event)
    job_id = f"user-upload-{uuid.uuid4().hex}"
    event.screening_job_id = job_id
    job = {"status": "complete", "result": {"data": [event.model_dump(mode="json")]}, "user_supplied": True}
    _screening_jobs[job_id] = job
    maneuver_result = optimize_maneuver(event, lead_seconds=lead_seconds, burn_magnitudes_m_s=(burn_magnitude_m_s,), initial_mass_kg=initial_mass_kg, specific_impulse_s=specific_impulse_s, rtn_direction=rtn_direction)
    if maneuver_result.get("event_id") != event.id:
        _screening_jobs.pop(job_id, None)
        raise HTTPException(status_code=409, detail={"reason_code": "MANEUVER_RESULT_IDENTITY_MISMATCH", "message": "The calculated maneuver result does not match the uploaded event."})
    maneuver_result.update({"screening_job_id": job_id, "screening_job_status": "complete", "user_supplied_input": True})
    job.setdefault("maneuver_results", {})[event.id] = maneuver_result
    return ManeuverAssessmentResponse(success=True, timestamp=datetime.now(timezone.utc).isoformat(), screening_job_id=job_id, data=maneuver_result, message="Research maneuver assessment calculated from the validated user-supplied state event.")


@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/assessment.pdf")
async def selected_event_assessment_pdf(job_id: str, event_id: str) -> StreamingResponse:
    job, event = _stored_physical_event_for_report(job_id, event_id)
    event_payload = event.model_dump(mode="json")
    maneuver_result = _maneuver_result_for_report(job, job_id, event_id)
    screening_summary = {
        **(job["result"].get("screening") or {}), "screening_job_id": job_id,
        "screening_job_status": job.get("status"), "screening_job_archived": bool(job.get("restored_from_archive")),
    }
    pdf = event_report_pdf(event_payload, maneuver_result, screening_summary)
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{event_id}-maneuver-assessment.pdf"'},
    )


@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/report.json")
@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/assessment.json")
async def selected_event_report_json(job_id: str, event_id: str) -> JSONResponse:
    job, event = _stored_physical_event_for_report(job_id, event_id)
    maneuver_result = _maneuver_result_for_report(job, job_id, event_id)
    payload = event_report_payload(event.model_dump(mode="json"), maneuver_result, screening_job_id=job_id)
    return JSONResponse(content=payload, headers={"Content-Disposition": f'attachment; filename="{event_id}-orion-report.json"', "X-Screening-Job-Id": job_id})


@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/report.csv")
@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/assessment.csv")
async def selected_event_report_csv(job_id: str, event_id: str) -> Response:
    job, event = _stored_physical_event_for_report(job_id, event_id)
    maneuver_result = _maneuver_result_for_report(job, job_id, event_id)
    payload = event_report_payload(event.model_dump(mode="json"), maneuver_result, screening_job_id=job_id)
    return Response(content=event_report_csv(payload), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{event_id}-orion-report.csv"', "X-Screening-Job-Id": job_id})


@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/report.pdf")
@app.get("/api/conjunction-jobs/{job_id}/events/{event_id}/maneuver-report.pdf")
async def selected_event_report_pdf(job_id: str, event_id: str) -> StreamingResponse:
    job, event = _stored_physical_event_for_report(job_id, event_id)
    result = job["result"]
    event_payload = event.model_dump(mode="json")
    maneuver_result = _maneuver_result_for_report(job, job_id, event_id)
    screening_summary = {
        **(result.get("screening") or {}), "screening_job_id": job_id,
        "screening_job_status": job.get("status"), "screening_job_archived": bool(job.get("restored_from_archive")),
    }
    pdf = event_report_pdf(event_payload, maneuver_result, screening_summary)
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{event_id}-trajectory-assessment-report.pdf"'},
    )


@app.get("/api/smart-filter")
async def smart_filter() -> dict:
    snapshot, events = await build_event_context(limit=900, forecast_hours=24)
    payload = build_smart_filter(events, snapshot.stats.tracked_objects)
    payload["ml_model_status"] = model_status()
    payload["ml_scope"] = "independent estimates are attached only to physics-assessed events from /api/conjunctions; screening proxies remain heuristic-only"
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
        "message": "Heuristic screening proxies and model availability are reported separately; physical-event ML estimates are returned by /api/conjunctions.",
    }


@app.get("/api/heatmap")
async def heatmap(mode: str = "risk", forecast_hours: int = Query(24, ge=0, le=336)) -> dict:
    snapshot = await build_snapshot(limit=900, forecast_hours=forecast_hours)
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "mode": mode,
            "cells": [cell.model_dump(mode="json") for cell in snapshot.risk_cells],
            "legend": ["deep blue", "green", "yellow", "orange", "red"],
            "forecast_hours": forecast_hours,
            "source_summary": snapshot.source_summary.model_dump(),
            "result_kind": "heuristic_risk_visualization",
        },
        "message": "Heuristic score heatmap generated; values are not collision probabilities or physical density.",
    }


@app.get("/api/reports/mission.pdf")
async def mission_pdf() -> StreamingResponse:
    snapshot, events = await build_event_context(limit=900, forecast_hours=24)
    analytics_payload = (await analytics(limit=900))["data"]
    smart = build_smart_filter(events, snapshot.stats.tracked_objects)
    screening_snapshot, trajectory_run = await build_trajectory_context(limit=900)
    pdf = mission_report_pdf(
        {"source": screening_snapshot.source, "source_summary": screening_snapshot.source_summary.model_dump(), "briefing": smart["briefing"], "ml_status": model_status().get("status", "unavailable")},
        event_dicts(events),
        analytics_payload,
        physics_events=event_dicts(trajectory_run.events),
        screening_summary=trajectory_run.summary,
    )
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="orbital-mission-report.pdf"'},
    )


@app.get("/api/reports/conjunctions.csv")
async def conjunction_csv() -> Response:
    snapshot, run = await build_trajectory_context(limit=900)
    summary = run.summary
    if summary.get("completion_status") == "complete" and summary.get("status") == "valid":
        result_status = "valid_non_empty" if run.events else "valid_empty"
    elif summary.get("completion_status") == "partial":
        result_status = "partial"
    elif summary.get("completion_status") == "failed":
        result_status = "failed"
    else:
        result_status = "unavailable"
    return Response(
        content=conjunctions_csv(
            event_dicts(run.events),
            export_metadata={
                "screening_status": summary.get("status", "unavailable"),
                "screening_completion_status": summary.get("completion_status", "unavailable"),
                "screening_result_status": result_status,
                "catalog_source": snapshot.source,
                "catalog_object_count": snapshot.source_summary.object_count,
                "candidate_pair_count": summary.get("candidate_pair_count"),
                "candidate_minimum_count": summary.get("candidate_local_minimum_count"),
                "refinement_count": summary.get("refinement_count"),
                "close_approach_count": summary.get("close_approach_count"),
                "screening_horizon_start_utc": summary.get("screening_horizon_start"),
                "screening_horizon_end_utc": summary.get("screening_horizon_end"),
                "screening_threshold_km": summary.get("screening_threshold_km"),
            },
        ),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="trajectory-assessments.csv"'},
    )


def _screening_job_archive_copy(job: dict) -> dict:
    """Copy persisted job data without carrying process-local lifecycle state."""
    runtime_fields = {"task", "created_monotonic"}
    return copy.deepcopy({key: value for key, value in job.items() if key not in runtime_fields})


def _screening_job_for_export(job_id: str) -> dict | None:
    if not re.fullmatch(r"[A-Fa-f0-9]{32}", job_id):
        return None
    with _screening_registry_lock:
        live_job = _screening_jobs.get(job_id)
        archived_copy = _screening_job_archive_copy(live_job) if live_job is not None else None
    archive_path = SCREENING_EXPORT_ARCHIVE_DIR / f"screening-job-{job_id}.json"
    if archived_copy is not None:
        if archived_copy.get("status") in {"complete", "partial"} and not archived_copy.get("restored_from_archive"):
            SCREENING_EXPORT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            temporary_path = archive_path.with_suffix(".json.tmp")
            temporary_path.write_text(json.dumps(archived_copy, separators=(",", ":")), encoding="utf-8")
            temporary_path.replace(archive_path)
        return archived_copy
    try:
        archived = _load_archived_screening_job(job_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    if archived.get("job_id") != job_id:
        return None
    archived["restored_from_archive"] = True
    archived["archived"] = True
    return archived


@app.get("/api/conjunction-jobs/{job_id}/reports/conjunctions.csv")
async def completed_job_conjunction_csv(job_id: str) -> Response:
    job = _screening_job_for_export(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="The requested screening job is not available in memory or the export archive.")
    if job.get("status") not in {"complete", "partial"}:
        raise HTTPException(status_code=409, detail=f"The requested screening job is not exportable (status: {job.get('status', 'unknown')}).")
    result = job.get("result") or {}
    events = result.get("data")
    if not isinstance(events, list):
        raise HTTPException(status_code=409, detail="The requested screening job has no assessment records to export.")
    summary = result.get("screening") or {}
    source_summary = result.get("source_summary") or {}
    source_status = source_summary.get("status")
    source_label = source_summary.get("source") or {
        "all_live": "Live CelesTrak TLE records",
        "mixed_live_fallback": "Mixed live and bundled fallback TLE records",
        "mixed_live_synthetic": "Mixed live and synthetic records",
        "fallback": "Bundled fallback TLE sample",
        "synthetic_demo": "Synthetic demo data",
        "unavailable": "Source unavailable",
    }.get(source_status, source_status or "Source unavailable")
    invalid_count = sum(
        event.get("physics_result", {}).get("status") == "invalid"
        for event in events
        if isinstance(event, dict)
    )
    csv_content = conjunctions_csv(events, export_metadata={
        "export_scope": "stored_completed_screening_job",
        "screening_job_id": job_id,
        "screening_status": result.get("physics_assessment_status", summary.get("status", "unavailable")),
        "screening_completion_status": job.get("status"),
        "screening_result_status": result.get("result_status", job.get("status")),
        "catalog_source": source_label,
        "catalog_object_count": source_summary.get("object_count"),
        "candidate_pair_count": summary.get("candidate_pair_count"),
        "candidate_minimum_count": summary.get("candidate_local_minimum_count"),
        "refinement_count": summary.get("refinement_count"),
        "close_approach_count": summary.get("close_approach_count", len(events)),
        "screening_horizon_start_utc": summary.get("screening_horizon_start"),
        "screening_horizon_end_utc": summary.get("screening_horizon_end"),
        "screening_threshold_km": summary.get("screening_threshold_km"),
        "event_record_count": len(events),
        "invalid_assessment_count": invalid_count,
    })
    if job.get("restored_from_archive"):
        archived_csv_path = SCREENING_EXPORT_ARCHIVE_DIR / f"trajectory-assessments-{job_id}.csv"
        try:
            csv_content = archived_csv_path.read_bytes()
        except OSError:
            # The original archive remains the source of the result. Regenerate only
            # the response body if an older job archive has no paired CSV file.
            pass
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="trajectory-assessments-{job_id}.csv"',
            "X-Screening-Job-Id": job_id,
        },
    )


@app.get("/api/reports/screening-proxies.csv")
async def screening_proxies_csv() -> Response:
    _, events = await build_event_context(limit=900, forecast_hours=24)
    return Response(
        content=conjunctions_csv(event_dicts(events)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="screening-proxies.csv"'},
    )


@app.get("/api/reports/mission.json")
async def mission_json() -> Response:
    snapshot, events = await build_event_context(limit=900, forecast_hours=24)
    smart = build_smart_filter(events, snapshot.stats.tracked_objects)
    screening_snapshot, trajectory_run = await build_trajectory_context(limit=900)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
        "smart_filter": smart,
        "screening_proxy_pairs": event_dicts(events),
        "trajectory_assessments": event_dicts(trajectory_run.events),
        "trajectory_screening": trajectory_run.summary,
        "trajectory_screening_scope": "Fresh Stage 2A run generated for this report; not a previously completed Collision Analysis job.",
        "trajectory_screening_catalog": {
            "source": screening_snapshot.source,
            "source_summary": screening_snapshot.source_summary.model_dump(mode="json"),
        },
        "physics_assessment_status": trajectory_run.summary["status"],
        "ml_status": model_status().get("status", "unavailable"),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="orbital-mission-report.json"'},
    )


@app.get("/api/reports/{event_id}.pdf")
async def event_pdf(event_id: str) -> StreamingResponse:
    if not event_id.startswith("SP-"):
        raise _identity_http_error(409, "SCREENING_JOB_REQUIRED", "Physical event reports must use the selected event and screening job route.")
    _, events = await build_event_context(limit=900, forecast_hours=24)
    event = next((item for item in events if item.id == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found in the current screening run.")
    result_kind = getattr(event, "result_kind", None) or "screening_proxy"
    if result_kind != "screening_proxy":
        raise _identity_http_error(422, "DEMO_OR_PROXY_EVENT", "The generic event report route accepts screening proxies only.")
    event_payload = event.model_dump(mode="json")
    pdf = event_report_pdf(event_payload)
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{event_id}-screening-proxy-report.pdf"'},
    )
