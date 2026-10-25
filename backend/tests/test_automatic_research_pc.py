from __future__ import annotations

import json
import math
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import numpy as np

from app.services.automatic_research_pc import _integrate_log_disk, _log_foster_pc, _object_size_hbr_override, assess_automatic_research_pc
from app.main import event_dicts
from app.services.collision_probability import CovarianceInput, HardBodyRadiusInput, _integrate_circular_region, calculate_foster_2d
from app.services.orbit import propagate_records
from app.services.tle_provider import parse_tle_text
from app.services.trajectory_screening import screen_tle_records


class AutomaticResearchPcQualityTests(unittest.TestCase):
    def test_log_domain_foster_fallback_matches_probability_domain_for_representable_case(self):
        mean = [0.15, -0.1]
        direct, _, _ = _integrate_circular_region(mean, 1.0, 0.8, 0.5, 1e-8, 1024)
        log_result = _integrate_log_disk(mean, 1.0, 0.8, 0.5)
        self.assertIsNotNone(direct)
        self.assertAlmostEqual(math.exp(log_result), direct, delta=1e-12)

    def test_small_hbr_log_formula_agrees_with_full_foster_integral_in_overlap(self):
        tca = "2025-01-01T00:00:00+00:00"
        covs = [
            CovarianceInput(object_id=oid, frame="TEME", epoch=tca, matrix=[[0.5,0,0],[0,0.5,0],[0,0,0.5]],
                            units={"position":"km^2"}, source="test covariance", source_type="derived")
            for oid in ("A", "B")
        ]
        states = ((np.array([0.0,0.0,0.0]),np.array([0.0,0.0,0.0])), (np.array([10.0,0.0,0.0]),np.array([0.0,7.0,0.0])))
        hbr = 1e-4
        log_value = _log_foster_pc(None, covs, states, hbr)
        full = calculate_foster_2d(
            event_id="overlap", object_1_id="A", object_2_id="B", tca_utc=tca,
            position_1_km=states[0][0], velocity_1_km_s=states[0][1],
            position_2_km=states[1][0], velocity_2_km_s=states[1][1], state_frame="TEME",
            tca_status="valid", covariance_1=covs[0], covariance_2=covs[1],
            hbr=HardBodyRadiusInput(value_km=hbr, source="configured", source_type="derived", description="test"),
            assume_independent_covariances=True, relative_tolerance=1e-6, max_quadrature_order=2048,
        )
        self.assertEqual(full.status, "available")
        self.assertIsNotNone(full.pc)
        self.assertAlmostEqual(log_value, math.log(full.pc), delta=1e-5)

    def test_live_tle_event_gets_prior_based_research_pc_and_sensitivity(self):
        event = _real_screened_event()
        assessment = event.automatic_research_pc_assessment
        api_event = event_dicts([event])[0]
        self.assertEqual(assessment.status, "prior_based_research_estimate")
        self.assertEqual(assessment.quality_status, "prior_based_unvalidated")
        self.assertGreaterEqual(assessment.estimated_pc, 0.0)
        self.assertLessEqual(assessment.estimated_pc, 1.0)
        self.assertAlmostEqual(assessment.percentage, assessment.estimated_pc * 100.0)
        self.assertTrue(assessment.negligible)
        self.assertLess(assessment.log10_pc, -30)
        self.assertEqual(assessment.estimated_pc_scientific, "< 1e-30")
        self.assertEqual(assessment.percentage_scientific, "< 1e-28")
        self.assertEqual(assessment.sensitivity_status, "available")
        self.assertEqual(assessment.hbr_provenance["combined_hbr_by_esa_span_quantile_km"], {"p10": 0.002, "p50": 0.002, "p90": 0.002})
        self.assertIn("covariance multipliers 0.5x, 1x, and 3x", assessment.sensitivity_reason)
        self.assertIn("HBR multipliers 0.75x, 1x, and 1.5x", assessment.sensitivity_reason)
        self.assertEqual(assessment.provenance["sensitivity_covariance_scales"], [0.5, 1.0, 3.0])
        self.assertEqual(assessment.provenance["sensitivity_hbr_scales"], [0.75, 1.0, 1.5])
        self.assertEqual(assessment.hbr_sensitivity_km, [assessment.hbr_km * 0.75, assessment.hbr_km * 1.5])
        self.assertEqual(assessment.hbr_km, event.automatic_research_pc_assessment.hbr_km)
        self.assertEqual(assessment.geometry_review_category, event.review_priority.category)
        self.assertEqual(assessment.reason_codes, [])
        self.assertEqual(assessment.risk_assessment.risk_score_pc_channel, "research_pc")
        self.assertEqual(assessment.risk_assessment.physics_risk_class, "Low")
        self.assertEqual(assessment.risk_assessment.final_risk_class, "Low")
        self.assertEqual(assessment.risk_assessment.risk_score, 0.0)
        self.assertIn("not an event-specific or operationally validated Pc", " ".join(assessment.assumptions))
        self.assertIn("source_archive_sha256", assessment.provenance)
        self.assertTrue(assessment.provenance["covariance_independence_assumed"])
        self.assertRegex(assessment.lower_sensitivity_pc_scientific, r"^(?:< 1e-30|[0-9.]+e[+-][0-9]+)$")
        self.assertEqual(api_event["id"], "CA-CDBC9233F65C7BE0EE0A")
        self.assertEqual(api_event["automatic_research_pc_assessment"], assessment.model_dump(mode="json"))
        self.assertEqual(api_event["automatic_research_pc_assessment"]["estimated_pc_scientific"], "< 1e-30")
        self.assertIsNone(api_event["collision_probability"]["pc"])

    def test_tle_age_covariance_is_default_and_all_policies_are_selectable(self):
        event = _real_screened_event()
        results = {
            policy: assess_automatic_research_pc(
                event.physics_result, event.collision_probability, event.review_priority,
                primary=event.primary, secondary=event.secondary, covariance_policy=policy,
            )
            for policy in ("esa_population_prior", "tle_age_baseline", "tle_age_baseline_2x")
        }
        self.assertEqual(event.automatic_research_pc_assessment.covariance_policy_id, "tle_age_baseline")
        self.assertEqual(set(results), {item.covariance_policy_id for item in results.values()})
        self.assertTrue(all(item.status == "prior_based_research_estimate" for item in results.values()))
        self.assertTrue(all(item.log10_pc is not None for item in results.values()))
        self.assertNotEqual(results["esa_population_prior"].log10_pc, results["tle_age_baseline"].log10_pc)
        self.assertNotEqual(results["tle_age_baseline"].log10_pc, results["tle_age_baseline_2x"].log10_pc)

    def test_known_object_hbr_override_is_explicit_and_changes_research_pc(self):
        event = _real_screened_event()
        primary = event.primary.model_copy(update={"name": "ISS (Zarya)"})
        baseline = assess_automatic_research_pc(event.physics_result, event.collision_probability, event.review_priority,
            primary=event.primary, secondary=event.secondary)
        overridden = assess_automatic_research_pc(event.physics_result, event.collision_probability, event.review_priority,
            primary=primary, secondary=event.secondary)
        self.assertEqual(_object_size_hbr_override(primary)["radius_km"], 0.015)
        self.assertEqual(overridden.hbr_source, "assumed_object_size_override")
        self.assertEqual(overridden.hbr_provenance["objects"][primary.id]["match"], "named ISS module")
        self.assertNotEqual(overridden.hbr_km, baseline.hbr_km)
        self.assertNotEqual(overridden.log10_pc, baseline.log10_pc)
        self.assertIn("assumption", overridden.hbr_provenance["assumption"].lower())

    def test_covariance_scale_changes_finite_research_log_pc(self):
        event = _real_screened_event()
        narrow = assess_automatic_research_pc(event.physics_result, event.collision_probability, event.review_priority,
            primary=event.primary, secondary=event.secondary, covariance_scale=0.5)
        wide = assess_automatic_research_pc(event.physics_result, event.collision_probability, event.review_priority,
            primary=event.primary, secondary=event.secondary, covariance_scale=2.0)
        self.assertTrue(math.isfinite(narrow.log10_pc))
        self.assertTrue(math.isfinite(wide.log10_pc))
        self.assertNotEqual(narrow.log10_pc, wide.log10_pc)

    def test_archived_real_celestrak_event_replays_reproducibly_through_screening(self):
        first = _real_screened_event()
        second = _real_screened_event()
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.physics_result.tca.value, second.physics_result.tca.value)
        self.assertEqual(first.physics_result.miss_distance.value, second.physics_result.miss_distance.value)
        self.assertEqual(first.automatic_research_pc_assessment.method_version, "2.0.0")
        self.assertEqual(first.automatic_research_pc_assessment.model_dump(), second.automatic_research_pc_assessment.model_dump())
        self.assertEqual(first.physics_result.status, "valid")
        self.assertEqual(first.primary.provenance.source_type, "live")
        self.assertEqual(first.collision_probability.status, "unavailable")
        self.assertIsNone(first.collision_probability.pc)
        self.assertEqual(first.automatic_research_pc_assessment.status, "prior_based_research_estimate")
        self.assertNotEqual(first.collision_probability.pc, first.automatic_research_pc_assessment.estimated_pc)

    def test_existing_ai_inference_is_event_bound_and_reports_model_provenance(self):
        event = _real_screened_event()
        ai = event.anomaly_result
        self.assertEqual(ai.status, "available")
        self.assertEqual(ai.provenance["source_physics_event_id"], event.id)
        self.assertEqual(ai.model_name, "ORION orbital feature Isolation Forest")
        self.assertTrue(ai.model_version)
        self.assertGreaterEqual(ai.anomaly_score, 0.0)
        self.assertLessEqual(ai.anomaly_score, 1.0)
        self.assertIn("not a probability", ai.score_definition)

    def test_invalid_geometry_does_not_get_an_automatic_probability(self):
        event = _real_screened_event()
        invalid_physics = event.physics_result.model_copy(update={"status": "invalid", "tca_status": "invalid"})
        assessed = assess_automatic_research_pc(invalid_physics, event.collision_probability, event.review_priority)
        self.assertEqual(assessed.status, "not_applicable")
        self.assertEqual(assessed.quality_status, "not_assessed")
        self.assertIsNone(assessed.estimated_pc)
        self.assertEqual(assessed.reason_codes, ["VALID_INTERIOR_TCA_REQUIRED"])
        self.assertIn("no valid interior TCA", assessed.reason_message)

    def test_valid_event_specific_foster_result_stays_a_separate_result_type(self):
        event = _real_screened_event()
        matching_pc = event.collision_probability.model_copy(update={
            "status": "available", "event_id": event.id, "pc": 1e-5,
        })
        assessed = assess_automatic_research_pc(event.physics_result, matching_pc, event.review_priority)
        self.assertEqual(assessed.status, "event_specific_foster_available")
        self.assertEqual(assessed.quality_status, "validated_event_inputs")
        self.assertIsNone(assessed.estimated_pc)
        mismatched = matching_pc.model_copy(update={"event_id": "different-event"})
        rejected = assess_automatic_research_pc(event.physics_result, mismatched, event.review_priority)
        self.assertEqual(rejected.status, "not_estimable")
        self.assertIsNone(rejected.estimated_pc)
        self.assertEqual(rejected.reason_codes, ["OBJECT_PROVENANCE_UNAVAILABLE"])
        self.assertIn("Object provenance is missing", rejected.reason_message)


def _real_screened_event():
    """Replay the pair from an archived real CelesTrak GP/TLE screening result."""
    project_root = Path(__file__).resolve().parents[1]
    archive = project_root / "exports" / "screening-job-2a50f67a597442279de1d5178468953d.json"
    result = json.loads(archive.read_text(encoding="utf-8"))["result"]
    archived = next(
        item for item in result["data"]
        if item.get("physics_result", {}).get("status") == "valid"
        and item.get("primary", {}).get("id") == "33762"
        and item.get("secondary", {}).get("id") == "33776"
    )
    records = []
    for obj in (archived["primary"], archived["secondary"]):
        record = obj["provenance"]["source_record"]
        records.extend(parse_tle_text(
            "\n".join((obj["name"], record["normalized_line1"], record["normalized_line2"])),
            record["source_group"],
            source_timestamp=record["retrieval_timestamp"],
            source_type="live",
            source_url=record["source_url"],
            retrieval_http_status=record["retrieval_http_status"],
            raw_response_hash=record.get("raw_response_hash"),
        ))
    start = datetime.fromisoformat(archived["physics_result"]["screening_horizon_start"])
    objects, _, unavailable = propagate_records(records, limit=2, now=start)
    run = screen_tle_records(
        records,
        objects,
        start_utc=start,
        horizon_hours=24.0,
        sample_step_seconds=60,
        screening_threshold_km=25.0,
        unavailable_objects=unavailable,
    )
    return next(
        item for item in run.events
        if item.physics_result.status == "valid"
        and {item.primary.id, item.secondary.id} == {"33762", "33776"}
    )


if __name__ == "__main__":
    unittest.main()
