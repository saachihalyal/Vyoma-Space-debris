from __future__ import annotations

import unittest
import re
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.models import (
    ConjunctionAssessmentEvent,
    ObjectSummary,
    PhysicsResult,
    Provenance,
    ScientificField,
)
from app.services.cdm_ingestion import parse_cdm_input, parse_cdm_xml
from app.services.event_pc_inputs import apply_cdm_inputs, apply_scenario_inputs, evaluate_cdm_reference


TCA = "2025-01-01T00:00:00+00:00"


class CdmInputTests(unittest.TestCase):
    def test_tracss_json_tracss_v20_preserves_ids_units_covariance_and_per_object_hbr(self) -> None:
        parsed = parse_cdm_input(json.dumps(tracss_json_fixture()), source_label="synthetic parser contract fixture")
        self.assertEqual(parsed.source_format, "TraCSS JSON-TraCSS CDM 2.0")
        self.assertEqual(parsed.tca_utc, "2025-05-16T11:08:55.944000+00:00")
        self.assertEqual([item.object_designator for item in parsed.inputs], ["43013", "147"])
        self.assertEqual([item.object_hbr_km for item in parsed.inputs], [0.005, 0.001])
        self.assertAlmostEqual(parsed.hbr.value_km, 0.006)
        self.assertEqual(parsed.hbr.source_type, "user_supplied")
        self.assertEqual(parsed.inputs[0].covariance.frame, "EME2000")
        self.assertEqual(parsed.inputs[1].covariance.epoch, parsed.tca_utc)
        self.assertEqual(parsed.inputs[0].position_km, [7000.0, 0.0, 0.0])
        self.assertTrue(all("Object 1's TCA RTN basis" in item.covariance.source for item in parsed.inputs))
        result = evaluate_cdm_reference(parsed, assume_independent_covariances=False)
        self.assertEqual(result["source_format"], "TraCSS JSON-TraCSS CDM 2.0")
        self.assertEqual(result["object_hbr_inputs_km"], {"43013": 0.005, "147": 0.001})
        self.assertEqual(result["collision_probability"].status, "unsupported")
        self.assertIsNone(result["collision_probability"].pc)

    def test_tracss_json_standalone_api_reports_format_and_hbr_provenance(self) -> None:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/collision-probability/cdm",
                json={
                    "cdm_xml": json.dumps(tracss_json_fixture()),
                    "source_label": "synthetic parser contract fixture",
                    "assume_independent_covariances": False,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["input_provenance"]["source_format"], "TraCSS JSON-TraCSS CDM 2.0")
        self.assertFalse(payload["input_provenance"]["source_authenticated"])
        self.assertEqual(payload["data"]["object_hbr_inputs_km"], {"43013": 0.005, "147": 0.001})
        self.assertIn("43013=0.005 km", payload["data"]["collision_probability"]["hbr_provenance"]["description"])

    def test_tracss_json_standard_itf_frame_is_rejected_without_inertial_transform(self) -> None:
        document = tracss_json_fixture()
        document["tracssCdms"][0]["SAT1_REF_FRAME"] = "ITRF"
        document["tracssCdms"][0]["SAT2_REF_FRAME"] = "ITRF"
        with self.assertRaisesRegex(ValueError, "CDM_REFERENCE_FRAME_UNSUPPORTED"):
            parse_cdm_input(json.dumps(document), source_label="synthetic parser contract fixture")

    def test_tracss_json_requires_both_documented_object_hbr_values(self) -> None:
        document = tracss_json_fixture()
        del document["tracssCdms"][0]["SAT2_HBR"]
        del document["tracssCdms"][0]["SAT2_HBR_UNIT"]
        with self.assertRaisesRegex(ValueError, "CDM_HBR_INVALID"):
            parse_cdm_input(json.dumps(document), source_label="synthetic parser contract fixture")

    def test_standalone_reference_cdm_api_does_not_require_or_mutate_screening_job(self) -> None:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/collision-probability/cdm",
                json={
                    "cdm_xml": NASA_CARA_KVN,
                    "source_label": "NASA CARA reference test",
                    "assume_independent_covariances": True,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["result_kind"], "standalone_cdm_reference_assessment")
        self.assertEqual(payload["data"]["object_1"]["id"], "000020580")
        self.assertEqual(payload["data"]["object_2"]["id"], "000002017")
        self.assertEqual(payload["data"]["collision_probability"]["status"], "available")
        self.assertTrue(payload["data"]["collision_probability"]["independence_assumption_authorized"])
        self.assertIsNotNone(payload["data"]["collision_probability"]["pc"])
        self.assertNotIn("RELATIVE_COVARIANCE_CORRELATION_UNKNOWN", payload["data"]["collision_probability"]["reason_codes"])
        self.assertEqual(payload["data"]["source_reported_pc"], 1.862e-5)
        self.assertFalse(payload["data"]["source_authenticated"])

    def test_standalone_reference_cdm_requires_explicit_covariance_independence(self) -> None:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/collision-probability/cdm",
                json={
                    "cdm_xml": NASA_CARA_KVN,
                    "source_label": "NASA CARA reference test",
                    "assume_independent_covariances": False,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        probability = response.json()["data"]["collision_probability"]
        self.assertEqual(probability["status"], "unsupported")
        self.assertFalse(probability["independence_assumption_authorized"])
        self.assertIn("RELATIVE_COVARIANCE_CORRELATION_UNKNOWN", probability["reason_codes"])
        self.assertIsNone(probability["pc"])

    def test_nasa_cara_kvn_reference_cdm_parses_and_calculates_separate_pc(self) -> None:
        parsed = parse_cdm_input(NASA_CARA_KVN, source_label="NASA CARA public Pc test CDM")
        self.assertEqual(parsed.tca_utc, "2023-06-13T00:19:23.766000+00:00")
        self.assertEqual(parsed.message_id, "000020580_conj_000002017_20230613_001923_20230608_063715")
        self.assertEqual(parsed.source_pc, 1.862e-5)
        self.assertEqual(parsed.source_pc_method, "FOSTER-1992")
        self.assertAlmostEqual(parsed.source_miss_distance_km, 12.303)
        self.assertEqual({item.object_designator for item in parsed.inputs}, {"000020580", "000002017"})
        self.assertEqual({item.covariance.frame for item in parsed.inputs}, {"EME2000"})
        self.assertAlmostEqual(parsed.hbr.value_km, 0.01)
        self.assertAlmostEqual(parsed.inputs[0].covariance.matrix[0][0], 23.45734890697948, places=10)
        result = evaluate_cdm_reference(parsed, assume_independent_covariances=True)
        pc = result["collision_probability"]
        self.assertEqual(result["event_id"], f"CDM-{parsed.input_sha256[:24]}")
        self.assertEqual(pc.event_id, result["event_id"])
        self.assertEqual((pc.object_1_id, pc.object_2_id), ("000020580", "000002017"))
        self.assertEqual(pc.status, "available", pc.reason_codes)
        self.assertIsNotNone(pc.pc)
        # The source value is printed to four significant digits in the CDM;
        # this absolute tolerance is the corresponding rounding half-step.
        self.assertAlmostEqual(pc.pc, parsed.source_pc, delta=5e-9)
        self.assertEqual(pc.probability_classification["category"], "ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE")
        # The CDM miss distance is printed to the nearest metre.
        self.assertAlmostEqual(pc.miss_distance_km, parsed.source_miss_distance_km, delta=0.0005)
        self.assertEqual(result["source_reported_pc"], 1.862e-5)
        self.assertTrue(any("not attached to any live TLE" in warning for warning in pc.warnings))

    def test_bundled_nasa_reference_workflow_returns_calculated_pc_comparison_and_identity(self) -> None:
        response = TestClient(main.app).post("/api/collision-probability/reference-cases/nasa-cara-foster-2d")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        case = payload["data"]["reference_case"]
        pc = payload["data"]["collision_probability"]
        self.assertEqual(payload["result_kind"], "standalone_nasa_cara_reference_assessment")
        self.assertEqual(payload["data"]["message_id"], "000020580_conj_000002017_20230613_001923_20230608_063715")
        self.assertEqual((pc["object_1_id"], pc["object_2_id"]), ("000020580", "000002017"))
        self.assertEqual(pc["tca_utc"], "2023-06-13T00:19:23.766000+00:00")
        self.assertEqual(pc["covariance_frame"], "EME2000")
        self.assertEqual(case["expected_pc"], 1.862e-5)
        self.assertEqual(case["comparison_tolerance"], 5e-9)
        self.assertLessEqual(case["absolute_difference"], case["comparison_tolerance"])
        self.assertTrue(case["within_tolerance"])
        self.assertTrue(case["source_url"].startswith("https://github.com/nasa/CARA_Analysis_Tools/"))
        self.assertEqual(pc["probability_classification"]["category"], "ABOVE_NASA_ATTENTION_BELOW_MITIGATION_REFERENCE")
        self.assertIn("standalone", case["live_event_binding"])

    def test_valid_cdm_is_normalized_and_bound_to_user_declared_provenance(self) -> None:
        parsed = parse_cdm_xml(cdm_xml(), source_label="test CDM fixture")
        self.assertEqual(parsed.tca_utc, TCA)
        self.assertEqual({item.object_designator for item in parsed.inputs}, {"A", "B"})
        self.assertEqual({item.covariance.frame for item in parsed.inputs}, {"TEME"})
        self.assertEqual(parsed.inputs[0].covariance.matrix[0][0], 0.1)
        self.assertEqual(parsed.inputs[0].covariance.source_type, "user_supplied")
        self.assertEqual(parsed.hbr.value_km, 0.0005)
        self.assertEqual(parsed.hbr.source_type, "user_supplied")
        self.assertEqual(len(parsed.input_sha256), 64)

    def test_rtn_position_covariance_is_rotated_to_the_cdm_reference_frame(self) -> None:
        xml = cdm_xml()
        xml = xml.replace('<CR_R units="km^2">0.1</CR_R>', '<CR_R units="km^2">0.1</CR_R>', 1)
        xml = xml.replace('<CT_T units="km^2">0.1</CT_T>', '<CT_T units="km^2">0.2</CT_T>', 1)
        xml = xml.replace('<CN_N units="km^2">0.1</CN_N>', '<CN_N units="km^2">0.3</CN_N>', 1)
        xml = xml.replace('<X units="km">7000</X><Y units="km">0</Y><Z units="km">0</Z>', '<X units="km">0</X><Y units="km">7000</Y><Z units="km">0</Z>', 1)
        xml = xml.replace('<X_DOT units="km/s">0</X_DOT><Y_DOT units="km/s">7.5</Y_DOT>', '<X_DOT units="km/s">-7.5</X_DOT><Y_DOT units="km/s">0</Y_DOT>', 1)
        parsed = parse_cdm_xml(xml, source_label="test RTN rotation")
        covariance = parsed.inputs[0].covariance.matrix
        self.assertAlmostEqual(covariance[0][0], 0.2)
        self.assertAlmostEqual(covariance[1][1], 0.1)
        self.assertAlmostEqual(covariance[2][2], 0.3)

    def test_ccsds_m_squared_unit_notation_is_converted_to_km_based_units(self) -> None:
        xml = cdm_xml().replace("km^2/s^2", "m**2/s**2").replace("km^2/s", "m**2/s").replace("km^2", "m**2")
        parsed = parse_cdm_xml(xml, source_label="test CCSDS units")
        self.assertAlmostEqual(parsed.inputs[0].covariance.matrix[0][0], 1e-7)
        self.assertAlmostEqual(parsed.hbr.value_km, 0.0005)

    def test_malformed_missing_hbr_incomplete_covariance_and_unsupported_units_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "CDM_XML_MALFORMED"):
            parse_cdm_xml("<cdm>", source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_HBR_MISSING"):
            parse_cdm_xml(cdm_xml().replace('<HARD_BODY_RADIUS units="m">0.5</HARD_BODY_RADIUS>', ""), source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_COVARIANCE_MATRIX_INCOMPLETE"):
            parse_cdm_xml(re.sub(r"<CNDOT_NDOT[^>]*>.*?</CNDOT_NDOT>", "", cdm_xml(), flags=re.DOTALL), source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_COVARIANCE_UNITS_UNSUPPORTED"):
            parse_cdm_xml(cdm_xml().replace('CR_R units="km^2"', 'CR_R units="furlong^2"'), source_label="fixture")

    def test_event_id_tca_and_frame_mismatches_are_rejected(self) -> None:
        event = physical_event()
        parsed = parse_cdm_xml(cdm_xml(object_a="X"), source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_OBJECT_ID_MISMATCH"):
            apply_cdm_inputs(event, parsed, assume_independent_covariances=True)
        parsed = parse_cdm_xml(cdm_xml(tca="2025-01-01T00:00:01Z"), source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_TCA_MISMATCH"):
            apply_cdm_inputs(event, parsed, assume_independent_covariances=True)
        with self.assertRaisesRegex(ValueError, "CDM_FRAME_MISMATCH"):
            parse_cdm_xml(cdm_xml(frame_b="GCRF"), source_label="fixture")
        parsed = parse_cdm_xml(cdm_xml(frame="EME2000"), source_label="fixture")
        with self.assertRaisesRegex(ValueError, "CDM_FRAME_MISMATCH"):
            apply_cdm_inputs(event, parsed, assume_independent_covariances=True)

    def test_unknown_matching_reference_frame_is_rejected_with_stable_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "CDM_REFERENCE_FRAME_UNSUPPORTED"):
            parse_cdm_xml(cdm_xml(frame="ORION-FICTIONAL-FRAME"), source_label="fixture")

    def test_missing_reference_frame_is_rejected_with_stable_reason(self) -> None:
        xml = cdm_xml().replace("<REF_FRAME>TEME</REF_FRAME>", "", 1)
        with self.assertRaisesRegex(ValueError, "CDM_REFERENCE_FRAME_MISSING"):
            parse_cdm_xml(xml, source_label="fixture")

    def test_covariance_reference_frame_must_be_rtn_for_rtn_component_keys(self) -> None:
        xml = cdm_xml().replace("<REF_FRAME>TEME</REF_FRAME>", "<REF_FRAME>TEME</REF_FRAME><COV_REF_FRAME>GCRF</COV_REF_FRAME>", 1)
        with self.assertRaisesRegex(ValueError, "CDM_COVARIANCE_FRAME_UNSUPPORTED"):
            parse_cdm_xml(xml, source_label="mismatched covariance frame")

    def test_different_segment_frames_are_rejected_before_supported_frame_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "CDM_FRAME_MISMATCH"):
            parse_cdm_xml(cdm_xml(frame="TEME", frame_b="ORION-FICTIONAL-FRAME"), source_label="fixture")

    def test_unsupported_frame_cannot_produce_available_pc_through_event_api(self) -> None:
        job_id = "unsupported-cdm-frame-test-job"
        event = physical_event()
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunction-jobs/{job_id}/events/{event.id}/cdm",
                json={
                    "cdm_xml": cdm_xml(frame="ORION-FICTIONAL-FRAME"),
                    "source_label": "unsupported-frame fixture",
                    "assume_independent_covariances": True,
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["reason_code"], "CDM_REFERENCE_FRAME_UNSUPPORTED")

    def test_imported_cdm_calculates_and_serializes_source_pc_when_explicit_independence_is_authorized(self) -> None:
        updated = apply_cdm_inputs(
            physical_event(),
            parse_cdm_xml(cdm_xml(source_pc=1e-6), source_label="test CDM fixture"),
            assume_independent_covariances=True,
        )
        self.assertEqual(updated.collision_probability.status, "available")
        self.assertGreater(updated.collision_probability.pc, 0)
        self.assertEqual(updated.collision_probability.covariance_sources[0].source_type, "user_supplied")
        self.assertEqual(updated.collision_probability.source_reported_pc, 1e-6)
        self.assertEqual(updated.collision_probability.source_reported_pc_method, "FOSTER-1992")
        self.assertEqual(updated.collision_probability.source_reported_event_id, updated.id)
        self.assertFalse(updated.collision_probability.source_reported_pc_provenance["authenticated"])
        self.assertEqual(updated.physics_result.covariance.status, "unavailable")
        self.assertIsNone(updated.physics_result.hard_body_radius.value)
        self.assertIsNone(updated.physics_result.probability_of_collision.value)
        self.assertIn("the Stage 2A TLE state remains a separate assessment", updated.collision_probability.warnings[-1])
        self.assertAlmostEqual(updated.collision_probability.miss_distance_km, 0.1)
        self.assertIsNone(updated.scenario_collision_probability)

    def test_imported_cdm_without_source_pc_still_gets_orion_computed_pc(self) -> None:
        job_id = "cdm-no-source-pc-test-job"
        event = physical_event()
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunction-jobs/{job_id}/events/{event.id}/cdm",
                json={"cdm_xml": cdm_xml(), "source_label": "event-matched CDM without reported Pc", "assume_independent_covariances": True},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]["collision_probability"]
        self.assertEqual(payload["status"], "available")
        self.assertIsNotNone(payload["pc"])
        self.assertGreater(payload["pc"], 0)
        self.assertIsNone(payload["source_reported_pc"])
        self.assertIsNone(payload["source_reported_event_id"])
        self.assertEqual(payload["event_id"], event.id)
        self.assertEqual(payload["covariance_status"], "available")
        self.assertEqual(payload["hbr_km"], 0.0005)

    def test_live_tle_event_without_covariance_and_hbr_keeps_pc_unavailable(self) -> None:
        event = physical_event()
        probability = event.collision_probability
        self.assertEqual(probability.status, "unavailable")
        self.assertIsNone(probability.pc)
        self.assertIn("NO_COVARIANCE", probability.reason_codes)
        self.assertIn("HBR_UNAVAILABLE", probability.reason_codes)

    def test_unknown_independence_never_produces_source_pc(self) -> None:
        updated = apply_cdm_inputs(
            physical_event(),
            parse_cdm_xml(cdm_xml(), source_label="test CDM fixture"),
            assume_independent_covariances=False,
        )
        self.assertEqual(updated.collision_probability.status, "unsupported")
        self.assertIn("RELATIVE_COVARIANCE_CORRELATION_UNKNOWN", updated.collision_probability.reason_codes)
        self.assertIsNone(updated.collision_probability.pc)

    def test_scenario_result_remains_separate_from_source_supported_physical_result(self) -> None:
        event = physical_event()
        original_physics = event.physics_result.model_dump(mode="json")
        original_pc = event.collision_probability.model_dump(mode="json")
        updated = apply_scenario_inputs(
            event,
            covariance_primary_km2=diagonal_position_covariance(0.1),
            covariance_secondary_km2=diagonal_position_covariance(0.1),
            hbr_km=0.001,
            assumptions="Test-only explicit assumed diagonal scenario parameters.",
            assume_independent_covariances=True,
        )
        self.assertEqual(updated.scenario_collision_probability.status, "available")
        self.assertTrue(updated.scenario_collision_probability.provenance.is_synthetic)
        self.assertEqual(updated.collision_probability.model_dump(mode="json"), original_pc)
        self.assertEqual(updated.physics_result.model_dump(mode="json"), original_physics)
        self.assertIn("RESEARCH SCENARIO ONLY", updated.scenario_assumptions[0])
        self.assertEqual(updated.scenario_inputs["covariance_primary_km2"], diagonal_position_covariance(0.1))
        self.assertEqual(updated.scenario_inputs["covariance_secondary_km2"], diagonal_position_covariance(0.1))
        self.assertEqual(updated.scenario_inputs["hbr_km"], 0.001)
        self.assertEqual(updated.scenario_inputs["frame"], "TEME")
        self.assertTrue(updated.scenario_inputs["assume_independent_covariances"])
        self.assertEqual(updated.scenario_inputs["declared_assumptions"], "Test-only explicit assumed diagonal scenario parameters.")
        self.assertEqual(updated.scenario_inputs["sensitivity_status"], "not_calculated_no_input_uncertainty_ranges")

    def test_scenario_pc_rejects_inconsistent_event_tca_state_metadata_and_geometry(self) -> None:
        mutations = (
            ("state_object_id", lambda event: event.physics_result.primary_state_at_tca.update(object_id="WRONG"), "EVENT_TCA_STATE_OBJECT_ID_MISMATCH"),
            ("state_epoch", lambda event: event.physics_result.primary_state_at_tca.update(epoch="2024-12-31T23:59:59+00:00"), "EVENT_TCA_STATE_EPOCH_MISMATCH"),
            ("state_frame", lambda event: event.physics_result.primary_state_at_tca.update(frame="GCRF"), "EVENT_TCA_STATE_FRAME_MISMATCH"),
            ("state_units", lambda event: event.physics_result.state_information.update(position_units="m"), "EVENT_TCA_STATE_FRAME_OR_UNITS_INVALID"),
            ("miss_distance", lambda event: setattr(event.physics_result.miss_distance, "value", 0.2), "EVENT_MISS_DISTANCE_INCONSISTENT_WITH_TCA_STATES"),
            ("physics_event_id", lambda event: setattr(event.physics_result, "event_id", "OTHER"), "PHYSICS_EVENT_IDENTITY_MISMATCH"),
        )
        for name, mutate, reason in mutations:
            with self.subTest(name=name):
                event = physical_event()
                mutate(event)
                with self.assertRaisesRegex(ValueError, reason):
                    apply_scenario_inputs(
                        event,
                        covariance_primary_km2=diagonal_position_covariance(0.1),
                        covariance_secondary_km2=diagonal_position_covariance(0.1),
                        hbr_km=0.001,
                        assumptions="Test-only explicit assumed scenario parameters.",
                        assume_independent_covariances=True,
                    )

    def test_scenario_api_rejects_inconsistent_state_epoch_without_persisting_pc(self) -> None:
        job_id = "scenario-state-mismatch-test-job"
        event = physical_event()
        event.physics_result.primary_state_at_tca["epoch"] = "2024-12-31T23:59:59+00:00"
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunction-jobs/{job_id}/events/{event.id}/scenario-pc",
                json={
                    "covariance_primary_km2": diagonal_position_covariance(0.1),
                    "covariance_secondary_km2": diagonal_position_covariance(0.1),
                    "hbr_km": 0.001,
                    "assume_independent_covariances": True,
                    "assumptions": "Test-only explicit assumed scenario parameters.",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["reason_code"], "EVENT_TCA_STATE_EPOCH_MISMATCH")
        self.assertIsNone(job["result"]["data"][0]["scenario_collision_probability"])

    def test_job_bound_api_import_updates_only_the_matching_stored_event(self) -> None:
        job_id = "cdm-ingestion-test-job"
        event = physical_event()
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunction-jobs/{job_id}/events/{event.id}/cdm",
                json={"cdm_xml": cdm_xml(source_pc=1e-6), "source_label": "test fixture", "assume_independent_covariances": True},
            )
            persisted = client.get(f"/api/conjunction-jobs/{job_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["job_id"], job_id)
        self.assertEqual(response.json()["input_provenance"]["source_authenticated"], False)
        self.assertEqual(response.json()["data"]["collision_probability"]["status"], "available")
        self.assertEqual(response.json()["data"]["collision_probability"]["source_reported_pc"], 1e-6)
        self.assertEqual(response.json()["data"]["collision_probability"]["source_reported_event_id"], event.id)
        self.assertEqual(persisted.json()["result"]["data"][0]["collision_probability"]["status"], "available")
        self.assertEqual(persisted.json()["result"]["data"][0]["collision_probability"]["source_reported_pc"], 1e-6)

    def test_scenario_api_serializes_separate_result_and_preserves_source_pc(self) -> None:
        job_id = "scenario-test-job"
        event = physical_event()
        original_pc = event.collision_probability.model_dump(mode="json")
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunction-jobs/{job_id}/events/{event.id}/scenario-pc",
                json={
                    "covariance_primary_km2": diagonal_position_covariance(0.1),
                    "covariance_secondary_km2": diagonal_position_covariance(0.1),
                    "hbr_km": 0.001,
                    "assume_independent_covariances": True,
                    "assumptions": "Test-only explicit assumed scenario parameters.",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["data"]
        self.assertEqual(payload["collision_probability"], original_pc)
        self.assertEqual(payload["scenario_collision_probability"]["status"], "available")
        self.assertTrue(payload["scenario_collision_probability"]["provenance"]["is_synthetic"])
        self.assertEqual(payload["scenario_inputs"]["hbr_km"], 0.001)
        self.assertEqual(payload["scenario_inputs"]["tca_utc"], event.physics_result.tca.value)

    def test_job_event_and_selected_object_mismatches_return_422(self) -> None:
        job_id = "mismatch-test-job"
        event = physical_event()
        job = {"job_id": job_id, "status": "complete", "result": {"data": [event.model_dump(mode="json")]}}
        with patch.dict(main._screening_jobs, {job_id: job}), TestClient(main.app) as client:
            missing = client.post(f"/api/conjunction-jobs/{job_id}/events/other/cdm", json={"cdm_xml": cdm_xml(), "source_label": "test", "assume_independent_covariances": True})
            mismatch = client.post(f"/api/conjunction-jobs/{job_id}/events/{event.id}/cdm", json={"cdm_xml": cdm_xml(object_a="X"), "source_label": "test", "assume_independent_covariances": True})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(mismatch.json()["detail"]["reason_code"], "CDM_OBJECT_ID_MISMATCH")


def physical_event() -> ConjunctionAssessmentEvent:
    event_id = "EV-INPUT-TEST"
    provenance = Provenance(source="test Stage 2A state", source_type="fallback", method="test fixture", method_version="1", reference_frame="TEME", validity_status="valid", is_fallback=True)
    primary = object_summary("A", provenance)
    secondary = object_summary("B", provenance)
    physics = PhysicsResult(
        event_id=event_id,
        status="valid",
        applicability="test fixture only",
        provenance=provenance,
        object_primary_id="A",
        object_secondary_id="B",
        screening_horizon_start="2024-12-31T23:00:00+00:00",
        screening_horizon_end="2025-01-01T01:00:00+00:00",
        screening_threshold_km=25,
        tca_status="valid",
        state_information={"source_frame": "TEME", "position_units": "km", "velocity_units": "km/s"},
        tca=ScientificField(status="available", value=TCA, units="UTC"),
        miss_distance=ScientificField(status="available", value=0.1, units="km"),
        relative_position_at_tca=ScientificField(status="available", value=[0.1, 0, 0], units="km"),
        relative_velocity_at_tca=ScientificField(status="available", value=[0, -0.1, 0], units="km/s"),
        relative_speed_at_tca=ScientificField(status="available", value=0.1, units="km/s"),
        primary_state_at_tca={"object_id": "A", "epoch": TCA, "position_km": [7000, 0, 0], "velocity_km_s": [0, 7.5, 0], "frame": "TEME"},
        secondary_state_at_tca={"object_id": "B", "epoch": TCA, "position_km": [7000.1, 0, 0], "velocity_km_s": [0, 7.4, 0], "frame": "TEME"},
    )
    from app.services.collision_probability import calculate_foster_2d
    unavailable_pc = calculate_foster_2d(event_id=event_id, object_1_id="A", object_2_id="B", tca_utc=TCA, tca_status="valid")
    return ConjunctionAssessmentEvent(
        id=event_id,
        primary=primary,
        secondary=secondary,
        obj_a=primary,
        obj_b=secondary,
        pair_type="SATELLITE vs DEBRIS",
        provenance=provenance,
        physics_result=physics,
        collision_probability=unavailable_pc,
    )


def object_summary(object_id: str, provenance: Provenance) -> ObjectSummary:
    return ObjectSummary(
        id=object_id, name=f"Test object {object_id}", category="active" if object_id == "A" else "debris",
        object_type="TEST", band="LEO", orbit_type="test", altitude_km=700, inclination_deg=51,
        velocity_kms=7.5, heuristic_risk_score=0.1, heuristic_forecast_score=0.1,
        provenance=provenance, heuristic_score_provenance=provenance,
    )


def diagonal_covariance(position_variance: float, velocity_variance: float) -> list[list[float]]:
    values = [position_variance] * 3 + [velocity_variance] * 3
    return [[values[row] if row == col else 0 for col in range(6)] for row in range(6)]


def diagonal_position_covariance(position_variance: float) -> list[list[float]]:
    return [[position_variance if row == col else 0 for col in range(3)] for row in range(3)]


def tracss_json_fixture() -> dict:
    """Small synthetic contract fixture using TraCSS Spec 001 v2.1 field names."""
    record = {
        "TRACSS_CDM_VERS": "2.0",
        "CREATION_DATE": "2025-05-16T02:14:49.000",
        "ORIGINATOR": "TEST ONLY",
        "MESSAGE_ID": "synthetic-parser-fixture",
        "TCA": "2025-05-16T11:08:55.944",
        "MISS_DISTANCE": "1000",
        "MISS_DISTANCE_UNIT": "m",
        "COLLISION_PROBABILITY": "1e-6",
        "COLLISION_PROBABILITY_METHOD": "FOSTER-1992",
    }
    axes = ("R", "T", "N", "RDOT", "TDOT", "NDOT")
    for index, (designator, x, hbr) in enumerate((("43013", "7000", "5"), ("147", "7000", "1")), start=1):
        prefix = f"SAT{index}_"
        record.update({
            prefix + "OBJECT_DESIGNATOR": designator,
            prefix + "OBJECT_NAME": f"synthetic object {index}",
            prefix + "REF_FRAME": "EME2000",
            prefix + "HBR": hbr,
            prefix + "HBR_UNIT": "m",
            prefix + "X": x,
            prefix + "X_UNIT": "km",
            prefix + "Y": str(index - 1),
            prefix + "Y_UNIT": "km",
            prefix + "Z": "0",
            prefix + "Z_UNIT": "km",
            prefix + "X_DOT": "0",
            prefix + "X_DOT_UNIT": "km/s",
            prefix + "Y_DOT": "7.5",
            prefix + "Y_DOT_UNIT": "km/s",
            prefix + "Z_DOT": "0",
            prefix + "Z_DOT_UNIT": "km/s",
        })
        for row, axis in enumerate(axes):
            for col in range(row + 1):
                other = axes[col]
                key = prefix + f"C{axis}_{other}"
                is_position = row < 3 and col < 3
                is_velocity = row >= 3 and col >= 3
                unit = "m**2" if is_position else "m**2/s**2" if is_velocity else "m**2/s"
                record[key] = "4" if row == col and is_position else "0.01" if row == col else "0"
                record[key + "_UNIT"] = unit
    return {"tracssCdms": [record]}


def cdm_xml(*, object_a: str = "A", object_b: str = "B", tca: str = TCA, frame: str = "TEME", frame_b: str | None = None, source_pc: float | None = None) -> str:
    axis = ("R", "T", "N", "RDOT", "TDOT", "NDOT")
    units = {"pp": "km^2", "pv": "km^2/s", "vv": "km^2/s^2"}
    segments = []
    for index, designator in enumerate((object_a, object_b)):
        object_frame = frame if index == 0 or frame_b is None else frame_b
        entries = []
        for row in range(6):
            for col in range(row + 1):
                is_pos = row < 3 and col < 3
                is_vel = row >= 3 and col >= 3
                dimension = "pp" if is_pos else "vv" if is_vel else "pv"
                value = 0.1 if row == col and row < 3 else 0.000001 if row == col else 0
                name = f"C{axis[row]}_{axis[col]}"
                entries.append(f'<{name} units="{units[dimension]}">{value}</{name}>')
        segments.append(
            f"<segment><metadata><OBJECT>OBJECT1</OBJECT><OBJECT_DESIGNATOR>{designator}</OBJECT_DESIGNATOR>"
            f"<OBJECT_ID>TEST-{designator}</OBJECT_ID><REF_FRAME>{object_frame}</REF_FRAME><COVARIANCE_TYPE>CARTESIAN</COVARIANCE_TYPE></metadata>"
            f"<data><stateVector><X units=\"km\">{7000 if index == 0 else 7000.1}</X><Y units=\"km\">0</Y><Z units=\"km\">0</Z>"
            f"<X_DOT units=\"km/s\">0</X_DOT><Y_DOT units=\"km/s\">{7.5 if index == 0 else 7.4}</Y_DOT><Z_DOT units=\"km/s\">0</Z_DOT></stateVector>"
            f"<covarianceMatrix>{''.join(entries)}</covarianceMatrix></data></segment>"
        )
    source_pc_fields = (
        f"<COLLISION_PROBABILITY>{source_pc}</COLLISION_PROBABILITY>"
        "<COLLISION_PROBABILITY_METHOD>FOSTER-1992</COLLISION_PROBABILITY_METHOD>"
        if source_pc is not None else ""
    )
    return (
        "<cdm><header><CREATED>2025-01-01T00:01:00Z</CREATED><ORIGINATOR>TEST ONLY</ORIGINATOR></header>"
        f"<body><relativeMetadata><TCA>{tca}</TCA><HARD_BODY_RADIUS units=\"m\">0.5</HARD_BODY_RADIUS>"
        f"{source_pc_fields}</relativeMetadata>"
        f"{''.join(segments)}</body></cdm>"
    )


# Verbatim numerical state/covariance fields from NASA CARA_Analysis_Tools
# DataFiles/PcTestCaseCDMs/000020580_conj_000002017_20230613_001923_20230608_063715.cdm.
# NASA source: https://github.com/nasa/CARA_Analysis_Tools/blob/master/DataFiles/PcTestCaseCDMs/000020580_conj_000002017_20230613_001923_20230608_063715.cdm
NASA_CARA_KVN = (Path(__file__).parent / "fixtures" / "nasa_cara_pc_reference.cdm").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
