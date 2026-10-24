"""Train the separate orbital anomaly model from ESA training-event features.

Run from ``backend`` with the existing optional ML runtime installed:
``python -m app.ai.anomaly_training``. The model uses one latest pre-final
feature row from each event in the existing event-level training split. ESA
risk targets are not passed to Isolation Forest and no accuracy is claimed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

from app.ai import FEATURE_SCHEMA_VERSION
from app.ai.anomaly import ARTIFACT_DIR, ARTIFACT_PATH, DATASET_NAME, METADATA_PATH, MODEL_NAME, MODEL_VERSION, _sha256_file
from app.ai.features import FEATURE_NAMES, FEATURE_UNITS
from app.ai.training import DATA_PATH, DATASET_SOURCE, SEED, read_esa_training_data, split_event_ids


MIN_TRAINING_EVENTS = 100


def fit_anomaly_model(X: np.ndarray, minimum_events: int = MIN_TRAINING_EVENTS):
    """Fit only complete finite event-level rows; reject undersized samples."""
    matrix = np.asarray(X, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
        raise ValueError("Anomaly training matrix does not match the feature schema")
    if not np.isfinite(matrix).all():
        raise ValueError("Anomaly training features must be finite; no imputation is performed")
    if len(matrix) < minimum_events:
        raise ValueError(f"At least {minimum_events} independent training events are required")
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(n_estimators=200, contamination="auto", random_state=SEED, n_jobs=1)
    model.fit(matrix)
    scores = np.asarray(model.decision_function(matrix), dtype=np.float64)
    if scores.shape != (len(matrix),) or not np.isfinite(scores).all():
        raise ValueError("Anomaly estimator produced an invalid training reference distribution")
    return model, scores


def train_anomaly_artifact(zip_path: Path = DATA_PATH, artifact_dir: Path = ARTIFACT_DIR) -> dict[str, Any]:
    data = read_esa_training_data(zip_path)
    splits = split_event_ids(data.event_ids, SEED)
    selected_ids = sorted(set(data.latest_forecast_indices) & splits["train"])
    selected_indices = [data.latest_forecast_indices[event_id] for event_id in selected_ids]
    matrix = np.asarray(data.X[selected_indices], dtype=np.float64)
    complete = np.isfinite(matrix).all(axis=1)
    excluded_incomplete = int((~complete).sum())
    matrix = matrix[complete]
    selected_ids = [event_id for event_id, is_complete in zip(selected_ids, complete) if is_complete]
    model, reference_scores = fit_anomaly_model(matrix)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / ARTIFACT_PATH.name
    metadata_path = artifact_dir / METADATA_PATH.name
    bundle = {
        "model": model,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": dict(FEATURE_UNITS),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_decision_scores": reference_scores,
    }
    import joblib
    import sklearn

    joblib.dump(bundle, artifact_path, compress=3)
    split_hash = hashlib.sha256("\n".join(selected_ids).encode("utf-8")).hexdigest()
    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "estimator": "sklearn.ensemble.IsolationForest",
        "estimator_parameters": {"n_estimators": 200, "contamination": "auto", "random_state": SEED, "n_jobs": 1},
        "dataset_name": DATASET_NAME,
        "dataset_source": DATASET_SOURCE,
        "dataset_archive": zip_path.name,
        "dataset_sha256": _sha256_file(zip_path),
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": FEATURE_UNITS,
        "training_split": "existing deterministic 70/15/15 ESA event split; training IDs only",
        "training_event_ids_sha256": split_hash,
        "training_reference_event_count": len(selected_ids),
        "minimum_training_events": MIN_TRAINING_EVENTS,
        "incomplete_training_events_excluded": excluded_incomplete,
        "feature_row_policy": "one latest pre-final CDM feature row per forecastable event; final CDM is excluded",
        "target_usage": "risk target and ESA model predictions are not estimator inputs or labels",
        "score_definition": "1 minus empirical percentile rank of Isolation Forest decision_function among training rows; unitless unusualness rank, not probability or danger",
        "limitations": [
            "ESA challenge events are a historical curated dataset and may not represent live TLE-derived conjunctions.",
            "No labelled anomaly ground truth exists in this training process; no accuracy or danger prediction is claimed.",
            "An unusual event is not necessarily dangerous, and a typical event is not necessarily safe.",
        ],
        "package_versions": {"python": sys.version.split()[0], "scikit_learn": sklearn.__version__, "numpy": np.__version__, "joblib": joblib.__version__},
        "artifact_filename": artifact_path.name,
        "artifact_sha256": _sha256_file(artifact_path),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    print(json.dumps(train_anomaly_artifact(), indent=2, sort_keys=True))
