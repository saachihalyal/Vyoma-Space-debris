from __future__ import annotations

import re
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from tests.test_automatic_research_pc import _real_screened_event


JOB_ID = "9876543210abcdef9876543210abcdef"


class ResearchPcScenarioApiTests(unittest.TestCase):
    def test_covariance_policies_are_selectable_and_api_strings_stay_bounded(self) -> None:
        event = _real_screened_event()
        record = main.event_dicts([event])[0]
        main._screening_jobs[JOB_ID] = {"job_id": JOB_ID, "status": "complete", "result": {"data": [record]}}
        try:
            with TestClient(main.app) as client:
                outputs = {}
                for policy in ("esa_population_prior", "tle_age_baseline", "tle_age_baseline_2x"):
                    response = client.post(
                        f"/api/conjunction-jobs/{JOB_ID}/events/{event.id}/research-pc-scenario",
                        json={"covariance_policy": policy},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    payload = response.json()
                    self.assertEqual(payload["data"]["covariance_policy_id"], policy)
                    self.assertEqual(payload["data"]["method_version"], "2.0.0")
                    outputs[policy] = payload
                    exponents = [int(match) for match in re.findall(
                        r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d*)?|\.\d+)[eE]([+-]?\d+)", response.text,
                    )]
                    self.assertTrue(all(abs(exponent) <= 300 for exponent in exponents), exponents)
                self.assertNotEqual(
                    outputs["esa_population_prior"]["data"]["log10_pc"],
                    outputs["tle_age_baseline"]["data"]["log10_pc"],
                )
                invalid = client.post(
                    f"/api/conjunction-jobs/{JOB_ID}/events/{event.id}/research-pc-scenario",
                    json={"covariance_policy": "unknown"},
                )
                self.assertEqual(invalid.status_code, 422)
        finally:
            main._screening_jobs.pop(JOB_ID, None)

    def test_archived_job_what_if_is_readable_after_process_registry_is_empty(self) -> None:
        event = _real_screened_event()
        source_path = Path(__file__).resolve().parents[1] / "exports" / "screening-job-2a50f67a597442279de1d5178468953d.json"
        archive = json.loads(source_path.read_text(encoding="utf-8"))
        archive["job_id"] = JOB_ID
        record = next(item for item in archive["result"]["data"]
            if {str(item.get("primary", {}).get("id")), str(item.get("secondary", {}).get("id"))} == {"33762", "33776"})
        record["id"] = event.id
        record["physics_result"]["event_id"] = event.id
        record["screening_job_id"] = JOB_ID
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"screening-job-{JOB_ID}.json"
            archived_text = json.dumps(archive)
            path.write_text(archived_text, encoding="utf-8")
            with patch.object(main, "SCREENING_EXPORT_ARCHIVE_DIR", Path(temp_dir)):
                self.assertNotIn(JOB_ID, main._screening_jobs)
                with TestClient(main.app) as client:
                    response = client.post(
                        f"/api/conjunction-jobs/{JOB_ID}/events/{event.id}/research-pc-scenario",
                        json={"covariance_scale": 2.0},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertTrue(payload["success"])
                self.assertEqual(payload["data"]["status"], "prior_based_research_estimate")
                self.assertEqual(payload["data"]["provenance"]["scenario_covariance_scale"], 2.0)
                persisted = json.loads(path.read_text(encoding="utf-8"))
                stored = next(item for item in persisted["result"]["data"] if item["id"] == event.id)
                self.assertEqual(stored, record)
                self.assertEqual(path.read_text(encoding="utf-8"), archived_text, "what-if must not mutate the archived job")


if __name__ == "__main__":
    unittest.main()
