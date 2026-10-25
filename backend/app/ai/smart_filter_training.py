"""Offline grouped training for the physics-supervised Smart Filter."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.collision_features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.ai.collision_training import DATASET_PATH, SEED, _sha256, grouped_split


MODEL_VERSION = "2.3.0"
SIGNIFICANT_PC_THRESHOLD = 1e-4
SIGNIFICANT_LOG10_THRESHOLD = -4.0
CLASS_ORDER = ("insignificant", "significant")
ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "orion_smart_filter_classifier.joblib"
METADATA_PATH = ARTIFACT_PATH.with_suffix(".metadata.json")


def _metrics(y_true, y_pred, parent_count: int, encounter_group_count: int) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=CLASS_ORDER, zero_division=0,
    )
    return {
        "sample_count": int(len(y_true)),
        "parent_event_count": parent_count,
        "encounter_group_count": encounter_group_count,
        "class_order": list(CLASS_ORDER),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_significant": float(precision[1]),
        "recall_significant": float(recall[1]),
        "false_negative_significant_count": int(confusion_matrix(y_true, y_pred, labels=CLASS_ORDER)[1, 0]),
        "macro_f1": float(f1_score(y_true, y_pred, labels=CLASS_ORDER, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=CLASS_ORDER, average="weighted", zero_division=0)),
        "confusion_matrix_rows_true_columns_predicted": confusion_matrix(y_true, y_pred, labels=CLASS_ORDER).tolist(),
        "per_class": {
            name: {"precision": float(precision[i]), "recall": float(recall[i]), "f1": float(f1[i]), "support": int(support[i])}
            for i, name in enumerate(CLASS_ORDER)
        },
        "class_balance": {name: int(np.sum(np.asarray(y_true) == name)) for name in CLASS_ORDER},
    }


def train_smart_filter() -> dict[str, Any]:
    from joblib import dump
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    scenarios = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not scenarios:
        raise ValueError(f"Physics scenario dataset is missing or empty: {DATASET_PATH}")
    group_by_parent = {row["parent_event_id"]: row["encounter_group_id"] for row in scenarios}
    parent_splits = grouped_split(list(group_by_parent), seed=SEED, group_by_parent=group_by_parent)
    encounter_splits = {name: sorted({group_by_parent[parent_id] for parent_id in ids}) for name, ids in parent_splits.items()}
    partitions = {
        name: np.asarray([i for i, row in enumerate(scenarios) if row["parent_event_id"] in set(ids)], dtype=int)
        for name, ids in parent_splits.items()
    }
    X = np.asarray([[row["features"][name] for name in FEATURE_NAMES] for row in scenarios], dtype=np.float64)
    y = np.asarray([
        "significant" if float(row["generated_pc_log10"]) >= SIGNIFICANT_LOG10_THRESHOLD else "insignificant"
        for row in scenarios
    ], dtype=object)
    if set(y) != set(CLASS_ORDER):
        raise ValueError(f"Scenario dataset must contain both binary labels; found {sorted(set(y))}")
    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("random_forest", RandomForestClassifier(
            n_estimators=300, max_depth=12, min_samples_leaf=2,
            class_weight="balanced_subsample", random_state=SEED, n_jobs=1,
        )),
    ])
    model.fit(X[partitions["train"]], y[partitions["train"]])
    baseline = DummyClassifier(strategy="most_frequent").fit(X[partitions["train"]], y[partitions["train"]])
    metrics = {}
    for split in ("validation", "test"):
        indexes = partitions[split]
        metrics[split] = _metrics(y[indexes], model.predict(X[indexes]), len(parent_splits[split]), len(encounter_splits[split]))
        metrics[split]["majority_class_baseline"] = _metrics(
            y[indexes], baseline.predict(X[indexes]), len(parent_splits[split]), len(encounter_splits[split]),
        )
        metrics[split]["majority_class_baseline"]["training_majority_class"] = str(
            baseline.classes_[int(np.argmax(baseline.class_prior_))]
        )
        # A transparent deterministic comparison rule, independent of the
        # learned classifier. It is not the runtime safety guard.
        simple_prediction = np.where(X[indexes, FEATURE_NAMES.index("miss_distance_km")] <= 1.0,
                                     "significant", "insignificant")
        metrics[split]["deterministic_miss_distance_baseline"] = _metrics(
            y[indexes], simple_prediction, len(parent_splits[split]), len(encounter_splits[split]),
        )

    split_counts = {
        name: {"parent_event_count": len(parent_splits[name]), "encounter_group_count": len(encounter_splits[name]), "scenario_count": int(len(indexes))}
        for name, indexes in partitions.items()
    }
    split_manifest = {
        "seed": SEED,
        "grouping_key": "encounter_group_id",
        "split_strategy": "fixed-seed shuffled physical encounter groups; approximately 70/15/15",
        "encounter_group_ids": encounter_splits,
        "parent_event_ids": parent_splits,
        "split_counts": split_counts,
    }
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dump({"estimator": model, "feature_names": FEATURE_NAMES, "feature_schema_version": FEATURE_SCHEMA_VERSION}, ARTIFACT_PATH, compress=3)
    split_json = json.dumps(split_manifest, indent=2, sort_keys=True) + "\n"
    split_path = ARTIFACT_PATH.with_suffix(".splits.json")
    split_path.write_text(split_json, encoding="utf-8")
    dataset_sha256 = _sha256(DATASET_PATH)
    metadata = {
        "model_name": "ORION Physics-Supervised Smart Filter Classifier",
        "model_version": MODEL_VERSION,
        "artifact_filename": ARTIFACT_PATH.name,
        "artifact_sha256": _sha256(ARTIFACT_PATH),
        "model_task": "binary significant/insignificant classification",
        "target_definition": f"significant iff physics-generated research Pc >= {SIGNIFICANT_PC_THRESHOLD:g}",
        "significant_pc_threshold": SIGNIFICANT_PC_THRESHOLD,
        "label_source": "ORION Foster 2D research Pc from saved physics-generated scenario dataset",
        "dataset_filename": DATASET_PATH.name,
        "dataset_sha256": dataset_sha256,
        "dataset_scenario_count": len(scenarios),
        "dataset_independent_parent_count": len({row["parent_event_id"] for row in scenarios}),
        "dataset_independent_encounter_group_count": len({row["encounter_group_id"] for row in scenarios}),
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "grouping_strategy": "physical encounter group across saved screening jobs; all related parent events and scenario variants remain in one partition",
        "random_seed": SEED,
        "split_counts": split_counts,
        "scenario_split": split_manifest,
        "preprocessing": "median SimpleImputer in pipeline; fitted on train partition only",
        "metrics": metrics,
        "usable_for_inference": (
            metrics["test"]["macro_f1"] > metrics["test"]["majority_class_baseline"]["macro_f1"]
            and metrics["test"]["macro_f1"] > metrics["test"]["deterministic_miss_distance_baseline"]["macro_f1"]
            and metrics["test"]["false_negative_significant_count"]
            < metrics["test"]["majority_class_baseline"]["false_negative_significant_count"]
        ),
        "baseline_comparison": {
            "majority_baseline_macro_f1_beaten": metrics["test"]["macro_f1"] > metrics["test"]["majority_class_baseline"]["macro_f1"],
            "deterministic_miss_distance_baseline_macro_f1_beaten": metrics["test"]["macro_f1"] > metrics["test"]["deterministic_miss_distance_baseline"]["macro_f1"],
            "majority_baseline_false_negatives_beaten": metrics["test"]["false_negative_significant_count"] < metrics["test"]["majority_class_baseline"]["false_negative_significant_count"],
        },
        "confidence_definition": "maximum random-forest significant-class vote fraction over the 12 configured covariance/HBR scenarios; not calibrated probability",
        "safety_guard_policy": {
            "miss_distance_threshold_km": 1.0,
            "retain_if_any_scenario_pc_at_or_above": SIGNIFICANT_PC_THRESHOLD,
            "retain_if_any_scenario_fails_or_input_is_uncertain": True,
        },
        "limitations": [
            "Labels come from the ORION research-Pc model, not observed collision outcomes.",
            "Generated variants do not increase the number of independent conjunctions.",
            "The safety guard is evaluated independently of classifier output.",
        ],
        "training_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "model_name": metadata["model_name"],
        "model_version": MODEL_VERSION,
        "usable_for_inference": metadata["usable_for_inference"],
        "baseline_comparison": metadata["baseline_comparison"],
        "target_definition": metadata["target_definition"],
        "dataset_scenario_count": len(scenarios),
        "dataset_independent_parent_count": metadata["dataset_independent_parent_count"],
        "split_counts": split_counts,
        "metrics": metrics,
        "artifact": ARTIFACT_PATH.name,
        "dataset_sha256": dataset_sha256,
    }


def main() -> None:
    print(json.dumps(train_smart_filter(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
