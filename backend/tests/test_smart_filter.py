from __future__ import annotations

import json
import hashlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai import smart_filter
from app.ai.collision_training import BACKEND_DIR, read_parent_events
from app.ai.smart_filter_training import ARTIFACT_PATH, METADATA_PATH
from app.main import _screening_jobs, app


class PhysicsSmartFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot, cls.events = read_parent_events()
        cls.event = cls.events[0]

    def test_safety_guard_retains_close_real_celestrak_event(self) -> None:
        result = smart_filter.evaluate_physical_smart_filter([self.event])
        row = result["decisions"][0]
        self.assertEqual(result["status"], "available")
        self.assertEqual(row["decision"], "retain")
        self.assertTrue(row["safety_guard_retained"])
        self.assertIn("SAFETY_GUARD_MISS_DISTANCE", row["safety_guard_reasons"])
        self.assertEqual(row["scenario_count_calculated"], row["scenario_count_required"])
        self.assertIn(row["model_prediction"], {"significant", "insignificant"})
        self.assertIsInstance(row["confidence"], float)

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

    def test_saved_scenario_labels_and_grouped_metadata_match_trained_filter(self) -> None:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["dataset_filename"], "orion-collision-scenarios-v1.jsonl")
        dataset_path = BACKEND_DIR / "ml_data" / metadata["dataset_filename"]
        self.assertEqual(metadata["dataset_sha256"], hashlib.sha256(dataset_path.read_bytes()).hexdigest())
        self.assertEqual(metadata["grouping_strategy"], "parent_event_id; scenario variants from one conjunction never cross partitions")
        parent_groups = metadata["scenario_split"]["parent_event_ids"]
        self.assertFalse(set(parent_groups["train"]) & set(parent_groups["validation"]))
        self.assertFalse(set(parent_groups["train"]) & set(parent_groups["test"]))
        self.assertFalse(set(parent_groups["validation"]) & set(parent_groups["test"]))
        self.assertEqual(metadata["significant_pc_threshold"], 1e-4)
        self.assertGreater(metadata["metrics"]["test"]["false_negative_significant_count"], 0)


if __name__ == "__main__":
    unittest.main()
