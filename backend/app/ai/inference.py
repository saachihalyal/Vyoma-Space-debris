"""Physics-feature adapter to an independently trained ESA risk estimator."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.ai import DATASET_NAME, FEATURE_SCHEMA_VERSION, HIGH_RISK_THRESHOLD_LOG10, MODEL_NAME, MODEL_VERSION
from app.ai.eligibility import live_time_to_tca_ineligibility_reason
from app.ai.features import FEATURE_NAMES, FEATURE_UNITS, extract_live_features
from app.models import MLResult, MLRiskPrediction, PhysicsResult


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "esa_event_log10_risk.joblib"
METADATA_PATH = ARTIFACT_DIR / "esa_event_log10_risk.metadata.json"
LIVE_FEATURE_COMPATIBILITY_REASON = "ESA_LIVE_FEATURE_SEMANTICS_UNVERIFIED"
# Matching names, order, units, and an adapter are not evidence that the
# historical ESA CDM feature conventions match live TLE-derived features.
LIVE_FEATURE_SEMANTICS_VERIFIED = False


def predict_from_physics(
    physics: PhysicsResult,
    *,
    artifact_path: Path = ARTIFACT_PATH,
    metadata_path: Path = METADATA_PATH,
) -> MLResult:
    model, metadata, failure = _load_artifact(str(artifact_path), str(metadata_path))
    if failure:
        return MLResult(
            status="unavailable",
            model_name=MODEL_NAME,
            model_version=None,
            training_dataset=DATASET_NAME,
            feature_schema=_feature_schema(),
            feature_availability={name: False for name in FEATURE_NAMES},
            features_imputed=False,
            provenance={"source_physics_event_id": physics.event_id, "reason_code": failure},
            reason_code=failure,
        )

    feature_build = extract_live_features(physics)
    if feature_build.values is None:
        return MLResult(
            status="unavailable",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=_inference_provenance(physics, metadata, feature_build.frame),
            reason_code=feature_build.reason_code or "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE",
        )

    eligibility_reason = live_time_to_tca_ineligibility_reason(
        feature_build.values.get("time_to_tca_days")
    )
    if eligibility_reason:
        return MLResult(
            status="unavailable",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=_inference_provenance(physics, metadata, feature_build.frame),
            reason_code=eligibility_reason,
        )

    if not LIVE_FEATURE_SEMANTICS_VERIFIED:
        provenance = _inference_provenance(physics, metadata, feature_build.frame)
        provenance["live_feature_semantics_compatibility"] = "unverified"
        return MLResult(
            status="unavailable",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=provenance,
            reason_code=LIVE_FEATURE_COMPATIBILITY_REASON,
        )

    import numpy as np

    row = np.asarray([[feature_build.values[name] for name in FEATURE_NAMES]], dtype=np.float64)
    try:
        log_risk = float(model["primary_model"].predict(row)[0])
    except Exception:
        return MLResult(
            status="error",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=_inference_provenance(physics, metadata, feature_build.frame),
            reason_code="MODEL_INFERENCE_FAILED",
        )
    if not math.isfinite(log_risk) or log_risk > 0.0:
        return MLResult(
            status="error",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=_inference_provenance(physics, metadata, feature_build.frame),
            reason_code="MODEL_OUTPUT_OUT_OF_RISK_RANGE",
        )
    try:
        risk_probability = 10.0 ** log_risk
    except OverflowError:
        risk_probability = float("inf")
    if not math.isfinite(risk_probability) or not 0.0 < risk_probability <= 1.0:
        return MLResult(
            status="error",
            model_name=metadata["model_name"],
            model_version=metadata["model_version"],
            training_dataset=metadata["dataset_name"],
            feature_schema=_feature_schema(),
            feature_availability=feature_build.availability,
            features_imputed=False,
            provenance=_inference_provenance(physics, metadata, feature_build.frame),
            reason_code="MODEL_OUTPUT_OUT_OF_RISK_RANGE",
        )
    return MLResult(
        status="available",
        model_name=metadata["model_name"],
        model_version=metadata["model_version"],
        training_dataset=metadata["dataset_name"],
        feature_schema=_feature_schema(),
        input_features=feature_build.values,
        feature_units=dict(FEATURE_UNITS),
        feature_frame=feature_build.frame,
        prediction=MLRiskPrediction(
            predicted_log_risk=log_risk,
            predicted_risk_estimate=risk_probability,
            predicted_risk_probability=risk_probability,
            threshold_flag_at_minus_6=log_risk >= HIGH_RISK_THRESHOLD_LOG10,
            high_risk=log_risk >= HIGH_RISK_THRESHOLD_LOG10,
            high_risk_threshold_log10=HIGH_RISK_THRESHOLD_LOG10,
        ),
        feature_availability=feature_build.availability,
        features_imputed=False,
        provenance=_inference_provenance(physics, metadata, feature_build.frame),
        reason_code="prediction_available",
    )


def model_status() -> dict[str, Any]:
    _, metadata, failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
    if failure:
        return {"status": "unavailable", "artifact_status": "unavailable", "reason_code": failure, "model_name": MODEL_NAME}
    return {
        "status": "unavailable",
        "artifact_status": "available",
        "reason_code": LIVE_FEATURE_COMPATIBILITY_REASON,
        "model_name": metadata["model_name"],
        "model_version": metadata["model_version"],
        "training_dataset": metadata["dataset_name"],
        "artifact_sha256": metadata["artifact_sha256"],
        "feature_compatibility_status": "unverified",
    }


@lru_cache(maxsize=4)
def _load_artifact(artifact_path: str, metadata_path: str):
    artifact = Path(artifact_path)
    metadata_file = Path(metadata_path)
    if not artifact.is_file() or not metadata_file.is_file():
        return None, None, "MODEL_ARTIFACT_UNAVAILABLE"
    try:
        import joblib
        import sklearn
    except ImportError:
        return None, None, "MODEL_RUNTIME_UNAVAILABLE"
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if _sha256_file(artifact) != metadata.get("artifact_sha256"):
            return None, None, "MODEL_ARTIFACT_HASH_MISMATCH"
        if metadata.get("model_name") != MODEL_NAME or metadata.get("model_version") != MODEL_VERSION:
            return None, None, "MODEL_METADATA_IDENTITY_MISMATCH"
        if (
            metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
            or metadata.get("feature_names") != list(FEATURE_NAMES)
            or metadata.get("feature_units") != FEATURE_UNITS
        ):
            return None, None, "MODEL_METADATA_FEATURE_SCHEMA_MISMATCH"
        if metadata.get("target_column") != "risk" or metadata.get("target_units") != "log10 risk":
            return None, None, "MODEL_METADATA_TARGET_SEMANTICS_MISMATCH"
        expected_version = metadata.get("package_versions", {}).get("scikit_learn")
        if not expected_version or expected_version != sklearn.__version__:
            return None, None, "MODEL_RUNTIME_VERSION_MISMATCH"
        bundle = joblib.load(artifact)
        if bundle.get("feature_names") != list(FEATURE_NAMES):
            return None, None, "MODEL_FEATURE_SCHEMA_MISMATCH"
        if bundle.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            return None, None, "MODEL_FEATURE_SCHEMA_MISMATCH"
        if bundle.get("target_definition") != metadata.get("target_definition"):
            return None, None, "MODEL_METADATA_TARGET_SEMANTICS_MISMATCH"
        return bundle, metadata, None
    except Exception:
        return None, None, "MODEL_ARTIFACT_INVALID"


def _feature_schema() -> dict[str, Any]:
    return {
        "version": FEATURE_SCHEMA_VERSION,
        "features": [{"name": name, "units": FEATURE_UNITS[name]} for name in FEATURE_NAMES],
        "source_frame": "Stage 2A TEME, projected to instantaneous primary-object RTN at TCA",
        "target": "final event risk in log10 space",
        "target_units": "log10 risk",
        "live_feature_semantics_compatibility": "unverified; model inference is withheld until historical ESA CDM and live TLE feature conventions are confirmed equivalent",
        "exponentiated_event_risk_display": "10 ** predicted_log_risk on the ESA event-risk scale; not a calibrated probability or Foster Pc",
        "probability_display": "Deprecated compatibility alias for exponentiated_event_risk_display; not a calibrated probability or Foster Pc",
    }


def _inference_provenance(physics: PhysicsResult, metadata: dict[str, Any], feature_frame: str | None) -> dict[str, Any]:
    return {
        "inference_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_physics_event_id": physics.event_id,
        "source_physics_method": physics.provenance.method,
        "source_physics_method_version": physics.provenance.method_version,
        "source_physics_frame": physics.state_information.get("source_frame") if physics.state_information else None,
        "feature_frame": feature_frame,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_dataset": metadata["dataset_name"],
        "training_dataset_sha256": metadata["dataset_sha256"],
        "artifact_sha256": metadata["artifact_sha256"],
        "is_synthetic": physics.provenance.is_synthetic,
        "is_fallback": physics.provenance.is_fallback,
        "input_features_imputed": False,
        "live_feature_semantics_compatibility": "verified" if LIVE_FEATURE_SEMANTICS_VERIFIED else "unverified",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
