from __future__ import annotations

import unittest

from app.models import ScientificField
from app.services.ai_risk_prioritization import assess_live_geometry, rank_screening_events
from tests.test_automatic_research_pc import _real_screened_event


class AiRiskPrioritizationTests(unittest.TestCase):
    def test_real_screening_record_receives_numerical_separate_fallback_and_ranks(self):
        event = _real_screened_event()
        event = rank_screening_events([event])[0]
        assessment = event.ai_risk_assessment
        self.assertIsNotNone(assessment)
        self.assertGreaterEqual(assessment.score, 0.0)
        self.assertLessEqual(assessment.score, 1.0)
        self.assertIn(assessment.category, {"Critical", "High", "Medium", "Low"})
        self.assertEqual(assessment.prediction_method, "deterministic_geometry_speed_fallback")
        self.assertIn("not collision probability", assessment.target_definition)
        self.assertEqual(assessment.research_pc_rank, 1)
        self.assertEqual(assessment.final_priority_rank, 1)
        self.assertEqual(event.collision_probability.pc, None)
        self.assertNotEqual(event.automatic_research_pc_assessment.estimated_pc, assessment.score)

    def test_research_pc_rank_uses_exact_log10_then_miss_sigma_and_stable_id(self):
        base = _real_screened_event()
        research = base.automatic_research_pc_assessment
        first = base.model_copy(update={
            "id": "z-event",
            "physics_result": base.physics_result.model_copy(update={"event_id": "z-event"}),
            "automatic_research_pc_assessment": research.model_copy(update={
                "estimated_pc": 0.0, "estimated_pc_scientific": "1e-320", "log10_pc": -320.0,
                "miss_sigma_ratio": 3.0,
            }),
            "ai_risk_assessment": assess_live_geometry(base.physics_result),
        })
        tied_better_geometry = base.model_copy(update={
            "id": "a-event",
            "physics_result": base.physics_result.model_copy(update={"event_id": "a-event"}),
            "automatic_research_pc_assessment": research.model_copy(update={
                "estimated_pc": 0.0, "estimated_pc_scientific": "1e-320", "log10_pc": -320.0,
                "miss_sigma_ratio": 2.0,
            }),
            "ai_risk_assessment": assess_live_geometry(base.physics_result),
        })
        stronger_pc = base.model_copy(update={
            "id": "m-event",
            "physics_result": base.physics_result.model_copy(update={"event_id": "m-event"}),
            "automatic_research_pc_assessment": research.model_copy(update={
                "estimated_pc": 0.0, "estimated_pc_scientific": "1e-320", "log10_pc": -319.0,
                "miss_sigma_ratio": 50.0,
            }),
            "ai_risk_assessment": assess_live_geometry(base.physics_result),
        })

        ranked = rank_screening_events([first, tied_better_geometry, stronger_pc])
        pc_ranks = {item.id: item.ai_risk_assessment.research_pc_rank for item in ranked}
        self.assertEqual(pc_ranks, {"z-event": 3, "a-event": 2, "m-event": 1})

    def test_score_varies_with_geometry_and_is_reproducible(self):
        event = _real_screened_event()
        physics = event.physics_result
        low_miss = physics.model_copy(update={
            "event_id": "near", "miss_distance": ScientificField(status="available", value=0.01, units="km"),
        })
        high_miss = physics.model_copy(update={
            "event_id": "far", "miss_distance": ScientificField(status="available", value=20.0, units="km"),
        })
        near_score = assess_live_geometry(low_miss)
        far_score = assess_live_geometry(high_miss)
        self.assertGreater(near_score.score, far_score.score)
        self.assertEqual(near_score.model_dump(), assess_live_geometry(low_miss).model_dump())

    def test_missing_or_invalid_live_features_do_not_create_score(self):
        event = _real_screened_event()
        physics = event.physics_result
        missing_speed = physics.model_copy(update={
            "relative_speed_at_tca": ScientificField(status="unavailable", units="km/s"),
        })
        invalid = physics.model_copy(update={"status": "invalid"})
        self.assertIsNone(assess_live_geometry(missing_speed))
        self.assertIsNone(assess_live_geometry(invalid))
        boundary = physics.model_copy(update={"status": "boundary", "tca_status": "boundary"})
        boundary_assessment = assess_live_geometry(boundary)
        self.assertIsNotNone(boundary_assessment)
        self.assertTrue(any("screening-horizon boundary" in item for item in boundary_assessment.model_quality["limitations"]))

    def test_final_ranking_is_stable_and_prior_pc_remains_labeled(self):
        event = _real_screened_event()
        event.ai_risk_assessment = assess_live_geometry(event.physics_result)
        other_physics = event.physics_result.model_copy(update={
            "event_id": "event-nearer",
            "miss_distance": ScientificField(status="available", value=0.01, units="km"),
        })
        other = event.model_copy(update={
            "id": "event-nearer", "physics_result": other_physics,
            "collision_probability": event.collision_probability.model_copy(update={"event_id": "event-nearer"}),
            "automatic_research_pc_assessment": event.automatic_research_pc_assessment.model_copy(update={
                "estimated_pc": 0.1, "estimated_pc_scientific": "1.0e-1", "log10_pc": -1.0,
            }),
            "ai_risk_assessment": assess_live_geometry(other_physics),
        })
        first = rank_screening_events([event, other])
        second = rank_screening_events([other, event])
        first_ranks = {item.id: item.ai_risk_assessment.final_priority_rank for item in first}
        second_ranks = {item.id: item.ai_risk_assessment.final_priority_rank for item in second}
        self.assertEqual(first_ranks, second_ranks)
        self.assertEqual(next(item for item in first if item.id == "event-nearer").ai_risk_assessment.research_pc_rank, 1)
        ranked_other = next(item for item in first if item.id == "event-nearer")
        self.assertIn("ESA-prior Pc retains its unvalidated research-prior status", ranked_other.ai_risk_assessment.ranking_explanation)


if __name__ == "__main__":
    unittest.main()
