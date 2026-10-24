from __future__ import annotations

from datetime import datetime, timezone
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from app.services.spacetrack_cdm_provider import (
    EVENT_REQUEST_COOLDOWN_SECONDS,
    SpaceTrackCdmProvider,
)
from tests.test_cdm_ingestion import cdm_xml, physical_event


class SpaceTrackProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "throttle.json"
        self.now = [1_800_000_000.0]
        self.calls: list[httpx.Request] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def provider(self, handler):
        def transport(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)
        return SpaceTrackCdmProvider(
            transport=httpx.MockTransport(transport),
            state_path=self.state,
            clock=lambda: self.now[0],
        )

    def credentials(self):
        return patch.dict(os.environ, {"SPACE_TRACK_IDENTITY": "test@example.invalid", "SPACE_TRACK_PASSWORD": "mock-secret"})

    def test_retrieves_summary_then_full_cdm_with_authenticated_session(self) -> None:
        xml = cdm_xml()
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ajaxauth/login"):
                return httpx.Response(200, headers={"set-cookie": "chocolatechip=session; Path=/; Secure"})
            if "/class/cdm_public/" in request.url.path:
                return httpx.Response(200, json=[{
                    "CDM_ID": "12345", "SAT_1_ID": "A", "SAT_2_ID": "B", "TCA": "2025-01-01T00:00:00Z",
                }])
            return httpx.Response(200, content=xml.encode(), headers={"content-type": "application/xml"})
        with self.credentials():
            result = self.provider(handler).retrieve_for_event(physical_event())
        self.assertEqual(result.status, "retrieved")
        self.assertEqual(result.cdm_id, "12345")
        self.assertEqual(result.cdm_text, xml)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("/class/cdm_public/", str(self.calls[1].url))
        self.assertIn("/class/cdm/CONSTELLATION/ALL/CDM_ID/12345/", str(self.calls[2].url))

    def test_missing_credentials_fails_without_network_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = self.provider(lambda request: self.fail("network must not be called")).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_CREDENTIALS_NOT_CONFIGURED")
        self.assertEqual(self.calls, [])

    def test_authentication_failure_is_specific(self) -> None:
        with self.credentials():
            result = self.provider(lambda request: httpx.Response(401)).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_AUTHENTICATION_FAILED")
        self.assertEqual(len(self.calls), 1)

    def test_insufficient_full_cdm_permission_is_specific(self) -> None:
        def handler(request):
            if request.url.path.endswith("/ajaxauth/login"):
                return httpx.Response(200, headers={"set-cookie": "chocolatechip=session; Path=/; Secure"})
            if "/class/cdm_public/" in request.url.path:
                return httpx.Response(200, json=[{"CDM_ID": "12345", "SAT_1_ID": "A", "SAT_2_ID": "B", "TCA": "2025-01-01T00:00:00Z"}])
            return httpx.Response(403, text="Forbidden")
        with self.credentials():
            result = self.provider(handler).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_CDM_ACCESS_REQUIRED")

    def test_no_matching_pair_and_tca_returns_no_match(self) -> None:
        def handler(request):
            if request.url.path.endswith("/ajaxauth/login"):
                return httpx.Response(200, headers={"set-cookie": "chocolatechip=session; Path=/; Secure"})
            return httpx.Response(200, json=[{"CDM_ID": "12345", "SAT_1_ID": "A", "SAT_2_ID": "X", "TCA": "2025-01-01T00:00:00Z"}])
        with self.credentials():
            result = self.provider(handler).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_CDM_NOT_FOUND")
        self.assertEqual(len(self.calls), 2)

    def test_reverse_id_order_matches_but_mismatched_tca_does_not(self) -> None:
        from app.services.spacetrack_cdm_provider import _matching_summaries
        event_tca = datetime(2025, 1, 1, tzinfo=timezone.utc)
        reverse = {"CDM_ID": "1", "SAT_1_ID": "B", "SAT_2_ID": "A", "TCA": "2025-01-01T00:00:30Z"}
        late = {"CDM_ID": "2", "SAT_1_ID": "A", "SAT_2_ID": "B", "TCA": "2025-01-01T00:02:00Z"}
        self.assertEqual(_matching_summaries([late, reverse], "A", "B", event_tca), [reverse])

    def test_tca_tolerance_is_inclusive_at_sixty_seconds(self) -> None:
        from app.services.spacetrack_cdm_provider import _matching_summaries
        event_tca = datetime(2025, 1, 1, tzinfo=timezone.utc)
        candidates = [
            {"CDM_ID": "1", "SAT_1_ID": "A", "SAT_2_ID": "B", "TCA": "2024-12-31T23:59:00Z"},
            {"CDM_ID": "2", "SAT_1_ID": "B", "SAT_2_ID": "A", "TCA": "2025-01-01T00:01:00Z"},
            {"CDM_ID": "3", "SAT_1_ID": "A", "SAT_2_ID": "B", "TCA": "2025-01-01T00:01:00.001Z"},
        ]
        matched = _matching_summaries(candidates, "A", "B", event_tca)
        self.assertEqual([candidate["CDM_ID"] for candidate in matched], ["1", "2"])

    def test_authentication_failure_still_starts_event_cooldown(self) -> None:
        with self.credentials():
            first = self.provider(lambda request: httpx.Response(401)).retrieve_for_event(physical_event())
            second = self.provider(lambda request: self.fail("cooldown must prevent a second request")).retrieve_for_event(physical_event())
        self.assertEqual(first.reason_code, "SPACETRACK_AUTHENTICATION_FAILED")
        self.assertEqual(second.reason_code, "SPACETRACK_EVENT_COOLDOWN")
        self.assertEqual(len(self.calls), 1)

    def test_invalid_summary_and_timeout_fail_safely(self) -> None:
        def bad_summary(request):
            if request.url.path.endswith("/ajaxauth/login"):
                return httpx.Response(200, headers={"set-cookie": "chocolatechip=session; Path=/; Secure"})
            return httpx.Response(200, json={"unexpected": True})
        with self.credentials():
            invalid = self.provider(bad_summary).retrieve_for_event(physical_event())
        self.assertEqual(invalid.reason_code, "SPACETRACK_SUMMARY_INVALID")
        self.state.unlink()
        def timeout(request):
            raise httpx.ReadTimeout("mock timeout", request=request)
        with self.credentials():
            timed_out = self.provider(timeout).retrieve_for_event(physical_event())
        self.assertEqual(timed_out.reason_code, "SPACETRACK_REQUEST_TIMEOUT")

    def test_cooldown_persists_across_provider_instances(self) -> None:
        def handler(request):
            if request.url.path.endswith("/ajaxauth/login"):
                return httpx.Response(200, headers={"set-cookie": "chocolatechip=session; Path=/; Secure"})
            return httpx.Response(200, json=[])
        with self.credentials():
            first = self.provider(handler).retrieve_for_event(physical_event())
            second = self.provider(handler).retrieve_for_event(physical_event())
        self.assertEqual(first.reason_code, "SPACETRACK_CDM_NOT_FOUND")
        self.assertEqual(second.reason_code, "SPACETRACK_EVENT_COOLDOWN")
        self.assertLess(EVENT_REQUEST_COOLDOWN_SECONDS, 86400)
        self.assertEqual(len(self.calls), 2)

    def test_rate_limit_response_is_specific(self) -> None:
        with self.credentials():
            result = self.provider(lambda request: httpx.Response(429)).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_RATE_LIMITED")

    def test_global_request_budget_blocks_before_network(self) -> None:
        from app.services.spacetrack_cdm_provider import GLOBAL_REQUESTS_PER_HOUR
        self.state.write_text(json.dumps({
            "version": 1, "events": {},
            "requests": [self.now[0] - 1] * (GLOBAL_REQUESTS_PER_HOUR - 2),
        }), encoding="utf-8")
        with self.credentials():
            result = self.provider(lambda request: self.fail("rate-limited request must not reach the network")).retrieve_for_event(physical_event())
        self.assertEqual(result.reason_code, "SPACETRACK_GLOBAL_COOLDOWN")
        self.assertEqual(self.calls, [])

    def test_retrieval_is_not_mounted_in_the_application_api(self) -> None:
        from fastapi.testclient import TestClient
        from app import main
        paths = {route.path for route in main.app.routes}
        self.assertNotIn("/api/conjunction-jobs/{job_id}/events/{event_id}/cdm/space-track", paths)
        self.assertFalse(hasattr(main, "spacetrack_cdm_provider"))


if __name__ == "__main__":
    unittest.main()
