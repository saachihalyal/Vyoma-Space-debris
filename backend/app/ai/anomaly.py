"""Separate unsupervised unusualness signal for validated Stage 2A events."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.ai import FEATURE_SCHEMA_VERSION
from app.ai.features import FEATURE_NAMES, FEATURE_UNITS, extract_live_features
from app.models import OrbitalAnomalyResult, PhysicsResult


MODEL_NAME = "ORION orbital feature Isolation Forest"
MODEL_VERSION = "1.0.0"
DATASET_NAME = "ESA Collision Avoidance Challenge training dataset"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "orbital_anomaly_iforest.joblib"
METADATA_PATH = ARTIFACT_DIR / "orbital_anomaly_iforest.metadata.json"


def predict_orbital_anomaly(
    physics: PhysicsResult,
    *,
    artifact_path: Path = ARTIFACT_PATH,
    metadata_path: Path = METADATA_PATH,
) -> OrbitalAnomalyResult:
    feature_build = extract_live_features(physics)
    if feature_build.values is None:
        return OrbitalAnomalyResult(
            status="unavailable", reason_code=feature_build.reason_code or "PHYSICS_FEATURES_UNAVAILABLE",
            provenance={"source_physics_event_id": physics.event_id},
        )
    bundle, metadata, failure = _load_artifact(str(artifact_path), str(metadata_path))
    if failure:
        return OrbitalAnomalyResult(
            status="unavailable", reason_code=failure,
            provenance={"source_physics_event_id": physics.event_id},
        )
    import numpy as np

    row = np.asarray([[feature_build.values[name] for name in FEATURE_NAMES]], dtype=np.float64)
    try:
        decision = float(bundle["model"].decision_function(row)[0])
        predicted = int(bundle["model"].predict(row)[0])
        reference = np.asarray(bundle["training_decision_scores"], dtype=np.float64)
    except Exception:
        return OrbitalAnomalyResult(
            status="error", reason_code="ANOMALY_INFERENCE_FAILED",
            provenance={"source_physics_event_id": physics.event_id},
        )
    if not math.isfinite(decision) or reference.ndim != 1 or not reference.size or not np.isfinite(reference).all():
        return OrbitalAnomalyResult(
            status="error", reason_code="ANOMALY_MODEL_OUTPUT_INVALID",
            provenance={"source_physics_event_id": physics.event_id},
        )
    # Lower decision scores are more unusual. This is an empirical tail-rank
    # within the training reference set, not a probability or risk estimate.
    score = 1.0 - float(np.searchsorted(np.sort(reference), decision, side="right") / reference.size)
    return OrbitalAnomalyResult(
        status="available",
        model_name=metadata["model_name"],
        model_version=metadata["model_version"],
        training_dataset=metadata["dataset_name"],
        classification="unusual" if predicted == -1 else "not_flagged",
        decision_score=decision,
        anomaly_score=min(1.0, max(0.0, score)),
        input_features=feature_build.values,
        feature_units=dict(FEATURE_UNITS),
        feature_frame=feature_build.frame,
        training_reference_event_count=metadata["training_reference_event_count"],
        reason_code="ANOMALY_ASSESSED",
        provenance={
            "source_physics_event_id": physics.event_id,
            "source_physics_method": physics.provenance.method,
            "source_physics_frame": physics.state_information.get("source_frame") if physics.state_information else None,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "training_dataset_sha256": metadata["dataset_sha256"],
            "artifact_sha256": metadata["artifact_sha256"],
            "training_event_split": "ESA risk model's event-level training split only; risk targets excluded from anomaly estimator",
            "is_synthetic": physics.provenance.is_synthetic,
            "is_fallback": physics.provenance.is_fallback,
        },
    )


def model_status() -> dict[str, Any]:
    _, metadata, failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
    if failure:
        return {"status": "unavailable", "reason_code": failure, "model_name": MODEL_NAME}
    return {
        "status": "available", "reason_code": None, "model_name": metadata["model_name"],
        "model_version": metadata["model_version"], "training_dataset": metadata["dataset_name"],
        "training_reference_event_count": metadata["training_reference_event_count"],
        "artifact_sha256": metadata["artifact_sha256"],
    }


@lru_cache(maxsize=4)
def _load_artifact(artifact_path: str, metadata_path: str):
    artifact, metadata_file = Path(artifact_path), Path(metadata_path)
    if not artifact.is_file() or not metadata_file.is_file():
        return None, None, "ANOMALY_ARTIFACT_UNAVAILABLE"
    try:
        import joblib
        import sklearn
        import numpy as np
        from sklearn.ensemble import IsolationForest

        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if _sha256_file(artifact) != metadata.get("artifact_sha256"):
            return None, None, "ANOMALY_ARTIFACT_HASH_MISMATCH"
        if metadata.get("package_versions", {}).get("scikit_learn") != sklearn.__version__:
            return None, None, "ANOMALY_RUNTIME_VERSION_MISMATCH"
        bundle = joblib.load(artifact)
        if (
            bundle.get("feature_names") != list(FEATURE_NAMES)
            or bundle.get("feature_units") != FEATURE_UNITS
            or bundle.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
            or metadata.get("feature_names") != list(FEATURE_NAMES)
            or metadata.get("feature_units") != FEATURE_UNITS
            or metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
        ):
            return None, None, "ANOMALY_FEATURE_SCHEMA_MISMATCH"
        reference = np.asarray(bundle.get("training_decision_scores"), dtype=np.float64)
        if reference.ndim != 1 or len(reference) != metadata.get("training_reference_event_count") or len(reference) < metadata.get("minimum_training_events", 100) or not np.isfinite(reference).all():
            return None, None, "ANOMALY_REFERENCE_DISTRIBUTION_INVALID"
        if (
            not isinstance(bundle.get("model"), IsolationForest)
            or not hasattr(bundle.get("model"), "decision_function")
            or not hasattr(bundle.get("model"), "predict")
        ):
            return None, None, "ANOMALY_ESTIMATOR_INVALID"
        return bundle, metadata, None
    except ImportError:
        return None, None, "ANOMALY_RUNTIME_UNAVAILABLE"
    except Exception:
        return None, None, "ANOMALY_ARTIFACT_INVALID"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
