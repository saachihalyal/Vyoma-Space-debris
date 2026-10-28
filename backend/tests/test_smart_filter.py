from __future__ import annotations

import json
import hashlib
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai import smart_filter
from app.ai.collision_training import BACKEND_DIR, read_parent_events
from app.ai.smart_filter_training import ARTIFACT_PATH, METADATA_PATH
from app.main import _screening_job_for_smart_filter, _screening_jobs, app


class PhysicsSmartFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot, cls.events = read_parent_events()
        cls.event = cls.events[0]

    def test_safety_guard_retains_real_event_when_scenarios_are_uncertain(self) -> None:
        with patch.object(smart_filter, "_log10_pc", return_value=None):
            result = smart_filter.evaluate_physical_smart_filter([self.event])
        row = result["decisions"][0]
        self.assertEqual(result["status"], "available")
        self.assertEqual(row["decision"], "retain")
        self.assertTrue(row["safety_guard_retained"])
        self.assertIn("SAFETY_GUARD_UNCERTAIN_SCENARIOS", row["safety_guard_reasons"])
        self.assertLess(row["scenario_count_calculated"], row["scenario_count_required"])
        self.assertIsNone(row["model_prediction"])
        self.assertIsNone(row["confidence"])

    def test_probability_scoring_uses_numeric_log_beneath_display_floor(self) -> None:
        self.assertEqual(smart_filter._log10_pc("< 1e-30", -47.835758197384806), -47.835758197384806)
        self.assertEqual(smart_filter._scientific_from_log10(-47.835758197384806), "< 1e-30")

    def test_missing_model_is_labeled_fallback_and_never_claims_a_prediction(self) -> None:
        missing = ARTIFACT_PATH.with_name("missing-smart-filter.joblib")
        with patch.object(smart_filter, "ARTIFACT_PATH", missing), patch.object(
            smart_filter, "METADATA_PATH", missing.with_suffix(".metadata.json")
        ):
            smart_filter._load_artifact.cache_clear()
            result = smart_filter.evaluate_physical_smart_filter([self.event])
            self.assertEqual(result["status"], "fallback")
            row = result["decisions"][0]
            self.assertEqual(row["model_status"], "unavailable")
            self.assertEqual(row["decision_source"], "safety_guard")
            self.assertIsNone(row["model_prediction"])
            self.assertEqual(row["decision"], "retain")
        smart_filter._load_artifact.cache_clear()

    def test_medium_physics_pc_is_kept_when_ai_predicts_insignificant(self) -> None:
        class InsignificantModel:
            classes_ = ["insignificant", "significant"]

            def predict_proba(self, values):
                return [[1.0, 0.0] for _ in values]

        medium_scenario = SimpleNamespace(
            status="prior_based_research_estimate", reason_codes=[],
            estimated_pc_scientific="3e-7", log10_pc=math.log10(3e-7),
        )
        features = {name: 0.0 for name in smart_filter.FEATURE_NAMES}
        with patch.object(smart_filter, "assess_automatic_research_pc", return_value=medium_scenario), patch.object(
            smart_filter, "build_collision_features", return_value=features,
        ):
            row = smart_filter._assess_one(self.event, InsignificantModel(), {"model_name": "test"}, smart_filter.filter_policy())
        self.assertEqual(row["model_prediction"], "insignificant")
        self.assertTrue(row["safety_guard_retained"])
        self.assertIn("SAFETY_GUARD_SCENARIO_PC", row["safety_guard_reasons"])
        self.assertEqual(row["decision"], "retain")

    def test_physics_filter_api_and_csv_keep_event_reason_and_guard_fields(self) -> None:
        job_id = "0123456789abcdef0123456789abcdef"
        job = {
            "job_id": job_id, "status": "complete", "archived": False,
            "result": {"data": [self.event.model_dump(mode="json")]},
        }
        with patch.dict(_screening_jobs, {job_id: job}, clear=False):
            client = TestClient(app)
            response = client.get(f"/api/conjunction-jobs/{job_id}/smart-filter")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["evaluation"]["before_count"], 1)
            self.assertEqual(payload["evaluation"]["kept_count"] + payload["evaluation"]["filtered_count"], 1)
            self.assertIn("reason", payload["decisions"][0])
            self.assertIn("decision_source", payload["decisions"][0])
            csv_response = client.get(f"/api/conjunction-jobs/{job_id}/smart-filter.csv")
            self.assertEqual(csv_response.status_code, 200)
            self.assertIn("event_id,object_ids,object_names", csv_response.text)
            self.assertIn(self.event.id, csv_response.text)
            self.assertIn("safety_guard_retained", csv_response.text)

    def test_physics_filter_api_ignores_process_local_screening_task(self) -> None:
        class RuntimeTask:
            def __deepcopy__(self, memo):
                raise TypeError("runtime task cannot be copied")

        job_id = "fedcba9876543210fedcba9876543210"
        job = {"job_id": job_id, "status": "complete", "task": RuntimeTask(),
               "result": {"data": [self.event.model_dump(mode="json")]}}
        with patch.dict(_screening_jobs, {job_id: job}, clear=False):
            response = TestClient(app).get(f"/api/conjunction-jobs/{job_id}/smart-filter")
        self.assertEqual(response.status_code, 200, response.text)

    def test_filter_request_registers_restored_archive_as_latest_accepted_job(self) -> None:
        job_id = "abcdef0123456789abcdef0123456789"
        archived = {
            "job_id": job_id,
            "status": "complete",
            "created_at": "2999-01-01T00:00:00+00:00",
            "finished_at": "2999-01-01T00:01:00+00:00",
            "result": {"data": [self.event.model_dump(mode="json")]},
        }
        with patch("app.main._load_archived_screening_job", return_value=archived):
            restored = _screening_job_for_smart_filter(job_id)
            latest = TestClient(app).get("/api/conjunction-jobs/latest")
        self.assertTrue(restored["restored_from_archive"])
        self.assertTrue(restored["archived"])
        self.assertEqual(latest.status_code, 200, latest.text)
        self.assertEqual(latest.json()["job"]["job_id"], job_id)
        _screening_jobs.pop(job_id, None)

    def test_saved_scenario_labels_and_grouped_metadata_match_trained_filter(self) -> None:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["dataset_filename"], "orion-collision-scenarios-v5.jsonl")
        self.assertEqual(metadata["model_version"], "2.3.0")
        self.assertTrue(metadata["usable_for_inference"])
        dataset_path = BACKEND_DIR / "ml_data" / metadata["dataset_filename"]
        self.assertEqual(metadata["dataset_sha256"], hashlib.sha256(dataset_path.read_bytes()).hexdigest())
        self.assertIn("physical encounter group across saved screening jobs", metadata["grouping_strategy"])
        parent_groups = metadata["scenario_split"]["parent_event_ids"]
        self.assertFalse(set(parent_groups["train"]) & set(parent_groups["validation"]))
        self.assertFalse(set(parent_groups["train"]) & set(parent_groups["test"]))
        self.assertFalse(set(parent_groups["validation"]) & set(parent_groups["test"]))
        encounter_groups = metadata["scenario_split"]["encounter_group_ids"]
        self.assertFalse(set(encounter_groups["train"]) & set(encounter_groups["validation"]))
        self.assertFalse(set(encounter_groups["train"]) & set(encounter_groups["test"]))
        self.assertFalse(set(encounter_groups["validation"]) & set(encounter_groups["test"]))
        self.assertTrue(metadata["baseline_comparison"]["deterministic_miss_distance_baseline_macro_f1_beaten"])
        self.assertEqual(metadata["significant_pc_threshold"], 1e-4)
        self.assertEqual(smart_filter.filter_policy()["physics_keep_pc_threshold"], 1e-7)
        self.assertGreater(metadata["metrics"]["test"]["false_negative_significant_count"], 0)


if __name__ == "__main__":
    unittest.main()
