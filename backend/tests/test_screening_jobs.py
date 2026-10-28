from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class ScreeningJobLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main._screening_jobs.clear()

    async def test_archived_job_loader_finds_demo_snapshot_directory(self):
        job_id = "0123456789abcdef0123456789abcdef"
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            demo = archive / "demo"
            demo.mkdir()
            snapshot = {"job_id": job_id, "status": "complete"}
            (demo / f"screening-job-{job_id}.json").write_text(json.dumps(snapshot), encoding="utf-8")
            with patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", archive), patch.object(
                main, "_validate_archived_screening_job", side_effect=lambda _job_id, value: value
            ):
                loaded = main._load_archived_screening_job(job_id)
        self.assertEqual(loaded["job_id"], job_id)

    async def test_committed_demo_snapshot_is_a_restorable_finished_job(self):
        job_id = "fcec3945251c45f38f215485ecbb5605"
        archived = main._load_archived_screening_job(job_id)
        self.assertEqual(archived["status"], "partial")
        self.assertEqual(archived["result"]["completion_status"], "partial")
        self.assertEqual(len(archived["result"]["data"]), 109)

    async def test_real_archived_screening_job_produces_common_epoch_globe_positions(self):
        job_id = "c207f19cb37a4551b5f9e276ba0d6fec"
        job = json.loads((Path(main.__file__).resolve().parent.parent / "exports" / f"screening-job-{job_id}.json").read_text(encoding="utf-8"))
        smart_filter = json.loads((Path(main.__file__).resolve().parent.parent / "exports" / f"smart-filter-{job_id}.json").read_text(encoding="utf-8"))

        globe = main._smart_filter_globe_positions(job, smart_filter)

        self.assertEqual(globe["frame"], "TEME")
        self.assertEqual(len(globe["before_objects"]), 162)
        self.assertEqual(len(globe["after_objects"]), 15)
        self.assertEqual(globe["failed_object_ids"], [])
        self.assertTrue(all(
            obj["provenance"]["reference_frame"] == "TEME"
            and obj["provenance"]["propagation_epoch"] == globe["propagation_epoch"]
            and len(obj["position"]) == 3
            for obj in globe["before_objects"] + globe["after_objects"]
        ))

    async def test_result_status_distinguishes_invalid_records_from_valid_events(self):
        valid_provenance = SimpleNamespace(validity_status="valid", is_synthetic=False, source_type="live")
        invalid = SimpleNamespace(result_kind="physics_assessment", provenance=valid_provenance,
                                  physics_result=SimpleNamespace(status="invalid"))
        boundary = SimpleNamespace(result_kind="physics_assessment", provenance=valid_provenance,
                                   physics_result=SimpleNamespace(status="boundary"))
        valid = SimpleNamespace(result_kind="physics_assessment", provenance=valid_provenance,
                                physics_result=SimpleNamespace(status="valid"))
        proxy = SimpleNamespace(result_kind="screening_proxy", provenance=valid_provenance,
                                physics_result=SimpleNamespace(status="valid"))
        synthetic = SimpleNamespace(result_kind="physics_assessment",
                                    provenance=SimpleNamespace(validity_status="valid", is_synthetic=True, source_type="synthetic"),
                                    physics_result=SimpleNamespace(status="valid"))
        unverified = SimpleNamespace(result_kind="physics_assessment",
                                     provenance=SimpleNamespace(validity_status="unverified", is_synthetic=False, source_type="live"),
                                     physics_result=SimpleNamespace(status="valid"))
        self.assertEqual(main._screening_result_status("valid", [invalid], False), "valid_empty")
        self.assertEqual(main._screening_result_status("valid", [boundary], False), "valid_empty")
        self.assertEqual(main._screening_result_status("valid", [proxy, synthetic, unverified], False), "valid_empty")
        self.assertEqual(main._screening_result_status("valid", [invalid, valid], False), "valid_non_empty")
        self.assertEqual(main._screening_result_status("valid", [valid], True), "partial")
        self.assertEqual(main._screening_result_status("unavailable", [valid], False), "unavailable")

    async def test_job_reports_queued_running_then_complete_empty(self):
        started = asyncio.Event()
        finish = asyncio.Event()
        calls = 0

        async def delayed_screen(**kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            return {
                "success": True,
                "result_kind": "physics_assessment",
                "result_status": "valid_empty",
                "completion_status": "complete",
                "data": [],
                "message": "Screening completed with no qualifying events.",
            }

        with patch.object(main, "conjunctions", side_effect=delayed_screen):
            accepted = await main.create_conjunction_job(
                limit=120, horizon_hours=24, sample_step_seconds=60,
                screening_threshold_km=25, start_utc=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
            job_id = accepted["job_id"]
            self.assertEqual(accepted["status"], "queued")
            self.assertEqual((await main.get_conjunction_job(job_id))["status"], "queued")
            await started.wait()
            running = await main.get_conjunction_job(job_id)
            self.assertEqual(running["status"], "running")
            self.assertIsNone(running["progress"]["percent"])
            self.assertEqual((await main.get_conjunction_job(job_id))["status"], "running")
            finish.set()
            await main._screening_jobs[job_id]["task"]
            complete = await main.get_conjunction_job(job_id)
            self.assertEqual(complete["completion_status"], "complete")
            self.assertEqual(complete["result"]["result_status"], "valid_empty")
            self.assertEqual(complete["result"]["data"], [])
            self.assertEqual(calls, 1)

    async def test_unhandled_execution_failure_is_failed_not_valid_empty(self):
        async def broken_screen(**kwargs):
            raise RuntimeError("screen failed")

        with patch.object(main, "conjunctions", side_effect=broken_screen):
            accepted = await main.create_conjunction_job(
                limit=120, horizon_hours=24, sample_step_seconds=60,
                screening_threshold_km=25, start_utc=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
            job_id = accepted["job_id"]
            await main._screening_jobs[job_id]["task"]
            failed = await main.get_conjunction_job(job_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["result"]["completion_status"], "failed")
            self.assertNotEqual(failed["result"]["result_status"], "valid_empty")
            self.assertEqual(failed["result"]["reason_code"], "SCREENING_EXECUTION_FAILED")
            self.assertNotIn("screen failed", failed["result"]["message"])
            self.assertEqual(failed["error_code"], "SCREENING_EXECUTION_FAILED")
            self.assertIsNotNone(failed["finished_at"])

    def test_http_job_status_preserves_partial_and_failed_results(self):
        for completion, result_status in (("partial", "partial"), ("failed", "error")):
            with self.subTest(completion=completion):
                main._screening_jobs.clear()

                async def fake_screen(**kwargs):
                    return {
                        "success": completion != "failed",
                        "result_kind": "physics_assessment",
                        "result_status": result_status,
                        "completion_status": completion,
                        "data": [],
                        "message": f"{completion} result",
                    }

                with patch.object(main, "conjunctions", side_effect=fake_screen):
                    client = TestClient(main.app)
                    response = client.post(
                        "/api/conjunction-jobs?limit=37&start_utc=2026-10-10T00%3A00%3A00Z&horizon_hours=24"
                        "&sample_step_seconds=60&screening_threshold_km=25"
                    )
                    self.assertEqual(response.status_code, 202)
                    job_id = response.json()["job_id"]
                    accepted_configuration = response.json()["configuration"]
                    self.assertEqual(accepted_configuration["requested_limit"], 37)
                    self.assertEqual(accepted_configuration["effective_catalog_limit"], 37)
                    final = None
                    for _ in range(20):
                        final = client.get(f"/api/conjunction-jobs/{job_id}")
                        if final.json()["status"] in {"complete", "partial", "failed"}:
                            break
                    self.assertEqual(final.status_code, 200)
                    self.assertEqual(final.json()["status"], completion)
                    self.assertEqual(final.json()["result"]["result_status"], result_status)
                    self.assertEqual(final.json()["configuration"]["requested_horizon_hours"], 24)

    async def test_job_forwards_requested_catalog_limit_without_replacing_it(self):
        received = {}

        async def capture_screen(**kwargs):
            received.update(kwargs)
            return {
                "success": True, "result_kind": "physics_assessment",
                "result_status": "valid_empty", "completion_status": "complete",
                "data": [], "message": "complete fixture",
            }

        with patch.object(main, "conjunctions", side_effect=capture_screen):
            accepted = await main.create_conjunction_job(
                limit=37, horizon_hours=1, sample_step_seconds=60,
                screening_threshold_km=25, start_utc=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
            await main._screening_jobs[accepted["job_id"]]["task"]
            self.assertEqual(received["limit"], 37)
            self.assertEqual(accepted["configuration"]["requested_limit"], 37)
            self.assertEqual(accepted["configuration"]["effective_catalog_limit"], 37)

    def test_unknown_job_returns_404(self):
        client = TestClient(main.app)
        self.assertEqual(client.get("/api/conjunction-jobs/missing").status_code, 404)

    def test_assessment_pages_retain_all_rows_and_diagnostics(self):
        job_id = "a" * 32
        records = [
            {"id": f"EV-{index:03d}", "physics_result": {
                "status": "invalid" if index % 5 == 0 else "valid",
                "reason_codes": ["NO_COVARIANCE", f"DIAGNOSTIC_{index}"] if index % 5 == 0 else [],
            }}
            for index in range(245)
        ]
        main._screening_jobs[job_id] = {
            "job_id": job_id, "status": "complete", "result": {
                "result_status": "valid_non_empty", "completion_status": "complete",
                "screening": {"assessment_record_count": len(records)}, "data": records,
            },
        }
        client = TestClient(main.app)
        status = client.get(f"/api/conjunction-jobs/{job_id}").json()
        self.assertEqual(len(status["result"]["data"]), 120)
        self.assertEqual(status["result"]["assessment_pagination"]["total_records"], 245)
        self.assertTrue(status["result"]["assessment_pagination"]["has_more"])
        self.assertEqual(status["result"]["screening"]["assessment_record_count"], 245)
        self.assertEqual(status["result"]["screening"]["returned_assessment_record_count"], 120)
        self.assertTrue(status["result"]["screening"]["response_page_partial"])
        pages = [client.get(f"/api/conjunction-jobs/{job_id}/assessments?page={page}&page_size=120").json()
                 for page in (1, 2, 3)]
        self.assertEqual([page["returned_records"] for page in pages], [120, 120, 5])
        self.assertFalse(pages[-1]["has_more"])
        self.assertEqual(pages[0], client.get(f"/api/conjunction-jobs/{job_id}/assessments?page=1&page_size=120").json())
        combined = [record for page in pages for record in page["data"]]
        self.assertEqual([record["id"] for record in combined], [record["id"] for record in records])
        self.assertEqual(len({record["id"] for record in combined}), 245)
        self.assertEqual(combined[5]["physics_result"]["reason_codes"], ["NO_COVARIANCE", "DIAGNOSTIC_5"])
        self.assertEqual(client.get(f"/api/conjunction-jobs/{job_id}/assessments?page=4&page_size=120").json()["data"], [])


if __name__ == "__main__":
    unittest.main()
