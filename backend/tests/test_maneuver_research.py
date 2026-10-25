import unittest
import math
import time
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app import main
from app.models import AutomaticResearchPcAssessment, CollisionProbabilityResult, ComparisonResult, ConjunctionAssessmentEvent, MLResult, ObjectSummary, OrbitalAnomalyResult, PhysicsResult, Provenance, ScientificField
from app.services.conjunction import _maneuver_research_pc, _propagate_samples, _refine_sampled_minimum, _rk4, optimize_maneuver
from app.services.automatic_research_pc import assess_automatic_research_pc
from app.ai.collision_training import read_parent_events
from app.services.orbit import propagate_records
from app.services.tle_provider import parse_tle_text
import app.services.trajectory_screening as trajectory_screening
import app.ai.maneuver_ranker as maneuver_ranker


EPOCH = "2025-01-01T00:00:00+00:00"
REAL_TLE_FIXTURE_START = datetime.fromisoformat("2026-10-13T12:10:22.590000+00:00")
REAL_TLE_FIXTURE_RECORDS = (
    (
        "COSMOS 2251\n1 22675U 93036A   26285.93214546  .00000073  00000+0  35918-4 0  9999\n"
        "2 22675  74.0370 120.0610 0023996 132.3110 228.0080 14.33273188741311",
        "cosmos_debris",
        "2026-10-13T12:10:21.534664+00:00",
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-2251-debris&FORMAT=TLE",
        "1ee37bc96e35283d2d9176eb7c81806547a6062bc8530de828443ceda20483f4",
    ),
    (
        "IRIDIUM 33 DEB\n1 33870U 97051AP  26285.96568532  .00001809  00000+0  48993-3 0  9993\n"
        "2 33870  86.3691 287.7128 0018141 248.6443 139.4894 14.47132973925350",
        "iridium_debris",
        "2026-10-13T12:10:21.131364+00:00",
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-33-debris&FORMAT=TLE",
        "8e4b8c80f2c4e71d78eac0fe34cbbff3be763991ff21d5f768ac8f017c70c0dc",
    ),
)
REAL_TLE_MULTI_CASES = (
    {
        "stored_event_id": "CA-0E45D17A7FD97444E98C",
        "replay_event_id": "CA-CDBC9233F65C7BE0EE0A",
        "pair": ("33762", "33776"),
        "stored_tca": "2026-10-14T06:22:15.243382+00:00",
        "stored_miss_km": 21.946216702033038,
        "replay_tca": "2026-10-14T06:22:15.243148+00:00",
        "replay_miss_km": 21.946217950319106,
        "records": (
            ("COSMOS 2251 DEB\n1 33762U 93036K   26286.64287698  .00000069  00000+0  34014-4 0  9996\n2 33762  74.0390 112.5641 0014240 105.0979 331.8326 14.33737591924170", "cosmos_debris", "2026-10-14T06:01:30.677075+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-2251-debris&FORMAT=TLE", "d8f9e202d5b7c07dd0afb1760dc602b9d7449569f76c93eaffc9e4717543986a"),
            ("IRIDIUM 33 DEB\n1 33776U 97051P   26286.56590829  .00000577  00000+0  18178-3 0  9992\n2 33776  86.4018 312.7314 0012203 277.6953 195.0424 14.38652239924646", "iridium_debris", "2026-10-14T06:01:29.847801+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-33-debris&FORMAT=TLE", "43d80d178dc33240c33676584ed4d962e4ed297a77a16b5a2639dc85f12d4e3f"),
        ),
    },
    {
        "stored_event_id": "CA-14365994EC97422475C2",
        "replay_event_id": "CA-1469EBDA89F2BC86704C",
        "pair": ("05560", "33758"),
        "stored_tca": "2026-10-14T09:46:53.177064+00:00",
        "stored_miss_km": 5.506604732139153,
        "replay_tca": "2026-10-14T09:46:53.177605+00:00",
        "replay_miss_km": 5.506603401422112,
        "records": (
            ("ASTEX 1\n1 05560U 71089A   26286.83485240  .00000420  00000+0  10639-3 0  9996\n2 05560  92.7154 222.1424 0017752  70.2248 290.0870 14.50928448893931", "visual", "2026-10-14T06:01:29.943187+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=TLE", "95926ddf078d4a0ec2803b6da6c31985331dd14c2ef5673ff32ca7adf91c8779"),
            ("COSMOS 2251 DEB\n1 33758U 93036F   26286.66461397  .00002354  00000+0  57268-3 0  9997\n2 33758  74.0298 359.7417 0017174 350.0328 161.9737 14.53285369927328", "cosmos_debris", "2026-10-14T06:01:30.677075+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-2251-debris&FORMAT=TLE", "d8f9e202d5b7c07dd0afb1760dc602b9d7449569f76c93eaffc9e4717543986a"),
        ),
    },
    {
        "stored_event_id": "CA-2C674611A47F15400B76",
        "replay_event_id": "CA-42115326481265331187",
        "pair": ("10967", "33761"),
        "stored_tca": "2026-10-14T12:27:22.877726+00:00",
        "stored_miss_km": 4.370215863115639,
        "replay_tca": "2026-10-14T12:27:22.878701+00:00",
        "replay_miss_km": 4.370224958145784,
        "records": (
            ("SEASAT 1\n1 10967U 78064A   26286.79142995  .00000340  00000+0  13318-3 0  9993\n2 10967 108.0099 223.2307 0002597 286.4630  73.6231 14.46305386538045", "visual", "2026-10-14T06:01:29.943187+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=TLE", "95926ddf078d4a0ec2803b6da6c31985331dd14c2ef5673ff32ca7adf91c8779"),
            ("COSMOS 2251 DEB\n1 33761U 93036J   26286.78167957  .00001095  00000+0  33251-3 0  9996\n2 33761  74.0366  45.8232 0022198  53.1880  70.6776 14.43226061926345", "cosmos_debris", "2026-10-14T06:01:30.677075+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-2251-debris&FORMAT=TLE", "d8f9e202d5b7c07dd0afb1760dc602b9d7449569f76c93eaffc9e4717543986a"),
        ),
    },
    {
        "stored_event_id": "CA-33433777811BD607D203",
        "replay_event_id": "CA-AFE6985DB5B3791D96BF",
        "pair": ("24946", "33776"),
        "stored_tca": "2026-10-14T15:20:52.448517+00:00",
        "stored_miss_km": 22.183029131358662,
        "replay_tca": "2026-10-14T15:20:52.448445+00:00",
        "replay_miss_km": 22.183029130807117,
        "records": (
            ("IRIDIUM 33\n1 24946U 97051C   26286.54131464  .00000202  00000+0  63807-4 0  9990\n2 24946  86.3828 300.2841 0006061 309.5601  50.5059 14.35185780522068", "iridium_debris", "2026-10-14T06:01:29.847801+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-33-debris&FORMAT=TLE", "43d80d178dc33240c33676584ed4d962e4ed297a77a16b5a2639dc85f12d4e3f"),
            ("IRIDIUM 33 DEB\n1 33776U 97051P   26286.56590829  .00000577  00000+0  18178-3 0  9992\n2 33776  86.4018 312.7314 0012203 277.6953 195.0424 14.38652239924646", "iridium_debris", "2026-10-14T06:01:29.847801+00:00", "https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-33-debris&FORMAT=TLE", "43d80d178dc33240c33676584ed4d962e4ed297a77a16b5a2639dc85f12d4e3f"),
        ),
    },
)


def _screen_with_ai_hooks_stubbed(records, start_utc, *, horizon_hours, sample_step_seconds, screening_threshold_km):
    prediction_stub = Mock(return_value=MLResult(status="unavailable", reason_code="VALIDATION_AI_HOOK_STUB"))
    anomaly_stub = Mock(return_value=OrbitalAnomalyResult(status="unavailable", reason_code="VALIDATION_AI_HOOK_STUB"))
    comparison_stub = Mock(return_value=ComparisonResult(status="not_applicable", reason_code="VALIDATION_AI_HOOK_STUB"))
    objects, _, unavailable = propagate_records(records, limit=len(records), now=start_utc)
    with (
        patch.object(trajectory_screening, "predict_from_physics", new=prediction_stub),
        patch.object(trajectory_screening, "predict_orbital_anomaly", new=anomaly_stub),
        patch.object(trajectory_screening, "compare_ml_and_physics", new=comparison_stub),
    ):
        # Assert replacements immediately before the screening invocation.
        assert trajectory_screening.predict_from_physics is prediction_stub
        assert trajectory_screening.predict_orbital_anomaly is anomaly_stub
        assert trajectory_screening.compare_ml_and_physics is comparison_stub
        run = trajectory_screening.screen_tle_records(
            records,
            objects,
            start_utc=start_utc,
            horizon_hours=horizon_hours,
            sample_step_seconds=sample_step_seconds,
            screening_threshold_km=screening_threshold_km,
            unavailable_objects=unavailable,
        )
    return run, prediction_stub, anomaly_stub, comparison_stub


def _object(object_id, category):
    provenance = Provenance(source="test TLE", source_type="fallback", object_id=object_id, reference_frame="TEME")
    return ObjectSummary(id=object_id, name=object_id, category=category, object_type="ACTIVE_SATELLITE" if category == "active" else "SPACE_DEBRIS", band="LEO", orbit_type="LEO", altitude_km=621.86, inclination_deg=0, velocity_kms=7.5, heuristic_risk_score=0.2, heuristic_forecast_score=0.2, provenance=provenance, heuristic_score_provenance=provenance)


def _event():
    primary, secondary = _object("11111", "active"), _object("22222", "debris")
    provenance = Provenance(source="test", source_type="fallback", reference_frame="TEME", method="fixture", validity_status="valid", is_fallback=True)
    state1 = {"object_id": primary.id, "epoch": EPOCH, "position_km": [7000.0, 0.0, 0.0], "velocity_km_s": [0.0, 7.5, 0.0], "frame": "TEME"}
    state2 = {"object_id": secondary.id, "epoch": EPOCH, "position_km": [7000.0, 1.0, 0.0], "velocity_km_s": [0.0, 7.5, 0.0], "frame": "TEME"}
    physics = PhysicsResult(event_id="event-1", status="valid", applicability="test", provenance=provenance, object_primary_id=primary.id, object_secondary_id=secondary.id, state_information={"source_frame": "TEME", "target_frame": "TEME", "position_units": "km", "velocity_units": "km/s"}, tca_status="valid", tca=ScientificField(status="available", value=EPOCH, units="UTC"), miss_distance=ScientificField(status="available", value=1.0, units="km"), primary_state_at_tca=state1, secondary_state_at_tca=state2)
    return ConjunctionAssessmentEvent(id="event-1", primary=primary, secondary=secondary, obj_a=primary, obj_b=secondary, pair_type="SATELLITE vs DEBRIS", provenance=provenance, physics_result=physics)


class ResearchManeuverTests(unittest.TestCase):
    def test_maneuver_baseline_matches_collision_analysis_for_every_valid_saved_parent(self):
        _snapshot, events = read_parent_events()
        compared = 0
        for event in events:
            assessment = event.automatic_research_pc_assessment
            if assessment is None or assessment.status != "prior_based_research_estimate":
                assessment = assess_automatic_research_pc(
                    event.physics_result, event.collision_probability, event.review_priority,
                    primary=event.primary, secondary=event.secondary,
                )
                event = event.model_copy(update={"automatic_research_pc_assessment": assessment})
            self.assertEqual(assessment.status, "prior_based_research_estimate", event.id)
            maneuver_baseline = _maneuver_research_pc(event, {"delta_v_m_s": 0.0}, covariance_scale=1.0)
            self.assertEqual(maneuver_baseline["status"], "available", event.id)
            self.assertEqual(maneuver_baseline["pc_scientific"], assessment.estimated_pc_scientific, event.id)
            self.assertEqual(maneuver_baseline["log10_pc"], assessment.log10_pc, event.id)
            self.assertEqual(maneuver_baseline["hbr_km"], assessment.hbr_km, event.id)
            self.assertEqual(maneuver_baseline["comparison_role"], "collision_analysis_research_pc_record", event.id)
            compared += 1
        self.assertEqual(compared, 118)

    def test_zero_burn_baseline_reuses_selected_collision_analysis_research_pc(self):
        event = _event()
        event.automatic_research_pc_assessment = AutomaticResearchPcAssessment(
            status="prior_based_research_estimate", quality_status="prior_based_unvalidated",
            estimated_pc=2.5e-7, estimated_pc_scientific="2.500000e-7", log10_pc=math.log10(2.5e-7),
            covariance_policy_id="tle_age_baseline", covariance_method="configured TLE-age policy",
            hbr_method="assumed object-size HBR", hbr_km=0.001,
        )
        baseline = optimize_maneuver(event, lead_seconds=180, burn_magnitudes_m_s=(0.01,), refine_candidates=False)["probability_before"]
        self.assertEqual(baseline["comparison_role"], "collision_analysis_research_pc_record")
        self.assertEqual(baseline["pc_scientific"], event.automatic_research_pc_assessment.estimated_pc_scientific)
        self.assertEqual(baseline["log10_pc"], event.automatic_research_pc_assessment.log10_pc)
        self.assertEqual(baseline["event_id"], event.id)

    def test_user_maneuver_upload_validates_json_and_csv_state_requirements(self):
        event = _event()
        event.provenance.source_type = "user_supplied"
        event.provenance.is_fallback = False
        for obj in (event.primary, event.secondary):
            obj.provenance.source_type = "user_supplied"
            obj.provenance.is_fallback = False
        body = event.model_dump(mode="json")
        for obj in (event.primary, event.secondary):
            obj.provenance.element_epoch = EPOCH
        valid_body = event.model_dump(mode="json")
        csv_payload = "event_json\r\n\"" + json.dumps(valid_body, separators=(",", ":")).replace("\"", "\"\"") + "\"\r\n"
        with TestClient(main.app) as client:
            with patch.object(main, "optimize_maneuver", return_value={"event_id": event.id, "status": "available_with_warning"}):
                valid_response = client.post("/api/maneuver/user-upload", json=valid_body)
                valid_csv_response = client.post("/api/maneuver/user-upload", content=csv_payload, headers={"content-type": "text/csv"})
            json_response = client.post("/api/maneuver/user-upload", json=body)
            csv_response = client.post("/api/maneuver/user-upload", content="event_json\n\"{}\"\n", headers={"content-type": "text/csv"})
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(valid_response.json()["data"]["event_id"], event.id)
        self.assertTrue(valid_response.json()["data"]["user_supplied_input"])
        self.assertEqual(valid_csv_response.status_code, 200)
        self.assertEqual(json_response.status_code, 422)
        self.assertEqual(json_response.json()["detail"]["reason_code"], "MANDATORY_STATE_OR_EPOCH_MISSING")
        self.assertEqual(csv_response.status_code, 422)
        self.assertEqual(csv_response.json()["detail"]["reason_code"], "INVALID_MANEUVER_UPLOAD")

    def test_created_job_to_selected_event_maneuver_and_report_preserves_identity(self):
        event = _event()
        event.provenance.source_type = "live"
        event.provenance.is_fallback = False
        event.physics_result.provenance.source_type = "live"
        event.physics_result.provenance.is_fallback = False
        event.primary.provenance.source_type = "live"
        event.primary.provenance.is_fallback = False
        event.secondary.provenance.source_type = "live"
        event.secondary.provenance.is_fallback = False
        body = event.model_dump(mode="json")
        result = {
            "success": True, "result_kind": "physics_assessment", "result_status": "valid_non_empty",
            "completion_status": "complete", "physics_assessment_status": "valid", "data": [body],
            "source_summary": {"status": "all_live", "object_count": 2},
            "screening": {"status": "valid", "completion_status": "complete"},
        }
        with TestClient(main.app) as client, patch.object(main, "conjunctions", new=AsyncMock(return_value=result)), patch.object(
            main, "optimize_maneuver", return_value={"status": "available_with_warning", "event_id": event.id, "candidates": []},
        ) as optimize:
            accepted = client.post("/api/conjunction-jobs?limit=2&horizon_hours=1&sample_step_seconds=60&screening_threshold_km=25")
            self.assertEqual(accepted.status_code, 202)
            job_id = accepted.json()["job_id"]
            state = None
            for _ in range(20):
                polled = client.get(f"/api/conjunction-jobs/{job_id}")
                state = polled.json()
                if state.get("status") in {"complete", "partial", "failed"}:
                    break
                time.sleep(0.01)
            self.assertEqual(state["status"], "complete")
            stored = state["result"]["data"][0]
            self.assertEqual(stored["screening_job_id"], job_id)
            maneuver = client.post(
                f"/api/conjunctions/{event.id}/maneuver?screening_job_id={job_id}&burn_magnitudes_m_s=0.01",
                json=stored,
            )
            report = client.get(f"/api/conjunction-jobs/{job_id}/events/{event.id}/report.pdf")
            main._screening_jobs.pop(job_id, None)

        self.assertEqual(maneuver.status_code, 200)
        self.assertEqual(maneuver.json()["screening_job_id"], job_id)
        self.assertEqual(maneuver.json()["data"]["event_id"], event.id)
        optimized_event = optimize.call_args.args[0]
        self.assertEqual(optimized_event.id, event.id)
        self.assertEqual((optimized_event.primary.id, optimized_event.secondary.id), (event.primary.id, event.secondary.id))
        self.assertEqual(optimized_event.provenance.source, event.provenance.source)
        self.assertEqual(optimized_event.provenance.source_type, "live")
        self.assertEqual(optimized_event.provenance.validity_status, "valid")
        self.assertEqual(optimized_event.screening_job_id, job_id)
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.content.startswith(b"%PDF-"))
        self.assertIn(event.id.encode(), report.content)
        self.assertIn(job_id.encode(), report.content)

    def test_saved_maneuver_ranker_predicts_pc_reduction_and_requires_physics_confirmation(self):
        event = _event()
        result = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,), refine_candidates=False)
        self.assertEqual(result["physics_candidate_status"], "evaluated")
        self.assertEqual(result["status"], "available_with_warning")
        self.assertEqual(result["ml_result"]["status"], "fallback_physics_ranking")
        self.assertEqual(result["ml_result"]["reason_code"], "HELD_OUT_RANKING_NOT_USEFUL_VS_BASELINE")
        self.assertEqual(result["ml_result"]["model_name"], "ORION physics-supervised maneuver research-Pc reduction ranker")
        self.assertEqual(result["ml_result"]["model_version"], "2.0.0")
        self.assertEqual(result["ml_result"]["score_units"], "log10 ratio; positive predicts reduction")
        self.assertEqual(result["ml_result"]["provenance"]["source_event_id"], event.id)
        scored = [row for row in result["candidates"] if row.get("maneuver_ml_predicted_log10_pc_reduction") is not None]
        self.assertTrue(scored)
        self.assertTrue(all(row.get("maneuver_ml_rank") is None for row in result["candidates"]))
        self.assertTrue(all(row["maneuver_ml_status"] == "physics_fallback_rank" for row in scored))
        evaluation = result["ml_result"]["evaluation_summary"]
        self.assertEqual(evaluation["held_out_scenario_count"], 8)
        self.assertAlmostEqual(evaluation["top1_agreement_with_physics_best"], 0.625)
        self.assertGreater(evaluation["model_mean_regret_log10_pc_reduction"], evaluation["baseline_mean_regret_log10_pc_reduction"])
        self.assertEqual(result["candidates"][0]["direction"], "zero-burn baseline")
        self.assertIsNone(result["candidates"][0]["maneuver_ml_rank"])
        self.assertTrue(all(isinstance(row["predicted_miss_distance_km"], (int, float)) for row in result["candidates"]))

    def test_maneuver_ranker_rejects_bad_event_states_and_missing_artifact_explicitly(self):
        event = _event()
        action = {"delta_v_m_s": 0.01, "direction": "radial +"}
        with self.assertRaisesRegex(ValueError, "STATE_VECTOR_INVALID"):
            event.physics_result.primary_state_at_tca["position_km"] = [float("nan"), 0.0, 0.0]
            maneuver_ranker.feature_vector(event, action, 300)
        event = _event()
        event.physics_result.event_id = "other-event"
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            maneuver_ranker.feature_vector(event, action, 300)
        event = _event()
        event.physics_result.state_information["position_units"] = "m"
        with self.assertRaisesRegex(ValueError, "FRAME_OR_UNITS_INVALID"):
            maneuver_ranker.feature_vector(event, action, 300)
        event = _event()
        event.physics_result.secondary_state_at_tca["epoch"] = "2025-01-01T00:01:00+00:00"
        with self.assertRaisesRegex(ValueError, "EPOCH_OR_FRAME_MISMATCH"):
            maneuver_ranker.feature_vector(event, action, 300)
        event = _event()
        event.physics_result.primary_state_at_tca["epoch"] = "2025-01-01T05:30:00+05:30"
        self.assertEqual(len(maneuver_ranker.feature_vector(event, action, 300)), len(maneuver_ranker.FEATURES))

        maneuver_ranker._load_model.cache_clear()
        original = maneuver_ranker.ARTIFACT_PATH
        try:
            maneuver_ranker.ARTIFACT_PATH = Path("missing-maneuver-ranker.joblib")
            unavailable = maneuver_ranker.score_candidates(_event(), [action], 300)
            self.assertEqual(unavailable["status"], "unavailable")
            self.assertEqual(unavailable["reason_code"], "MANEUVER_MODEL_ARTIFACT_UNAVAILABLE")
            self.assertEqual(unavailable["candidate_scores"], {})
        finally:
            maneuver_ranker.ARTIFACT_PATH = original
            maneuver_ranker._load_model.cache_clear()

    def test_maneuver_model_inference_failure_does_not_replace_physics_outcomes(self):
        class BrokenEstimator:
            def predict(self, _features):
                raise RuntimeError("injected model failure")

        maneuver_ranker._load_model.cache_clear()
        with patch.object(maneuver_ranker, "_load_model", return_value=({"estimator": BrokenEstimator()}, {"model_name": "fixture", "model_version": "fixture", "limitations": []}, None)):
            result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(result["physics_candidate_status"], "evaluated")
        self.assertEqual(result["ml_result"]["status"], "unavailable")
        self.assertEqual(result["ml_result"]["reason_code"], "MANEUVER_MODEL_INFERENCE_FAILED")
        self.assertGreater(len(result["candidates"]), 7)
        self.assertTrue(all(row["predicted_miss_distance_km"] is not None for row in result["candidates"]))
        maneuver_ranker._load_model.cache_clear()

    def test_unexpected_ranker_exception_keeps_structured_physics_blocks(self):
        with patch("app.services.conjunction.score_candidates", side_effect=RuntimeError("ranker unavailable")):
            result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(result["physics_candidate_status"], "evaluated")
        self.assertEqual(result["surrogate_rank"]["status"], "unavailable")
        self.assertEqual(result["surrogate_rank"]["reason_code"], "MANEUVER_MODEL_INFERENCE_FAILED")
        self.assertTrue(result["surrogate_rank"]["is_simulator_surrogate"])
        self.assertFalse(result["surrogate_rank"]["synthetic_training_labels"])
        self.assertFalse(result["surrogate_rank"]["ranking_used"])
        self.assertEqual(result["stage2a_reference"]["event_id"], "event-1")
        self.assertEqual(result["stage2a_reference"]["propagator"], "SGP4")
        self.assertEqual(result["zero_burn_baseline"]["method"], "Earth two-body point-mass RK4")
        self.assertGreaterEqual(len(result["physics_candidates"]["candidates"]), 6)
        self.assertEqual(result["probability_before"]["status"], "unavailable")
        self.assertEqual(result["probability_after"]["status"], "unavailable")
        self.assertEqual(result["probability_reason_code"], "TLE_ELEMENT_EPOCH_UNAVAILABLE")
        self.assertIsNotNone(result["fuel_cost_kg"])
        self.assertEqual(result["fuel"]["assumption_status"], "estimated_from_default_assumptions")
    def test_search_boundary_candidates_are_not_assigned_ml_ranks(self):
        with patch("app.services.conjunction._refine_sampled_minimum", side_effect=lambda times, distances, evaluate: {
            "distance_km": float(min(distances)), "elapsed_seconds": float(times[0]),
            "sample_index": 0, "refinement_evaluations": 0,
        }):
            result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(result["physics_candidate_status"], "evaluated")
        self.assertEqual(result["ml_result"]["status"], "fallback_physics_ranking")
        self.assertFalse(result["ml_result"]["ranking_used"])
        self.assertTrue(all(row["objective_status"] == "search_boundary_minimum" for row in result["candidates"]))
        self.assertTrue(all(row["maneuver_ml_rank"] is None for row in result["candidates"]))

    def test_captured_real_tle_screening_event_has_repeatable_zero_burn_baseline(self):
        records = [
            parse_tle_text(
                text,
                source_group,
                source_timestamp=source_timestamp,
                source_type="live",
                source_url=source_url,
                retrieval_http_status=200,
                raw_response_hash=raw_response_hash,
            )[0]
            for text, source_group, source_timestamp, source_url, raw_response_hash in REAL_TLE_FIXTURE_RECORDS
        ]
        run, prediction_stub, anomaly_stub, comparison_stub = _screen_with_ai_hooks_stubbed(
            records,
            REAL_TLE_FIXTURE_START,
            horizon_hours=24.0,
            sample_step_seconds=60,
            screening_threshold_km=25.0,
        )

        self.assertEqual(run.summary["status"], "valid")
        self.assertEqual(prediction_stub.call_count, 1)
        self.assertEqual(anomaly_stub.call_count, 1)
        self.assertEqual(comparison_stub.call_count, 1)
        self.assertEqual(run.summary["valid_track_count"], 2)
        self.assertEqual(run.summary["candidate_pair_count"], 1)
        self.assertEqual(len(run.events), 1)
        event = run.events[0]
        self.assertEqual(event.physics_result.status, "valid")
        self.assertEqual(event.physics_result.state_information["gravity_model"], "WGS72")
        self.assertEqual(event.physics_result.provenance.reference_frame, "TEME")
        self.assertEqual(
            event.physics_result.primary_state_at_tca["provenance"]["method"],
            "SGP4 TLE propagation",
        )
        research_pc = assess_automatic_research_pc(
            event.physics_result, event.collision_probability, event.review_priority,
            primary=event.primary, secondary=event.secondary,
        )
        self.assertEqual(research_pc.status, "prior_based_research_estimate")
        event = event.model_copy(update={"automatic_research_pc_assessment": research_pc})

        first = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        second = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(first["status"], "available_with_warning")
        self.assertEqual(first["candidates"], second["candidates"])
        baseline = first["candidates"][0]
        self.assertEqual(first["probability_before"]["comparison_role"], "collision_analysis_research_pc_record")
        self.assertEqual(first["probability_before"]["pc_scientific"], research_pc.estimated_pc_scientific)
        evaluated_candidate = next(row for row in first["candidates"] if row["direction"] == "along-track +")
        after_pc = evaluated_candidate["research_pc_after"]
        self.assertEqual(after_pc["status"], "available", after_pc.get("reason_code"))
        self.assertTrue(after_pc["provenance"]["fixed_comparison_uncertainty"])
        self.assertEqual(len(after_pc["provenance"]["fixed_covariance_matrix_sha256"]), 2)
        self.assertEqual(
            after_pc["provenance"]["fixed_covariance_matrix_sha256"],
            research_pc.provenance["central_covariance_matrix_sha256"],
        )
        self.assertEqual(after_pc["hbr_km"], research_pc.hbr_km)
        self.assertTrue(math.isfinite(evaluated_candidate["research_pc_reduction_log10"]))
        comparison = first["baseline_reference_comparison"]
        self.assertEqual(baseline["direction"], "zero-burn baseline")
        self.assertEqual(baseline["closest_approach_utc"], event.physics_result.tca.value)
        # These tight fixture assertions check repeatable numerical behavior;
        # they are not acceptance criteria for physical baseline equivalence.
        self.assertLess(abs(comparison["miss_distance_difference_km"]), 1e-6)
        self.assertAlmostEqual(comparison["zero_burn_tca_offset_from_reference_seconds"], 0.0, delta=1e-3)

    def test_additional_captured_tle_encounters_replay_and_zero_burn_deterministically(self):
        start = datetime.fromisoformat("2026-10-14T06:13:37.447147+00:00")
        for case in REAL_TLE_MULTI_CASES:
            with self.subTest(event_id=case["stored_event_id"]):
                records = [
                    parse_tle_text(
                        text,
                        source_group,
                        source_timestamp=source_timestamp,
                        source_type="live",
                        source_url=source_url,
                        retrieval_http_status=200,
                        raw_response_hash=raw_response_hash,
                    )[0]
                    for text, source_group, source_timestamp, source_url, raw_response_hash in case["records"]
                ]
                run, prediction_stub, anomaly_stub, comparison_stub = _screen_with_ai_hooks_stubbed(
                    records,
                    start,
                    horizon_hours=24.0,
                    sample_step_seconds=60,
                    screening_threshold_km=25.0,
                )
                self.assertGreater(prediction_stub.call_count, 0)
                self.assertGreater(anomaly_stub.call_count, 0)
                self.assertEqual(prediction_stub.call_count, anomaly_stub.call_count)
                self.assertEqual(comparison_stub.call_count, prediction_stub.call_count)
                self.assertEqual(run.summary["valid_track_count"], 2)
                self.assertEqual(run.summary["status"], "valid")

                stored_tca = datetime.fromisoformat(case["stored_tca"])
                matches = [
                    event for event in run.events
                    if {event.primary.id, event.secondary.id} == set(case["pair"])
                ]
                self.assertTrue(matches)
                replay = min(
                    matches,
                    key=lambda event: abs(
                        (datetime.fromisoformat(event.physics_result.tca.value) - stored_tca).total_seconds()
                    ),
                )
                self.assertEqual(replay.id, case["replay_event_id"])
                self.assertEqual(replay.physics_result.status, "valid")
                self.assertEqual(replay.physics_result.tca.value, case["replay_tca"])
                self.assertAlmostEqual(replay.physics_result.miss_distance.value, case["replay_miss_km"], places=11)
                # These bounds protect the captured replay fixture, not a
                # scientifically validated SGP4/two-body acceptance criterion.
                self.assertLess(abs((datetime.fromisoformat(replay.physics_result.tca.value) - stored_tca).total_seconds()), 0.002)
                self.assertLess(abs(replay.physics_result.miss_distance.value - case["stored_miss_km"]), 1e-4)

                first = optimize_maneuver(replay, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
                second = optimize_maneuver(replay, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
                self.assertEqual(first["status"], "available_with_warning")
                self.assertEqual(first["candidates"], second["candidates"])
                baseline = first["candidates"][0]
                comparison = first["baseline_reference_comparison"]
                self.assertEqual(baseline["direction"], "zero-burn baseline")
                self.assertEqual(baseline["closest_approach_utc"], replay.physics_result.tca.value)
                self.assertLess(abs(comparison["miss_distance_difference_km"]), 1e-6)
                self.assertAlmostEqual(comparison["zero_burn_tca_offset_from_reference_seconds"], 0.0, delta=1e-3)

    def test_two_body_unperturbed_state_returns_near_initial_state(self):
        r, v = _rk4((7000.0, 0.0, 0.0), (0.0, 7.5, 0.0), -300.0, 5.0, 398600.4418)
        r2, v2 = _rk4(r, v, 300.0, 5.0, 398600.4418)
        self.assertLess(sum((a-b)**2 for a, b in zip(r2, (7000.0, 0.0, 0.0))) ** 0.5, 1e-5)
        self.assertLess(sum((a-b)**2 for a, b in zip(v2, (0.0, 7.5, 0.0))) ** 0.5, 1e-8)

    def test_circular_orbit_matches_analytic_two_body_period(self):
        radius, mu = 7000.0, 398600.4418
        speed = math.sqrt(mu / radius)
        period = 2 * math.pi * math.sqrt(radius**3 / mu)
        r, v = _rk4((radius, 0.0, 0.0), (0.0, speed, 0.0), period, 5.0, mu)
        self.assertLess(math.dist(r, (radius, 0.0, 0.0)), 0.05)
        self.assertLess(math.dist(v, (0.0, speed, 0.0)), 5e-5)

    def test_candidates_include_zero_burn_and_are_repeatable(self):
        first = optimize_maneuver(_event())
        second = optimize_maneuver(_event())
        self.assertEqual(first["status"], "available_with_warning")
        self.assertEqual(first["reason_code"], "ZERO_BURN_BASELINE_DISCREPANCY")
        self.assertGreater(len(first["candidates"]), 13)
        self.assertEqual(first["candidates"], second["candidates"])
        baseline = first["candidates"][0]
        self.assertEqual(baseline["delta_v_m_s"], 0.0)
        self.assertEqual(baseline["direction"], "zero-burn baseline")
        self.assertAlmostEqual(baseline["change_from_zero_burn_km"], 0.0, delta=1e-12)
        self.assertTrue(any(row["delta_v_m_s"] > 0 for row in first["candidates"]))
        self.assertIn(first["best_candidate_status"], {"improved_geometry_found", "no_candidate_improved_separation_within_search_bounds"})
        self.assertEqual(first["search_configuration"]["refinement_method"].startswith("bounded golden-section"), True)
        self.assertTrue(all(isinstance(row["relative_velocity_km_s"], list) for row in first["candidates"]))
        self.assertTrue(all(len(row["delta_v_rtn_m_s"]) == 3 for row in first["candidates"]))
        self.assertTrue(all(len(row["delta_v_inertial_teme_km_s"]) == 3 for row in first["candidates"]))
        for row in first["candidates"]:
            self.assertAlmostEqual(math.sqrt(sum(value * value for value in row["delta_v_rtn_m_s"])), row["delta_v_m_s"], places=9)
        self.assertTrue(all(row["integration_state_convergence_km"] <= 0.001 for row in first["candidates"]))
        self.assertIsNone(first["risk_reduction_pct"])
        self.assertEqual(first["probability_after"]["status"], "unavailable")
        self.assertEqual(first["baseline_reference_comparison"]["zero_burn_closest_approach_utc"], baseline["closest_approach_utc"])
        self.assertEqual(baseline["closest_approach_offset_from_original_tca_seconds"], first["baseline_reference_comparison"]["zero_burn_tca_offset_from_reference_seconds"])
        self.assertTrue(baseline["closest_approach_utc"].endswith("+00:00"))

    def test_event_specific_foster_pc_stays_separate_from_consistent_research_comparison(self):
        event = _event()
        event.collision_probability = CollisionProbabilityResult(
            status="available", event_id=event.id,
            object_1_id=event.primary.id, object_2_id=event.secondary.id,
            tca_utc=event.physics_result.tca.value, pc=2e-5,
            provenance=Provenance(source="event-matched test CDM", source_type="user_supplied", reference_frame="TEME"),
        )
        result = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(result["event_context"]["event_specific_foster_pc"]["pc"], 2e-5)
        self.assertEqual(result["probability_before"]["status"], "unavailable")
        self.assertEqual(result["probability_before"]["event_id"], event.id)
        self.assertEqual(result["probability_after"]["status"], "unavailable")
        self.assertIsNone(result["risk_reduction_pct"])
        self.assertEqual(result["probability_comparison"]["status"], "unavailable")
        event.collision_probability.event_id = "another-event"
        mismatch = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(mismatch["event_context"]["event_specific_foster_pc"]["status"], "unavailable")

    def test_maneuver_response_carries_selected_event_context_and_keeps_pc_channels_separate(self):
        event = _event()
        event.collision_probability = CollisionProbabilityResult(
            status="available", event_id=event.id,
            object_1_id=event.primary.id, object_2_id=event.secondary.id,
            tca_utc=event.physics_result.tca.value, pc=2e-5,
            source_reported_event_id="other-event", source_reported_pc=0.5,
            provenance=Provenance(source="event-matched test CDM", source_type="user_supplied", reference_frame="TEME"),
        )
        result = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        context = result["event_context"]
        self.assertEqual(context["event_id"], event.id)
        self.assertEqual(context["object_ids"], [event.primary.id, event.secondary.id])
        self.assertEqual(context["tca_utc"], event.physics_result.tca.value)
        self.assertEqual(context["miss_distance_km"], 1.0)
        self.assertEqual(context["reference_frame"], "TEME")
        self.assertEqual(context["event_specific_foster_pc"]["pc"], 2e-5)
        self.assertEqual(context["source_reported_pc"]["status"], "unavailable")
        self.assertEqual(context["ai_queue_index"]["status"], "unavailable")
        self.assertIn("not_dynamically_propagated", context["uncertainty_provenance"]["post_burn_covariance_propagation"])
        self.assertEqual(result["probability_comparison"]["status"], "unavailable")

    def test_configurable_delta_v_search_refines_candidates_and_returns_bounded_best(self):
        result = optimize_maneuver(_event(), lead_seconds=240, max_delta_v_m_s=0.04)
        self.assertEqual(result["physics_candidate_status"], "evaluated")
        self.assertEqual(result["search_configuration"]["max_delta_v_m_s"], 0.04)
        self.assertEqual(result["search_configuration"]["coarse_magnitudes_m_s"], [0.01, 0.02, 0.03, 0.04])
        self.assertEqual(result["search_configuration"]["refinement_evaluations_per_axis_max"], 6)
        self.assertIn("not globally optimal", result["search_configuration"]["optimality_claim"])
        self.assertEqual(result["candidates"][0]["direction"], "zero-burn baseline")
        self.assertTrue(all(len(row["relative_velocity_km_s"]) == 3 for row in result["candidates"]))
        refined = [row for row in result["candidates"] if row["direction"] != "zero-burn baseline" and row["delta_v_m_s"] not in {0.01, 0.02, 0.03, 0.04}]
        self.assertTrue(refined)
        self.assertTrue(all(0 < row["delta_v_m_s"] <= 0.04 for row in result["candidates"][1:]))
        if result["best_candidate"]:
            self.assertGreater(result["best_candidate"]["change_from_zero_burn_km"], 0)
            self.assertEqual(result["best_candidate_status"], "improved_geometry_found")
        else:
            self.assertEqual(result["best_candidate_status"], "no_candidate_improved_separation_within_search_bounds")
        self.assertEqual(result["probability_after"]["status"], "unavailable")

    def test_fuel_estimate_uses_only_user_supplied_mass_and_specific_impulse(self):
        result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.01,), initial_mass_kg=500.0, specific_impulse_s=300.0)
        self.assertEqual(result["fuel"]["status"], "estimated")
        self.assertEqual(result["fuel"]["initial_mass_kg"], 500.0)
        self.assertEqual(result["fuel"]["specific_impulse_s"], 300.0)
        expected = 500.0 * (1.0 - math.exp(-result["best_candidate"]["delta_v_m_s"] / (300.0 * 9.80665)))
        self.assertAlmostEqual(result["fuel_cost_kg"], expected, places=12)
        self.assertTrue(any("Tsiolkovsky" in assumption for assumption in result["assumptions"]))

    def test_fuel_uses_configurable_default_assumptions_when_parameters_are_omitted(self):
        result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        self.assertIsNotNone(result["fuel_cost_kg"])
        self.assertEqual(result["fuel"]["initial_mass_kg"], 500.0)
        self.assertEqual(result["fuel"]["specific_impulse_s"], 220.0)
        self.assertEqual(result["fuel"]["assumption_status"], "estimated_from_default_assumptions")
        self.assertEqual(result["fuel"]["standard_gravity_m_s2"], 9.80665)

    def test_search_finds_maneuver_shifted_closest_approach_outside_old_local_window(self):
        result = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.1,))
        self.assertEqual(result["status"], "available_with_warning")
        baseline = result["candidates"][0]
        maneuver = next(row for row in result["candidates"] if row["direction"] == "along-track +")
        self.assertGreater(abs(baseline["closest_approach_offset_from_original_tca_seconds"]), 120)
        self.assertGreater(abs(maneuver["closest_approach_offset_from_original_tca_seconds"] - baseline["closest_approach_offset_from_original_tca_seconds"]), 30)
        self.assertLessEqual(maneuver["search_sample_step_seconds"], 5)
        self.assertIn("bounded", result["assumptions"][0].lower())

    def test_search_keeps_and_flags_a_minimum_at_the_interval_boundary(self):
        result = _refine_sampled_minimum([0.0, 5.0, 10.0], [0.1, 1.0, 2.0], lambda t: t + 0.1)
        self.assertEqual(result["sample_index"], 0)
        self.assertEqual(result["elapsed_seconds"], 0.0)
        self.assertEqual(result["refinement_evaluations"], 0)

    def test_search_keeps_and_flags_a_minimum_at_the_end_boundary(self):
        result = _refine_sampled_minimum([0.0, 5.0, 10.0], [2.0, 1.0, 0.1], lambda t: t + 0.1)
        self.assertEqual(result["sample_index"], 2)
        self.assertEqual(result["elapsed_seconds"], 10.0)
        self.assertEqual(result["distance_km"], 0.1)
        self.assertEqual(result["refinement_evaluations"], 0)

    def test_invalid_and_insufficient_propagation_samples_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "insufficient_valid_propagation_samples"):
            _propagate_samples(((7000.0, 0.0, 0.0), (0.0, 7.5, 0.0)), [0.0, 5.0], 5.0, 398600.4418)
        with self.assertRaisesRegex(ValueError, "insufficient_valid_propagation_samples"):
            _refine_sampled_minimum([0.0, 5.0, 10.0], [0.1, float("nan"), 0.2], lambda t: t)
        with patch("app.services.conjunction._rk4", side_effect=ValueError("two_body_radius_below_earth_surface")):
            failed = optimize_maneuver(_event())
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["reason_code"], "two_body_radius_below_earth_surface")

    def test_zero_burn_baseline_is_repeatable_and_flagged_against_known_event_reference(self):
        first = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.1,))
        second = optimize_maneuver(_event(), lead_seconds=300, burn_magnitudes_m_s=(0.1,))
        self.assertEqual(first["candidates"][0], second["candidates"][0])
        comparison = first["baseline_reference_comparison"]
        self.assertEqual(comparison["status"], "discrepancy")
        self.assertAlmostEqual(comparison["reference_miss_distance_km"], 1.0, places=8)
        self.assertAlmostEqual(comparison["zero_burn_two_body_miss_distance_km"], 0.8154, delta=0.01)
        self.assertAlmostEqual(comparison["zero_burn_tca_offset_from_reference_seconds"], 781.1, delta=1.0)
        self.assertAlmostEqual(comparison["miss_distance_difference_km"], -0.1846, delta=0.01)
        self.assertEqual(comparison["reference_tca_utc"], EPOCH)
        self.assertEqual(comparison["zero_burn_closest_approach_utc"], first["candidates"][0]["closest_approach_utc"])
        reference_tca = datetime.fromisoformat(comparison["reference_tca_utc"])
        simulated_tca = datetime.fromisoformat(comparison["zero_burn_closest_approach_utc"])
        self.assertAlmostEqual(
            (simulated_tca - reference_tca).total_seconds(),
            comparison["zero_burn_tca_offset_from_reference_seconds"],
            places=5,
        )
        baseline = first["candidates"][0]
        self.assertEqual(baseline["search_interval_start_utc"], "2024-12-31T23:55:00+00:00")
        self.assertEqual(baseline["search_interval_end_utc"], "2025-01-01T00:30:00+00:00")
        self.assertEqual(baseline["search_sample_step_seconds"], 5.0)
        self.assertEqual(baseline["search_sample_count"], 421)
        self.assertIn("not an independent validation", comparison["interpretation"])
        self.assertEqual(first["status"], "available_with_warning")
        self.assertEqual(first["reason_code"], "ZERO_BURN_BASELINE_DISCREPANCY")
        self.assertIn("not verified improvements", first["reason"])
        self.assertIn("relative to the zero-burn two-body simulation", first["candidate_interpretation"])

    def test_baseline_within_existing_thresholds_is_explicit_but_not_validation(self):
        event = _event()
        event.physics_result.secondary_state_at_tca["velocity_km_s"] = [0.01, 7.5, 0.0]
        result = optimize_maneuver(event, lead_seconds=300, burn_magnitudes_m_s=(0.01,))
        comparison = result["baseline_reference_comparison"]
        self.assertEqual(comparison["status"], "within_comparison_tolerance")
        self.assertEqual(result["status"], "available_with_warning")
        self.assertEqual(result["reason_code"], "BASELINE_COMPARISON_TOLERANCE_UNVALIDATED")
        self.assertEqual(comparison["reference_source"], "stored original Stage 2A SGP4 event")
        self.assertEqual(comparison["reference_miss_distance_km"], 1.0)
        self.assertIsNotNone(comparison["zero_burn_two_body_miss_distance_km"])
        self.assertLessEqual(abs(comparison["zero_burn_tca_offset_from_reference_seconds"]), 5.0)
        self.assertIn("not scientifically validated tolerances", comparison["interpretation"])

    def test_missing_or_invalid_reference_miss_rejects_solver_input(self):
        for status, value, units in (
            ("unavailable", None, "km"),
            ("invalid", 1.0, "km"),
            ("available", None, "km"),
            ("available", float("nan"), "km"),
            ("available", float("inf"), "km"),
            ("available", "1.0", "km"),
            ("available", 1.0, "m"),
        ):
            with self.subTest(status=status, value=value, units=units):
                event = _event()
                event.physics_result.miss_distance = ScientificField(status=status, value=value, units=units)
                result = optimize_maneuver(event, burn_magnitudes_m_s=(0.01,))
                self.assertEqual(result["status"], "unavailable")
                self.assertIn(result["reason_code"], {"REFERENCE_MISS_DISTANCE_STATUS_OR_UNITS_UNAVAILABLE", "REFERENCE_MISS_DISTANCE_INVALID"})
                self.assertEqual(result["physics_candidate_status"], "not_evaluated")
                self.assertNotIn("candidates", result)

    def test_service_rejects_invalid_tca_identity_state_units_and_event_object_mismatch(self):
        invalid_mutations = (
            ("event_id", lambda event: setattr(event.physics_result, "event_id", "different-event"), "PHYSICS_EVENT_IDENTITY_MISMATCH"),
            ("object_id", lambda event: setattr(event.physics_result, "object_primary_id", "different-object"), "DISTINCT_OBJECT_STATE_IDENTITY_REQUIRED"),
            ("tca_status", lambda event: setattr(event.physics_result, "tca_status", "boundary"), "VALID_INTERIOR_TCA_STATES_REQUIRED"),
            ("tca_status_missing", lambda event: setattr(event.physics_result, "tca_status", "unavailable"), "VALID_INTERIOR_TCA_STATES_REQUIRED"),
            ("tca_units", lambda event: setattr(event.physics_result.tca, "units", "TAI"), "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"),
            ("tca_missing", lambda event: setattr(event.physics_result.tca, "status", "unavailable"), "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"),
            ("tca_value_missing", lambda event: setattr(event.physics_result.tca, "value", None), "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"),
            ("tca_naive", lambda event: setattr(event.physics_result.tca, "value", "2025-01-01T00:00:00"), "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"),
            ("state_epoch", lambda event: event.physics_result.secondary_state_at_tca.update(epoch="not-a-time"), "CONSISTENT_TCA_EPOCH_AND_FRAME_REQUIRED"),
            ("state_units", lambda event: event.physics_result.state_information.update(position_units="m"), "TCA_STATE_FRAME_OR_UNITS_UNAVAILABLE"),
            ("missing_vector", lambda event: event.physics_result.primary_state_at_tca.pop("velocity_km_s"), "invalid_or_non_finite_cartesian_state"),
            ("nonfinite_vector", lambda event: event.physics_result.primary_state_at_tca.update(position_km=[float("inf"), 0.0, 0.0]), "invalid_or_non_finite_cartesian_state"),
            ("nonnumeric_vector", lambda event: event.physics_result.primary_state_at_tca.update(position_km=["7000", 0.0, 0.0]), "invalid_or_non_finite_cartesian_state"),
        )
        for name, mutate, reason_code in invalid_mutations:
            with self.subTest(name=name):
                event = _event()
                mutate(event)
                result = optimize_maneuver(event, burn_magnitudes_m_s=(0.01,))
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["reason_code"], reason_code)
                self.assertEqual(result["physics_candidate_status"], "not_evaluated")
                self.assertNotIn("candidates", result)

        event = _event()
        event.secondary = event.primary.model_copy(deep=True)
        result = optimize_maneuver(event, burn_magnitudes_m_s=(0.01,))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], "DISTINCT_OBJECT_STATE_IDENTITY_REQUIRED")

    def test_solver_configuration_validation_is_independent_of_http_parsing(self):
        for lead, magnitudes in ((None, (0.01,)), (True, (0.01,)), (300, None), (300, (float("nan"),)), (300, ("0.01",))):
            with self.subTest(lead=lead, magnitudes=magnitudes):
                result = optimize_maneuver(_event(), lead_seconds=lead, burn_magnitudes_m_s=magnitudes)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["reason_code"], "MANEUVER_CONFIGURATION_OUT_OF_BOUNDS")
                self.assertNotIn("candidates", result)

    def test_api_unavailable_latest_result_clears_stale_assessment(self):
        event = _event()
        job_id = "screen-job-stale-maneuver-fixture"
        stored_body = event.model_dump(mode="json")
        job = {"status": "complete", "result": {"data": [stored_body]}}
        main._screening_jobs[job_id] = job
        with TestClient(main.app) as client:
            query = f"screening_job_id={job_id}&burn_magnitudes_m_s=0.01&max_delta_v_m_s=0.02&initial_mass_kg=500&specific_impulse_s=300"
            successful = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}", json=stored_body)
            self.assertEqual(successful.json()["data"]["status"], "available_with_warning")
            self.assertTrue(any(row["fuel"]["status"] == "estimated" for row in successful.json()["data"]["candidates"]))
            self.assertIn(event.id, job["maneuver_results"])
            missing_isp = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={job_id}&initial_mass_kg=500", json=stored_body)

            invalid_reference = event.model_dump(mode="json")
            invalid_reference["physics_result"]["miss_distance"] = {"status": "unavailable", "value": None, "units": "km"}
            job["result"]["data"] = [invalid_reference]
            rejected_reference = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}", json=stored_body)
            stale_pdf = client.get(f"/api/conjunction-jobs/{job_id}/events/{event.id}/assessment.pdf")

            invalid_state = event.model_dump(mode="json")
            invalid_state["physics_result"]["secondary_state_at_tca"]["object_id"] = "wrong-object"
            job["result"]["data"] = [invalid_state]
            rejected_state = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}", json=stored_body)

        for response in (rejected_reference, rejected_state):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["status"], "unavailable")
            self.assertEqual(response.json()["data"]["physics_candidate_status"], "not_evaluated")
            self.assertNotIn("candidates", response.json()["data"])
        self.assertEqual(rejected_state.json()["data"]["reason_code"], "DISTINCT_OBJECT_STATE_IDENTITY_REQUIRED")
        self.assertEqual(missing_isp.status_code, 422)
        self.assertEqual(stale_pdf.status_code, 200)
        self.assertIn(b"MANEUVER_ASSESSMENT_NOT_AVAILABLE", stale_pdf.content)
        self.assertNotIn(event.id, job.get("maneuver_results", {}))

    def test_invalid_or_boundary_states_are_unavailable(self):
        event = _event()
        event.physics_result.status = "boundary"
        self.assertEqual(optimize_maneuver(event)["status"], "unavailable")
        invalid = _event()
        invalid.physics_result.primary_state_at_tca["position_km"] = [float("nan"), 0.0, 0.0]
        self.assertEqual(optimize_maneuver(invalid)["status"], "unavailable")

    def test_invalid_physics_reason_is_preserved_without_candidates(self):
        event = _event()
        event.physics_result.status = "invalid"
        event.physics_result.reason_codes = ["identical_propagation_parameters_for_distinct_catalog_ids"]
        result = optimize_maneuver(event)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], "identical_propagation_parameters_for_distinct_catalog_ids")
        self.assertEqual(result["assessment_reason_codes"], event.physics_result.reason_codes)
        self.assertNotIn("candidates", result)

    def test_valid_result_states_missing_physical_inputs_explicitly(self):
        result = optimize_maneuver(_event(), lead_seconds=180, burn_magnitudes_m_s=(0.02,))
        self.assertEqual(result["status"], "available_with_warning")
        self.assertEqual(result["probability_before"]["status"], "unavailable")
        self.assertEqual(result["probability_after"]["status"], "unavailable")
        self.assertIsNotNone(result["fuel_cost_kg"])
        self.assertTrue(any("configured TLE-age covariance/HBR" in item for item in result["limitations"]))
        self.assertTrue(any("configurable default spacecraft assumptions" in item for item in result["limitations"]))
        along_track = next(row for row in result["candidates"] if row["direction"] == "along-track +")
        sanity = along_track["along_track_sanity_check"]
        self.assertEqual(sanity["relation"], "delta_s ~= 3 * delta_v * delta_t")
        self.assertAlmostEqual(sanity["estimated_displacement_m"], 3 * along_track["delta_v_m_s"] * along_track["lead_time_seconds"])

    def test_maneuver_api_uses_valid_event_and_bounded_configuration(self):
        event = _event()
        job_id = "screen-job-fixture-1"
        body = event.model_dump(mode="json")
        main._screening_jobs[job_id] = {"status": "complete", "result": {"data": [body]}}
        with TestClient(main.app) as client:
            with patch.object(main, "build_trajectory_context", side_effect=AssertionError("maneuver must not launch another screening run")):
                query = f"screening_job_id={job_id}"
                response = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}&lead_seconds=180&burn_magnitudes_m_s=0.02", json=body)
                out_of_bounds = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}&lead_seconds=5", json=body)
                mismatched_id = client.post(f"/api/conjunctions/other-event/maneuver?{query}", json=body)
                mismatched_tca = event.model_copy(deep=True)
                mismatched_tca.physics_result.tca.value = "2025-01-01T00:10:01+00:00"
                mismatched_tca_response = client.post(
                    f"/api/conjunctions/{event.id}/maneuver?{query}", json=mismatched_tca.model_dump(mode="json"),
                )
                altered = event.model_copy(deep=True)
                altered.physics_result.primary_state_at_tca["position_km"][0] += 1
                with patch.object(main, "optimize_maneuver", return_value={"status": "available", "event_id": event.id, "candidates": []}) as simulator:
                    altered_event = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}", json=altered.model_dump(mode="json"))
                stored_assessment = client.post(
                    f"/api/conjunctions/{event.id}/maneuver?{query}&lead_seconds=300&burn_magnitudes_m_s=0.01,0.05",
                    json=body,
                )
                bad_identity_job_id = "screen-job-bad-maneuver-result-identity"
                main._screening_jobs[bad_identity_job_id] = {"status": "complete", "result": {"data": [body]}}
                with patch.object(main, "optimize_maneuver", return_value={"status": "available", "event_id": "another-event"}):
                    bad_result_identity = client.post(
                        f"/api/conjunctions/{event.id}/maneuver?screening_job_id={bad_identity_job_id}",
                        json=body,
                    )
                cross_job_id = "screen-job-cross-identity"
                cross_job_body = {**body, "screening_job_id": "another-screening-job"}
                main._screening_jobs[cross_job_id] = {"status": "complete", "result": {"data": [cross_job_body]}}
                cross_job_request = client.post(
                    f"/api/conjunctions/{event.id}/maneuver?screening_job_id={cross_job_id}", json=cross_job_body,
                )
                wrong_job_event = _event()
                wrong_job_event.id = "event-not-in-job"
                wrong_job = client.post(f"/api/conjunctions/{wrong_job_event.id}/maneuver?{query}", json=wrong_job_event.model_dump(mode="json"))
                missing_job = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id=expired-job", json=body)
                proxy_job_id = "screen-job-proxy-fixture"
                proxy_body = {**body, "result_kind": "screening_proxy"}
                main._screening_jobs[proxy_job_id] = {"status": "complete", "result": {"data": [proxy_body]}}
                proxy_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={proxy_job_id}", json=body)
                boundary_job_id = "screen-job-boundary-fixture"
                boundary_body = {**body, "physics_result": {**body["physics_result"], "status": "boundary"}}
                main._screening_jobs[boundary_job_id] = {"status": "complete", "result": {"data": [boundary_body]}}
                boundary_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={boundary_job_id}", json=boundary_body)
                invalid_job_id = "screen-job-invalid-fixture"
                invalid_body = {**body, "physics_result": {**body["physics_result"], "status": "invalid", "reason_codes": ["identical_propagation_parameters_for_distinct_catalog_ids"]}}
                main._screening_jobs[invalid_job_id] = {"status": "complete", "result": {"data": [invalid_body]}}
                invalid_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={invalid_job_id}", json=invalid_body)
                partial_job_id = "screen-job-partial-maneuver-rejected"
                main._screening_jobs[partial_job_id] = {"status": "partial", "result": {"data": [body]}}
                partial_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={partial_job_id}", json=body)
                archived_partial_job_id = "screen-job-archived-partial-maneuver"
                archived_partial_source = {"status": "partial", "restored_from_archive": True, "result": {"data": [body.copy()]}}
                main._screening_jobs[archived_partial_job_id] = archived_partial_source
                archived_partial_request = client.post(
                    f"/api/conjunctions/{event.id}/maneuver?screening_job_id={archived_partial_job_id}", json=body,
                )
                failed_job_id = "screen-job-failed-maneuver-rejected"
                main._screening_jobs[failed_job_id] = {"status": "failed", "result": {"data": [body]}}
                failed_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={failed_job_id}", json=body)
                queued_job_id = "screen-job-queued-maneuver-rejected"
                main._screening_jobs[queued_job_id] = {"status": "queued", "result": None}
                queued_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={queued_job_id}", json=body)
                object_mismatch = event.model_copy(deep=True)
                object_mismatch.primary.id = "99999"
                mismatch_job_id = "screen-job-object-mismatch"
                main._screening_jobs[mismatch_job_id] = {"status": "complete", "result": {"data": [body]}}
                object_mismatch_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={mismatch_job_id}", json=object_mismatch.model_dump(mode="json"))
                source_mismatch = event.model_copy(deep=True)
                source_mismatch.provenance.source = "different source"
                source_mismatch_job_id = "screen-job-source-mismatch"
                main._screening_jobs[source_mismatch_job_id] = {"status": "complete", "result": {"data": [body]}}
                source_mismatch_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={source_mismatch_job_id}", json=source_mismatch.model_dump(mode="json"))
                synthetic = event.model_copy(deep=True)
                synthetic.provenance.source_type = "synthetic"
                synthetic.provenance.is_synthetic = True
                synthetic_job_id = "screen-job-synthetic-rejected"
                synthetic_body = synthetic.model_dump(mode="json")
                main._screening_jobs[synthetic_job_id] = {"status": "complete", "result": {"data": [synthetic_body]}}
                synthetic_request = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={synthetic_job_id}", json=synthetic_body)
                archived_job_id = "screen-job-archived-maneuver-rejected"
                main._screening_jobs[archived_job_id] = {"status": "complete", "restored_from_archive": True, "result": {"data": [body]}}
                archived_maneuver = client.post(f"/api/conjunctions/{event.id}/maneuver?screening_job_id={archived_job_id}", json=body)
                bad_burn = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}&burn_magnitudes_m_s=0.2", json=body)
                malformed_burn = client.post(f"/api/conjunctions/{event.id}/maneuver?{query}&burn_magnitudes_m_s=abc", json=body)
                assessment_pdf = client.get(f"/api/conjunction-jobs/{job_id}/events/{event.id}/assessment.pdf")
                stored_result = main._screening_jobs[job_id]["maneuver_results"][event.id]
                stored_result["baseline_reference_comparison"]["zero_burn_closest_approach_utc"] = None
                stored_result["candidates"][0]["closest_approach_utc"] = None
                stored_result["candidates"][0]["closest_approach_offset_from_original_tca_seconds"] = None
                unavailable_time_pdf = client.get(f"/api/conjunction-jobs/{job_id}/events/{event.id}/assessment.pdf")
                selected_event_pdf = client.get(f"/api/conjunction-jobs/{job_id}/events/{event.id}/report.pdf")
                missing_pdf = client.get(f"/api/conjunction-jobs/unknown/events/{event.id}/assessment.pdf")
            with patch.object(main, "build_trajectory_context", new=AsyncMock(return_value=(None, SimpleNamespace(events=[event], summary={"status": "valid", "completion_status": "complete"})))):
                event_pdf = client.get(f"/api/reports/{event.id}.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["screening_job_id"], job_id)
        self.assertEqual(response.json()["data"]["event_id"], event.id)
        maneuver_schema = client.get("/openapi.json").json()["paths"]["/api/conjunctions/{event_id}/maneuver"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        response_schema = client.get("/openapi.json").json()["components"]["schemas"][maneuver_schema["$ref"].rsplit("/", 1)[-1]]
        self.assertIn("screening_job_id", response_schema["required"])
        data_schema_ref = response_schema["properties"]["data"]["$ref"]
        data_schema = client.get("/openapi.json").json()["components"]["schemas"][data_schema_ref.rsplit("/", 1)[-1]]
        self.assertIn("event_id", data_schema["required"])
        self.assertEqual(data_schema["additionalProperties"], True)
        self.assertEqual(response.json()["data"]["status"], "available_with_warning")
        for block_name in ("stage2a_reference", "zero_burn_baseline", "physics_candidates", "surrogate_rank"):
            self.assertEqual(response.json()["data"][block_name]["event_id"], event.id)
            self.assertEqual(response.json()["data"][block_name]["screening_job_id"], job_id)
        self.assertGreaterEqual(len(response.json()["data"]["physics_candidates"]["candidates"]), 6)
        self.assertEqual(response.json()["data"]["surrogate_rank"]["synthetic_training_labels"], False)
        self.assertFalse(response.json()["data"]["surrogate_rank"]["ranking_used"])
        self.assertGreater(len(response.json()["data"]["candidates"]), 7)
        maneuver_ml = response.json()["data"]["ml_result"]
        self.assertEqual(maneuver_ml["status"], "fallback_physics_ranking")
        self.assertEqual(maneuver_ml["provenance"]["source_event_id"], event.id)
        self.assertEqual(maneuver_ml["provenance"]["screening_job_id"], job_id)
        self.assertEqual(maneuver_ml["score_units"], "log10 ratio; positive predicts reduction")
        self.assertEqual(maneuver_ml["evaluation_summary"]["held_out_scenario_count"], 8)
        self.assertGreater(
            maneuver_ml["evaluation_summary"]["model_mean_regret_log10_pc_reduction"],
            maneuver_ml["evaluation_summary"]["baseline_mean_regret_log10_pc_reduction"],
        )
        scored_candidates = [item for item in response.json()["data"]["candidates"] if item.get("maneuver_ml_predicted_log10_pc_reduction") is not None]
        self.assertTrue(scored_candidates)
        self.assertTrue(all(item.get("maneuver_ml_rank") is None for item in response.json()["data"]["candidates"]))
        self.assertEqual(response.json()["data"]["baseline_reference_comparison"]["status"], "discrepancy")
        self.assertEqual(response.json()["data"]["baseline_reference_comparison"]["reference_tca_utc"], EPOCH)
        self.assertEqual(response.json()["data"]["baseline_reference_comparison"]["reference_miss_distance_km"], 1.0)
        self.assertIsInstance(response.json()["data"]["baseline_reference_comparison"]["zero_burn_two_body_miss_distance_km"], (int, float))
        self.assertEqual(response.json()["data"]["baseline_reference_comparison"]["zero_burn_closest_approach_utc"], response.json()["data"]["candidates"][0]["closest_approach_utc"])
        self.assertIsInstance(response.json()["data"]["candidates"][0]["closest_approach_offset_from_original_tca_seconds"], (int, float))
        self.assertIsInstance(response.json()["data"]["candidates"][0]["predicted_miss_distance_km"], (int, float))
        self.assertIsInstance(response.json()["data"]["candidates"][0]["change_from_zero_burn_km"], (int, float))
        self.assertIn("zero-burn two-body simulation", response.json()["data"]["candidate_interpretation"])
        self.assertEqual(out_of_bounds.status_code, 422)
        self.assertEqual(mismatched_id.status_code, 422)
        self.assertEqual(mismatched_tca_response.status_code, 409)
        self.assertEqual(mismatched_tca_response.json()["detail"]["reason_code"], "EVENT_IDENTITY_MISMATCH")
        self.assertEqual(altered_event.status_code, 200)
        self.assertEqual(altered_event.json()["data"]["event_id"], event.id)
        self.assertEqual(altered_event.json()["data"]["status"], "available")
        self.assertEqual(simulator.call_args.args[0].model_dump(mode="json"), body)
        self.assertEqual(stored_assessment.json()["data"]["status"], "available_with_warning")
        self.assertEqual(bad_result_identity.status_code, 409)
        self.assertEqual(bad_result_identity.json()["detail"]["message"], "Maneuver result identity does not match the selected event and screening job.")
        self.assertNotIn("maneuver_results", main._screening_jobs[bad_identity_job_id])
        self.assertEqual(cross_job_request.status_code, 409)
        self.assertEqual(cross_job_request.json()["detail"]["reason_code"], "EVENT_JOB_MISMATCH")
        self.assertEqual(wrong_job.status_code, 404)
        self.assertEqual(missing_job.status_code, 404)
        self.assertEqual(missing_job.json()["detail"]["reason_code"], "JOB_NOT_FOUND")
        self.assertEqual(proxy_request.status_code, 422)
        self.assertEqual(boundary_request.status_code, 422)
        self.assertEqual(boundary_request.json()["detail"]["reason_code"], "EVENT_NOT_PHYSICALLY_VALID")
        self.assertEqual(invalid_request.status_code, 422)
        self.assertEqual(invalid_request.json()["detail"]["reason_code"], "EVENT_NOT_PHYSICALLY_VALID")
        self.assertEqual(partial_request.status_code, 200)
        self.assertEqual(partial_request.json()["data"]["event_id"], event.id)
        self.assertFalse(partial_request.json()["data"]["screening_job_archived"])
        self.assertEqual(partial_request.json()["data"]["status"], "available_with_warning")
        self.assertTrue(any("originating screening job was partial" in item for item in partial_request.json()["data"]["limitations"]))
        self.assertEqual(archived_partial_request.status_code, 200)
        archived_partial_result = archived_partial_request.json()["data"]
        self.assertEqual(archived_partial_result["event_id"], event.id)
        self.assertEqual(archived_partial_result["screening_job_status"], "partial")
        self.assertTrue(archived_partial_result["screening_job_archived"])
        self.assertEqual(archived_partial_result["status"], "available_with_warning")
        self.assertTrue(any("originating screening job was partial" in item for item in archived_partial_result["limitations"]))
        self.assertEqual(archived_partial_source["result"]["data"][0], body)
        self.assertIn(event.id, main._screening_jobs[archived_partial_job_id]["maneuver_results"])
        self.assertEqual(failed_request.json()["detail"]["reason_code"], "JOB_FAILED")
        self.assertEqual(queued_request.json()["detail"]["reason_code"], "JOB_NOT_TERMINAL")
        self.assertEqual(object_mismatch_request.json()["detail"]["reason_code"], "EVENT_IDENTITY_MISMATCH")
        self.assertEqual(source_mismatch_request.json()["detail"]["reason_code"], "EVENT_IDENTITY_MISMATCH")
        self.assertEqual(synthetic_request.json()["detail"]["reason_code"], "DEMO_OR_PROXY_EVENT")
        self.assertEqual(archived_maneuver.status_code, 200)
        self.assertEqual(archived_maneuver.json()["data"]["event_id"], event.id)
        self.assertTrue(archived_maneuver.json()["data"]["screening_job_archived"])
        self.assertEqual(bad_burn.status_code, 422)
        self.assertEqual(malformed_burn.status_code, 422)
        self.assertEqual(assessment_pdf.status_code, 200)
        self.assertTrue(assessment_pdf.content.startswith(b"%PDF-"))
        self.assertIn(f"Screening job ID: {job_id}".encode(), assessment_pdf.content)
        self.assertIn(b"Status: available_with_warning", assessment_pdf.content)
        self.assertIn(b"Original Stage 2A SGP4 reference miss distance", assessment_pdf.content)
        self.assertIn(b"Zero-burn two-body simulated baseline miss distance", assessment_pdf.content)
        pdf_text = assessment_pdf.content.decode("latin-1")
        tca_label = "Zero-burn two-body simulated closest-approach TCA:"
        tca_value = "2025-01-01T00:13:01.056980+00:00"
        self.assertIn(tca_label, pdf_text)
        self.assertIn(tca_value, pdf_text)
        self.assertIn("Candidate TCA 2025-01-01T00:12:10.784806+00:00", pdf_text)
        self.assertIn(b"Zero-burn closest-approach TCA offset from original TCA", assessment_pdf.content)
        self.assertIn(b"0.8154338340375001 km", assessment_pdf.content)
        self.assertRegex(pdf_text, r"change from\) Tj\n/F1 13 Tf\n0 -18 Td\n\(zero-burn\) Tj")
        self.assertIn(b"Maneuver ML status: fallback_physics_ranking", assessment_pdf.content)
        # The loaded maneuver model supplies its actual held-out evaluation;
        # the PDF wraps "38 candidates" across a line boundary.
        self.assertIn(b"8 parents", assessment_pdf.content)
        self.assertIn(b"38) Tj", assessment_pdf.content)
        self.assertIn(b"(candidates; within-parent Spearman", assessment_pdf.content)
        self.assertIn(b"ORION physics-supervised maneuver", assessment_pdf.content)
        self.assertIn(b"research-Pc reduction ranker v2.0.0", assessment_pdf.content)
        self.assertIn(b"Maneuver ML provenance:", assessment_pdf.content)
        self.assertIn(f"Maneuver event ID: {event.id}".encode(), assessment_pdf.content)
        self.assertIn(f"Maneuver screening job ID: {job_id}".encode(), assessment_pdf.content)
        self.assertIn(b"discrepancy", assessment_pdf.content)
        self.assertIn(b"not automatically an improvement", assessment_pdf.content)
        self.assertIn(b"over the original conjunction", assessment_pdf.content)
        self.assertTrue(unavailable_time_pdf.content.startswith(b"%PDF-"))
        self.assertIn(b"Zero-burn two-body simulated closest-approach TCA:", unavailable_time_pdf.content)
        self.assertIn(b"unavailable", unavailable_time_pdf.content)
        # The original and zero-burn TCA can be unavailable while simulated
        # candidate trajectories still produce their own TCA.
        self.assertIn(b"Candidate TCA 2025-01-01T00:12:24.992669", unavailable_time_pdf.content)
        self.assertIn(b"Original Stage 2A SGP4 TCA: 2025-01-01T00:00:00+00:00", unavailable_time_pdf.content)
        self.assertEqual(selected_event_pdf.status_code, 200)
        self.assertTrue(selected_event_pdf.content.startswith(b"%PDF-"))
        self.assertIn(event.id.encode(), selected_event_pdf.content)
        self.assertEqual(missing_pdf.status_code, 404)
        self.assertEqual(event_pdf.status_code, 409)
        self.assertEqual(event_pdf.json()["detail"]["reason_code"], "SCREENING_JOB_REQUIRED")

    def test_partial_job_report_preserves_event_and_job_when_maneuver_is_unavailable(self):
        event = _event()
        event_id = "partial-event-report"
        event.id = event_id
        event.physics_result.event_id = event_id
        job_id = "partial-job-report"
        main._screening_jobs[job_id] = {
            "status": "partial",
            "result": {
                "data": [event.model_dump(mode="json")],
                "screening": {"completion_status": "partial", "status": "partial"},
            },
        }
        try:
            with TestClient(main.app) as client:
                response = client.get(f"/api/conjunction-jobs/{job_id}/events/{event_id}/assessment.pdf")
            self.assertEqual(response.status_code, 200)
            self.assertIn(f"Maneuver event ID: {event_id}".encode(), response.content)
            self.assertIn(f"Maneuver screening job ID: {job_id}".encode(), response.content)
            self.assertIn(b"Status: unavailable | JOB_INCOMPLETE", response.content)
            self.assertIn(b"PC_RESULT_NOT_RETURNED", response.content)
            self.assertNotIn(b"EVENT_MATCHED_COVARIANCE_AND_HBR_REQUIRED", response.content)
        finally:
            main._screening_jobs.pop(job_id, None)

    def test_maneuver_api_allows_valid_selected_event_from_partial_screening_job(self):
        event = _event()
        job_id = "screen-job-partial-maneuver-fixture"
        body = event.model_dump(mode="json")
        job = {
            "status": "partial",
            "result": {
                "completion_status": "partial",
                "result_status": "partial",
                "data": [body],
            },
        }
        main._screening_jobs[job_id] = job

        with TestClient(main.app) as client:
            response = client.post(
                f"/api/conjunctions/{event.id}/maneuver?screening_job_id={job_id}&burn_magnitudes_m_s=0.01",
                json=body,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["event_id"], event.id)
        self.assertEqual(response.json()["data"]["status"], "available_with_warning")
        self.assertTrue(any("originating screening job was partial" in item for item in response.json()["data"]["limitations"]))
        self.assertIn(event.id, job["maneuver_results"])


if __name__ == "__main__":
    unittest.main()
