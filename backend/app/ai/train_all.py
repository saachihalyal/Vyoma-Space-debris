"""Reproducible offline T5 training entry point for the three collision models."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from app.ai.collision_training import train_models
from app.ai.smart_filter_training import train_smart_filter


ROOT = Path(__file__).resolve().parents[3]
METRICS_PATH = ROOT / "docs" / "MODEL_METRICS.json"
MANEUVER_METADATA_PATH = Path(__file__).resolve().parent / "artifacts" / "maneuver_pc_reduction_ranker.metadata.json"


def train_all() -> dict:
    collision = train_models()
    smart_filter = train_smart_filter()
    result = {
        "schema_version": "orion-t5-model-metrics-v1",
        "training_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "training_mode": "offline_only",
        "collision_models": collision,
        "smart_filter": smart_filter,
        "maneuver_ranker": _maneuver_ranker_summary(),
        "scientific_limitations": [
            "All targets are physics-generated proxies from saved real parent events, not observed collision outcomes.",
            "Scenario variants are correlated within their parent event; grouped evaluation uses parent_event_id.",
            "No operational calibration or collision-outcome validation is claimed.",
        ],
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _maneuver_ranker_summary() -> dict:
    if not MANEUVER_METADATA_PATH.is_file():
        return {"status": "not_trained", "reason": "No saved Stage 4 maneuver ranker metadata is available."}
    metadata = json.loads(MANEUVER_METADATA_PATH.read_text(encoding="utf-8"))
    metrics = metadata.get("test_metrics") or {}
    baseline = (metadata.get("baseline") or {}).get("test_metrics") or {}
    ranking_used = (
        metrics.get("mean_regret_log10_pc_reduction") is not None
        and baseline.get("mean_regret_log10_pc_reduction") is not None
        and metrics["mean_regret_log10_pc_reduction"] < baseline["mean_regret_log10_pc_reduction"]
    )
    return {
        "status": "trained" if ranking_used else "trained_fallback_physics_ranking",
        "model_version": metadata.get("model_version"),
        "dataset_sha256": metadata.get("dataset_sha256"),
        "parent_event_count": metadata.get("parent_event_count"),
        "candidate_scenario_count": metadata.get("candidate_scenario_count"),
        "split_counts": metadata.get("split_counts"),
        "test_metrics": metrics,
        "baseline_test_metrics": baseline,
        "ranking_used": ranking_used,
    }


if __name__ == "__main__":
    print(json.dumps(train_all(), indent=2, sort_keys=True, allow_nan=False))
