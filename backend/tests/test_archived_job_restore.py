from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


JOB_ID = "0123456789abcdef0123456789abcdef"


def archived_job(job_id: str = JOB_ID) -> dict:
    events = []
    for event_id, status, reasons in (
        ("CA-valid", "valid", []),
        ("CA-invalid", "invalid", ["identical_propagation_parameters_for_distinct_catalog_ids"]),
    ):
        events.append({
            "id": event_id,
            "event_identity_type": "trajectory_event_deterministic",
            "result_kind": "physics_assessment",
            "primary": {"id": "10114", "name": "Object A"},
            "secondary": {"id": "25544", "name": "Object B"},
            "physics_result": {
                "object_primary_id": "10114",
                "object_secondary_id": "25544",
                "tca": {"value": "2026-10-13T12:56:17.152617+00:00"},
                "miss_distance": {"value": 1.765},
                "relative_velocity_at_tca": {"value": [1.0, 2.0, 3.0]},
                "relative_speed_at_tca": {"value": 3.742},
                "status": status,
                "reason_codes": reasons,
                "provenance": {"input_hash": event_id},
            },
        })
    return {
        "job_id": job_id,
        "status": "partial",
        "created_at": "2026-10-13T12:10:30.861421+00:00",
        "started_at": "2026-10-13T12:10:31.446637+00:00",
        "finished_at": "2026-10-13T12:11:08.137269+00:00",
        "completion_status": "partial",
        "progress": {"stage": "partial", "percent": 100, "message": "Completed partially."},
        "configuration": {
            "limit": 120,
            "horizon_hours": 24.0,
            "sample_step_seconds": 60,
            "screening_threshold_km": 25.0,
            "start_utc": "2026-10-13T12:10:22.590000+00:00",
        },
        "maneuver_results": {},
        "result": {
            "success": True,
            "result_kind": "physics_assessment",
            "result_status": "partial",
            "completion_status": "partial",
            "physics_assessment_status": "partial",
            "source_summary": {"status": "all_live", "object_count": 120},
            "screening": {
                "status": "partial",
                "completion_status": "partial",
                "candidate_pair_count": 1894,
                "candidate_local_minimum_count": 6878,
                "refinement_count": 6878,
                "close_approach_count": 1,
                "invalid_assessment_count": 1,
            },
            "data": events,
        },
    }


class ArchivedJobRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.archive_dir = Path(self.temp_dir.name)
        self.job = archived_job()
        self.json_path = self.archive_dir / f"screening-job-{JOB_ID}.json"
        self.csv_path = self.archive_dir / f"trajectory-assessments-{JOB_ID}.csv"
        self.original_json = json.dumps(self.job, separators=(",", ":")).encode("utf-8")
        self.original_csv = b"event_id,record_type\r\nCA-valid,event\r\nCA-invalid,event\r\n"
        self.json_path.write_bytes(self.original_json)
        self.csv_path.write_bytes(self.original_csv)
        self.registry_patch = patch.dict(main._screening_jobs, {}, clear=True)
        self.registry_patch.start()
        self.archive_patch = patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", self.archive_dir)
        self.archive_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.archive_patch.stop()
        self.registry_patch.stop()
        self.temp_dir.cleanup()

    def test_latest_endpoint_restores_the_newest_accepted_archive_on_first_load(self) -> None:
        response = self.client.get("/api/conjunction-jobs/latest")
        self.assertEqual(response.status_code, 200)
        job = response.json()["job"]
        self.assertEqual(job["job_id"], JOB_ID)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(len(job["result"]["data"]), 2)
        self.assertTrue(job["result"]["assessment_pagination"]["loaded_all"])
        self.assertTrue(main._screening_jobs[JOB_ID]["restored_from_archive"])

    def test_active_endpoint_does_not_create_a_replacement_run(self) -> None:
        response = self.client.get("/api/conjunction-jobs/active")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["job"])
        self.assertEqual(main._screening_jobs, {})

    def test_restore_preserves_job_metadata_events_and_original_archives(self) -> None:
        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 200)
        restored = response.json()
        self.assertEqual(restored["job_id"], JOB_ID)
        self.assertEqual(restored["status"], "partial")
        self.assertTrue(restored["archived"])
        self.assertTrue(restored["restored_from_archive"])
        self.assertEqual(restored["configuration"], self.job["configuration"])
        self.assertEqual(restored["created_at"], self.job["created_at"])
        self.assertEqual(restored["finished_at"], self.job["finished_at"])
        self.assertEqual([item["id"] for item in restored["result"]["data"]], ["CA-valid", "CA-invalid"])
        self.assertEqual(restored["result"]["data"][1]["physics_result"]["reason_codes"], [
            "identical_propagation_parameters_for_distinct_catalog_ids",
        ])

        status_response = self.client.get(f"/api/conjunction-jobs/{JOB_ID}")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(len(status_response.json()["result"]["data"]), 2)

        csv_response = self.client.get(f"/api/conjunction-jobs/{JOB_ID}/reports/conjunctions.csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response.content, self.original_csv)
        self.assertEqual(self.json_path.read_bytes(), self.original_json)
        self.assertEqual(self.csv_path.read_bytes(), self.original_csv)

    def test_restore_preserves_the_historical_archive_and_serves_its_paired_csv(self) -> None:
        historical_id = "8fa7230ce99e4182afc2c1a8506130bf"
        archive_dir = Path(__file__).resolve().parents[1] / "exports"
        json_path = archive_dir / f"screening-job-{historical_id}.json"
        csv_path = archive_dir / f"trajectory-assessments-{historical_id}.csv"
        if not json_path.is_file() or not csv_path.is_file():
            self.skipTest("Historical archive pair is not present in this checkout.")
        original_json = json_path.read_bytes()
        original_csv = csv_path.read_bytes()

        with patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", archive_dir), patch.dict(main._screening_jobs, {}, clear=True):
            response = self.client.post(f"/api/conjunction-jobs/{historical_id}/restore")
            self.assertEqual(response.status_code, 200)
            restored = response.json()
            records = restored["result"]["data"]
            self.assertEqual(restored["status"], "partial")
            self.assertEqual(len(records), 52)
            self.assertEqual(sum(record["physics_result"].get("status") == "invalid" for record in records), 12)
            self.assertTrue(all(record.get("id") for record in records))

            csv_response = self.client.get(f"/api/conjunction-jobs/{historical_id}/reports/conjunctions.csv")
            self.assertEqual(csv_response.status_code, 200)
            self.assertEqual(csv_response.content, original_csv)

        self.assertEqual(json_path.read_bytes(), original_json)
        self.assertEqual(csv_path.read_bytes(), original_csv)

    def test_restore_backfills_research_pc_from_a_real_legacy_screening_event(self) -> None:
        historical_id = "2a50f67a597442279de1d5178468953d"
        archive_dir = Path(__file__).resolve().parents[1] / "exports"
        json_path = archive_dir / f"screening-job-{historical_id}.json"
        if not json_path.is_file():
            self.skipTest("Captured historical screening record is not present in this checkout.")
        original_json = json_path.read_bytes()

        with patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", archive_dir), patch.dict(main._screening_jobs, {}, clear=True):
            response = self.client.post(f"/api/conjunction-jobs/{historical_id}/restore")
            self.assertEqual(response.status_code, 200)
            restored = response.json()
            event = next(item for item in restored["result"]["data"] if item["id"] == "CA-0E45D17A7FD97444E98C")
            assessment = event["automatic_research_pc_assessment"]
            self.assertEqual(event["primary"]["id"], "33762")
            self.assertEqual(event["secondary"]["id"], "33776")
            self.assertEqual(event["physics_result"]["tca"]["value"], "2026-10-14T06:22:15.243382+00:00")
            self.assertEqual(assessment["status"], "prior_based_research_estimate")
            self.assertEqual(assessment["estimated_pc_scientific"], "< 1e-30")
            self.assertEqual(assessment["percentage_scientific"], "< 1e-28")
            self.assertEqual(assessment["sensitivity_status"], "available")
            self.assertEqual(assessment["risk_assessment"]["risk_score_pc_channel"], "research_pc")
            self.assertEqual(assessment["risk_assessment"]["physics_risk_class"], "Low")
            self.assertEqual(assessment["risk_assessment"]["final_risk_class"], "Low")
            self.assertEqual(assessment["risk_assessment"]["risk_score"], 0.0)
            self.assertEqual(event["collision_probability"]["pc"], None)
            self.assertEqual(event["collision_probability"]["reason_codes"], ["NO_COVARIANCE", "HBR_UNAVAILABLE"])
            self.assertGreaterEqual(event["ai_risk_assessment"]["score"], 0.0)
            self.assertLessEqual(event["ai_risk_assessment"]["score"], 1.0)
            self.assertIn(event["ai_risk_assessment"]["category"], {"Critical", "High", "Medium", "Low"})
            self.assertIsInstance(event["ai_risk_assessment"]["final_priority_rank"], int)

        self.assertEqual(json_path.read_bytes(), original_json)

    def test_restore_recomputes_research_pc_even_when_foster_has_a_current_risk_record(self) -> None:
        # A Foster risk assessment belongs to a different Pc channel and must
        # not suppress the archived event's research-Pc backfill.
        from tests.test_automatic_research_pc import _real_screened_event
        from app.services.probability_classification import classify_orion_physics_pc

        event = _real_screened_event()
        record = main.event_dicts([event])[0]
        record.pop("automatic_research_pc_assessment", None)
        record["collision_probability"]["risk_assessment"] = classify_orion_physics_pc(
            1e-4, "event_specific_foster_pc",
        )
        old_foster_risk = record["collision_probability"]["risk_assessment"].copy()
        old_foster_risk["risk_score_policy_version"] = "orion-physics-pc-risk-v1"
        record["collision_probability"]["risk_assessment"] = old_foster_risk

        archive = archived_job()
        archive["result"]["data"] = [record]
        archive["result"]["screening"]["close_approach_count"] = 1
        archive["result"]["screening"]["invalid_assessment_count"] = 0
        self.json_path.write_text(json.dumps(archive), encoding="utf-8")
        original_json = self.json_path.read_bytes()

        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 200)
        restored_event = response.json()["result"]["data"][0]
        self.assertEqual(restored_event["automatic_research_pc_assessment"]["status"], "prior_based_research_estimate")
        self.assertEqual(restored_event["automatic_research_pc_assessment"]["method_version"], "2.0.0")
        self.assertEqual(restored_event["collision_probability"]["risk_assessment"]["risk_score"], 80.0)
        self.assertEqual(self.json_path.read_bytes(), original_json)

    def test_missing_archive_returns_404_without_registry_changes(self) -> None:
        missing_id = "11111111111111111111111111111111"
        response = self.client.post(f"/api/conjunction-jobs/{missing_id}/restore")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(missing_id, main._screening_jobs)

    def test_malformed_archive_returns_409(self) -> None:
        self.json_path.write_bytes(b"{not-json")
        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(JOB_ID, main._screening_jobs)

    def test_mismatched_archive_id_returns_409(self) -> None:
        wrong_id = "22222222222222222222222222222222"
        self.json_path.write_text(json.dumps(archived_job(wrong_id)), encoding="utf-8")
        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(JOB_ID, main._screening_jobs)

    def test_invalid_archive_structure_returns_409(self) -> None:
        malformed = archived_job()
        malformed["result"]["data"][0]["physics_result"] = None
        self.json_path.write_text(json.dumps(malformed), encoding="utf-8")
        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(JOB_ID, main._screening_jobs)

    def test_path_traversal_id_is_rejected(self) -> None:
        response = self.client.post("/api/conjunction-jobs/%2E%2E%2Foutside/restore")
        self.assertIn(response.status_code, {404, 422})
        self.assertEqual(set(self.archive_dir.iterdir()), {self.json_path, self.csv_path})

    def test_restore_does_not_replace_an_existing_live_job_with_same_id(self) -> None:
        live = {"job_id": JOB_ID, "status": "complete", "result": {"data": [{"id": "CA-live"}]}}
        main._screening_jobs[JOB_ID] = live
        response = self.client.post(f"/api/conjunction-jobs/{JOB_ID}/restore")
        self.assertEqual(response.status_code, 409)
        self.assertIs(main._screening_jobs[JOB_ID], live)
        self.assertEqual(main._screening_jobs[JOB_ID]["result"]["data"][0]["id"], "CA-live")


if __name__ == "__main__":
    unittest.main()
