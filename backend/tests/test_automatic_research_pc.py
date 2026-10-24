from __future__ import annotations

import json
import math
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.services.automatic_research_pc import _integrate_log_disk, assess_automatic_research_pc
from app.main import event_dicts
from app.services.collision_probability import _integrate_circular_region
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

    def test_live_tle_event_gets_prior_based_research_pc_and_sensitivity(self):
        event = _real_screened_event()
        assessment = event.automatic_research_pc_assessment
        api_event = event_dicts([event])[0]
        self.assertEqual(assessment.status, "prior_based_research_estimate")
        self.assertEqual(assessment.quality_status, "prior_based_unvalidated")
        self.assertGreaterEqual(assessment.estimated_pc, 0.0)
        self.assertLessEqual(assessment.estimated_pc, 1.0)
        self.assertAlmostEqual(assessment.percentage, assessment.estimated_pc * 100.0)
        self.assertLessEqual(Decimal(assessment.lower_sensitivity_pc_scientific), Decimal(assessment.estimated_pc_scientific))
        self.assertGreaterEqual(Decimal(assessment.upper_sensitivity_pc_scientific), Decimal(assessment.estimated_pc_scientific))
        self.assertEqual(assessment.sensitivity_status, "available")
        self.assertEqual(assessment.hbr_km, event.automatic_research_pc_assessment.hbr_km)
        self.assertEqual(assessment.geometry_review_category, event.review_priority.category)
        self.assertEqual(assessment.reason_codes, [])
        self.assertIn("not an event-specific or operationally validated Pc", " ".join(assessment.assumptions))
        self.assertIn("source_archive_sha256", assessment.provenance)
        self.assertTrue(assessment.provenance["covariance_independence_assumed"])
        self.assertRegex(assessment.lower_sensitivity_pc_scientific, r"^[0-9.]+e[+-][0-9]+$")
        self.assertEqual(api_event["id"], "CA-CDBC9233F65C7BE0EE0A")
        self.assertEqual(api_event["automatic_research_pc_assessment"], assessment.model_dump(mode="json"))
        self.assertEqual(api_event["automatic_research_pc_assessment"]["estimated_pc_scientific"], "1.55992e-167")
        self.assertIsNone(api_event["collision_probability"]["pc"])

    def test_archived_real_celestrak_event_replays_reproducibly_through_screening(self):
        first = _real_screened_event()
        second = _real_screened_event()
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.physics_result.tca.value, second.physics_result.tca.value)
        self.assertEqual(first.physics_result.miss_distance.value, second.physics_result.miss_distance.value)
        self.assertEqual(first.automatic_research_pc_assessment.method_version, "1.0.0")
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
