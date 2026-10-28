"""Validated offline-trained research-Pc inference for physical conjunctions."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.ai.collision_features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, build_collision_features
from app.models import (
    CollisionAiAssessment,
    CollisionPcSurrogateResult,
    CollisionRiskClassifierResult,
    ConjunctionAssessmentEvent,
)


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
PC_ARTIFACT = ARTIFACT_DIR / "orion_research_pc_surrogate.joblib"
PC_METADATA = ARTIFACT_DIR / "orion_research_pc_surrogate.metadata.json"
RISK_ARTIFACT = ARTIFACT_DIR / "orion_physics_risk_classifier.joblib"
RISK_METADATA = ARTIFACT_DIR / "orion_physics_risk_classifier.metadata.json"
PC_TARGET_MIN_LOG10 = -30.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=8)
def _load_validated_artifact(artifact_path: str, metadata_path: str, modified_ns: int, size: int):
    del modified_ns, size  # Cache key invalidates the loaded estimator after replacement.
    artifact = Path(artifact_path)
    metadata_file = Path(metadata_path)
    meta = _metadata(metadata_file)
    if not artifact.is_file() or not meta:
        raise ValueError("MODEL_ARTIFACT_OR_METADATA_MISSING")
    if meta.get("usable_for_inference") is not True:
        raise ValueError("MODEL_DID_NOT_BEAT_HELD_OUT_BASELINE")
    if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("MODEL_FEATURE_SCHEMA_VERSION_MISMATCH")
    if meta.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("MODEL_FEATURE_SCHEMA_MISMATCH")
    expected_hash = meta.get("artifact_sha256")
    if not isinstance(expected_hash, str) or _sha256(artifact) != expected_hash:
        raise ValueError("MODEL_ARTIFACT_HASH_MISMATCH")
    from joblib import load
    bundle = load(artifact)
    if (not isinstance(bundle, dict)
            or tuple(bundle.get("feature_names", ())) != FEATURE_NAMES
            or bundle.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
            or bundle.get("estimator") is None):
        raise ValueError("MODEL_ARTIFACT_SCHEMA_MISMATCH")
    return bundle["estimator"], meta


def _load_model(artifact: Path, metadata: Path):
    stat = artifact.stat()
    return _load_validated_artifact(str(artifact), str(metadata), stat.st_mtime_ns, stat.st_size)


def _model_status(artifact: Path, metadata_path: Path) -> dict[str, Any]:
    metadata = _metadata(metadata_path)
    try:
        _estimator, validated = _load_model(artifact, metadata_path)
    except FileNotFoundError:
        reason = "MODEL_ARTIFACT_OR_METADATA_MISSING"
        return {"status": "unavailable", "reason_code": reason, "model_name": metadata.get("model_name") if metadata else None,
                "version": metadata.get("model_version") if metadata else None, "metrics": None}
    except Exception as exc:
        reason = str(exc) if str(exc).startswith("MODEL_") else "MODEL_ARTIFACT_INVALID"
        return {"status": "unavailable", "reason_code": reason, "model_name": metadata.get("model_name") if metadata else None,
                "version": metadata.get("model_version") if metadata else None, "metrics": None}
    return {"status": "available", "reason_code": None, "model_name": validated.get("model_name"),
            "version": validated.get("model_version"), "metrics": validated.get("metrics"),
            "feature_schema_version": validated.get("feature_schema_version"),
            "target_definition": validated.get("target_definition"),
            "training_data_provenance": validated.get("dataset_provenance"),
            "limitations": validated.get("limitations", [])}


def collision_model_status() -> dict[str, Any]:
    """Return only persisted metrics whose corresponding artifacts validate."""
    pc = _model_status(PC_ARTIFACT, PC_METADATA)
    risk = _model_status(RISK_ARTIFACT, RISK_METADATA)
    return {
        "service": "ORION physics-supervised collision models",
        "training_mode": "offline_only",
        "inference_mode": "saved artifacts only; no training in API requests",
        "pc_surrogate": pc,
        "risk_classifier": risk,
    }


def _reference_log10(event: ConjunctionAssessmentEvent) -> float | None:
    research = event.automatic_research_pc_assessment
    if research is None or research.status != "prior_based_research_estimate":
        return None
    value = research.estimated_pc_scientific
    if not isinstance(value, str):
        return None
    try:
        mantissa, exponent = value.lower().split("e", 1)
        log_value = math.log10(float(mantissa)) + int(exponent)
        return log_value if math.isfinite(log_value) and log_value <= 0 else None
    except (ValueError, OverflowError):
        return None


def _pc_fallback(event: ConjunctionAssessmentEvent, reason: str) -> CollisionPcSurrogateResult:
    return CollisionPcSurrogateResult(
        status="fallback" if _reference_log10(event) is not None else "unavailable",
        deterministic_reference_log10_pc=_reference_log10(event),
        fallback_method="physics_research_pc_reference" if _reference_log10(event) is not None else None,
        reason_code=reason,
    )


def _risk_fallback(event: ConjunctionAssessmentEvent, reason: str) -> CollisionRiskClassifierResult:
    risk = event.automatic_research_pc_assessment.risk_assessment if event.automatic_research_pc_assessment else None
    class_value = risk.physics_risk_class if risk and risk.status == "classified" else None
    return CollisionRiskClassifierResult(
        status="fallback" if class_value else "unavailable",
        deterministic_reference_risk_class=class_value,
        fallback_method="physics_research_pc_classification" if class_value else None,
        reason_code=reason,
    )


def assess_collision_ai(event: ConjunctionAssessmentEvent) -> CollisionAiAssessment:
    """Infer separate surrogate outputs without changing any physics fields."""
    features = build_collision_features(event)
    feature_error = "LIVE_FEATURES_UNAVAILABLE" if features is None else None
    try:
        pc_estimator, pc_meta = _load_model(PC_ARTIFACT, PC_METADATA)
        if feature_error:
            pc_result = _pc_fallback(event, feature_error)
        else:
            value = float(pc_estimator.predict([[features[name] for name in FEATURE_NAMES]])[0])
            if not math.isfinite(value) or value > 0:
                pc_result = _pc_fallback(event, "MODEL_PREDICTION_INVALID")
            elif value < PC_TARGET_MIN_LOG10:
                # Training labels are floored at -30. More negative inference is
                # extrapolation beyond the target domain, not a valid Pc estimate.
                pc_result = CollisionPcSurrogateResult(
                    status="unavailable", reason_code="MODEL_PREDICTION_OUTSIDE_TRAINING_TARGET_RANGE",
                    target_definition=pc_meta.get("target_definition", "log10(research_pc)"),
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    artifact_sha256=pc_meta.get("artifact_sha256"),
                )
            else:
                pc_result = CollisionPcSurrogateResult(
                    status="available", model_name=pc_meta.get("model_name"),
                    model_version=pc_meta.get("model_version"), ai_predicted_log10_pc=value,
                    target_definition=pc_meta.get("target_definition", "log10(research_pc)"),
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    artifact_sha256=pc_meta.get("artifact_sha256"),
                )
    except Exception as exc:
        reason = str(exc) if str(exc).startswith("MODEL_") else "MODEL_INFERENCE_FAILED"
        pc_result = _pc_fallback(event, reason)

    try:
        risk_estimator, risk_meta = _load_model(RISK_ARTIFACT, RISK_METADATA)
        if feature_error:
            risk_result = _risk_fallback(event, feature_error)
        else:
            values = [[features[name] for name in FEATURE_NAMES]]
            label = str(risk_estimator.predict(values)[0])
            if label not in {"Low", "Medium", "High"}:
                risk_result = _risk_fallback(event, "MODEL_PREDICTION_INVALID")
            else:
                probabilities = None
                if hasattr(risk_estimator, "predict_proba"):
                    raw = risk_estimator.predict_proba(values)[0]
                    probabilities = {str(name): float(score) for name, score in zip(risk_estimator.classes_, raw)}
                risk_result = CollisionRiskClassifierResult(
                    status="available", model_name=risk_meta.get("model_name"),
                    model_version=risk_meta.get("model_version"), ai_risk_class=label,
                    class_probabilities=probabilities,
                    target_definition=risk_meta.get("target_definition", "Physics-derived risk class"),
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    artifact_sha256=risk_meta.get("artifact_sha256"),
                )
    except Exception as exc:
        reason = str(exc) if str(exc).startswith("MODEL_") else "MODEL_INFERENCE_FAILED"
        risk_result = _risk_fallback(event, reason)

    states = (pc_result.status, risk_result.status)
    overall = "available" if states == ("available", "available") else "partial" if "available" in states else "fallback" if "fallback" in states else "unavailable"
    return CollisionAiAssessment(
        status=overall,
        inference_provenance={
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "source_event_id": event.id,
            "source_research_pc_method": event.automatic_research_pc_assessment.method_name if event.automatic_research_pc_assessment else None,
            "physics_research_pc_remains_authoritative": True,
            "training_runs_during_request": False,
            "limitations": ["Surrogates learn ORION physics-generated labels and are not validated against observed collisions."],
        },
        pc_surrogate=pc_result,
        risk_classifier=risk_result,
    )
