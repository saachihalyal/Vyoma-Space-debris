from __future__ import annotations

import math
import csv
import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from sgp4.api import Satrec, WGS72

from app import main
from app.models import ComparisonResult, MLResult, MLRiskPrediction, OrbitalAnomalyResult
from app.services import trajectory_screening
from app.services.orbit import propagate_records
from app.services.reports import conjunctions_csv, event_report_pdf
from app.services import tle_provider
from app.services.tle_provider import FALLBACK_TLES, TleProvider, _valid_tle_record, parse_omm_json, parse_tle_text
from app.services.trajectory_screening import StateVector, _prepare_tracks, _same_propagation_parameters, minimize_relative_distance, screen_tle_records


VANGUARD_LINES = FALLBACK_TLES.splitlines()[:3]
TEST_START = datetime(2000, 6, 27, 18, 50, 19, 733568, tzinfo=timezone.utc)
ARCHIVED_ISS_POISK_TLES = """ISS (ZARYA)
1 25544U 98067A   26285.85396186  .00006018  00000+0  11791-3 0  9995
2 25544  51.6314  77.7958 0006705 255.2292 104.7953 15.48843879589996
POISK
1 36086U 09060A   26285.85396186  .00006018  00000+0  11791-3 0  9993
2 36086  51.6314  77.7958 0006705 255.2292 104.7953 15.48843879586356"""


class _TleHttpResponse:
    def __init__(self, text: str):
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")


class _TleHttpClient:
    """Route only the captured station TLEs through the provider's HTTP boundary."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        body = ARCHIVED_ISS_POISK_TLES if "GROUP=STATIONS" in url.upper() else ""
        return _TleHttpResponse(body)


class TcaReferenceTests(unittest.TestCase):
    def test_distinct_live_omm_records_survive_cache_and_screening_preparation(self) -> None:
        common = {
            "CENTER_NAME": "EARTH", "REF_FRAME": "TEME", "TIME_SYSTEM": "UTC",
            "MEAN_ELEMENT_THEORY": "SGP4", "EPOCH": "2026-10-16T18:57:11.727648",
            "MEAN_MOTION": "15.48899044", "ECCENTRICITY": "0.0006748",
            "INCLINATION": "51.6326", "RA_OF_ASC_NODE": "58.3278",
            "ARG_OF_PERICENTER": "271.9059", "MEAN_ANOMALY": "88.1156",
            "EPHEMERIS_TYPE": "0", "CLASSIFICATION_TYPE": "U", "ELEMENT_SET_NO": "999",
            "BSTAR": "0.00015012", "MEAN_MOTION_DOT": "7.803e-5", "MEAN_MOTION_DDOT": "0",
        }
        iss = {**common, "OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A", "NORAD_CAT_ID": "25544", "REV_AT_EPOCH": "59060"}
        poisk = {**common, "OBJECT_NAME": "POISK", "OBJECT_ID": "2009-060A", "NORAD_CAT_ID": "36086", "REV_AT_EPOCH": "58652"}

        class OmmClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url):
                return _TleHttpResponse(json.dumps([iss, poisk]) if "GROUP=STATIONS" in url.upper() else "[]")

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "celestrak-cache.json"
            with patch.object(tle_provider.httpx, "AsyncClient", OmmClient):
                fetched, _ = asyncio.run(TleProvider(retry_attempts=1, retry_state_path=cache_path).get_catalog_with_state(20))
            # Re-open persisted live cache to cover the production reload path.
            restored_provider = TleProvider(retry_attempts=1, retry_state_path=cache_path)
            restored = restored_provider._selected(20)

        self.assertEqual([record.catalog_id for record in fetched], ["25544", "36086"])
        self.assertEqual([record.catalog_id for record in restored], ["25544", "36086"])
        self.assertEqual([record.omm_fields["OBJECT_NAME"] for record in restored], ["ISS (ZARYA)", "POISK"])
        self.assertEqual([record.omm_fields["OBJECT_ID"] for record in restored], ["1998-067A", "2009-060A"])
        self.assertEqual([record.omm_fields["NORAD_CAT_ID"] for record in restored], ["25544", "36086"])
        self.assertNotEqual(restored[0].input_hash, restored[1].input_hash)
        self.assertEqual(
            [{key: record.omm_fields[key] for key in common} for record in restored],
            [{key: record[key] for key in common} for record in (iss, poisk)],
        )

        start = datetime(2026, 10, 16, 18, 57, 11, 727648, tzinfo=timezone.utc)
        objects, _, unavailable = propagate_records(restored, limit=20, now=start)
        tracks, rejected = _prepare_tracks(restored, objects, unavailable)
        self.assertEqual(rejected, [])
        self.assertEqual([track.record.catalog_id for track in tracks], ["25544", "36086"])
        self.assertEqual([track.satellite.satnum for track in tracks], [25544, 36086])
        self.assertTrue(_same_propagation_parameters(tracks[0].satellite, tracks[1].satellite))

        run = screen_tle_records(
            restored, objects, start_utc=start, horizon_hours=1 / 60,
            sample_step_seconds=30, screening_threshold_km=1.0,
            unavailable_objects=unavailable,
        )
        self.assertEqual(len(run.events), 1)
        self.assertEqual(run.events[0].physics_result.status, "invalid")
        self.assertEqual(run.events[0].physics_result.reason_codes, ["identical_propagation_parameters_for_distinct_catalog_ids"])

    def test_omm_record_is_accepted_by_stage2a_sgp4_track_preparation(self) -> None:
        fields = {
            "OBJECT_NAME": "NEW OBJECT", "OBJECT_ID": "2026-123A", "CENTER_NAME": "EARTH",
            "REF_FRAME": "TEME", "TIME_SYSTEM": "UTC", "MEAN_ELEMENT_THEORY": "SGP4",
            "EPOCH": "2026-10-18T12:34:56.123456", "MEAN_MOTION": "15.2", "ECCENTRICITY": "0.001",
            "INCLINATION": "51.6", "RA_OF_ASC_NODE": "120.0", "ARG_OF_PERICENTER": "40.0",
            "MEAN_ANOMALY": "210.0", "EPHEMERIS_TYPE": "0", "CLASSIFICATION_TYPE": "U",
            "NORAD_CAT_ID": "100123", "ELEMENT_SET_NO": "1", "REV_AT_EPOCH": "10",
            "BSTAR": "0.0001", "MEAN_MOTION_DOT": "0.00001", "MEAN_MOTION_DDOT": "0.0",
        }
        record = parse_omm_json(json.dumps([fields]), "stations")[0]
        objects, _, unavailable = propagate_records(
            [record], limit=1,
            now=datetime(2026, 10, 18, 12, 34, 56, 123456, tzinfo=timezone.utc),
        )

        tracks, rejected = _prepare_tracks([record], objects, unavailable)

        self.assertEqual(rejected, [])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].obj.id, "100123")
        self.assertEqual(tracks[0].satellite.satnum, 100123)

    def test_identical_trajectories_have_zero_separation_but_no_unique_tca(self) -> None:
        primary = lambda t: StateVector((7000.0, 1.0, -2.0), (0.0, 7.5, 0.0))
        secondary = lambda t: StateVector((7000.0, 1.0, -2.0), (0.0, 7.5, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=30.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=60.0,
        )
        # A constant zero-distance interval has no unique closest-approach epoch.
        # Preserve the known miss distance while withholding an arbitrary TCA.
        self.assertEqual(solution.status, "invalid")
        self.assertEqual(solution.reason_code, "non_unique_tca_flat_distance")
        self.assertIsNotNone(solution.miss_distance_km)
        self.assertAlmostEqual(solution.miss_distance_km, 0.0, delta=1e-12)
        self.assertIsNone(solution.offset_seconds)

    def test_linear_relative_motion_matches_analytic_tca_and_miss_distance(self) -> None:
        # r_rel(t) = (5, 2(t - 123.4), 3) km; v_rel = (0, 2, 0) km/s.
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 7.0, 0.0))
        secondary = lambda t: StateVector((7005.0, -246.8 + 2.0 * t, 3.0), (0.0, 9.0, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=100.0,
            upper_offset_seconds=140.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=300.0,
        )
        self.assertEqual(solution.status, "valid")
        self.assertAlmostEqual(solution.offset_seconds or -1.0, 123.4, delta=0.01)
        self.assertAlmostEqual(solution.miss_distance_km or -1.0, math.sqrt(34.0), delta=1e-7)
        self.assertAlmostEqual(solution.relative_position_km[0], 5.0, delta=1e-7)
        self.assertAlmostEqual(solution.relative_position_km[1], 0.0, delta=0.01)
        self.assertAlmostEqual(solution.relative_position_km[2], 3.0, delta=1e-7)
        self.assertEqual(solution.relative_velocity_km_s, (0.0, 2.0, 0.0))

    def test_bounded_subdivision_refines_both_basins_and_selects_lower_minimum(self) -> None:
        def distance(t):
            first_dip = 2.0 * math.exp(-((t - 0.38) / 0.07) ** 2)
            lower_dip = 3.9 * math.exp(-((t - 0.80) / 0.04) ** 2)
            return 4.0 - first_dip - lower_dip

        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector((7000.0 + distance(t), 0.0, 0.0), (0.0, 0.0, 0.0))
        solution = minimize_relative_distance(
            primary, secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=1.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=1.0,
        )
        self.assertEqual(solution.status, "valid")
        self.assertAlmostEqual(solution.offset_seconds, 0.80, delta=0.01)
        self.assertAlmostEqual(solution.miss_distance_km, 0.10, delta=0.02)

    def test_refinement_returns_unresolved_when_bounded_basin_cap_is_exceeded(self) -> None:
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector(
            (7001.0 + math.cos(2.0 * math.pi * 8.0 * t), 0.0, 0.0),
            (0.0, 0.0, 0.0),
        )
        solution = minimize_relative_distance(
            primary, secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=1.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=1.0,
        )
        self.assertEqual(solution.status, "invalid")
        self.assertEqual(solution.reason_code, "tca_refinement_basin_limit_exceeded")
        self.assertIsNone(solution.offset_seconds)
        self.assertIsNone(solution.miss_distance_km)

    def test_equal_distinct_refined_minima_do_not_claim_a_unique_tca(self) -> None:
        distance = lambda t: 4.0 - 2.0 * math.exp(-((t - 0.38) / 0.07) ** 2) - 2.0 * math.exp(-((t - 0.80) / 0.04) ** 2)
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector((7000.0 + distance(t), 0.0, 0.0), (0.0, 0.0, 0.0))
        solution = minimize_relative_distance(
            primary, secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=1.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=1.0,
            time_tolerance_seconds=1e-8,
        )
        self.assertEqual(solution.status, "invalid")
        self.assertEqual(solution.reason_code, "non_unique_tca_multiple_minima")
        self.assertIsNone(solution.offset_seconds)
        self.assertAlmostEqual(solution.miss_distance_km, 2.0, delta=0.02)

    def test_refinement_reuses_exact_state_evaluations_without_changing_solution(self) -> None:
        primary_calls: list[float] = []
        secondary_calls: list[float] = []

        def primary(t: float) -> StateVector:
            primary_calls.append(t)
            return StateVector((7000.0, 0.0, 0.0), (0.0, 7.0, 0.0))

        def secondary(t: float) -> StateVector:
            secondary_calls.append(t)
            return StateVector((7005.0, -246.8 + 2.0 * t, 3.0), (0.0, 9.0, 0.0))

        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=100.0,
            upper_offset_seconds=140.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=300.0,
        )

        self.assertEqual(solution.status, "valid")
        self.assertAlmostEqual(solution.offset_seconds or -1.0, 123.4, delta=0.01)
        self.assertAlmostEqual(solution.miss_distance_km or -1.0, math.sqrt(34.0), delta=1e-7)
        self.assertEqual(len(primary_calls), len(set(primary_calls)))
        self.assertEqual(len(secondary_calls), len(set(secondary_calls)))
        self.assertEqual(primary_calls, secondary_calls)

    def test_candidate_tracker_keeps_distinct_sampled_minima_for_one_pair(self) -> None:
        tracker = trajectory_screening._CandidateTracker(pair=(0, 1))
        for sample_index, distance in enumerate((100.0, 80.0, 70.0, 80.0, 60.0, 90.0)):
            tracker.add(sample_index, distance)

        self.assertEqual(tracker.finish(), [(2, 70.0), (4, 60.0)])

    def test_relative_state_sign_is_secondary_minus_primary(self) -> None:
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 7.0, 0.0))
        secondary = lambda t: StateVector((7005.0, -20.0 + 2.0 * t, 3.0), (0.0, 9.0, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=30.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=30.0,
        )
        self.assertEqual(solution.relative_position_km[0], 5.0)
        self.assertEqual(solution.relative_position_km[2], 3.0)
        self.assertEqual(solution.relative_velocity_km_s, (0.0, 2.0, 0.0))

    def test_time_reversal_preserves_minimum_distance_and_reverses_tca(self) -> None:
        horizon = 300.0
        tca = 111.2
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector((7002.0, 4.0 * (t - tca), 1.0), (0.0, 4.0, 0.0))
        reversed_primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        reversed_secondary = lambda t: StateVector(
            (7002.0, 4.0 * ((horizon - t) - tca), 1.0),
            (0.0, -4.0, 0.0),
        )
        forward = minimize_relative_distance(
            primary, secondary, lower_offset_seconds=90.0, upper_offset_seconds=130.0,
            horizon_start_offset_seconds=0.0, horizon_end_offset_seconds=horizon,
        )
        reverse = minimize_relative_distance(
            reversed_primary, reversed_secondary, lower_offset_seconds=160.0, upper_offset_seconds=200.0,
            horizon_start_offset_seconds=0.0, horizon_end_offset_seconds=horizon,
        )
        self.assertAlmostEqual(forward.miss_distance_km, reverse.miss_distance_km, delta=1e-7)
        self.assertAlmostEqual(reverse.offset_seconds, horizon - forward.offset_seconds, delta=0.01)

    def test_minimum_at_horizon_start_is_marked_boundary(self) -> None:
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector((7002.0 + t, 0.0, 0.0), (1.0, 0.0, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=10.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=10.0,
        )
        self.assertEqual(solution.status, "boundary")
        self.assertEqual(solution.offset_seconds, 0.0)
        self.assertEqual(solution.miss_distance_km, 2.0)

    def test_artificial_bracket_edge_basin_does_not_invalidate_horizon_minimum(self) -> None:
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        # The distance has a valid minimum at the true horizon start and a
        # decreasing artificial edge basin at the bracket's right edge.
        secondary = lambda t: StateVector((7002.0 + t - t * t, 0.0, 0.0), (1.0 - 2.0 * t, 0.0, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=0.0,
            upper_offset_seconds=1.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=2.0,
        )
        self.assertEqual(solution.status, "boundary")
        self.assertEqual(solution.offset_seconds, 0.0)
        self.assertAlmostEqual(solution.miss_distance_km or -1.0, 2.0, delta=1e-12)
        self.assertTrue(solution.neighbor_check_passed)

    def test_artificial_bracket_edge_is_not_accepted_as_tca(self) -> None:
        primary = lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        secondary = lambda t: StateVector((7002.0 + t, 0.0, 0.0), (1.0, 0.0, 0.0))
        solution = minimize_relative_distance(
            primary,
            secondary,
            lower_offset_seconds=10.0,
            upper_offset_seconds=20.0,
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=30.0,
        )
        self.assertEqual(solution.status, "invalid")
        self.assertEqual(solution.reason_code, "no_local_minimum_in_interval")
        self.assertIsNone(solution.offset_seconds)

    def test_non_finite_state_is_invalid_and_has_no_numeric_result(self) -> None:
        invalid = lambda t: StateVector((float("nan"), 0.0, 0.0), (0.0, 1.0, 0.0))
        valid = lambda t: StateVector((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        solution = minimize_relative_distance(
            invalid, valid, lower_offset_seconds=0.0, upper_offset_seconds=1.0,
            horizon_start_offset_seconds=0.0, horizon_end_offset_seconds=1.0,
        )
        self.assertEqual(solution.status, "invalid")
        self.assertEqual(solution.reason_code, "non_finite_state")
        self.assertIsNone(solution.offset_seconds)
        self.assertIsNone(solution.miss_distance_km)


class TrajectoryPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep all deterministic screening fixtures offline and inexpensive. Tests
        # that exercise the API contract assert their explicit hook stubs below.
        self._ai_hook_patches = [
            patch.object(
                trajectory_screening,
                "predict_from_physics",
                side_effect=lambda physics: MLResult(
                    status="unavailable",
                    reason_code="test_ai_hook_stub",
                    provenance={"source_physics_event_id": physics.event_id},
                ),
            ),
            patch.object(
                trajectory_screening,
                "predict_orbital_anomaly",
                side_effect=lambda physics: OrbitalAnomalyResult(
                    status="unavailable",
                    reason_code="test_ai_hook_stub",
                    provenance={"source_physics_event_id": physics.event_id},
                ),
            ),
            patch.object(
                trajectory_screening,
                "compare_ml_and_physics",
                return_value=ComparisonResult(
                    status="not_comparable",
                    reason_code="test_ai_hook_stub",
                    validation_claim="none",
                ),
            ),
        ]
        for hook_patch in self._ai_hook_patches:
            hook_patch.start()
            self.addCleanup(hook_patch.stop)

    def _synthetic_screen(self, state_by_id, *, horizon_seconds=120, sample_step_seconds=30,
                          threshold_km=10.0, max_candidate_pairs=25_000, max_candidate_minima=10_000,
                          start_utc=TEST_START, records=None):
        records = records or make_distinct_synthetic_records(len(state_by_id))
        objects, _, unavailable = propagate_records(records, limit=len(records), now=start_utc)
        start_jd, start_fr = trajectory_screening._julian_parts(start_utc)

        class SyntheticSatrecArray:
            def __init__(self, satellites):
                self.satellites = satellites

            def sgp4(self, jd, fr):
                errors = np.zeros((len(self.satellites), len(jd)), dtype=int)
                positions = np.zeros((len(self.satellites), len(jd), 3), dtype=float)
                velocities = np.zeros_like(positions)
                for row, satellite in enumerate(self.satellites):
                    state_at = state_by_id[f"{satellite.satnum:05d}"]
                    for column, (date, fraction) in enumerate(zip(jd, fr)):
                        offset = ((float(date) + float(fraction)) - (start_jd + start_fr)) * 86400.0
                        state = state_at(offset)
                        positions[row, column] = state.position_km
                        velocities[row, column] = state.velocity_km_s
                return errors, positions, velocities

        def state_callback(track, origin, perf_counts=None):
            del origin, perf_counts
            return state_by_id[track.obj.id]

        with patch.object(trajectory_screening, "SatrecArray", SyntheticSatrecArray), \
                patch.object(trajectory_screening, "_state_callback", side_effect=state_callback):
            return screen_tle_records(
                records, objects, start_utc=start_utc,
                horizon_hours=horizon_seconds / 3600,
                sample_step_seconds=sample_step_seconds,
                screening_threshold_km=threshold_km,
                unavailable_objects=unavailable,
                include_synthetic_test_records=True,
                max_candidate_pairs=max_candidate_pairs,
                max_candidate_minima=max_candidate_minima,
            )

    def test_broad_phase_retains_known_synthetic_close_approach(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, -120.0 + 2.0 * t, 0.0), (0.0, 2.0, 0.0)),
        }
        with patch.object(trajectory_screening, "minimize_relative_distance", wraps=minimize_relative_distance) as minimizer:
            run = self._synthetic_screen(states)
        self.assertGreater(minimizer.call_count, 0)
        self.assertEqual(run.summary["status"], "valid")
        self.assertEqual(run.summary["candidate_pair_count"], 1)
        self.assertEqual(run.summary["close_approach_count"], 1)
        event = next(item for item in run.events if item.physics_result.status == "valid")
        tca = datetime.fromisoformat(event.physics_result.tca.value)
        self.assertAlmostEqual((tca - TEST_START).total_seconds(), 60.0, delta=0.02)
        self.assertAlmostEqual(event.physics_result.miss_distance.value, 5.0, delta=1e-6)

    def test_controlled_close_approach_reaches_api_with_matching_priority_and_pc_status(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, -120.0 + 2.0 * t, 0.0), (0.0, 2.0, 0.0)),
        }
        run = self._synthetic_screen(states)
        event = next(item for item in run.events if item.physics_result.status == "valid")
        snapshot = SimpleNamespace(
            source_summary=SimpleNamespace(model_dump=lambda: {"status": "synthetic_demo", "object_count": 2}),
            source_state={"status": "synthetic_demo"},
            stats=SimpleNamespace(provenance=SimpleNamespace(input_hash="controlled-fixture")),
            tle_epoch=TEST_START.isoformat(),
        )
        with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(snapshot, run))), TestClient(main.app) as client:
            response = client.get("/api/conjunctions?horizon_hours=0.0333333333&sample_step_seconds=30&screening_threshold_km=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        api_event = next(item for item in payload["data"] if item["id"] == event.id)
        self.assertEqual(api_event["physics_result"]["status"], "valid")
        self.assertEqual(api_event["physics_result"]["tca"]["value"], event.physics_result.tca.value)
        self.assertAlmostEqual(api_event["physics_result"]["miss_distance"]["value"], 5.0, delta=1e-6)
        self.assertEqual(api_event["review_priority"]["category"], event.review_priority.category)
        self.assertEqual(api_event["review_priority"]["policy_version"], "orion-geometry-review-v1")
        self.assertEqual(api_event["automatic_research_pc_assessment"]["status"], "not_estimable")
        self.assertEqual(api_event["automatic_research_pc_assessment"]["geometry_review_category"], api_event["review_priority"]["category"])
        self.assertIsNone(api_event["automatic_research_pc_assessment"]["estimated_pc"])
        self.assertEqual(payload["screening"]["review_priority_counts"][api_event["review_priority"]["category"]], 1)
        self.assertNotEqual(api_event["collision_probability"]["status"], "available")

    def test_screening_generates_supported_pair_types_without_classification_filtering(self):
        expected = [
            ("PAYLOAD", "DEBRIS", "SATELLITE vs DEBRIS"),
            ("PAYLOAD", "ROCKET_BODY", "SATELLITE vs ROCKET BODY"),
            ("PAYLOAD", "PAYLOAD", "SATELLITE vs SATELLITE"),
            ("PAYLOAD", None, "SATELLITE vs UNKNOWN"),
            ("DEBRIS", "ROCKET_BODY", "DEBRIS vs ROCKET BODY"),
        ]
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, -120.0 + 2.0 * t, 0.0), (0.0, 2.0, 0.0)),
        }
        for first_type, second_type, expected_pair in expected:
            with self.subTest(expected_pair=expected_pair):
                records = make_distinct_synthetic_records(2)
                records = [
                    replace(records[0], object_type=first_type),
                    replace(records[1], object_type=second_type),
                ]
                run = self._synthetic_screen(states, records=records)
                event = next(item for item in run.events if item.physics_result.status == "valid")
                self.assertEqual(event.pair_type, expected_pair)
                self.assertIn(event.review_priority.category, {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
                self.assertEqual(event.review_priority.status, "classified")
                self.assertFalse(event.review_priority.input_signals["pc_signal_used"])
                self.assertFalse(event.review_priority.input_signals["ml_signal_used"])
                self.assertEqual(run.summary["candidate_pair_count"], 1)
                self.assertEqual(run.summary["close_approach_count"], 1)

    def test_flat_nonzero_distance_preserves_minimum_without_claiming_unique_tca(self):
        angular_rate = 0.01

        def primary(t):
            return StateVector((7000.0, 0.0, 0.0), (0.0, 7.0, 0.0))

        def secondary(t):
            relative_position = (5.0 * math.cos(angular_rate * t), 5.0 * math.sin(angular_rate * t), 0.0)
            relative_velocity = (
                -5.0 * angular_rate * math.sin(angular_rate * t),
                5.0 * angular_rate * math.cos(angular_rate * t),
                0.0,
            )
            return StateVector(
                tuple((7000.0 + relative_position[0], relative_position[1], relative_position[2])),
                tuple((relative_velocity[0], 7.0 + relative_velocity[1], relative_velocity[2])),
            )

        run = self._synthetic_screen({"00005": primary, "00006": secondary})

        self.assertEqual(run.summary["status"], "valid")
        self.assertGreaterEqual(len(run.events), 1)
        self.assertEqual(run.summary["invalid_assessment_count"], len(run.events))
        self.assertEqual(len({event.id for event in run.events}), len(run.events))
        for event in run.events:
            physics = event.physics_result
            self.assertEqual(physics.status, "invalid")
            self.assertEqual(physics.reason_codes, ["non_unique_tca_flat_distance"])
            self.assertEqual(event.review_priority.category, "REVIEW_REQUIRED")
            self.assertIn("non_unique_tca_flat_distance", event.review_priority.explanation)
            self.assertEqual(physics.tca_status, "unavailable")
            self.assertEqual(physics.tca.status, "unavailable")
            self.assertIsNone(physics.tca.value)
            self.assertEqual(physics.miss_distance.status, "available")
            self.assertAlmostEqual(physics.miss_distance.value, 5.0, delta=1e-9)
            self.assertIsNone(physics.relative_position_at_tca.value)
            self.assertIsNone(physics.relative_velocity_at_tca.value)

    def test_end_to_end_screening_preserves_two_distinct_valid_minima(self):
        angular_rate = 2.0 * math.pi / 60.0
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector(
                (7005.0 + 5.0 * (1.0 - math.cos(angular_rate * (t - 30.0))), 0.0, 0.0),
                (5.0 * angular_rate * math.sin(angular_rate * (t - 30.0)), 0.0, 0.0),
            ),
        }
        run = self._synthetic_screen(states, sample_step_seconds=10, threshold_km=10.0)
        valid_events = [event for event in run.events if event.physics_result.status == "valid"]
        self.assertEqual(len(valid_events), 2)
        self.assertEqual(len({event.id for event in valid_events}), 2)
        tcas = sorted(
            (datetime.fromisoformat(event.physics_result.tca.value) - TEST_START).total_seconds()
            for event in valid_events
        )
        self.assertAlmostEqual(tcas[0], 30.0, delta=0.02)
        self.assertAlmostEqual(tcas[1], 90.0, delta=0.02)
        self.assertEqual(run.summary["close_approach_count"], 2)
        for event in valid_events:
            # TLE-only screening has valid encounter geometry but no
            # event-specific covariance or HBR. Keep the useful review
            # priority while leaving Foster Pc explicitly unavailable.
            self.assertEqual(event.review_priority.status, "classified")
            self.assertIn(event.review_priority.category, {"CRITICAL", "HIGH", "MEDIUM", "LOW"})
            self.assertEqual(event.collision_probability.status, "unavailable")
            self.assertIn("NO_COVARIANCE", event.collision_probability.reason_codes)
            self.assertIn("HBR_UNAVAILABLE", event.collision_probability.reason_codes)

    def test_valid_minima_within_one_second_keep_distinct_ids_and_events(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        }
        primary_state = StateVector((7000.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        secondary_state = StateVector((7005.0, 0.0, 0.0), (0.0, 2.0, 0.0))
        solutions = [
            trajectory_screening.ClosestApproachSolution(
                status="valid", offset_seconds=14.1, miss_distance_km=5.0,
                relative_position_km=(5.0, 0.0, 0.0), relative_velocity_km_s=(0.0, 1.0, 0.0),
                primary_state=primary_state, secondary_state=secondary_state,
            ),
            trajectory_screening.ClosestApproachSolution(
                status="valid", offset_seconds=14.8, miss_distance_km=5.0,
                relative_position_km=(5.0, 0.0, 0.0), relative_velocity_km_s=(0.0, 1.0, 0.0),
                primary_state=primary_state, secondary_state=secondary_state,
            ),
        ]
        with patch.object(trajectory_screening._CandidateTracker, "finish", return_value=[(1, 5.0), (2, 5.0)]), \
                patch.object(trajectory_screening, "minimize_relative_distance", side_effect=solutions):
            run = self._synthetic_screen(states, horizon_seconds=40, sample_step_seconds=10)

        valid_events = [event for event in run.events if event.physics_result.status == "valid"]
        self.assertEqual(len(valid_events), 2)
        self.assertEqual(len({event.id for event in valid_events}), 2)
        event_offsets = sorted(
            (datetime.fromisoformat(event.physics_result.tca.value) - TEST_START).total_seconds()
            for event in valid_events
        )
        self.assertEqual(event_offsets, [14.1, 14.8])
        self.assertEqual(run.summary["close_approach_count"], 2)

    def test_candidate_invalid_ids_include_absolute_epoch_and_are_deterministic(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        }
        invalid = trajectory_screening.ClosestApproachSolution(
            status="invalid", reason_code="tca_refinement_basin_limit_exceeded",
        )
        records = make_distinct_synthetic_records(2)

        def run_at(start, inputs):
            with patch.object(trajectory_screening._CandidateTracker, "finish", return_value=[(1, 5.0)]), \
                    patch.object(trajectory_screening, "minimize_relative_distance", return_value=invalid):
                return self._synthetic_screen(
                    states, horizon_seconds=40, sample_step_seconds=10,
                    start_utc=start, records=inputs,
                )

        first = run_at(TEST_START, records)
        repeated = run_at(TEST_START, records)
        shifted = run_at(TEST_START + timedelta(hours=1), records)
        reversed_inputs = run_at(TEST_START, list(reversed(records)))

        self.assertEqual([event.id for event in first.events], [event.id for event in repeated.events])
        self.assertEqual([event.id for event in first.events], [event.id for event in reversed_inputs.events])
        self.assertNotEqual(first.events[0].id, shifted.events[0].id)
        self.assertEqual(first.events[0].physics_result.status, "invalid")
        self.assertIsNone(first.events[0].physics_result.tca.value)
        self.assertEqual(first.summary["invalid_assessment_count"], 1)
        self.assertEqual(first.summary["status"], "valid")
        self.assertEqual(first.summary["assessment_diagnostic_codes"], ["invalid_assessments_generated"])

    def test_repeated_flat_candidates_keep_distinct_invalid_records_and_counts(self):
        angular_rate = 2.0 * math.pi / 60.0
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector(
                (7005.0 + math.cos(angular_rate * t), 0.0, 0.0),
                (-angular_rate * math.sin(angular_rate * t), 0.0, 0.0),
            ),
        }
        flat_solution = trajectory_screening.ClosestApproachSolution(
            status="invalid",
            miss_distance_km=5.0,
            reason_code="non_unique_tca_flat_distance",
        )
        with patch.object(trajectory_screening, "minimize_relative_distance", side_effect=[flat_solution, flat_solution]):
            run = self._synthetic_screen(states, sample_step_seconds=10, threshold_km=10.0)
        invalid_events = [event for event in run.events if event.physics_result.status == "invalid"]
        self.assertEqual(len(invalid_events), 2)
        self.assertEqual(len({event.id for event in invalid_events}), 2)
        self.assertTrue(all(event.physics_result.reason_codes == ["non_unique_tca_flat_distance"] for event in invalid_events))
        self.assertTrue(all(event.physics_result.tca.value is None for event in invalid_events))
        self.assertTrue(all(event.physics_result.miss_distance.value == 5.0 for event in invalid_events))
        self.assertEqual(run.summary["invalid_assessment_count"], 2)
        self.assertEqual(run.summary["close_approach_count"], 0)
        self.assertEqual(run.summary["status"], "valid")
        self.assertEqual(run.summary["assessment_diagnostic_codes"], ["invalid_assessments_generated"])

    def test_known_non_close_pair_does_not_become_physical_event(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((9000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        }
        run = self._synthetic_screen(states)
        self.assertEqual(run.summary["status"], "valid")
        self.assertEqual(run.summary["candidate_pair_count"], 0)
        self.assertEqual(run.events, [])

    def test_screening_encounters_at_both_horizon_boundaries_are_reported_as_boundary(self):
        duration = 120.0
        for secondary in (
            lambda t: StateVector((7005.0 + t, 0.0, 0.0), (1.0, 0.0, 0.0)),
            lambda t: StateVector((7005.0 + duration - t, 0.0, 0.0), (-1.0, 0.0, 0.0)),
        ):
            with self.subTest(boundary="start" if secondary(0).position_km[0] == 7005.0 else "end"):
                run = self._synthetic_screen({
                    "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
                    "00006": secondary,
                })
                self.assertEqual(run.summary["status"], "valid")
                event = next(item for item in run.events if item.physics_result.status == "boundary")
                self.assertIn(event.physics_result.tca.value, {TEST_START.isoformat(), (TEST_START + timedelta(seconds=duration)).isoformat()})

    def test_pair_and_minimum_caps_are_exposed_as_partial_coverage(self):
        states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector((7005.0, -120.0 + 2.0 * t, 0.0), (0.0, 2.0, 0.0)),
            "00007": lambda t: StateVector((7010.0, -120.0 + 2.0 * t, 0.0), (0.0, 2.0, 0.0)),
        }
        pair_capped = self._synthetic_screen(states, max_candidate_pairs=1)
        self.assertEqual(pair_capped.summary["status"], "partial")
        self.assertTrue(pair_capped.summary["candidate_pair_limit_reached"])
        self.assertTrue(pair_capped.summary["candidate_limit_reached"])
        self.assertEqual(pair_capped.summary["coverage_status"], "partial")
        self.assertIn("candidate_pair_limit", pair_capped.summary["caps_hit"])

        minima_capped = self._synthetic_screen(states, max_candidate_minima=1)
        self.assertEqual(minima_capped.summary["status"], "partial")
        self.assertTrue(minima_capped.summary["candidate_minimum_limit_reached"])
        self.assertIn("candidate_pair_or_minimum_limit_reached", minima_capped.summary["partial_reasons"])

    def test_sample_epoch_cap_reports_partial_coverage(self):
        records = make_distinct_synthetic_records(1)
        objects, _, unavailable = propagate_records(records, limit=1, now=TEST_START)
        run = screen_tle_records(
            records, objects, start_utc=TEST_START, horizon_hours=28,
            sample_step_seconds=10, unavailable_objects=unavailable,
            include_synthetic_test_records=True,
        )
        self.assertEqual(run.summary["status"], "partial")
        self.assertEqual(run.summary["coverage_status"], "partial")
        self.assertIn("sample_epoch_limit_reached", run.summary["partial_reasons"])
        self.assertIn("sample_epoch_limit", run.summary["caps_hit"])
        self.assertLess(run.summary["sampled_coverage_end"], run.summary["screening_horizon_end"])

    def test_per_pair_minimum_cap_is_detected(self):
        tracker = trajectory_screening._CandidateTracker(pair=(0, 1), max_minima=1)
        for index, distance in enumerate((10.0, 5.0, 10.0, 4.0, 10.0)):
            tracker.add(index, distance)
        self.assertEqual(len(tracker.finish()), 1)
        self.assertTrue(tracker.truncated)

        angular_rate = 2 * math.pi / 60.0
        periodic_states = {
            "00005": lambda t: StateVector((7000.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            "00006": lambda t: StateVector(
                (7005.0 + math.cos(angular_rate * t), 0.0, 0.0),
                (-angular_rate * math.sin(angular_rate * t), 0.0, 0.0),
            ),
        }
        tracker_type = trajectory_screening._CandidateTracker
        with patch.object(trajectory_screening, "_CandidateTracker", side_effect=lambda pair: tracker_type(pair, max_minima=1)):
            run = self._synthetic_screen(periodic_states, sample_step_seconds=10)
        self.assertEqual(run.summary["status"], "partial")
        self.assertTrue(run.summary["local_minima_per_pair_limit_reached"])
        self.assertTrue(run.summary["candidate_limit_reached"])

    def test_catalog_limit_does_not_truncate_assessment_records(self):
        assessments = [
            SimpleNamespace(
                result_kind="physics_assessment",
                provenance=SimpleNamespace(validity_status="valid", is_synthetic=False, source_type="live"),
                ml_result=SimpleNamespace(status="unavailable", prediction=None),
                physics_result=SimpleNamespace(status="valid"),
            )
            for _ in range(2)
        ]
        summary = {"status": "valid", "completion_status": "complete", "candidate_limit_reached": False}
        snapshot = SimpleNamespace(
            source_summary=SimpleNamespace(model_dump=lambda: {"object_count": 4}),
            source_state={"status": "live", "source": "CelesTrak live GP/TLE", "last_error_code": None},
            stats=SimpleNamespace(provenance=SimpleNamespace(input_hash="synthetic-test")),
            tle_epoch=None,
        )
        run = SimpleNamespace(events=assessments, summary=summary)
        with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(snapshot, run))), \
                patch.object(main, "event_dicts", side_effect=lambda values: [{"fixture": index} for index, _ in enumerate(values)]), \
                TestClient(main.app) as client:
            response = client.get("/api/conjunctions?limit=1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result_status"], "valid_non_empty")
        self.assertEqual(body["completion_status"], "complete")
        self.assertEqual(body["physics_assessment_status"], "valid")
        self.assertEqual(body["screening"]["computation_status"], "valid")
        self.assertEqual(body["screening"]["assessment_record_count"], 2)
        self.assertEqual(body["screening"]["returned_assessment_record_count"], 2)
        self.assertFalse(body["screening"]["assessment_response_limit_reached"])
        self.assertEqual(body["source_state"]["status"], "live")
        self.assertEqual(len(body["data"]), 2)
        self.assertEqual(summary["status"], "valid")

    def test_archived_iss_and_poisk_tles_reach_identical_parameter_screening_guard(self) -> None:
        provider = TleProvider(retry_attempts=1)
        with patch.object(tle_provider.httpx, "AsyncClient", _TleHttpClient):
            records, source_state = asyncio.run(provider.get_catalog_with_state(limit=2))

        self.assertEqual(source_state["status"], "live")
        self.assertEqual(len(records), 2)
        self.assertEqual([record.name for record in records], ["ISS (ZARYA)", "POISK"])
        self.assertEqual([record.line1[2:7] for record in records], ["25544", "36086"])
        self.assertEqual([record.source_type for record in records], ["live", "live"])
        self.assertTrue(all(_valid_tle_record(record) for record in records))
        self.assertTrue(all(record.original_line1 == record.line1 for record in records))
        self.assertTrue(all(record.original_line2 == record.line2 for record in records))

        satellites = [Satrec.twoline2rv(record.line1, record.line2, WGS72) for record in records]
        self.assertTrue(_same_propagation_parameters(*satellites))
        self.assertNotEqual(records[0].input_hash, records[1].input_hash)

        screen_start = datetime(2026, 10, 13, 12, 10, 22, 590000, tzinfo=timezone.utc)
        objects, _, unavailable = propagate_records(records, limit=2, now=screen_start)
        self.assertEqual({obj.id for obj in objects}, {"25544", "36086"})
        run = screen_tle_records(
            records,
            objects,
            start_utc=screen_start,
            horizon_hours=1 / 60,
            sample_step_seconds=30,
            screening_threshold_km=1.0,
            unavailable_objects=unavailable,
        )

        self.assertEqual(len(run.events), 1)
        event = run.events[0]
        self.assertEqual({event.primary.id, event.secondary.id}, {"25544", "36086"})
        source_records = event.provenance.source_record
        self.assertEqual(source_records["primary"]["parsed_catalog_id"], "25544")
        self.assertEqual(source_records["secondary"]["parsed_catalog_id"], "36086")
        self.assertEqual(source_records["primary"]["original_line1"], records[0].line1)
        self.assertEqual(source_records["primary"]["original_line2"], records[0].line2)
        self.assertEqual(source_records["secondary"]["original_line1"], records[1].line1)
        self.assertEqual(source_records["secondary"]["original_line2"], records[1].line2)
        self.assertEqual(
            event.physics_result.reason_codes,
            ["identical_propagation_parameters_for_distinct_catalog_ids"],
        )
        self.assertEqual(event.physics_result.status, "invalid")
        self.assertIsNone(event.physics_result.tca.value)
        self.assertIsNone(event.physics_result.miss_distance.value)
        self.assertIsNone(event.physics_result.relative_velocity_at_tca.value)
        self.assertIsNone(event.physics_result.relative_speed_at_tca.value)
        self.assertIsNone(event.physics_result.probability_of_collision.value)
        self.assertIsNone(event.collision_probability.tca_utc)
        self.assertIsNone(event.collision_probability.miss_distance_km)
        self.assertIsNone(event.collision_probability.pc)

    def test_screening_exception_returns_explicit_failed_status_not_empty_success(self) -> None:
        with patch.object(main, "build_trajectory_context", new=AsyncMock(side_effect=RuntimeError("injected failure"))), TestClient(main.app) as client:
            response = client.get("/api/conjunctions?limit=20")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["completion_status"], "failed")
        self.assertEqual(body["result_status"], "error")
        self.assertEqual(body["reason_code"], "SCREENING_EXECUTION_FAILED")
        self.assertFalse(body["success"])

    def test_duplicate_tle_states_are_invalid_and_never_report_zero_as_a_physical_event(self) -> None:
        records = make_identical_tle_records()
        objects, _, unavailable = propagate_records(records, limit=2, now=datetime(2026, 10, 13, tzinfo=timezone.utc))
        run = screen_tle_records(
            records,
            objects,
            start_utc=TEST_START,
            horizon_hours=1 / 60,
            sample_step_seconds=30,
            screening_threshold_km=1.0,
            unavailable_objects=unavailable,
            include_synthetic_test_records=True,
        )
        self.assertEqual(run.summary["status"], "valid")
        self.assertFalse(run.summary["candidate_limit_reached"])
        self.assertNotIn("invalid_assessments_generated", run.summary["partial_reasons"])
        self.assertEqual(run.summary["assessment_diagnostic_codes"], ["invalid_assessments_generated"])
        self.assertEqual(len(run.events), 1)
        self.assertNotEqual(run.events[0].primary.id, run.events[0].secondary.id)
        physics = run.events[0].physics_result
        self.assertEqual(physics.status, "invalid")
        self.assertIn(physics.reason_codes[0], {"duplicate_tle_state_for_distinct_catalog_ids", "identical_propagation_parameters_for_distinct_catalog_ids", "degenerate_zero_relative_state"})
        self.assertIsNone(physics.miss_distance.value)
        self.assertIsNone(physics.relative_speed_at_tca.value)
        self.assertEqual(physics.provenance.reference_frame, "TEME")
        self.assertTrue(physics.provenance.is_synthetic)
        self.assertEqual(physics.provenance.source_type, "synthetic")
        self.assertEqual(physics.provenance.units["position"], "km")
        self.assertEqual(physics.provenance.units["velocity"], "km/s")
        self.assertIsNone(physics.primary_state_at_tca)
        self.assertIsNone(physics.secondary_state_at_tca)
        self.assertIsNone(physics.relative_position_at_tca.value)
        self.assertIsNone(physics.relative_velocity_at_tca.value)
        self.assertEqual(physics.covariance.status, "unavailable")
        self.assertEqual(physics.probability_of_collision.status, "unavailable")

    def test_distinct_catalog_ids_with_identical_propagation_parameters_are_invalid(self) -> None:
        records = make_identical_tle_records()
        self.assertNotEqual(records[0].input_hash, records[1].input_hash)
        self.assertNotEqual(records[0].propagation_input_hash, records[1].propagation_input_hash)
        sats = [Satrec.twoline2rv(record.line1, record.line2, WGS72) for record in records]
        self.assertTrue(_same_propagation_parameters(*sats))
        objects, _, unavailable = propagate_records(records, limit=2, now=datetime(2026, 10, 13, tzinfo=timezone.utc))
        self.assertEqual([obj.id for obj in objects], ["00005", "00006"])
        self.assertEqual(objects[0].position, objects[1].position)
        self.assertEqual(objects[0].velocity, objects[1].velocity)
        with patch.object(trajectory_screening, "minimize_relative_distance", wraps=minimize_relative_distance) as minimizer:
            run = screen_tle_records(records, objects, start_utc=TEST_START, horizon_hours=1 / 60,
                                     sample_step_seconds=30, screening_threshold_km=1.0,
                                     unavailable_objects=unavailable, include_synthetic_test_records=True)
        minimizer.assert_not_called()
        self.assertEqual(run.summary["status"], "valid")
        self.assertNotIn("invalid_assessments_generated", run.summary["partial_reasons"])
        self.assertEqual(run.summary["assessment_diagnostic_codes"], ["invalid_assessments_generated"])
        self.assertEqual(len(run.events), 1)
        event = run.events[0]
        self.assertEqual({event.primary.id, event.secondary.id}, {"00005", "00006"})
        self.assertEqual(event.provenance.source_record["primary"]["parsed_catalog_id"], event.primary.id)
        self.assertEqual(event.provenance.source_record["secondary"]["parsed_catalog_id"], event.secondary.id)
        self.assertEqual(event.provenance.source_record["primary"]["normalized_line1"][2:7], event.primary.id)
        self.assertEqual(event.provenance.source_record["secondary"]["normalized_line1"][2:7], event.secondary.id)
        self.assertEqual(event.physics_result.status, "invalid")
        self.assertIn("identical_propagation_parameters_for_distinct_catalog_ids", event.physics_result.reason_codes)
        self.assertIsNone(event.physics_result.miss_distance.value)
        self.assertIsNone(event.physics_result.tca.value)
        self.assertIsNone(event.collision_probability.pc)
        self.assertIn(event.collision_probability.status, {"unavailable", "unsupported"})

    def test_distinct_valid_tles_have_distinct_states_and_keep_identity(self) -> None:
        records = parse_tle_text(FALLBACK_TLES, "fallback", source_type="fallback")[:2]
        objects, _, unavailable = propagate_records(records, limit=2, now=datetime(2026, 10, 13, tzinfo=timezone.utc))
        self.assertEqual(len(objects), 2)
        self.assertEqual({obj.id for obj in objects}, {"00005", "25544"})
        self.assertNotEqual(objects[0].position, objects[1].position)
        self.assertFalse(unavailable)

    def test_invalid_tle_is_recorded_without_fabricated_assessment(self) -> None:
        line1, line2 = VANGUARD_LINES[1:]
        broken = line2[:2] + "25544" + line2[7:]
        records = parse_tle_text(f"[SYNTHETIC TEST] BAD\n{line1}\n{broken}", "synthetic_test", source_type="synthetic")
        _, _, unavailable = propagate_records(records, limit=1, now=TEST_START)
        run = screen_tle_records(records, [], start_utc=TEST_START, unavailable_objects=unavailable)
        self.assertEqual(run.summary["status"], "unavailable")
        self.assertEqual(run.events, [])
        self.assertIn("invalid_tle", [item["reason_code"] for item in run.summary["rejected_objects"]])

    def test_naive_timestamp_is_rejected_and_sampling_cap_is_partial(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            screen_tle_records([], [], start_utc=datetime(2000, 1, 1))
        capped = screen_tle_records([], [], start_utc=TEST_START, horizon_hours=72, sample_step_seconds=10)
        self.assertEqual(capped.summary["status"], "partial")
        self.assertIn("sample_epoch_limit_reached", capped.summary["partial_reasons"])
        self.assertEqual(trajectory_screening.MAX_SAMPLE_EPOCHS, 10_000)

    def test_sgp4_error_during_horizon_returns_invalid_pair_result(self) -> None:
        records = make_identical_tle_records()
        objects, _, unavailable = propagate_records(records, limit=2, now=TEST_START)
        class ErrorAtLastEpoch:
            def __init__(self, satellites):
                self.satellites = satellites

            def sgp4(self, jd, fr):
                errors = np.zeros((len(self.satellites), len(jd)), dtype=int)
                positions = np.zeros((len(self.satellites), len(jd), 3), dtype=float)
                velocities = np.zeros_like(positions)
                for sat_index, satellite in enumerate(self.satellites):
                    for time_index, (date, fraction) in enumerate(zip(jd, fr)):
                        error, pos, vel = satellite.sgp4(float(date), float(fraction))
                        errors[sat_index, time_index] = error
                        positions[sat_index, time_index] = pos
                        velocities[sat_index, time_index] = vel
                errors[0, -1] = 2
                return errors, positions, velocities

        with patch.object(trajectory_screening, "SatrecArray", ErrorAtLastEpoch):
            run = screen_tle_records(
                records, objects, start_utc=TEST_START, horizon_hours=1 / 60,
                sample_step_seconds=30, screening_threshold_km=1.0, unavailable_objects=unavailable,
                include_synthetic_test_records=True,
            )
        self.assertEqual(run.summary["status"], "partial")
        self.assertFalse(run.summary["candidate_limit_reached"])
        self.assertIn("sgp4_track_propagation_errors", run.summary["partial_reasons"])
        self.assertNotIn("candidate_pair_or_minimum_limit_reached", run.summary["partial_reasons"])
        self.assertEqual(len(run.events), 1)
        self.assertEqual(run.events[0].physics_result.status, "invalid")
        self.assertIn("sgp4_error_2", run.events[0].physics_result.reason_codes[0])
        self.assertIsNone(run.events[0].physics_result.tca.value)

    def test_valid_empty_result_stays_empty(self) -> None:
        all_records = parse_tle_text(FALLBACK_TLES, "fallback", source_timestamp=TEST_START.isoformat(), source_type="fallback")
        records = [record for record in all_records if record.line1[2:7].strip() in {"00005", "41866"}]
        objects, _, unavailable = propagate_records(records, limit=2, now=TEST_START)
        run = screen_tle_records(
            records, objects, start_utc=TEST_START, horizon_hours=1 / 60,
            sample_step_seconds=30, screening_threshold_km=1.0, unavailable_objects=unavailable,
        )
        self.assertEqual(run.summary["status"], "valid")
        self.assertEqual(run.events, [])

    def test_api_returns_trajectory_assessment_separate_from_proxy_api(self) -> None:
        test_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        records = parse_tle_text(
            FALLBACK_TLES,
            "fallback",
            source_timestamp=test_start.isoformat(),
            source_type="fallback",
        )
        records = [record for record in records if record.line1[2:7].strip() in {"25544", "33591"}]

        class PairProvider:
            source = "test TLE source"
            source_type = "fallback"
            source_state = {
                "status": "fallback",
                "source": "Bundled fallback TLE sample",
                "last_success_at": None,
                "last_error_code": "upstream_network_error",
            }
            latency_seconds = 0.0

            async def get_catalog(self, limit: int):
                return records

        with patch.object(main, "tle_provider", PairProvider()), \
                patch.object(
                    trajectory_screening,
                    "predict_from_physics",
                    side_effect=lambda physics: MLResult(
                        status="available",
                        model_name="integration-test ESA estimator",
                        model_version="test-version",
                        training_dataset="deterministic integration fixture",
                        input_features={"miss_distance_m": 42.0},
                        feature_units={"miss_distance_m": "m"},
                        feature_frame="instantaneous primary RTN at TCA",
                        prediction=MLRiskPrediction(
                            predicted_log_risk=-7.5,
                            predicted_risk_estimate=10 ** -7.5,
                            predicted_risk_probability=10 ** -7.5,
                            threshold_flag_at_minus_6=False,
                            high_risk=False,
                        ),
                        provenance={"source_physics_event_id": physics.event_id},
                        reason_code="prediction_available",
                    ),
                ) as ml_hook, \
                patch.object(
                    trajectory_screening,
                    "predict_orbital_anomaly",
                    side_effect=lambda physics: OrbitalAnomalyResult(
                        status="available",
                        classification="not_flagged",
                        anomaly_score=0.25,
                        input_features={
                            "time_to_tca_days": 2.0,
                            "miss_distance_m": 1.0,
                            "relative_speed_m_s": 1.0,
                            "relative_position_r_m": 1.0,
                            "relative_position_t_m": 0.0,
                            "relative_position_n_m": 0.0,
                            "relative_velocity_r_m_s": 0.0,
                            "relative_velocity_t_m_s": 1.0,
                            "relative_velocity_n_m_s": 0.0,
                        },
                        reason_code="integration_test_stub",
                        provenance={"source_physics_event_id": physics.event_id},
                    ),
                ) as anomaly_hook, \
                patch.object(
                    trajectory_screening,
                    "compare_ml_and_physics",
                    return_value=ComparisonResult(
                        status="not_comparable",
                        reason_code="integration_test_stub",
                        validation_claim="none",
                    ),
                ) as comparison_hook, \
                TestClient(main.app) as client:
            response = client.get(
                "/api/conjunctions?horizon_hours=24&sample_step_seconds=60&screening_threshold_km=1000"
                "&start_utc=2024-01-01T00%3A00%3A00%2B00%3A00"
            )
            proxies_response = client.get("/api/screening-proxies?limit=10")

        self.assertEqual(response.status_code, 200)
        # The offline bundled records remain explicit fallback data and must not enter physical screening.
        self.assertEqual(ml_hook.call_count, 0)
        self.assertEqual(anomaly_hook.call_count, 0)
        self.assertEqual(comparison_hook.call_count, 0)
        payload = response.json()
        self.assertEqual(payload["result_status"], "unavailable")
        self.assertEqual(payload["completion_status"], "failed")
        self.assertEqual(payload["result_kind"], "physics_assessment")
        self.assertEqual(payload["source_summary"]["status"], "fallback")
        self.assertEqual(payload["source_state"]["last_error_code"], "upstream_network_error")
        self.assertEqual(payload["screening"]["reason_code"], "FALLBACK_CATALOG_NOT_SCREENED")
        self.assertEqual(payload["data"], [])
        self.assertIn("was not used for physical screening", payload["message"])
        self.assertEqual(proxies_response.status_code, 200)
        self.assertEqual(proxies_response.json()["result_kind"], "screening_proxy")
        self.assertEqual(proxies_response.json()["physics_assessment_status"], "not_assessed")

    def test_event_identity_is_stable_under_input_order_and_repeated_execution(self) -> None:
        records = make_identical_tle_records()
        objects, _, _ = propagate_records(records, limit=2, now=TEST_START)
        kwargs = dict(start_utc=TEST_START, horizon_hours=1 / 60, sample_step_seconds=30, screening_threshold_km=1.0)
        first = screen_tle_records(records, objects, include_synthetic_test_records=True, **kwargs)
        reversed_run = screen_tle_records(list(reversed(records)), list(reversed(objects)), include_synthetic_test_records=True, **kwargs)
        repeated = screen_tle_records(records, objects, include_synthetic_test_records=True, **kwargs)
        self.assertEqual([event.id for event in first.events], [event.id for event in reversed_run.events])
        self.assertEqual([event.id for event in first.events], [event.id for event in repeated.events])
        for a, b in zip(first.events, repeated.events):
            self.assertEqual(a.physics_result.tca.value, b.physics_result.tca.value)
            self.assertAlmostEqual(a.physics_result.miss_distance.value, b.physics_result.miss_distance.value, delta=1e-12)

    def test_duplicate_object_id_with_different_elements_is_rejected(self) -> None:
        original = parse_tle_text("\n".join(["[SYNTHETIC TEST] VANGUARD", *VANGUARD_LINES[1:]]), "synthetic_test", source_type="synthetic")[0]
        altered_line2 = original.line2[:8] + "349.0000" + original.line2[16:]
        altered = parse_tle_text(f"[SYNTHETIC TEST] VANGUARD ALTERED\n{original.line1}\n{altered_line2}", "synthetic_test", source_type="synthetic")[0]
        objects, _, _ = propagate_records([original], limit=1, now=TEST_START)
        run = screen_tle_records([original, altered], objects, start_utc=TEST_START, include_synthetic_test_records=True)
        self.assertEqual(run.summary["valid_track_count"], 0)
        self.assertIn("duplicate_object_id_conflicting_tles", [item["reason_code"] for item in run.summary["rejected_objects"]])


def make_identical_tle_records():
    first_line1 = VANGUARD_LINES[1]
    first_line2 = VANGUARD_LINES[2]
    second_line1 = with_tle_checksum(first_line1[:2] + "00006" + first_line1[7:])
    second_line2 = with_tle_checksum(first_line2[:2] + "00006" + first_line2[7:])
    first = parse_tle_text(f"[SYNTHETIC TEST] PRIMARY\n{first_line1}\n{first_line2}", "synthetic_test", source_type="synthetic")[0]
    second = parse_tle_text(f"[SYNTHETIC TEST] SECONDARY\n{second_line1}\n{second_line2}", "synthetic_test", source_type="synthetic")[0]
    return [first, second]


def make_distinct_synthetic_records(count: int):
    records = []
    for index in range(count):
        catalog_id = f"{5 + index:05d}"
        line1 = with_tle_checksum(VANGUARD_LINES[1][:2] + catalog_id + VANGUARD_LINES[1][7:])
        line2_base = VANGUARD_LINES[2][:2] + catalog_id + VANGUARD_LINES[2][7:]
        line2 = with_tle_checksum(line2_base[:43] + f"{30.0 + index:8.4f}" + line2_base[51:])
        records.extend(parse_tle_text(
            f"[SYNTHETIC TEST] CONTROLLED {catalog_id}\n{line1}\n{line2}",
            "synthetic_test", source_type="synthetic",
        ))
    return records


def with_tle_checksum(line: str) -> str:
    return line[:68] + str(sum(int(ch) if ch.isdigit() else (1 if ch == "-" else 0) for ch in line[:68]) % 10)


if __name__ == "__main__":
    unittest.main()
