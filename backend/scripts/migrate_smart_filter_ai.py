"""One-time v3 Smart Filter sidecar migration for a completed saved job.

This reads stored numeric Pc and stored event inputs only.  It never starts a
screening and never recalculates physics Pc.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.smart_filter import _infer_pair_ai, _load, filter_policy
from app.models import ConjunctionAssessmentEvent


def correlation(values: list[tuple[float, float]]) -> float | None:
    if len(values) < 2:
        return None
    left, right = zip(*values)
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in values)
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return numerator / denominator if denominator else None


def migrate(job_id: str) -> dict:
    exports = Path(__file__).resolve().parents[1] / "exports"
    archive_path = exports / f"screening-job-{job_id}.json"
    sidecar_path = exports / f"smart-filter-{job_id}.json"
    backup_path = sidecar_path.with_name(f"{sidecar_path.name}.pre-ai-surrogate-v3.bak")
    if not archive_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError("Saved screening job or Smart Filter sidecar was not found.")
    if not backup_path.exists():
        shutil.copy2(sidecar_path, backup_path)
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    events = {
        raw["id"]: ConjunctionAssessmentEvent.model_validate(raw)
        for raw in archive.get("result", {}).get("data", [])
        if isinstance(raw, dict) and raw.get("result_kind") == "physics_assessment"
    }
    classifier, metadata = _load()
    policy = filter_policy()
    threshold = math.log10(policy["physics_keep_pc_threshold"])
    valid_pairs = []
    paired_logs: list[tuple[float, float]] = []
    for row in sidecar.get("decisions", []):
        event = events.get(row.get("event_id"))
        if event is None:
            continue
        valid = event.physics_result.status == "valid" and event.physics_result.tca_status == "valid"
        if not valid:
            continue
        ai = _infer_pair_ai(event, classifier, metadata)
        row.update({
            "model_status": ai["status"],
            "model_prediction": ai["classifier_prediction"],
            "confidence": ai["classifier_confidence"],
            "reason_code": ai["reason_code"],
            "ai_predicted_log10_pc": ai["ai_log10_pc"],
            "ai_pc_status": ai["ai_pc_status"],
            "ai_imputed_features": ai["imputed_features"],
            "ai_surrogate_model_name": ai["surrogate_model_name"],
            "ai_surrogate_model_version": ai["surrogate_model_version"],
        })
        physics_log = row.get("maximum_scenario_log10_pc")
        physics_keep = isinstance(physics_log, (int, float)) and math.isfinite(physics_log) and physics_log >= threshold
        ai_keep = ai["status"].startswith("available") and ai["classifier_prediction"] == "significant"
        guarded = bool(row.get("safety_guard_retained"))
        row["decision"] = "retain" if guarded or physics_keep or ai_keep else "filter"
        row["decision_source"] = "safety_guard" if guarded else "physics_pc_threshold" if physics_keep else "trained_model" if ai_keep else "physics_and_ai_agree_insignificant"
        row["reason"] = "SAFETY_GUARD_INVALID_OR_UNCERTAIN" if guarded else "PHYSICS_PC_AT_OR_ABOVE_1E-7" if physics_keep else "MODEL_PREDICTED_SIGNIFICANT" if ai_keep else "MODEL_PREDICTED_INSIGNIFICANT"
        valid_pairs.append(row)
        if isinstance(physics_log, (int, float)) and isinstance(ai["ai_log10_pc"], (int, float)):
            paired_logs.append((physics_log, ai["ai_log10_pc"]))
    physics_kept = sum(isinstance(row.get("maximum_scenario_log10_pc"), (int, float)) and row["maximum_scenario_log10_pc"] >= threshold for row in valid_pairs)
    ai_kept = sum(row.get("model_prediction") == "significant" for row in valid_pairs)
    final_kept = sum(row.get("decision") == "retain" for row in valid_pairs)
    agree = sum(((isinstance(row.get("maximum_scenario_log10_pc"), (int, float)) and row["maximum_scenario_log10_pc"] >= threshold) == (row.get("model_prediction") == "significant")) for row in valid_pairs)
    sidecar["decision_policy_version"] = 3
    sidecar["ai_comparison"] = {
        "valid_pair_count": len(valid_pairs), "ai_available_count": sum(row.get("model_status", "").startswith("available") for row in valid_pairs),
        "physics_kept_count": physics_kept, "ai_kept_count": ai_kept, "final_kept_count": final_kept,
        "agree_count": agree, "disagree_count": len(valid_pairs) - agree,
        "log10_pc_pair_count": len(paired_logs),
        "log10_pc_mean_absolute_error": sum(abs(a - b) for a, b in paired_logs) / len(paired_logs) if paired_logs else None,
        "log10_pc_correlation": correlation(paired_logs),
    }
    sidecar_path.write_text(json.dumps(sidecar, separators=(",", ":")), encoding="utf-8")
    return sidecar["ai_comparison"]


if __name__ == "__main__":
    print(json.dumps(migrate(sys.argv[1]), indent=2))
