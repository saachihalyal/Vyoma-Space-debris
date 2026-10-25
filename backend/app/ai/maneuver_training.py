"""Generate and train a grouped research-Pc maneuver ranker offline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import random
import time

import numpy as np

from app.ai.maneuver_ranker import (
    ARTIFACT_DIR, ARTIFACT_PATH, FEATURES, FEATURE_SCHEMA_VERSION,
    METADATA_PATH, MODEL_NAME, MODEL_VERSION, feature_vector,
)
from app.ai.collision_training import read_parent_events
from app.services.conjunction import optimize_maneuver


BACKEND = Path(__file__).resolve().parents[2]
DATA_PATH = BACKEND / "ml_data" / "maneuver_pc_reduction_v1.csv"
SPLIT_PATH = BACKEND / "ml_data" / "maneuver_pc_reduction_v1-splits.json"
SEED = 1501
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def train_pc_reduction_and_evaluate(parent_event_limit: int = 60) -> dict:
    """Train only from saved real CelesTrak parent events and physics Pc labels."""
    if isinstance(parent_event_limit, bool) or not isinstance(parent_event_limit, int) or not 30 <= parent_event_limit <= 100:
        raise ValueError("parent_event_limit must be an integer from 30 through 100")
    try:
        import joblib
        import sklearn
        from sklearn.ensemble import RandomForestRegressor
    except ImportError as exc:
        raise RuntimeError("The existing scikit-learn/joblib runtime is required; no installation was attempted") from exc
    started = time.perf_counter()
    snapshot, events = read_parent_events()
    events = events[:parent_event_limit]
    if len(events) < 30:
        raise ValueError(f"At least 30 valid real parent events are required; found {len(events)}")
    rows: list[dict] = []
    leads = (60.0, 300.0, 900.0, 1800.0)
    magnitudes = (0.005, 0.01, 0.02, 0.05)
    for index, event in enumerate(events):
        lead, magnitude = leads[index % len(leads)], magnitudes[index % len(magnitudes)]
        result = optimize_maneuver(
            event, lead_seconds=lead, burn_magnitudes_m_s=(magnitude,),
            refine_candidates=False,
        )
        baseline = result.get("probability_before") or {}
        baseline_log = baseline.get("log10_pc") if baseline.get("status") == "available" else None
        if not isinstance(baseline_log, (int, float)) or not result.get("candidates"):
            continue
        for candidate in result["candidates"]:
            if candidate.get("delta_v_m_s") == 0:
                continue
            reduction = candidate.get("research_pc_reduction_log10")
            after = candidate.get("research_pc_after") or {}
            if candidate.get("objective_status") == "search_boundary_minimum" or not isinstance(reduction, (int, float)) or after.get("status") != "available":
                continue
            rows.append({
                "parent_event_id": event.id,
                "scenario_id": f"{event.id}|lead={lead:g}|dv={magnitude:g}|{candidate['direction']}",
                "lead_time_seconds": lead,
                "delta_v_m_s": magnitude,
                "direction": candidate["direction"],
                "features": feature_vector(event, candidate, lead),
                "target_log10_pc_reduction": float(reduction),
                "baseline_pc_scientific": baseline.get("pc_scientific"),
                "candidate_pc_scientific": after.get("pc_scientific"),
                "candidate_tca_utc": after.get("tca_utc"),
                "candidate_miss_distance_km": candidate.get("predicted_miss_distance_km"),
                "provenance": event.provenance.model_dump(mode="json"),
                "covariance_policy": after.get("covariance_method"),
                "hbr_policy": after.get("hbr_method"),
                "calculator_version": after.get("method_version"),
                "objective_status": candidate.get("objective_status"),
            })
    parent_ids = sorted({row["parent_event_id"] for row in rows})
    if len(parent_ids) < 30:
        raise ValueError(f"Fewer than 30 parent events produced comparable Pc labels: {len(parent_ids)}")
    split_ids = parent_ids[:]
    random.Random(SEED).shuffle(split_ids)
    train_end, val_end = int(0.70 * len(split_ids)), int(0.85 * len(split_ids))
    partitions = {"train": set(split_ids[:train_end]), "validation": set(split_ids[train_end:val_end]), "test": set(split_ids[val_end:])}
    if any(partitions[a] & partitions[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise AssertionError("Parent-event leakage detected")
    partition_rows = {name: [row for row in rows if row["parent_event_id"] in ids] for name, ids in partitions.items()}
    train_rows, validation_rows, test_rows = (partition_rows[name] for name in ("train", "validation", "test"))
    estimator = RandomForestRegressor(n_estimators=240, max_depth=14, min_samples_leaf=3, random_state=SEED, n_jobs=1)
    estimator.fit(np.asarray([row["features"] for row in train_rows]), np.asarray([row["target_log10_pc_reduction"] for row in train_rows]))

    def metrics(evaluation_rows: list[dict]) -> dict:
        actual = np.asarray([row["target_log10_pc_reduction"] for row in evaluation_rows], dtype=float)
        predicted = np.asarray(estimator.predict(np.asarray([row["features"] for row in evaluation_rows])), dtype=float)
        errors = predicted - actual
        grouped: dict[str, list[int]] = {}
        for i, row in enumerate(evaluation_rows):
            grouped.setdefault(row["parent_event_id"], []).append(i)
        ranks, regrets, baseline_regrets, top1 = [], [], [], []
        for indices in grouped.values():
            target, estimate = actual[indices], predicted[indices]
            predicted_best, physics_best = int(np.argmax(estimate)), int(np.argmax(target))
            ranks.append(float(__import__("scipy.stats", fromlist=["spearmanr"]).spearmanr(target, estimate).statistic))
            regrets.append(float(target[physics_best] - target[predicted_best]))
            first_direction = min(range(len(indices)), key=lambda local: (evaluation_rows[indices[local]]["delta_v_m_s"], evaluation_rows[indices[local]]["direction"]))
            baseline_regrets.append(float(target[physics_best] - target[first_direction]))
            top1.append(predicted_best == physics_best)
        return {
            "candidate_count": len(evaluation_rows), "parent_event_count": len(grouped),
            "mae_log10_pc_reduction": float(np.mean(np.abs(errors))),
            "rmse_log10_pc_reduction": float(np.sqrt(np.mean(errors ** 2))),
            "mean_within_parent_spearman": float(np.mean([value for value in ranks if math.isfinite(value)])) if any(math.isfinite(value) for value in ranks) else None,
            "top1_agreement_with_physics_best": float(np.mean(top1)) if top1 else None,
            "mean_regret_log10_pc_reduction": float(np.mean(regrets)) if regrets else None,
            "baseline": {
                "name": "lowest delta-v, then alphabetical direction tie-break",
                "mean_regret_log10_pc_reduction": float(np.mean(baseline_regrets)) if baseline_regrets else None,
            },
        }
    test_metrics = metrics(test_rows)
    validation_metrics = metrics(validation_rows)
    median_prediction = float(np.median([row["target_log10_pc_reduction"] for row in train_rows]))
    test_targets = np.asarray([row["target_log10_pc_reduction"] for row in test_rows], dtype=float)
    test_metrics["median_train_target_baseline"] = {
        "mae_log10_pc_reduction": float(np.mean(np.abs(test_targets - median_prediction))),
        "rmse_log10_pc_reduction": float(np.sqrt(np.mean((test_targets - median_prediction) ** 2))),
        "training_median_log10_pc_reduction": median_prediction,
    }
    dataset_rows = [{key: value for key, value in row.items() if key != "features"} | {name: value for name, value in zip(FEATURES, row["features"])} for row in rows]
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dataset_rows[0]))
        writer.writeheader(); writer.writerows(dataset_rows)
    dataset_hash = _sha256(DATA_PATH)
    split_manifest = {"seed": SEED, "grouping_key": "parent_event_id", "split_strategy": "70/15/15 fixed-seed parent-event split", "parent_event_ids": {name: sorted(ids) for name, ids in partitions.items()}, "scenario_counts": {name: sum(row["parent_event_id"] in ids for row in rows) for name, ids in partitions.items()}}
    SPLIT_PATH.write_text(json.dumps(split_manifest, indent=2) + "\n", encoding="utf-8")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {"estimator": estimator, "feature_names": list(FEATURES), "feature_schema_version": FEATURE_SCHEMA_VERSION, "model_name": MODEL_NAME, "model_version": MODEL_VERSION}
    joblib.dump(bundle, ARTIFACT_PATH, compress=3)
    metadata = {
        "model_name": MODEL_NAME, "model_version": MODEL_VERSION,
        "artifact_filename": ARTIFACT_PATH.name, "artifact_sha256": _sha256(ARTIFACT_PATH),
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_names": list(FEATURES),
        "target": "log10(Pc_zero_burn / Pc_candidate)", "target_units": "log10 ratio; positive means reduced Pc",
        "dataset_filename": DATA_PATH.name, "dataset_sha256": dataset_hash,
        "parent_event_count": len(parent_ids), "candidate_scenario_count": len(rows),
        "parent_source": {"snapshot_job_id": snapshot.get("job_id"), "snapshot_created_at_utc": snapshot.get("created_at_utc") or snapshot.get("created_at"), "input_policy": "both objects must have real, non-synthetic CelesTrak provenance"},
        "scenario_generation": {"lead_seconds_cycle": list(leads), "delta_v_m_s_cycle": list(magnitudes), "directions": list(sorted(set(row["direction"] for row in rows))), "propagator": "Earth two-body point-mass RK4", "research_pc_method": "ORION TLE-age-baseline Foster 2D at each calculated TCA with the exact selected-event TEME covariance matrices and HBR held fixed for baseline and candidate", "covariance_assignment": "Baseline-event covariance matrices reused numerically unchanged at candidate TCA; no dynamic covariance propagation or burn execution uncertainty"},
        "grouped_split": split_manifest,
        "split_counts": {name: {"parent_event_count": len(ids), "candidate_scenario_count": split_manifest["scenario_counts"][name]} for name, ids in partitions.items()},
        "estimator": f"RandomForestRegressor(n_estimators=240, max_depth=14, min_samples_leaf=3, random_state={SEED}, n_jobs=1)",
        "validation_metrics": validation_metrics, "test_metrics": test_metrics,
        "baseline": {"name": "lowest delta-v, then alphabetical direction tie-break", "test_metrics": test_metrics.get("baseline")},
        "scikit_learn_version": sklearn.__version__,
        "limitations": ["Targets are ORION physics-generated research-Pc differences for simulated burns from real parent conjunction states, not observed collision or maneuver outcomes.", "The 2-body simulator omits J2, drag, third-body effects, control constraints, and burn execution uncertainty.", "The baseline-event covariance matrix is held fixed for each candidate comparison rather than dynamically propagated; this is a documented consistent research approximation.", "Only six signed RTN directions and one configured magnitude per parent are used for training; performance may not generalize beyond this envelope.", "The ranker is used only if held-out mean regret beats the deterministic baseline; every live candidate is recalculated by the physics pipeline."],
        "training_elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def train_and_evaluate(parent_event_limit: int = 60) -> dict:
    """Compatibility entry point; always trains the real-parent Pc ranker."""
    return train_pc_reduction_and_evaluate(parent_event_limit)


if __name__ == "__main__":
    print(json.dumps(train_pc_reduction_and_evaluate(), indent=2))

