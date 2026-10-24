from __future__ import annotations

import re
import unittest
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


if __name__ == "__main__":
    unittest.main()
