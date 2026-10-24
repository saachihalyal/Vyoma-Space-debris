from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.ai import FEATURE_SCHEMA_VERSION
from app.ai.anomaly import ARTIFACT_PATH, METADATA_PATH, _load_artifact, model_status, predict_orbital_anomaly
from app.ai.anomaly_training import MIN_TRAINING_EVENTS, fit_anomaly_model
from app.ai.features import FEATURE_NAMES, FEATURE_UNITS
from app.models import (
    ConjunctionAssessmentEvent, ObjectSummary, OrbitalAnomalyResult, PhysicsResult,
    Provenance, ScientificField,
)
from app.main import app


HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


@unittest.skipUnless(HAS_SKLEARN, "optional scikit-learn runtime is not installed")
class OrbitalAnomalyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(_load_artifact.cache_clear)
        self.artifact = Path(self.temp.name) / "test.joblib"
        self.metadata = Path(self.temp.name) / "test.metadata.json"
        _write_fixture_artifact(self.artifact, self.metadata)

    def test_valid_stage2a_physics_runs_isolation_forest_and_serializes_features(self):
        result = predict_orbital_anomaly(_physics(), artifact_path=self.artifact, metadata_path=self.metadata)
        self.assertEqual(result.status, "available")
        self.assertIn(result.classification, {"unusual", "not_flagged"})
        self.assertGreaterEqual(result.anomaly_score, 0.0)
        self.assertLessEqual(result.anomaly_score, 1.0)
        self.assertEqual(set(result.input_features), set(FEATURE_NAMES))
        self.assertEqual(result.provenance["source_physics_event_id"], "CA-TEST")
        payload = result.model_dump(mode="json")
        self.assertEqual(payload["result_type"], "orbital_anomaly")
        event_payload = ConjunctionAssessmentEvent(
            id="CA-TEST", primary=_object("10001"), secondary=_object("10002"),
            obj_a=_object("10001"), obj_b=_object("10002"), pair_type="SATELLITE vs DEBRIS",
            provenance=_provenance(), physics_result=_physics(), anomaly_result=result,
        ).model_dump(mode="json")
        self.assertEqual(event_payload["anomaly_result"]["status"], "available")
        self.assertEqual(event_payload["anomaly_result"]["decision_score"], result.decision_score)
        self.assertNotIn("pc", event_payload["anomaly_result"])

    def test_invalid_or_incomplete_physics_is_unavailable_without_zero_score(self):
        invalid = _physics().model_copy(update={"status": "invalid", "tca_status": "invalid"})
        result = predict_orbital_anomaly(invalid, artifact_path=self.artifact, metadata_path=self.metadata)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "PHYSICS_ENCOUNTER_UNAVAILABLE")
        self.assertIsNone(result.anomaly_score)
        self.assertIsNone(result.decision_score)
        self.assertIsNone(result.input_features)

    def test_missing_artifact_and_schema_mismatch_are_unavailable(self):
        missing = predict_orbital_anomaly(_physics(), artifact_path=Path(self.temp.name) / "missing", metadata_path=self.metadata)
        self.assertEqual(missing.reason_code, "ANOMALY_ARTIFACT_UNAVAILABLE")
        body = json.loads(self.metadata.read_text(encoding="utf-8"))
        body["feature_names"] = ["wrong"]
        self.metadata.write_text(json.dumps(body), encoding="utf-8")
        _load_artifact.cache_clear()
        mismatch = predict_orbital_anomaly(_physics(), artifact_path=self.artifact, metadata_path=self.metadata)
        self.assertEqual(mismatch.reason_code, "ANOMALY_FEATURE_SCHEMA_MISMATCH")

    def test_nonfinite_live_input_never_becomes_prediction(self):
        physics = _physics().model_copy(update={
            "miss_distance": ScientificField(status="available", value=float("nan"), units="km"),
        })
        result = predict_orbital_anomaly(physics, artifact_path=self.artifact, metadata_path=self.metadata)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE")
        self.assertIsNone(result.anomaly_score)

    def test_training_rejects_insufficient_or_nonfinite_data(self):
        with self.assertRaisesRegex(ValueError, "independent training events"):
            fit_anomaly_model(np.zeros((MIN_TRAINING_EVENTS - 1, len(FEATURE_NAMES))))
        with self.assertRaisesRegex(ValueError, "must be finite"):
            fit_anomaly_model(np.full((MIN_TRAINING_EVENTS, len(FEATURE_NAMES)), np.nan))

    def test_openapi_event_contract_exposes_distinct_anomaly_result(self):
        schemas = app.openapi()["components"]["schemas"]
        self.assertIn("anomaly_result", schemas["ConjunctionAssessmentEvent"]["properties"])
        self.assertIn("anomaly_score", schemas["OrbitalAnomalyResult"]["properties"])
        self.assertIn("decision_score", schemas["OrbitalAnomalyResult"]["properties"])


@unittest.skipUnless(HAS_SKLEARN and ARTIFACT_PATH.is_file() and METADATA_PATH.is_file(), "trained artifact not present")
class SavedAnomalyArtifactTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_load_artifact.cache_clear)

    def test_saved_esa_trained_artifact_loads_and_produces_separate_score(self):
        self.assertEqual(model_status()["status"], "available")
        result = predict_orbital_anomaly(_physics())
        self.assertEqual(result.status, "available")
        self.assertEqual(result.model_name, model_status()["model_name"])
        self.assertEqual(result.training_dataset, "ESA Collision Avoidance Challenge training dataset")
        self.assertEqual(result.provenance["source_physics_event_id"], "CA-TEST")
        self.assertIn("not a probability", result.score_definition)

    def test_three_distinct_physical_events_use_their_own_features_and_model_scores(self):
        bundle, metadata, failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
        self.assertIsNone(failure)
        events = [
            _physics(event_id="TEST-EVENT-A", miss=(1.0, 2.0, 2.0), velocity=(0.0, 3.0, 4.0), tca_hour=12),
            _physics(event_id="TEST-EVENT-B", miss=(-2.0, 0.0, 0.0), velocity=(1.0, 2.0, 2.0), tca_hour=16),
            _physics(event_id="TEST-EVENT-C", miss=(0.0, 0.0, 4.0), velocity=(4.0, 0.0, 3.0), tca_hour=20),
        ]
        results = [predict_orbital_anomaly(event) for event in events]
        self.assertEqual(len({tuple(result.input_features[name] for name in FEATURE_NAMES) for result in results}), 3)
        reference = np.sort(np.asarray(bundle["training_decision_scores"], dtype=np.float64))
        for event, result in zip(events, results):
            row = np.asarray([[result.input_features[name] for name in FEATURE_NAMES]], dtype=np.float64)
            expected_decision = float(bundle["model"].decision_function(row)[0])
            expected_rank = 1.0 - float(np.searchsorted(reference, expected_decision, side="right") / reference.size)
            self.assertEqual(result.provenance["source_physics_event_id"], event.event_id)
            self.assertAlmostEqual(result.decision_score, expected_decision, places=12)
            self.assertAlmostEqual(result.anomaly_score, expected_rank, places=12)
            self.assertEqual(result.model_name, metadata["model_name"])
            self.assertEqual(result.provenance["artifact_sha256"], metadata["artifact_sha256"])


def _write_fixture_artifact(artifact: Path, metadata_path: Path) -> None:
    import joblib
    import sklearn
    from sklearn.ensemble import IsolationForest

    # Unit-test-only reference fixture; production artifacts are fitted by
    # anomaly_training.py from the ESA archive's event-level training split.
    rng = np.random.default_rng(42)
    X = rng.normal(size=(MIN_TRAINING_EVENTS, len(FEATURE_NAMES)))
    model = IsolationForest(n_estimators=10, random_state=42, contamination="auto", n_jobs=1).fit(X)
    scores = model.decision_function(X)
    joblib.dump({
        "model": model, "training_decision_scores": scores,
        "feature_names": list(FEATURE_NAMES), "feature_units": dict(FEATURE_UNITS),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }, artifact)
    metadata_path.write_text(json.dumps({
        "model_name": "unit-test fixture only", "model_version": "test",
        "dataset_name": "test fixture, not real observations",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES), "feature_units": FEATURE_UNITS,
        "dataset_sha256": "test-only", "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "training_reference_event_count": MIN_TRAINING_EVENTS,
        "minimum_training_events": MIN_TRAINING_EVENTS,
        "package_versions": {"scikit_learn": sklearn.__version__},
    }), encoding="utf-8")


def _physics(*, event_id="CA-TEST", miss=(1.0, 2.0, 2.0), velocity=(0.0, 3.0, 4.0), tca_hour=12) -> PhysicsResult:
    import math
    tca = f"2025-01-01T{tca_hour:02d}:00:00+00:00"
    miss_distance = math.sqrt(sum(value * value for value in miss))
    relative_speed = math.sqrt(sum(value * value for value in velocity))
    return PhysicsResult(
        event_id=event_id, status="valid", provenance=_provenance(),
        object_primary_id="10001", object_secondary_id="10002",
        screening_horizon_start="2025-01-01T00:00:00+00:00",
        screening_horizon_end="2025-01-02T00:00:00+00:00", tca_status="valid",
        state_information={"source_frame": "TEME"},
        tca=ScientificField(status="available", value=tca, units="UTC"),
        miss_distance=ScientificField(status="available", value=miss_distance, units="km"),
        relative_position_at_tca=ScientificField(status="available", value=list(miss), units="km"),
        relative_velocity_at_tca=ScientificField(status="available", value=list(velocity), units="km/s"),
        relative_speed_at_tca=ScientificField(status="available", value=relative_speed, units="km/s"),
        primary_state_at_tca={"epoch": tca, "position_km": [7000.0, 0.0, 0.0], "velocity_km_s": [0.0, 7.5, 0.0], "frame": "TEME"},
    )


def _provenance():
    return Provenance(source="unit test", source_type="live", method="test", method_version="1", validity_status="valid")


def _object(object_id: str):
    return ObjectSummary(
        id=object_id, name=f"Object {object_id}", category="debris", object_type="DEBRIS",
        band="LEO", orbit_type="LEO", altitude_km=500, inclination_deg=50, velocity_kms=7.5,
        heuristic_risk_score=0.1, heuristic_forecast_score=0.1, provenance=_provenance(),
        heuristic_score_provenance=_provenance(),
    )


if __name__ == "__main__":
    unittest.main()
