"""Reproducible event-level training from the ESA CSV inside its ZIP archive.

Run from ``backend`` with the optional ML requirements installed:
``python -m app.ai.training``. The CSV is streamed from the ZIP and is never
extracted to disk. Only the event key, time-to-TCA, target risk, and the nine
declared live-compatible features are retained.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import random
import sys
from typing import Any
import zipfile
from collections import defaultdict

import numpy as np

from app.ai import DATASET_NAME, FEATURE_SCHEMA_VERSION, HIGH_RISK_THRESHOLD_LOG10, MODEL_NAME, MODEL_VERSION
from app.ai.features import FEATURE_NAMES, FEATURE_UNITS
from app.ai.eligibility import prepare_eligible_splits, require_scorable_population
from app.ai.model import build_baseline_model, build_primary_model
from app.ai.validation import calculate_metrics


SEED = 42
DATA_PATH = Path(__file__).resolve().parents[2] / "ml_data" / "train_data.zip"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "esa_event_log10_risk.joblib"
METADATA_PATH = ARTIFACT_DIR / "esa_event_log10_risk.metadata.json"
BACKEND_DIR = Path(__file__).resolve().parents[2]
TARGET_COLUMN = "risk"
TARGET_DEFINITION = "final event risk in log10 space, selected from the latest CDM (minimum time_to_tca; last occurrence breaks ties)"
EVENT_TIME_SEMANTICS = "CDM rows in each event are ordered latest-to-earliest by decreasing time_to_tca; forecasting examples exclude the final/latest row."
REQUIRED_COLUMNS = ("event_id", "time_to_tca", TARGET_COLUMN, "miss_distance", "relative_speed",
                    "relative_position_r", "relative_position_t", "relative_position_n",
                    "relative_velocity_r", "relative_velocity_t", "relative_velocity_n")
DATASET_SOURCE = "https://kelvins.esa.int/collision-avoidance-challenge/data/"


@dataclass(frozen=True)
class CDMRow:
    file_row_index: int
    time_to_tca_days: float
    target_risk: float | None
    features: tuple[float, ...]


@dataclass
class TrainingData:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    latest_forecast_indices: dict[str, int]
    event_ids: list[str]
    summary: dict[str, Any]


def read_esa_training_data(zip_path: Path = DATA_PATH) -> TrainingData:
    """Read selected fields directly from ``train_data.csv`` inside the ZIP."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"ESA training archive not found: {zip_path}")

    by_event: dict[str, list[CDMRow]] = {}
    raw_event_ids: set[str] = set()
    missing_feature_counts = {name: 0 for name in FEATURE_NAMES}
    rows_read = 0
    malformed_rows = 0
    invalid_event_time_rows = 0
    archive_csv_name: str | None = None
    with zipfile.ZipFile(zip_path) as archive:
        candidates = [item.filename for item in archive.infolist() if item.filename.endswith("train_data.csv")]
        if len(candidates) != 1:
            raise ValueError(f"Expected one train_data.csv in the ESA archive; found {len(candidates)}")
        archive_csv_name = candidates[0]
        with archive.open(archive_csv_name, "r") as binary_csv:
            reader = csv.reader(io.TextIOWrapper(binary_csv, encoding="utf-8-sig", newline=""))
            header = next(reader, None)
            if not header:
                raise ValueError("ESA train_data.csv has no header")
            if len(set(header)) != len(header):
                raise ValueError("ESA train_data.csv contains duplicate column names")
            missing_columns = sorted(set(REQUIRED_COLUMNS) - set(header))
            if missing_columns:
                raise ValueError(f"ESA train_data.csv missing required columns: {', '.join(missing_columns)}")
            indexes = {name: header.index(name) for name in REQUIRED_COLUMNS}
            feature_columns = (
                "time_to_tca",
                "miss_distance",
                "relative_speed",
                "relative_position_r",
                "relative_position_t",
                "relative_position_n",
                "relative_velocity_r",
                "relative_velocity_t",
                "relative_velocity_n",
            )
            for row_index, row in enumerate(reader):
                rows_read += 1
                if len(row) != len(header):
                    malformed_rows += 1
                    continue
                event_id = row[indexes["event_id"]].strip()
                if not event_id:
                    malformed_rows += 1
                    continue
                raw_event_ids.add(event_id)
                try:
                    time_to_tca = _parse_number(row[indexes["time_to_tca"]])
                except ValueError:
                    invalid_event_time_rows += 1
                    continue
                if time_to_tca is None or time_to_tca < 0.0:
                    invalid_event_time_rows += 1
                    continue
                try:
                    risk = _parse_number(row[indexes[TARGET_COLUMN]])
                except ValueError:
                    risk = None
                feature_values: list[float] = []
                for column, feature_name in zip(feature_columns, FEATURE_NAMES):
                    try:
                        value = _parse_number(row[indexes[column]])
                    except ValueError:
                        value = None
                    if value is None:
                        missing_feature_counts[feature_name] += 1
                        feature_values.append(float("nan"))
                    else:
                        feature_values.append(value)
                by_event.setdefault(event_id, []).append(CDMRow(
                    file_row_index=row_index,
                    time_to_tca_days=time_to_tca,
                    target_risk=risk,
                    features=tuple(feature_values),
                ))

    examples: list[tuple[str, CDMRow, float]] = []
    latest_forecast_rows: dict[str, tuple[CDMRow, float]] = {}
    single_row_events = 0
    target_unavailable_events = 0
    nonmonotonic_events = 0
    for event_id, rows in by_event.items():
        if len(rows) == 1:
            single_row_events += 1
        # The challenge's final CDM is the last/latest row. time_to_tca
        # decreases toward that row; selecting the minimum is a data-checked
        # ordering fallback, and list order resolves equal-time ties.
        final_position = min(
            range(len(rows)),
            key=lambda i: (rows[i].time_to_tca_days, -rows[i].file_row_index),
        )
        final_row = rows[final_position]
        if any(rows[i].time_to_tca_days < rows[i + 1].time_to_tca_days for i in range(len(rows) - 1)):
            nonmonotonic_events += 1
        if final_row.target_risk is None:
            target_unavailable_events += 1
            continue
        prior_rows = rows[:final_position]
        if not prior_rows:
            continue
        for cdm_row in prior_rows:
            examples.append((event_id, cdm_row, final_row.target_risk))
        # One latest pre-final forecast per event for event-level validation.
        latest_forecast_rows[event_id] = (prior_rows[-1], final_row.target_risk)

    if not examples:
        raise ValueError("No earlier-CDM forecasting rows with a valid final event target were found")
    X = np.asarray([row.features for _, row, _ in examples], dtype=np.float64)
    y = np.asarray([target for _, _, target in examples], dtype=np.float64)
    groups = np.asarray([event_id for event_id, _, _ in examples], dtype=object)
    latest_forecast_indices: dict[str, int] = {}
    for index, (event_id, _, _) in enumerate(examples):
        if event_id in latest_forecast_rows:
            latest_row = latest_forecast_rows[event_id][0]
            if examples[index][1].file_row_index == latest_row.file_row_index:
                latest_forecast_indices[event_id] = index

    summary = {
        "dataset_name": DATASET_NAME,
        "dataset_source": DATASET_SOURCE,
        "archive_path": _dataset_archive_reference(zip_path),
        "archive_csv_member": archive_csv_name,
        "rows_read": rows_read,
        "unique_events": len(raw_event_ids),
        "events_with_any_valid_time": len(by_event),
        "event_ids_without_any_valid_time": len(raw_event_ids - set(by_event)),
        "forecastable_events": len(latest_forecast_rows),
        "single_row_events_excluded": single_row_events,
        "events_missing_final_target_excluded": target_unavailable_events,
        "rows_with_invalid_event_time_excluded": invalid_event_time_rows,
        "malformed_rows_excluded": malformed_rows,
        "events_with_nonmonotonic_time_order": nonmonotonic_events,
        "forecast_examples": len(examples),
        "feature_missing_counts": missing_feature_counts,
        "final_target_definition": TARGET_DEFINITION,
        "target_min_log10": float(np.min([value for _, value in latest_forecast_rows.values()])),
        "target_max_log10": float(np.max([value for _, value in latest_forecast_rows.values()])),
        "target_high_risk_events": int(sum(value >= HIGH_RISK_THRESHOLD_LOG10 for _, value in latest_forecast_rows.values())),
        "final_event_target_selection": "minimum time_to_tca; last file occurrence breaks ties",
        "forecast_row_policy": "all rows before selected final CDM; final row is never an input example",
    }
    return TrainingData(X, y, groups, latest_forecast_indices, sorted(latest_forecast_rows), summary)


def split_event_ids(event_ids: list[str], seed: int = SEED) -> dict[str, set[str]]:
    """Deterministic 70/15/15 split of unique event IDs, never individual rows."""
    shuffled = sorted(event_ids)
    random.Random(seed).shuffle(shuffled)
    train_end = int(0.70 * len(shuffled))
    validation_end = train_end + int(0.15 * len(shuffled))
    return {
        "train": set(shuffled[:train_end]),
        "validation": set(shuffled[train_end:validation_end]),
        "test": set(shuffled[validation_end:]),
    }


def read_event_missions(zip_path: Path = DATA_PATH) -> dict[str, set[str]]:
    """Read mission grouping keys without extracting the ESA CSV."""
    missions: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(zip_path) as archive:
        candidates = [item.filename for item in archive.infolist() if item.filename.endswith("train_data.csv")]
        if len(candidates) != 1:
            raise ValueError(f"Expected one train_data.csv in the ESA archive; found {len(candidates)}")
        with archive.open(candidates[0], "r") as binary_csv:
            reader = csv.reader(io.TextIOWrapper(binary_csv, encoding="utf-8-sig", newline=""))
            header = next(reader, None)
            if not header or "event_id" not in header or "mission_id" not in header:
                raise ValueError("ESA training CSV must contain event_id and mission_id columns")
            event_index, mission_index = header.index("event_id"), header.index("mission_id")
            for row in reader:
                if len(row) <= max(event_index, mission_index):
                    continue
                event_id, mission_id = row[event_index].strip(), row[mission_index].strip()
                if event_id and mission_id:
                    missions[event_id].add(mission_id)
    return dict(missions)


def split_group_ids(group_ids: set[str], seed: int = SEED) -> dict[str, set[str]]:
    shuffled = sorted(group_ids)
    random.Random(seed).shuffle(shuffled)
    train_end = int(0.70 * len(shuffled))
    validation_end = train_end + int(0.15 * len(shuffled))
    return {
        "train": set(shuffled[:train_end]),
        "validation": set(shuffled[train_end:validation_end]),
        "test": set(shuffled[validation_end:]),
    }


def train_and_evaluate(zip_path: Path = DATA_PATH, artifact_dir: Path = ARTIFACT_DIR) -> dict[str, Any]:
    """Fit and evaluate only on pre-final rows at least two days before TCA."""
    try:
        import joblib
        import scipy
        import sklearn
    except ImportError as exc:
        raise RuntimeError("Install backend/requirements-optional.txt to run Stage 3 training") from exc

    data = read_esa_training_data(zip_path)
    mission_by_event = read_event_missions(zip_path)
    single_mission_events = {
        event_id: next(iter(mission_by_event[event_id]))
        for event_id in data.event_ids if len(mission_by_event.get(event_id, set())) == 1
    }
    mission_splits = split_group_ids(set(single_mission_events.values()), SEED)
    splits = {
        split_name: {event_id for event_id, mission_id in single_mission_events.items() if mission_id in missions}
        for split_name, missions in mission_splits.items()
    }
    if set.intersection(*(splits[name] for name in ("train", "validation", "test"))):
        raise AssertionError("Event-level split has event overlap")
    eligible_splits = prepare_eligible_splits(data.X, data.y, data.groups, splits)
    train_split = eligible_splits["train"]
    if train_split["eligible_event_count"] < 2 or not train_split["row_indices"]:
        raise ValueError(
            "Training split has fewer than 2 events with eligible pre-final CDMs "
            "(time_to_tca_days >= 2.0); no model was fitted"
        )
    for split_name in ("validation", "test"):
        require_scorable_population(split_name, eligible_splits[split_name])

    train_row_counts: dict[str, int] = {}
    for event_id in data.groups[train_split["row_indices"]]:
        key = str(event_id)
        train_row_counts[key] = train_row_counts.get(key, 0) + 1
    sample_weights = np.asarray([
        1.0 / train_row_counts[str(event_id)]
        for event_id in data.groups[train_split["row_indices"]]
    ])

    baseline = build_baseline_model(SEED)
    gradient_boosting = build_primary_model(SEED)
    X_train = data.X[train_split["row_indices"]]
    y_train = data.y[train_split["row_indices"]]
    baseline.fit(X_train, y_train, ridge__sample_weight=sample_weights)
    gradient_boosting.fit(X_train, y_train, histgradientboostingregressor__sample_weight=sample_weights)

    event_metrics: dict[str, dict[str, dict[str, float | None]]] = {}
    predictions: dict[str, dict[str, list[float]]] = {}
    for split_name in ("validation", "test"):
        selected = [eligible_splits[split_name]["latest_indices"][event_id]
                    for event_id in eligible_splits[split_name]["event_ids"]]
        X_eval, y_eval = data.X[selected], data.y[selected]
        baseline_pred = baseline.predict(X_eval)
        primary_pred = gradient_boosting.predict(X_eval)
        event_metrics[split_name] = {
            "ridge_baseline": calculate_metrics(y_eval, baseline_pred),
            "hist_gradient_boosting": calculate_metrics(y_eval, primary_pred),
        }
        predictions[split_name] = {
            "truth_log10_risk": y_eval.astype(float).tolist(),
            "ridge_predicted_log10_risk": np.asarray(baseline_pred, dtype=float).tolist(),
            "primary_predicted_log10_risk": np.asarray(primary_pred, dtype=float).tolist(),
        }

    train_event_counts = {name: len(splits[name]) for name in splits}
    event_split_hashes = {
        name: hashlib.sha256("\n".join(sorted(event_ids)).encode("utf-8")).hexdigest()
        for name, event_ids in splits.items()
    }
    validation_candidates = event_metrics["validation"]
    selected_name = min(
        ("ridge_baseline", "hist_gradient_boosting"),
        key=lambda name: validation_candidates[name]["mae_log10"],
    )
    primary = baseline if selected_name == "ridge_baseline" else gradient_boosting
    feature_medians = primary.named_steps["imputer"].statistics_.astype(float).tolist()
    preprocessing = {
        "training_only_fit": True,
        "numeric_imputation": "median per feature, fitted on training forecast rows only; add missingness indicators",
        "training_missing_counts": data.summary["feature_missing_counts"],
        "imputer_medians_in_feature_order": feature_medians,
        "ridge_scaling": "StandardScaler fitted on imputed training rows only",
        "hgb_scaling": "none; tree estimator",
        "event_balanced_sample_weight": "each training event has total weight 1 across its earlier CDM rows",
        "live_inference_imputation": "none; missing required Stage 2A feature returns unavailable",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "primary_model": primary,
        "baseline_model": baseline,
        "candidate_models": {"ridge": baseline, "histogram_gradient_boosting": gradient_boosting},
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "target_definition": TARGET_DEFINITION,
    }
    joblib.dump(bundle, artifact_dir / ARTIFACT_PATH.name, compress=3)
    artifact_path = artifact_dir / ARTIFACT_PATH.name
    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "primary_estimator": "sklearn.linear_model.Ridge" if selected_name == "ridge_baseline" else "sklearn.ensemble.HistGradientBoostingRegressor",
        "validation_candidate_selected": "ridge" if selected_name == "ridge_baseline" else "histogram_gradient_boosting",
        "baseline_estimator": "sklearn.linear_model.Ridge",
        "dataset_name": DATASET_NAME,
        "dataset_source": DATASET_SOURCE,
        "dataset_archive": _dataset_archive_reference(zip_path),
        "dataset_sha256": _sha256_file(zip_path),
        "training_date_utc": datetime.now(timezone.utc).isoformat(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": FEATURE_UNITS,
        "target_column": TARGET_COLUMN,
        "target_definition": TARGET_DEFINITION,
        "target_units": "log10 risk",
        "high_risk_threshold_log10": HIGH_RISK_THRESHOLD_LOG10,
        "event_time_semantics": EVENT_TIME_SEMANTICS,
        "seed": SEED,
        "split_ratios": {"train": 0.70, "validation": 0.15, "test": 0.15},
        "split_group": "mission_id; events with missing or ambiguous mission assignment excluded",
        "split_algorithm": "sorted unique mission IDs, Python random.Random(seed).shuffle, floor(70%) then floor(15%), remainder test",
        "split_mission_counts": {name: len(values) for name, values in mission_splits.items()},
        "split_mission_hashes_sha256": {
            name: hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()
            for name, values in mission_splits.items()
        },
        "mission_split_overlap": False,
        "split_event_counts": train_event_counts,
        "event_split_hashes_sha256": event_split_hashes,
        "event_leakage_check": "pairwise disjoint event and mission ID sets; evaluated before fitting",
        "event_split_overlap": False,
        "train_forecast_example_count": len(train_split["row_indices"]),
        "eligible_input_protocol": {
            "minimum_time_to_tca_days_inclusive": 2.0,
            "training_rows": "all eligible pre-final CDMs within each training event",
            "validation_test_rows": "closest-to-TCA eligible pre-final CDM per event",
            "split_population_counts": {
                name: {key: values[key] for key in (
                    "total_event_count", "eligible_event_count", "excluded_event_count",
                    "eligible_row_count", "high_risk_event_count", "low_risk_event_count",
                )}
                for name, values in eligible_splits.items()
            },
        },
        "validation_event_count": len(predictions.get("validation", {}).get("truth_log10_risk", [])),
        "test_event_count": len(predictions.get("test", {}).get("truth_log10_risk", [])),
        "preprocessing": preprocessing,
        "dataset_summary": data.summary,
        "metrics": event_metrics,
        "metric_evaluation_unit": "one closest-to-TCA eligible pre-final CDM forecast per held-out event",
        "limitations": [
            "Historical ESA CDM domain differs from live CelesTrak TLE-derived encounters.",
            "Live ORION normally has no covariance or explicit hard-body radius.",
            "ESA log10 risk is not equivalent to validated physics collision probability Pc.",
            "TLE-derived state uncertainty is not represented by this ML model.",
            "Research prototype only; not operational collision-avoidance capability.",
        ],
        "excluded_inputs": [
            "risk (target only)", "max_risk_estimate", "max_risk_scaling", "mission_id", "event_id",
            "covariance determinant, sigma, Mahalanobis distance, and all other covariance-derived columns",
        ],
        "domain_shift_warning": "ESA hand-selected challenge training data over-represents high-risk events; model estimates may be miscalibrated or biased on live ORION catalogs.",
        "package_versions": {
            "python": sys.version.split()[0],
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "joblib": joblib.__version__,
        },
        "artifact_filename": artifact_path.name,
        "artifact_sha256": _sha256_file(artifact_path),
    }
    metadata_path = artifact_dir / METADATA_PATH.name
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def _parse_number(value: str) -> float | None:
    if value is None or not value.strip():
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_archive_reference(path: Path) -> str:
    try:
        return path.resolve().relative_to(BACKEND_DIR).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    result = train_and_evaluate()
    print(json.dumps(result, indent=2, sort_keys=True))
