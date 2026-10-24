from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.models import SourceSummary
from app.services.tle_provider import TleProvider


class LiveSourceStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_live_refresh_is_explicit_when_fallback_is_returned(self) -> None:
        provider = TleProvider()
        provider._last_error_code = "upstream_network_error"
        with patch.object(provider, "_fetch_live", new=AsyncMock(return_value=[])):
            records, state = await provider.get_catalog_with_state(limit=25)

        self.assertTrue(records)
        self.assertTrue(all(record.source_type == "fallback" for record in records))
        self.assertEqual(state["status"], "fallback")
        self.assertEqual(state["source"], "Bundled fallback TLE sample")
        self.assertEqual(state["last_error_code"], "upstream_network_error")
        self.assertIsNotNone(state["last_attempt_at"])
        self.assertIsNone(state["last_success_at"])

    def test_screening_response_preserves_the_acquisition_failure_reason(self) -> None:
        source_state = {
            "status": "fallback",
            "source": "Bundled fallback TLE sample",
            "last_attempt_at": "2026-10-18T16:42:48+00:00",
            "last_success_at": None,
            "last_error_code": "upstream_network_error",
        }
        snapshot = SimpleNamespace(
            source_state=source_state,
            source_summary=SourceSummary(
                status="fallback", counts_by_source_type={"fallback": 7}, object_count=7, unavailable_count=0,
            ),
            stats=SimpleNamespace(provenance=SimpleNamespace(input_hash="fallback-input-hash")),
            tle_epoch=None,
        )
        run = SimpleNamespace(
            events=[],
            summary={
                "status": "unavailable", "completion_status": "failed", "performance": {},
                "method": "test", "method_version": "1",
            },
        )
        with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(snapshot, run))), \
             patch.object(main, "model_status", return_value={"status": "unavailable"}), \
             TestClient(main.app) as client:
            response = client.get("/api/conjunctions?limit=25")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source_summary"]["status"], "fallback")
        self.assertEqual(payload["source_state"]["source"], "Bundled fallback TLE sample")
        self.assertEqual(payload["source_state"]["last_error_code"], "upstream_network_error")
        self.assertEqual(payload["source_state"]["last_attempt_at"], source_state["last_attempt_at"])
        self.assertEqual(payload["provenance"]["source_state"], payload["source_state"])

    async def test_fallback_catalog_is_never_passed_to_physical_screening(self) -> None:
        snapshot = SimpleNamespace(
            source_summary=SourceSummary(
                status="fallback", counts_by_source_type={"fallback": 7}, object_count=7, unavailable_count=0,
            ),
            objects=[], unavailable_objects=[],
        )
        with patch.object(main, "build_snapshot", new=AsyncMock(return_value=snapshot)), \
             patch.object(main, "screen_tle_records") as screen:
            _, run = await main._build_trajectory_context_uncached(
                "fallback-live-source-test",
                [],
                {"status": "fallback", "source": "Bundled fallback TLE sample", "last_error_code": "upstream_network_error"},
                25,
                datetime(2026, 10, 18, tzinfo=timezone.utc),
                24,
                60,
                25,
            )

        screen.assert_not_called()
        self.assertEqual(run.summary["completion_status"], "failed")
        self.assertEqual(run.summary["reason_code"], "FALLBACK_CATALOG_NOT_SCREENED")

