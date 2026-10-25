"""Physics-supervised Smart Filter and an independent safety guard."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
from collections import Counter
from typing import Any

from app.ai.collision_features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, build_collision_features
from app.ai.collision_training import COVARIANCE_SCALES, HBR_SCALES
from app.ai.smart_filter_training import SIGNIFICANT_PC_THRESHOLD
from app.models import ConjunctionAssessmentEvent
from app.services.automatic_research_pc import assess_automatic_research_pc


ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "orion_smart_filter_classifier.joblib"
METADATA_PATH = ARTIFACT_PATH.with_suffix(".metadata.json")
MODEL_NAME = "ORION Physics-Supervised Smart Filter Classifier"
MODEL_VERSION = "2.3.0"
SCENARIO_COUNT = len(COVARIANCE_SCALES) * len(HBR_SCALES)


def filter_policy() -> dict[str, Any]:
    try:
        miss_threshold = float(os.getenv("ORION_SMART_FILTER_SAFETY_MISS_KM", "1.0"))
        if not math.isfinite(miss_threshold) or miss_threshold <= 0:
            raise ValueError
    except ValueError:
        miss_threshold = 1.0
    try:
        pc_threshold = float(os.getenv("ORION_SMART_FILTER_SIGNIFICANT_PC", f"{SIGNIFICANT_PC_THRESHOLD:g}"))
        if not math.isfinite(pc_threshold) or not 0 < pc_threshold <= 1:
            raise ValueError
    except ValueError:
        pc_threshold = SIGNIFICANT_PC_THRESHOLD
    return {
        "significant_pc_threshold": pc_threshold,
        "safety_miss_distance_threshold_km": miss_threshold,
        "covariance_scales": list(COVARIANCE_SCALES),
        "hbr_scales": list(HBR_SCALES),
        "scenario_count": SCENARIO_COUNT,
        "classifier_threshold": 0.5,
        "confidence_definition": "maximum random-forest significant-class vote fraction over configured scenarios; not calibrated probability",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_metadata() -> dict[str, Any] | None:
    try:
        value = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=4)
def _load_artifact(modified_ns: int, size: int):
    del modified_ns, size
    metadata = _read_metadata()
    if not ARTIFACT_PATH.is_file() or not metadata:
        raise ValueError("SMART_FILTER_ARTIFACT_MISSING")
    if metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or metadata.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("SMART_FILTER_FEATURE_SCHEMA_MISMATCH")
    if metadata.get("model_version") != MODEL_VERSION or metadata.get("model_name") != MODEL_NAME:
        raise ValueError("SMART_FILTER_MODEL_IDENTITY_MISMATCH")
    if metadata.get("usable_for_inference") is not True:
        raise ValueError("SMART_FILTER_DID_NOT_BEAT_HELD_OUT_BASELINE")
    if metadata.get("artifact_sha256") != _sha256(ARTIFACT_PATH):
        raise ValueError("SMART_FILTER_ARTIFACT_HASH_MISMATCH")
    from joblib import load
    bundle = load(ARTIFACT_PATH)
    if (not isinstance(bundle, dict) or tuple(bundle.get("feature_names", ())) != FEATURE_NAMES
            or bundle.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or bundle.get("estimator") is None):
        raise ValueError("SMART_FILTER_ARTIFACT_SCHEMA_MISMATCH")
    return bundle["estimator"], metadata


def _load():
    stat = ARTIFACT_PATH.stat()
    return _load_artifact(stat.st_mtime_ns, stat.st_size)


def smart_filter_model_status() -> dict[str, Any]:
    metadata = _read_metadata()
    try:
        _estimator, metadata = _load()
    except FileNotFoundError:
        return {"status": "unavailable", "model_name": MODEL_NAME, "model_version": None,
                "reason_code": "SMART_FILTER_ARTIFACT_MISSING", "metrics": None}
    except Exception as exc:
        reason = str(exc) if str(exc).startswith("SMART_FILTER_") else "SMART_FILTER_ARTIFACT_INVALID"
        return {"status": "unavailable", "model_name": (metadata or {}).get("model_name", MODEL_NAME),
                "model_version": (metadata or {}).get("model_version"), "reason_code": reason, "metrics": None}
    return {
        "status": "available", "model_name": metadata["model_name"], "model_version": metadata["model_version"],
        "reason_code": None, "metrics": metadata.get("metrics"), "target_definition": metadata.get("target_definition"),
        "dataset_scenario_count": metadata.get("dataset_scenario_count"),
        "dataset_independent_parent_count": metadata.get("dataset_independent_parent_count"),
        "split_counts": metadata.get("split_counts"), "artifact_sha256": metadata.get("artifact_sha256"),
        "dataset_sha256": metadata.get("dataset_sha256"), "limitations": metadata.get("limitations", []),
    }


def _log10_pc(scientific: str | None) -> float | None:
    if not isinstance(scientific, str):
        return None
    try:
        result = float(Decimal(scientific).log10())
        return result if math.isfinite(result) and result <= 0 else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _scientific_from_log10(value: float) -> str:
    exponent = math.floor(value)
    mantissa = 10 ** (value - exponent)
    return f"{mantissa:.5f}e{exponent:+d}"


def _assess_one(event: ConjunctionAssessmentEvent, model, metadata: dict[str, Any] | None, policy: dict[str, Any]) -> dict[str, Any]:
    physics = event.physics_result
    is_valid = physics.status == "valid" and physics.tca_status == "valid"
    miss = physics.miss_distance.value if physics.miss_distance.status == "available" else None
    guard_reasons: list[str] = []
    if not is_valid:
        guard_reasons.append("SAFETY_GUARD_INVALID_OR_NONINTERIOR_TCA")
    if not isinstance(miss, (int, float)) or isinstance(miss, bool) or not math.isfinite(miss) or miss < 0:
        guard_reasons.append("SAFETY_GUARD_MISS_DISTANCE_UNAVAILABLE")
    elif miss <= policy["safety_miss_distance_threshold_km"]:
        guard_reasons.append("SAFETY_GUARD_MISS_DISTANCE")

    scenario_logs: list[float] = []
    scenario_features: list[dict[str, float]] = []
    scenario_failures: list[str] = []
    if is_valid:
        for covariance_scale in COVARIANCE_SCALES:
            for hbr_scale in HBR_SCALES:
                assessment = assess_automatic_research_pc(
                    physics, None, event.review_priority,
                    primary=event.primary, secondary=event.secondary,
                    covariance_scale=covariance_scale, hbr_scale=hbr_scale,
                )
                log_pc = _log10_pc(assessment.estimated_pc_scientific)
                if assessment.status != "prior_based_research_estimate" or log_pc is None:
                    scenario_failures.append(assessment.reason_codes[0] if assessment.reason_codes else assessment.status)
                    continue
                scenario_logs.append(log_pc)
                if log_pc >= math.log10(policy["significant_pc_threshold"]):
                    guard_reasons.append("SAFETY_GUARD_SCENARIO_PC")
                features = build_collision_features(event, assessment)
                if features is None:
                    scenario_failures.append("SMART_FILTER_FEATURES_UNAVAILABLE")
                    continue
                scenario_features.append(features)

    if len(scenario_logs) != SCENARIO_COUNT or len(scenario_features) != SCENARIO_COUNT:
        guard_reasons.append("SAFETY_GUARD_UNCERTAIN_SCENARIOS")
    if scenario_failures:
        guard_reasons = list(dict.fromkeys(guard_reasons + ["SAFETY_GUARD_UNCERTAIN_SCENARIOS"]))

    confidence = None
    model_prediction = None
    inference_status = "unavailable"
    reason_code = None
    if model is not None and len(scenario_features) == SCENARIO_COUNT:
        try:
            positive_index = list(model.classes_).index("significant")
            probabilities = model.predict_proba([[features[name] for name in FEATURE_NAMES] for features in scenario_features])
            confidence = max(float(row[positive_index]) for row in probabilities)
            model_prediction = "significant" if confidence >= policy["classifier_threshold"] else "insignificant"
            inference_status = "available"
        except Exception:
            reason_code = "SMART_FILTER_INFERENCE_FAILED"
    elif model is None:
        reason_code = "SMART_FILTER_MODEL_UNAVAILABLE"
    else:
        reason_code = "SMART_FILTER_FEATURES_UNAVAILABLE"

    guard_retained = bool(guard_reasons)
    if guard_retained:
        decision = "retain"
        reason = "; ".join(guard_reasons)
        decision_source = "safety_guard"
    elif inference_status == "available" and model_prediction == "significant":
        decision = "retain"
        reason = "MODEL_PREDICTED_SIGNIFICANT"
        decision_source = "trained_model"
    elif inference_status == "available":
        decision = "filter"
        reason = "MODEL_PREDICTED_INSIGNIFICANT; all configured physics scenarios were calculable and below the guard threshold"
        decision_source = "trained_model"
    elif scenario_failures:
        decision = "retain"
        reason = "SAFETY_GUARD_UNCERTAIN_SCENARIOS"
        decision_source = "safety_guard"
    else:
        # Explicit deterministic fallback: physics threshold and miss-distance rule only.
        decision = "filter"
        reason = "DETERMINISTIC_FALLBACK_ALL_SCENARIOS_BELOW_THRESHOLD_AND_MISS_GUARD"
        inference_status = "fallback"
        decision_source = "deterministic_fallback"

    return {
        "event_id": event.id,
        "object_ids": [event.primary.id, event.secondary.id],
        "object_names": [event.primary.name, event.secondary.name],
        "tca_utc": physics.tca.value if physics.tca else None,
        "miss_distance_km": miss,
        "relative_speed_km_s": physics.relative_speed_at_tca.value if physics.relative_speed_at_tca.status == "available" else None,
        "decision": decision,
        "reason": reason,
        "reason_code": reason_code,
        "decision_source": decision_source,
        "model_status": inference_status,
        "model_prediction": model_prediction,
        "confidence": confidence,
        "confidence_definition": policy["confidence_definition"],
        "safety_guard_retained": guard_retained,
        "safety_guard_reasons": list(dict.fromkeys(guard_reasons)),
        "scenario_count_calculated": len(scenario_logs),
        "scenario_count_required": SCENARIO_COUNT,
        "maximum_scenario_log10_pc": max(scenario_logs) if scenario_logs else None,
        "maximum_scenario_pc_scientific": _scientific_from_log10(max(scenario_logs)) if scenario_logs else None,
        "scenario_errors": dict(Counter(scenario_failures)),
        "model_name": metadata.get("model_name") if metadata else None,
        "model_version": metadata.get("model_version") if metadata else None,
    }


def evaluate_physical_smart_filter(events: list[ConjunctionAssessmentEvent]) -> dict[str, Any]:
    policy = filter_policy()
    try:
        model, metadata = _load()
        if not math.isclose(float(metadata.get("significant_pc_threshold", -1)), policy["significant_pc_threshold"], rel_tol=0, abs_tol=0):
            raise ValueError("SMART_FILTER_THRESHOLD_MISMATCH")
        model_status = smart_filter_model_status()
    except Exception as exc:
        model, metadata = None, None
        model_status = smart_filter_model_status()
        reason = str(exc) if str(exc).startswith("SMART_FILTER_") else "SMART_FILTER_ARTIFACT_INVALID"
        model_status = {**model_status, "status": "unavailable", "reason_code": reason, "metrics": None}
    decisions = [_assess_one(event, model, metadata, policy) for event in events]
    retained = [row for row in decisions if row["decision"] == "retain"]
    filtered = [row for row in decisions if row["decision"] == "filter"]
    false_negative_count = None
    if metadata and metadata.get("metrics", {}).get("test"):
        false_negative_count = metadata["metrics"]["test"].get("false_negative_significant_count")
    return {
        "result_type": "physics_smart_filter",
        "status": "available" if model_status["status"] == "available" else "fallback",
        "model": model_status,
        "policy": policy,
        "evaluation": {
            "before_count": len(decisions),
            "kept_count": len(retained),
            "filtered_count": len(filtered),
            "safety_guard_retained_count": sum(row["safety_guard_retained"] for row in decisions),
            "false_negative_significant_count_test": false_negative_count,
            "false_negative_scope": "Held-out training evaluation, not online observed-outcome labels.",
        },
        "decisions": decisions,
    }
