from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app import main
from app.services.tle_provider import TleRecord


class ScreeningSingleFlightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with main._screening_registry_lock:
            main._screening_inflight.clear()
            main._screening_cache.clear()

    async def test_identical_full_inputs_share_work_and_short_ttl_result(self):
        record = TleRecord("test", "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753", "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667", "test", "live", "catalog-generation-1")

        class Provider:
            async def get_catalog_with_state(self, limit):
                return [record], {"status": "live", "last_success_at": "catalog-generation-1"}

        calls = 0

        async def snapshot_builder(**kwargs):
            await asyncio.sleep(0)
            return SimpleNamespace(
                objects=[],
                unavailable_objects=[],
                source_summary=SimpleNamespace(status="live"),
            )

        async def fake_threadpool(func):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return SimpleNamespace(events=[], summary={"status": "valid", "performance": {}})

        start = datetime(2026, 10, 10, tzinfo=timezone.utc)
        with patch.object(main, "tle_provider", Provider()), \
             patch.object(main, "build_snapshot", side_effect=snapshot_builder), \
             patch.object(main, "run_in_threadpool", side_effect=fake_threadpool):
            first, second = await asyncio.gather(
                main.build_trajectory_context(start_utc=start, horizon_hours=24),
                main.build_trajectory_context(start_utc=start, horizon_hours=24),
            )
            self.assertEqual(calls, 1)
            self.assertEqual(first[1].summary["completion_status"], "complete")
            self.assertEqual(second[1].summary["completion_status"], "complete")
            await main.build_trajectory_context(start_utc=start, horizon_hours=24)
            self.assertEqual(calls, 1)
            await main.build_trajectory_context(start_utc=start, horizon_hours=12)
            self.assertEqual(calls, 2)
            await main.build_trajectory_context(start_utc=start, horizon_hours=24, screening_threshold_km=10)
            self.assertEqual(calls, 3)
            await main.build_trajectory_context(start_utc=start.replace(minute=1), horizon_hours=24)
            self.assertEqual(calls, 4)
            newer_record = TleRecord(record.name, record.line1, record.line2, record.source_group, record.source_type, "catalog-generation-2")

            class NewGenerationProvider:
                async def get_catalog_with_state(self, limit):
                    return [newer_record], {"status": "live", "last_success_at": "catalog-generation-2"}

            with patch.object(main, "tle_provider", NewGenerationProvider()):
                await main.build_trajectory_context(start_utc=start, horizon_hours=24)
            self.assertEqual(calls, 5)


if __name__ == "__main__":
    unittest.main()
