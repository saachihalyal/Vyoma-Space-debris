from __future__ import annotations

import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.models import OrbitVisual, Provenance, RiskCell, SpaceObject
from app.services.conjunction import build_conjunctions, build_screening_proxies, build_smart_filter, optimize_maneuver
from app.services.orbit import build_synthetic_objects, propagate_records
from app.services.risk import build_risk_cells
from app.services.tle_provider import FALLBACK_TLES, parse_omm_json, parse_tle_text


VANGUARD_TLE = "\n".join(FALLBACK_TLES.splitlines()[:3])


class TleProvenanceTests(unittest.TestCase):
    def test_parsed_records_keep_live_and_fallback_origins_separate(self) -> None:
        live = parse_tle_text(VANGUARD_TLE, "stations", source_timestamp="2025-01-02T03:04:05+00:00")[0]
        fallback = parse_tle_text(VANGUARD_TLE, "fallback", source_timestamp="2025-01-02T03:04:05+00:00")[0]

        self.assertEqual(live.source_type, "live")
        self.assertEqual(fallback.source_type, "fallback")
        self.assertNotEqual(live.input_hash, "")
        self.assertEqual(live.source_timestamp, "2025-01-02T03:04:05+00:00")
        self.assertEqual(live.element_epoch, "00179.78495062")

    def test_reference_sgp4_case_preserves_epoch_frame_units_and_state(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations", source_timestamp="2000-06-27T00:00:00+00:00")[0]
        epoch = datetime(2000, 6, 27, tzinfo=timezone.utc) + timedelta(days=0.78495062)

        objects, tle_epoch, unavailable = propagate_records([record], limit=1, now=epoch)

        self.assertEqual(len(objects), 1)
        self.assertEqual(unavailable, [])
        obj = objects[0]
        self.assertEqual(tle_epoch, "00179.78495062")
        self.assertEqual(obj.provenance.element_epoch, "00179.78495062")
        self.assertEqual(obj.provenance.propagation_epoch, epoch.isoformat())
        self.assertEqual(obj.provenance.reference_frame, "TEME")
        self.assertEqual(obj.provenance.units["position"], "km")
        self.assertEqual(obj.provenance.units["velocity"], "km/s")
        self.assertEqual(obj.provenance.validity_status, "valid")
        self.assertTrue(obj.provenance.propagator_version)
        self.assertEqual(obj.heuristic_score_provenance.source_type, "derived")
        self.assertIn("heuristic", obj.heuristic_score_provenance.method.lower())

    def test_omm_large_catalog_number_propagates_with_identity_and_provenance(self) -> None:
        omm = {
            "OBJECT_NAME": "NEW OBJECT", "OBJECT_ID": "2026-123A", "CENTER_NAME": "EARTH",
            "REF_FRAME": "TEME", "TIME_SYSTEM": "UTC", "MEAN_ELEMENT_THEORY": "SGP4",
            "EPOCH": "2026-10-18T12:34:56.123456", "MEAN_MOTION": "15.2",
            "ECCENTRICITY": "0.001", "INCLINATION": "51.6", "RA_OF_ASC_NODE": "120.0",
            "ARG_OF_PERICENTER": "40.0", "MEAN_ANOMALY": "210.0", "EPHEMERIS_TYPE": "0",
            "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": "100123", "ELEMENT_SET_NO": "1",
            "REV_AT_EPOCH": "10", "BSTAR": "0.0001", "MEAN_MOTION_DOT": "0.00001",
            "MEAN_MOTION_DDOT": "0.0",
        }
        record = parse_omm_json(json.dumps([omm]), "stations", source_timestamp="2026-10-18T12:35:00Z")[0]
        epoch = datetime(2026, 10, 18, 12, 34, 56, 123456, tzinfo=timezone.utc)

        objects, element_epoch, unavailable = propagate_records([record], limit=1, now=epoch)

        self.assertEqual(unavailable, [])
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertEqual(obj.id, "100123")
        self.assertEqual(obj.provenance.catalog_id, "100123")
        self.assertEqual(element_epoch, omm["EPOCH"])
        self.assertEqual(obj.provenance.element_epoch, omm["EPOCH"])
        self.assertEqual(obj.provenance.reference_frame, "TEME")
        self.assertEqual(obj.provenance.source_timestamp, "2026-10-18T12:35:00Z")
        self.assertEqual(obj.provenance.source_record["source_format"], "OMM-JSON")
        self.assertEqual(obj.heuristic_score_provenance.input_hash, obj.provenance.input_hash)
        self.assertTrue(all(math.isfinite(value) for value in [*obj.position, *obj.velocity]))

    def test_timezone_offsets_for_same_instant_produce_equivalent_states(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations")[0]
        epoch = datetime(2000, 6, 27, tzinfo=timezone.utc) + timedelta(days=0.78495062)
        offset_epoch = epoch.astimezone(timezone(timedelta(hours=5, minutes=30)))

        utc_objects, _, utc_unavailable = propagate_records([record], limit=1, now=epoch)
        offset_objects, _, offset_unavailable = propagate_records([record], limit=1, now=offset_epoch)

        self.assertFalse(utc_unavailable)
        self.assertFalse(offset_unavailable)
        self.assertEqual(utc_objects[0].position, offset_objects[0].position)
        self.assertEqual(utc_objects[0].velocity, offset_objects[0].velocity)
        self.assertEqual(
            utc_objects[0].provenance.propagation_epoch,
            offset_objects[0].provenance.propagation_epoch,
        )

    def test_naive_propagation_datetime_is_rejected(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations")[0]

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            propagate_records([record], limit=1, now=datetime(2000, 6, 27))

    def test_fractional_second_propagation_is_preserved(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations")[0]
        epoch = datetime(2000, 6, 27, tzinfo=timezone.utc) + timedelta(days=0.78495062)
        fractional_epoch = epoch + timedelta(microseconds=250_000)

        base_objects, _, _ = propagate_records([record], limit=1, now=epoch)
        fractional_objects, _, unavailable = propagate_records([record], limit=1, now=fractional_epoch)

        self.assertFalse(unavailable)
        self.assertEqual(fractional_objects[0].provenance.propagation_epoch, fractional_epoch.isoformat())
        self.assertNotEqual(base_objects[0].position, fractional_objects[0].position)

    def test_non_finite_sgp4_state_is_unavailable(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations")[0]

        class NonFiniteSatellite:
            epochyr = 0
            epochdays = 0.0
            ndot = 0.0
            nddot = 0.0
            bstar = 0.0
            inclo = 0.0
            nodeo = 0.0
            ecco = 0.0
            argpo = 0.0
            mo = 0.0
            no_kozai = 0.0

            def sgp4(self, jd, fr):
                return 0, (float("nan"), 1.0, 2.0), (1.0, 2.0, 3.0)

        with patch("app.services.orbit.Satrec.twoline2rv", return_value=NonFiniteSatellite()):
            objects, _, unavailable = propagate_records(
                [record], limit=1, now=datetime(2000, 6, 27, tzinfo=timezone.utc)
            )

        self.assertEqual(objects, [])
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].provenance.validity_status, "invalid")
        self.assertEqual(unavailable[0].provenance.reason_code, "non_finite_sgp4_state")
        self.assertNotIn("position", unavailable[0].model_dump())

    def test_invalid_tle_is_reported_without_a_fabricated_state(self) -> None:
        line1, line2 = VANGUARD_TLE.splitlines()[1:]
        mismatched_line2 = line2[:2] + "25544" + line2[7:]
        invalid = parse_tle_text(f"BAD OBJECT\n{line1}\n{mismatched_line2}", "stations")[0]

        objects, _, unavailable = propagate_records([invalid], limit=1)

        self.assertEqual(objects, [])
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].provenance.validity_status, "invalid")
        self.assertEqual(unavailable[0].provenance.reason_code, "invalid_tle")
        self.assertNotIn("position", unavailable[0].model_dump())

    def test_tle_catalog_is_not_expanded_with_implicit_synthetic_objects(self) -> None:
        record = parse_tle_text(VANGUARD_TLE, "stations")[0]
        objects, _, _ = propagate_records([record], limit=200)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].provenance.source_type, "live")


class HeuristicProvenanceTests(unittest.TestCase):
    def test_risk_cells_are_named_and_tagged_as_derived_heuristics(self) -> None:
        records = parse_tle_text(FALLBACK_TLES, "fallback", source_timestamp="2025-01-02T03:04:05+00:00")
        epoch = datetime(2000, 6, 27, tzinfo=timezone.utc) + timedelta(days=0.78495062)
        objects, _, _ = propagate_records(records, limit=len(records), now=epoch)
        cells = build_risk_cells(objects)

        self.assertTrue(cells)
        self.assertEqual(cells[0].provenance.source_type, "derived")
        self.assertTrue(cells[0].provenance.is_fallback)
        self.assertIn("heuristic", cells[0].provenance.method.lower())
        payload = cells[0].model_dump()
        self.assertIn("heuristic_risk_score", payload)
        self.assertNotIn("probability", payload)
        self.assertNotIn("uncertainty", payload)

    def test_live_plus_synthetic_records_report_a_mixed_snapshot(self) -> None:
        live = make_object("10001", source_type="live")
        synthetic = make_object("SYN-1", source_type="synthetic")
        summary = main.summarize_sources([live, synthetic], [])
        self.assertEqual(summary.status, "mixed_live_synthetic")
        self.assertEqual(summary.counts_by_source_type, {"live": 1, "synthetic": 1})

    def test_backend_demo_object_and_scores_are_explicitly_synthetic(self) -> None:
        demo_object = build_synthetic_objects(1)[0]
        self.assertTrue(demo_object.name.startswith("[DEMO]"))
        self.assertEqual(demo_object.provenance.source_type, "synthetic")
        self.assertTrue(demo_object.provenance.is_synthetic)
        self.assertEqual(demo_object.provenance.validity_status, "not_assessed")
        self.assertEqual(demo_object.heuristic_score_provenance.source_type, "derived")
        self.assertTrue(demo_object.heuristic_score_provenance.is_synthetic)
        self.assertIn("not_collision_probability", demo_object.heuristic_score_provenance.reason_code)

    def test_event_identity_is_stable_under_input_order_changes(self) -> None:
        first, second = make_object("10001"), make_object("10002")
        cell = make_cell()
        forward = build_conjunctions([first, second], [cell])
        reversed_inputs = build_conjunctions([second, first], [cell])
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0].id, reversed_inputs[0].id)
        self.assertTrue(forward[0].id.startswith("SP-"))
        self.assertEqual(forward[0].event_identity_type, "internal_deterministic")

    def test_proxy_event_keeps_physics_fields_unavailable_and_ml_absent(self) -> None:
        event = build_conjunctions([make_object("10001"), make_object("10002")], [make_cell()])[0]
        payload = event.model_dump(mode="json")
        physics = payload["physics_result"]
        self.assertEqual(physics["status"], "unavailable")
        self.assertIsNone(physics["tca"]["value"])
        self.assertEqual(physics["tca"]["reason_code"], "trajectory_assessment_not_attached")
        self.assertIsNone(physics["miss_distance"]["value"])
        self.assertIsNone(physics["covariance"]["value"])
        self.assertIsNone(physics["probability_of_collision"]["value"])
        self.assertNotIn("tca", payload)
        self.assertNotIn("miss_distance_m", payload)
        self.assertNotIn("covariance", payload)
        self.assertNotIn("ai_confidence", payload)
        self.assertEqual(payload["ml_result"]["status"], "unavailable")
        self.assertEqual(payload["ml_result"]["reason_code"], "PHYSICS_ASSESSMENT_FEATURES_REQUIRED")
        self.assertEqual(payload["comparison_result"]["validation_claim"], "none")

    def test_filter_and_maneuver_contracts_do_not_claim_ml_or_physics_results(self) -> None:
        events = build_conjunctions([make_object("10001"), make_object("10002")], [make_cell()])
        smart = build_smart_filter(events, total_objects=2)
        maneuver = optimize_maneuver(events[0])
        self.assertEqual(smart["model_status"], "not_applicable_to_proxy_events")
        self.assertIsNone(smart["reduction_pct"])
        self.assertEqual(smart["reduction_status"], "not_measured")
        self.assertEqual(smart["heuristic_only_proxy_count"], 1)
        self.assertEqual(smart["evaluation"]["candidate_count_before"], 1)
        self.assertIsNone(smart["evaluation"]["false_negative_count"])
        self.assertEqual(smart["evaluation"]["false_negative_status"], "not_measured")
        self.assertEqual(smart["item_decisions"][0]["decision"], "exclude")
        self.assertEqual(smart["item_decisions"][0]["rule_ids"], ["PROXY_RELATIVE_BAND_EXCLUSION"])
        retained = build_smart_filter([events[0].model_copy(update={"risk_level": "High"})], total_objects=2)
        self.assertEqual(retained["item_decisions"][0]["decision"], "retain")
        self.assertEqual(retained["item_decisions"][0]["rule_ids"], ["PROXY_RELATIVE_BAND_REVIEW"])
        self.assertIn("ESA_LIVE_INFERENCE_NOT_A_FILTER", {rule["rule_id"] for rule in smart["rule_catalog"]})
        self.assertNotIn("avg_confidence_pct", smart)
        self.assertEqual(maneuver["status"], "unavailable")
        self.assertIsNone(maneuver["delta_v_m_s"])
        self.assertIsNone(maneuver["probability_before"])
        self.assertEqual(maneuver["ml_result"]["status"], "not_applicable")
        self.assertEqual(maneuver["ml_result"]["reason_code"], "PHYSICAL_EVENT_REQUIRED")

    def test_proxy_classes_are_relative_and_do_not_mark_saturated_batch_all_critical(self) -> None:
        objects = [make_object(f"OBJ-{index:04d}") for index in range(240)]
        events = build_screening_proxies(objects, [make_cell()], limit=120)
        classes = {level: sum(event.risk_level == level for event in events) for level in ("Critical", "High", "Medium", "Low", "Safe")}
        self.assertEqual(len(events), 120)
        self.assertLess(classes["Critical"], len(events))
        self.assertEqual(sum(classes.values()), len(events))
        self.assertTrue(all(event.features["class_semantics"] == "relative ranking within this generated proxy batch" for event in events))
        proxy_payload = events[0].model_dump(mode="json")
        self.assertEqual(proxy_payload["physics_result"]["status"], "unavailable")
        self.assertEqual(proxy_payload["physics_result"]["applicability"], "candidate_pair_only")
        self.assertEqual(proxy_payload["physics_result"]["reason_codes"], [
            "screening_proxy_not_a_physical_event", "trajectory_assessment_not_attached",
        ])
        for field in ("tca", "miss_distance", "relative_speed_at_tca", "relative_velocity_at_tca"):
            self.assertEqual(proxy_payload["physics_result"][field]["status"], "unavailable")
            self.assertIsNone(proxy_payload["physics_result"][field]["value"])
        self.assertNotIn("collision_probability", proxy_payload)
        smart = build_smart_filter(events, total_objects=len(objects))
        self.assertIsNone(smart["reduction_pct"])
        self.assertEqual(smart["reduction_status"], "not_measured")
        self.assertEqual(smart["heuristic_only_proxy_count"], len(events))

    def test_proxy_generation_rejects_records_with_the_same_catalog_id(self) -> None:
        first = make_object("DUPLICATE-ID").model_copy(update={
            "provenance": make_object("DUPLICATE-ID").provenance.model_copy(
                update={"catalog_id": "12345", "input_hash": "record-a"}
            ),
        })
        second = make_object("DUPLICATE-ID").model_copy(update={
            "provenance": make_object("DUPLICATE-ID").provenance.model_copy(
                update={"catalog_id": "12345", "input_hash": "record-b"}
            ),
        })

        events = build_screening_proxies([second, first], [make_cell()])

        self.assertEqual(events, [])

    def test_proxy_generation_still_pairs_distinct_catalog_ids(self) -> None:
        first = make_object("10001").model_copy(update={
            "provenance": make_object("10001").provenance.model_copy(update={"catalog_id": "10001"}),
        })
        second = make_object("10002").model_copy(update={
            "provenance": make_object("10002").provenance.model_copy(update={"catalog_id": "10002"}),
        })

        events = build_screening_proxies([first, second], [make_cell()])

        self.assertEqual(len(events), 1)
        self.assertNotEqual(events[0].primary.id, events[0].secondary.id)

    def test_proxy_generation_duplicate_suppression_is_order_deterministic(self) -> None:
        duplicate_a = make_object("DUPLICATE-ID").model_copy(update={
            "provenance": make_object("DUPLICATE-ID").provenance.model_copy(
                update={"catalog_id": "12345", "input_hash": "record-a"}
            ),
        })
        duplicate_b = make_object("DUPLICATE-ID").model_copy(update={
            "provenance": make_object("DUPLICATE-ID").provenance.model_copy(
                update={"catalog_id": "12345", "input_hash": "record-b"}
            ),
        })
        distinct = make_object("DISTINCT-ID").model_copy(update={
            "provenance": make_object("DISTINCT-ID").provenance.model_copy(
                update={"catalog_id": "67890", "input_hash": "record-c"}
            ),
        })

        forward = build_screening_proxies([duplicate_a, duplicate_b, distinct], [make_cell()])
        reverse = build_screening_proxies([distinct, duplicate_b, duplicate_a], [make_cell()])

        signature = lambda events: [
            (event.id, event.primary.id, event.primary.provenance.input_hash,
             event.secondary.id, event.secondary.provenance.input_hash,
             event.risk_score, event.risk_level, event.priority_score)
            for event in events
        ]
        self.assertEqual(signature(forward), signature(reverse))
        self.assertTrue(all(event.primary.id != event.secondary.id for event in forward))

    def test_empty_filter_keeps_undefined_percentages_unavailable(self) -> None:
        smart = build_smart_filter([], total_objects=0)
        self.assertIsNone(smart["reduction_pct"])
        self.assertIsNone(smart["mean_heuristic_risk_score"])
        self.assertIsNone(smart["pipeline_stages"][1]["kept_pct"])
        self.assertIsNone(smart["pipeline_stages"][-1]["kept_pct"])

    def test_api_preserves_valid_empty_screening_result(self) -> None:
        class EmptyProvider:
            source = "test empty catalog"
            latency_seconds = 0.0
            requested_limits = []

            async def get_catalog(self, limit: int):
                self.requested_limits.append(limit)
                return []

        with patch.object(main, "tle_provider", EmptyProvider()), TestClient(main.app) as client:
            response = client.get("/api/conjunctions?limit=20")
            catalog_response = client.get("/api/catalog?limit=25")
            health_response = client.get("/api/health")
            system_health_response = client.get("/api/system-health")
            system_health_gzip_response = client.get("/api/system-health", headers={"accept-encoding": "gzip"})
            forecast_response = client.get("/api/forecast?horizon_hours=24&steps=2")
            analytics_response = client.get("/api/analytics?limit=25")
            smart_filter_response = client.get("/api/smart-filter")
            mission_json_response = client.get("/api/reports/mission.json")
            csv_response = client.get("/api/reports/conjunctions.csv")
            mission_pdf_response = client.get("/api/reports/mission.pdf")
            min_pc_response = client.get("/api/conjunctions?min_pc=0.01")

        self.assertEqual(response.status_code, 200)
        self.assertIn(20, EmptyProvider.requested_limits)
        body = response.json()
        self.assertEqual(body["result_status"], "unavailable")
        self.assertEqual(body["result_kind"], "physics_assessment")
        self.assertEqual(body["data"], [])
        self.assertEqual(body["physics_assessment_status"], "unavailable")
        self.assertEqual(body["completion_status"], "failed")
        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(system_health_gzip_response.headers.get("content-encoding"), "gzip")
        catalog_body = catalog_response.json()
        self.assertEqual(catalog_body["objects"], [])
        self.assertEqual(catalog_body["source_summary"]["status"], "unavailable")
        self.assertIsNone(catalog_body["stats"]["global_heuristic_risk_score"])
        self.assertIsNone(catalog_body["stats"]["heuristic_forecast_trend_score"])
        self.assertEqual(catalog_body["stats"]["provenance"]["validity_status"], "unavailable")
        self.assertEqual(health_response.json()["ai_status"], system_health_response.json()["data"]["ai_status"])
        self.assertEqual(health_response.json()["ai_reason"], system_health_response.json()["data"]["ai_reason"])
        self.assertEqual(health_response.json()["ml_model"]["model_name"], system_health_response.json()["data"]["ml_model"]["model_name"])
        self.assertEqual(health_response.json()["gpu_status"], "not_used")
        self.assertIn("no persistent database", health_response.json()["database_status"])
        # The model artifact is optional and this test environment does not
        # contain a loadable trained model. Health must report that state.
        self.assertEqual(system_health_response.json()["data"]["ai_status"], main.model_status()["status"])
        self.assertEqual(system_health_response.json()["data"]["ml_model"]["model_name"], "ORION ESA event final log10-risk estimator")
        self.assertTrue(all(frame["global_heuristic_risk_score"] is None for frame in forecast_response.json()["frames"]))
        analytics_data = analytics_response.json()["data"]
        self.assertIsNone(analytics_data["mean_heuristic_risk_score"])
        self.assertIsNone(analytics_data["smart_filter_reduction_pct"])
        smart_data = smart_filter_response.json()["data"]
        self.assertEqual(smart_data["model_status"], "not_applicable_to_proxy_events")
        self.assertIsNone(smart_data["reduction_pct"])
        mission_payload = json.loads(mission_json_response.content)
        self.assertEqual(mission_payload["screening_proxy_pairs"], [])
        self.assertIn("trajectory_assessments", mission_payload)
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response.headers["content-type"])
        self.assertTrue(csv_response.text.startswith("event_id,event_identity_type"))
        self.assertGreaterEqual(len(csv_response.text.splitlines()), 1)
        self.assertEqual(mission_pdf_response.status_code, 200)
        self.assertIn("application/pdf", mission_pdf_response.headers["content-type"])
        self.assertTrue(mission_pdf_response.content.startswith(b"%PDF-"))
        self.assertIn(b"Stage 2A trajectory screening status", mission_pdf_response.content)
        self.assertEqual(min_pc_response.status_code, 422)

    def test_api_reports_valid_empty_when_a_usable_catalog_was_screened(self) -> None:
        class TwoObjectProvider:
            source = "bundled fallback TLE sample"
            latency_seconds = 0.0

            async def get_catalog(self, limit: int):
                selected = parse_tle_text(
                    FALLBACK_TLES,
                    "fallback",
                    source_timestamp="2000-06-27T18:50:19.733568+00:00",
                    source_type="fallback",
                )
                return [record for record in selected if record.line1[2:7].strip() in {"00005", "41866"}]

        with patch.object(main, "tle_provider", TwoObjectProvider()), TestClient(main.app) as client:
            response = client.get(
                "/api/conjunctions?horizon_hours=0.01&sample_step_seconds=10&screening_threshold_km=1"
                "&start_utc=2000-06-27T18%3A50%3A19.733568%2B00%3A00"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Fallback-only records are deliberately excluded from physical live
        # screening; an empty usable live catalog is unavailable, not a valid
        # empty scientific result.
        self.assertEqual(payload["result_status"], "unavailable")
        self.assertEqual(payload["result_kind"], "physics_assessment")
        self.assertEqual(payload["physics_assessment_status"], "unavailable")
        self.assertEqual(payload["completion_status"], "failed")
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["screening"]["status"], "unavailable")
        self.assertEqual(payload["screening"]["reason_code"], "FALLBACK_CATALOG_NOT_SCREENED")


def make_object(object_id: str, *, source_type: str = "live") -> SpaceObject:
    provenance = Provenance(
        source=f"{source_type} test data",
        source_type=source_type,
        element_epoch="00179.78495062",
        propagation_epoch="2000-06-27T18:50:19.733568+00:00",
        reference_frame="TEME",
        units={"position": "km", "velocity": "km/s"},
        object_id=object_id,
        input_hash=f"hash-{object_id}",
        propagator="python-sgp4",
        propagator_version="test",
        method="test fixture",
        method_version="1",
        validity_status="valid",
        is_synthetic=source_type == "synthetic",
        is_fallback=source_type == "fallback",
    )
    return SpaceObject(
        id=object_id,
        name=f"TEST OBJECT {object_id}",
        category="debris",
        band="LEO",
        orbit_type="Low-inclination LEO",
        altitude_km=700.0,
        inclination_deg=51.6,
        velocity_kms=7.5,
        heuristic_risk_score=0.61,
        heuristic_debris_pressure_score=0.42,
        heuristic_forecast_score=0.66,
        position=[7000.0, 0.0, 0.0],
        velocity=[0.0, 7.5, 0.0],
        orbit=OrbitVisual(
            visual_radius=2.6,
            inclination_deg=51.6,
            raan_deg=22.5,
            phase_rad=0.3,
            angular_rate=0.01,
            eccentricity=0.001,
        ),
        provenance=provenance,
        heuristic_score_provenance=provenance.model_copy(
            update={"source_type": "derived", "method": "test heuristic", "reason_code": "heuristic_test"}
        ),
    )


def make_cell() -> RiskCell:
    return RiskCell(
        id="TEST-CELL",
        band="LEO",
        altitude_km=700.0,
        inclination_deg=51.0,
        raan_deg=22.5,
        severity="elevated",
        heuristic_risk_score=0.64,
        tracked_object_density_score=0.42,
        heuristic_untracked_pressure_score=0.3,
        heuristic_forecast_score=0.61,
        heuristic_uncertainty_score=0.4,
        contributors=["TEST OBJECT 10001", "TEST OBJECT 10002"],
        explanation="test heuristic cell",
        provenance=Provenance(
            source="test fixture",
            source_type="derived",
            method="test fixture",
            method_version="1",
            validity_status="valid",
        ),
    )


if __name__ == "__main__":
    unittest.main()
