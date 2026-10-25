from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import copy
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.ai import collision_models
from app.ai.collision_training import grouped_split
from app.main import _backfill_archived_research_pc, app
from app.models import ConjunctionAssessmentEvent
from app.services.automatic_research_pc import assess_automatic_research_pc


class CollisionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _snapshot, events = collision_models_event_source()
        cls.event = next(event for event in events if event.physics_result.status == "valid")
        research = assess_automatic_research_pc(
            cls.event.physics_result,
            cls.event.collision_probability,
            cls.event.review_priority,
            primary=cls.event.primary,
            secondary=cls.event.secondary,
        )
        cls.event = cls.event.model_copy(update={"automatic_research_pc_assessment": research})

    def test_grouped_split_is_fixed_seed_and_disjoint_by_encounter_group(self) -> None:
        parents = [f"parent-{index:02}" for index in range(40)]
        group_by_parent = {parent: f"encounter-{index // 2:02}" for index, parent in enumerate(parents)}
        first = grouped_split(parents, seed=31, group_by_parent=group_by_parent)
        self.assertEqual(first, grouped_split(parents, seed=31, group_by_parent=group_by_parent))
        groups = [set(first[name]) for name in ("train", "validation", "test")]
        self.assertFalse(groups[0] & groups[1])
        self.assertFalse(groups[0] & groups[2])
        self.assertFalse(groups[1] & groups[2])
        self.assertEqual(set.union(*groups), set(parents))
        group_splits = [{group_by_parent[parent] for parent in split} for split in groups]
        self.assertFalse(group_splits[0] & group_splits[1])
        self.assertFalse(group_splits[0] & group_splits[2])
        self.assertFalse(group_splits[1] & group_splits[2])

    def test_missing_models_use_explicit_deterministic_fallback_not_ai_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.joblib"
            with patch.multiple(
                collision_models,
                PC_ARTIFACT=missing,
                PC_METADATA=missing.with_suffix(".json"),
                RISK_ARTIFACT=missing,
                RISK_METADATA=missing.with_suffix(".json"),
            ):
                collision_models._load_validated_artifact.cache_clear()
                before_physics = self.event.physics_result.model_dump(mode="json")
                result = collision_models.assess_collision_ai(self.event)
                self.assertEqual(result.status, "fallback")
                self.assertEqual(result.pc_surrogate.status, "fallback")
                self.assertIsNone(result.pc_surrogate.ai_predicted_log10_pc)
                self.assertEqual(result.pc_surrogate.fallback_method, "physics_research_pc_reference")
                self.assertEqual(result.risk_classifier.status, "fallback")
                self.assertIsNone(result.risk_classifier.ai_risk_class)
                self.assertEqual(result.risk_classifier.fallback_method, "physics_research_pc_classification")
                self.assertTrue(result.inference_provenance["physics_research_pc_remains_authoritative"])
                self.assertEqual(before_physics, self.event.physics_result.model_dump(mode="json"))
            collision_models._load_validated_artifact.cache_clear()

    def test_model_status_does_not_claim_metrics_for_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.joblib"
            status = collision_models._model_status(missing, missing.with_suffix(".json"))
            self.assertEqual(status["status"], "unavailable")
            self.assertEqual(status["reason_code"], "MODEL_ARTIFACT_OR_METADATA_MISSING")
            self.assertIsNone(status["metrics"])

    def test_current_live_features_match_declared_schema(self) -> None:
        from app.ai.collision_features import FEATURE_NAMES, build_collision_features

        features = build_collision_features(self.event)
        self.assertIsNotNone(features)
        self.assertEqual(tuple(features), FEATURE_NAMES)
        self.assertTrue(all(isinstance(value, float) for value in features.values()))

    def test_archived_physics_event_receives_separate_research_and_ai_channels(self) -> None:
        snapshot, events = collision_models_event_source()
        source_record = next(record for record in snapshot["result"]["data"]
                             if record.get("physics_result", {}).get("status") == "valid")
        result = {"data": [copy.deepcopy(source_record)]}
        _backfill_archived_research_pc(result)
        restored = result["data"][0]
        self.assertEqual(restored["automatic_research_pc_assessment"]["status"], "prior_based_research_estimate")
        self.assertEqual(restored["collision_ai_assessment"]["result_type"], "collision_ai_assessment")
        self.assertIn(restored["collision_ai_assessment"]["status"], {"available", "partial", "fallback", "unavailable"})
        self.assertEqual(restored["physics_result"]["event_id"], restored["id"])
        self.assertIsNotNone(restored["automatic_research_pc_assessment"]["estimated_pc_scientific"])

    def test_collision_model_status_api_exposes_separate_model_tasks(self) -> None:
        response = TestClient(app).get("/api/collision-models")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["training_mode"], "offline_only")
        self.assertIn("pc_surrogate", body)
        self.assertIn("risk_classifier", body)


def collision_models_event_source():
    from app.ai.collision_training import read_parent_events

    return read_parent_events()


if __name__ == "__main__":
    unittest.main()
