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
        for event in events:
            research = event.automatic_research_pc_assessment
            if research is None or research.status != "prior_based_research_estimate":
                research = assess_automatic_research_pc(
                    event.physics_result, event.collision_probability, event.review_priority,
                    primary=event.primary, secondary=event.secondary,
                )
            if research.status == "prior_based_research_estimate" and research.log10_pc is not None and research.log10_pc > -30:
                cls.event = event.model_copy(update={"automatic_research_pc_assessment": research})
                break
        else:
            raise AssertionError("Newest saved screening job has no estimable real event")

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

    def test_saved_collision_model_split_has_no_physical_encounter_leakage(self) -> None:
        import json
        metadata = json.loads(collision_models.PC_METADATA.read_text(encoding="utf-8"))
        manifest = metadata["scenario_split"]
        encounter_splits = manifest["encounter_group_ids"]
        self.assertEqual(manifest["grouping_key"], "encounter_group_id")
        self.assertEqual(len(set.union(*(set(values) for values in encounter_splits.values()))),
                         metadata["dataset_provenance"]["unique_physical_encounter_groups_with_scenarios"])
        names = ("train", "validation", "test")
        for left_index, left in enumerate(names):
            for right in names[left_index + 1:]:
                self.assertFalse(set(encounter_splits[left]) & set(encounter_splits[right]))

    def test_miss_distance_scenarios_are_true_multiples_of_parent_geometry(self) -> None:
        from app.ai.collision_training import MISS_DISTANCE_SCALES, SCENARIO_DESIGNS, _scenario_event

        self.assertTrue({1.0, 2.0, 3.0}.issubset(set(MISS_DISTANCE_SCALES)))
        self.assertEqual(len(SCENARIO_DESIGNS), len(MISS_DISTANCE_SCALES) * 3)
        import numpy as np
        physics = self.event.physics_result
        primary = np.asarray(physics.primary_state_at_tca["position_km"], dtype=float)
        secondary = np.asarray(physics.secondary_state_at_tca["position_km"], dtype=float)
        velocity = (np.asarray(physics.secondary_state_at_tca["velocity_km_s"], dtype=float)
                    - np.asarray(physics.primary_state_at_tca["velocity_km_s"], dtype=float))
        relative = secondary - primary
        encounter = relative - velocity * (float(np.dot(relative, velocity)) / float(np.dot(velocity, velocity)))
        original = float(np.linalg.norm(encounter))
        for multiplier in (1.0, 2.0, 3.0):
            scenario = _scenario_event(self.event, 1.0, multiplier)
            self.assertAlmostEqual(scenario.physics_result.miss_distance.value, original * multiplier, places=6)
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

    def test_pc_surrogate_withholds_prediction_below_its_training_target_floor(self) -> None:
        class PcEstimator:
            def predict(self, _values):
                return [-295.3813]

        class RiskEstimator:
            classes_ = ["High", "Low", "Medium"]

            def predict(self, _values):
                return ["Low"]

            def predict_proba(self, _values):
                return [[0.01, 0.98, 0.01]]

        metadata = {"model_name": "test", "model_version": "test", "target_definition": "max(log10(research_pc), -30)"}
        def load_model(artifact, _metadata):
            return (PcEstimator() if artifact == collision_models.PC_ARTIFACT else RiskEstimator()), metadata

        with patch.object(collision_models, "_load_model", side_effect=load_model):
            result = collision_models.assess_collision_ai(self.event)

        self.assertEqual(result.pc_surrogate.status, "unavailable")
        self.assertIsNone(result.pc_surrogate.ai_predicted_log10_pc)
        self.assertEqual(result.pc_surrogate.reason_code, "MODEL_PREDICTION_OUTSIDE_TRAINING_TARGET_RANGE")
        self.assertEqual(result.risk_classifier.ai_risk_class, "Low")

    def test_archived_physics_event_receives_separate_research_and_ai_channels(self) -> None:
        _snapshot, events = collision_models_event_source()
        source_record = next(event.model_dump(mode="json") for event in events
                             if event.physics_result.status == "valid")
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
