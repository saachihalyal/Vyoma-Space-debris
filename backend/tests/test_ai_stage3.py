from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import numpy as np

from app.ai import FEATURE_SCHEMA_VERSION
from app.ai.comparison import compare_ml_and_physics
from app.ai.eligibility import (
    LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON,
    LIVE_TIME_TO_TCA_INVALID_REASON,
    live_time_to_tca_ineligibility_reason,
)
from app.ai.features import FEATURE_NAMES, extract_live_features
from app.ai.inference import ARTIFACT_PATH, LIVE_FEATURE_COMPATIBILITY_REASON, METADATA_PATH, _load_artifact, model_status, predict_from_physics
from app.ai.training import REQUIRED_COLUMNS, read_esa_training_data, split_event_ids, split_group_ids
from app.models import (
    CollisionProbabilityResult,
    MLResult,
    OrbitalAnomalyResult,
    PhysicsResult,
    Provenance,
    ScientificField,
)


HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


class ESAArchiveTrainingTests(unittest.TestCase):
    def test_reads_zip_without_extracting_and_uses_final_log10_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "train_data.zip"
            _write_training_zip(archive_path, include_leak_fields=True)
            result = read_esa_training_data(archive_path)
            self.assertEqual(result.summary["rows_read"], 6)
            self.assertEqual(result.summary["unique_events"], 3)
            self.assertEqual(result.summary["forecastable_events"], 2)
            self.assertEqual(result.summary["single_row_events_excluded"], 1)
            self.assertEqual(result.X.shape, (3, 9))
            self.assertEqual(result.y.tolist(), [-7.0, -6.0, -6.0])
            self.assertEqual(result.groups.tolist(), ["0", "1", "1"])
            self.assertEqual(result.X[:, 0].tolist(), [2.0, 3.0, 2.0])
            self.assertEqual(result.summary["target_min_log10"], -7.0)
            self.assertEqual(result.summary["target_max_log10"], -6.0)
            self.assertEqual(set(FEATURE_NAMES) & {"risk", "mission_id", "max_risk_estimate", "max_risk_scaling"}, set())
            self.assertFalse((Path(temp_dir) / "train_data.csv").exists())

    def test_required_columns_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "train_data.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("train_data.csv", "event_id,time_to_tca,risk\n1,1,-8\n")
            with self.assertRaisesRegex(ValueError, "missing required columns"):
                read_esa_training_data(archive_path)

    def test_event_split_has_no_event_overlap_and_expected_proportions(self) -> None:
        splits = split_event_ids([f"event-{i:03d}" for i in range(100)], seed=42)
        self.assertEqual({key: len(value) for key, value in splits.items()}, {"train": 70, "validation": 15, "test": 15})
        self.assertFalse(splits["train"] & splits["validation"])
        self.assertFalse(splits["train"] & splits["test"])
        self.assertFalse(splits["validation"] & splits["test"])


class Stage2AFeatureAdapterTests(unittest.TestCase):
    def test_mission_group_split_is_deterministic_and_disjoint(self) -> None:
        groups = {f"mission-{index:02d}" for index in range(20)}
        first = split_group_ids(groups, seed=42)
        self.assertEqual(first, split_group_ids(groups, seed=42))
        self.assertFalse(first["train"] & first["validation"])
        self.assertFalse(first["train"] & first["test"])
        self.assertFalse(first["validation"] & first["test"])
        self.assertEqual(sum(map(len, first.values())), len(groups))

    def test_teme_to_primary_instantaneous_rtn_and_unit_conversions(self) -> None:
        result = extract_live_features(_physics(time_to_tca_days=0.5))
        self.assertIsNone(result.reason_code)
        self.assertEqual(result.frame, "instantaneous primary RTN at TCA")
        self.assertEqual(result.values["time_to_tca_days"], 0.5)
        self.assertEqual(result.values["miss_distance_m"], 3000.0)
        self.assertEqual(result.values["relative_speed_m_s"], 5000.0)
        self.assertEqual(result.values["relative_position_r_m"], 1000.0)
        self.assertEqual(result.values["relative_position_t_m"], 2000.0)
        self.assertEqual(result.values["relative_position_n_m"], 2000.0)
        self.assertEqual(result.values["relative_velocity_r_m_s"], 0.0)
        self.assertEqual(result.values["relative_velocity_t_m_s"], 3000.0)
        self.assertEqual(result.values["relative_velocity_n_m_s"], 4000.0)
        self.assertEqual(set(result.values), set(FEATURE_NAMES))
        self.assertTrue(all(result.availability.values()))

    def test_degenerate_rtn_basis_is_unavailable(self) -> None:
        physics = _physics()
        degenerate = physics.model_copy(update={
            "primary_state_at_tca": {
                **physics.primary_state_at_tca,
                "velocity_km_s": [7.5, 0.0, 0.0],
            }
        })
        result = extract_live_features(degenerate)
        self.assertIsNone(result.values)
        self.assertEqual(result.reason_code, "DEGENERATE_RTN_BASIS")

    def test_missing_or_wrong_unit_live_features_are_not_imputed(self) -> None:
        physics = _physics().model_copy(update={
            "miss_distance": ScientificField(status="unavailable", reason_code="missing_test_feature"),
        })
        result = extract_live_features(physics)
        self.assertIsNone(result.values)
        self.assertEqual(result.reason_code, "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE")
        self.assertFalse(result.availability["miss_distance_m"])
        self.assertTrue(result.availability["relative_speed_m_s"])
        self.assertTrue(result.availability["time_to_tca_days"])
        wrong_units = _physics().model_copy(update={
            "relative_speed_at_tca": ScientificField(status="available", value=5.0, units="m/s"),
        })
        self.assertEqual(extract_live_features(wrong_units).reason_code, "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE")


@unittest.skipUnless(HAS_SKLEARN, "optional scikit-learn runtime is not installed")
class Stage3InferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(_load_artifact.cache_clear)
        self.artifact_path = Path(self.temp.name) / "test_model.joblib"
        self.metadata_path = Path(self.temp.name) / "test_model.metadata.json"
        _write_test_model(self.artifact_path, self.metadata_path)

    def test_loader_rejects_metadata_schema_and_model_identity_mismatches(self) -> None:
        original = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        mismatches = [
            ({**original, "feature_names": list(reversed(FEATURE_NAMES))}, "MODEL_METADATA_FEATURE_SCHEMA_MISMATCH"),
            ({**original, "feature_units": {**original["feature_units"], "miss_distance_m": "km"}}, "MODEL_METADATA_FEATURE_SCHEMA_MISMATCH"),
            ({**original, "model_version": "99.0"}, "MODEL_METADATA_IDENTITY_MISMATCH"),
            ({**original, "target_units": "probability"}, "MODEL_METADATA_TARGET_SEMANTICS_MISMATCH"),
        ]
        for metadata, expected_reason in mismatches:
            with self.subTest(reason=expected_reason, metadata=metadata):
                self.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                _load_artifact.cache_clear()
                _, _, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
                self.assertEqual(failure, expected_reason)
        self.metadata_path.write_text(json.dumps(original), encoding="utf-8")
        _load_artifact.cache_clear()
        _, _, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)

    def test_missing_artifact_returns_explicit_unavailable_result(self) -> None:
        result = predict_from_physics(
            _physics(),
            artifact_path=Path(self.temp.name) / "absent.joblib",
            metadata_path=Path(self.temp.name) / "absent.json",
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "MODEL_ARTIFACT_UNAVAILABLE")
        self.assertIsNone(result.prediction)

    def test_missing_live_features_return_unavailable_not_a_prediction(self) -> None:
        physics = _physics().model_copy(update={
            "relative_position_at_tca": ScientificField(reason_code="missing_test_feature"),
        })
        result = predict_from_physics(physics, artifact_path=self.artifact_path, metadata_path=self.metadata_path)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "REQUIRED_PHYSICS_FEATURE_UNAVAILABLE")
        self.assertIsNone(result.prediction)
        self.assertIsNone(result.validation_metrics)
        self.assertFalse(result.features_imputed)

    def test_live_time_to_tca_gate_is_inclusive_and_fails_closed(self) -> None:
        self.assertEqual(live_time_to_tca_ineligibility_reason(1.999), LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON)
        self.assertIsNone(live_time_to_tca_ineligibility_reason(2.0))
        self.assertIsNone(live_time_to_tca_ineligibility_reason(2.001))
        for value in (None, float("nan"), float("inf"), float("-inf"), -0.1, "2.0", True):
            with self.subTest(value=value):
                self.assertEqual(live_time_to_tca_ineligibility_reason(value), LIVE_TIME_TO_TCA_INVALID_REASON)

    def test_below_two_days_is_unavailable_without_changing_physics_or_pc(self) -> None:
        physics = _physics(time_to_tca_days=1.999)
        physics_before = physics.model_dump(mode="json")
        pc_result = CollisionProbabilityResult(
            status="available", event_id=physics.event_id, pc=1e-7,
            provenance=Provenance(source="independent test Pc", source_type="derived"),
        )
        pc_before = pc_result.model_dump(mode="json")
        bundle, metadata, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)
        with patch("app.ai.inference._load_artifact", return_value=(bundle, metadata, None)):
            with patch.object(bundle["primary_model"], "predict", wraps=bundle["primary_model"].predict) as predict:
                result = predict_from_physics(physics)
        predict.assert_not_called()
        payload = result.model_dump(mode="json")
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON)
        self.assertIsNone(result.prediction)
        self.assertIsNone(result.validation_metrics)
        self.assertEqual(payload["reason_code"], LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON)
        self.assertEqual(physics.status, "valid")
        self.assertEqual(physics.model_dump(mode="json"), physics_before)
        self.assertEqual(pc_result.status, "available")
        self.assertEqual(pc_result.pc, 1e-7)
        self.assertEqual(pc_result.model_dump(mode="json"), pc_before)

    def test_eligible_live_features_are_not_inferred_without_semantic_compatibility(self) -> None:
        bundle, metadata, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)
        with patch("app.ai.inference._load_artifact", return_value=(bundle, metadata, None)):
            with patch.object(bundle["primary_model"], "predict", wraps=bundle["primary_model"].predict) as predict:
                for days in (2.0, 2.001):
                    with self.subTest(days=days):
                        result = predict_from_physics(_physics(time_to_tca_days=days))
                        self.assertEqual(result.status, "unavailable")
                        self.assertEqual(result.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
                        self.assertIsNone(result.prediction)
                        self.assertEqual(result.provenance["live_feature_semantics_compatibility"], "unverified")
                predict.assert_not_called()

    def test_missing_nonfinite_and_invalid_timestamps_are_unavailable(self) -> None:
        bundle, metadata, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)
        invalid_horizons = (None, float("nan"), float("inf"), "not-a-timestamp")
        with patch("app.ai.inference._load_artifact", return_value=(bundle, metadata, None)):
            for value in invalid_horizons:
                with self.subTest(horizon=value):
                    physics = _physics(time_to_tca_days=2.0).model_copy(update={"screening_horizon_start": value})
                    result = predict_from_physics(physics)
                    self.assertEqual(result.status, "unavailable")
                    self.assertEqual(result.reason_code, LIVE_TIME_TO_TCA_INVALID_REASON)
                    self.assertIsNone(result.prediction)
            for value in (None, float("nan"), float("inf"), "not-a-timestamp"):
                with self.subTest(tca=value):
                    physics = _physics(time_to_tca_days=2.0).model_copy(update={
                        "tca": ScientificField(status="available", value=value, units="UTC"),
                    })
                    result = predict_from_physics(physics)
                    self.assertEqual(result.status, "unavailable")
                    self.assertEqual(result.reason_code, LIVE_TIME_TO_TCA_INVALID_REASON)
                    self.assertIsNone(result.prediction)
            inconsistent = _physics(time_to_tca_days=2.0).model_copy(update={
                "primary_state_at_tca": {
                    **_physics(time_to_tca_days=2.0).primary_state_at_tca,
                    "epoch": "2025-01-01T12:00:01+00:00",
                },
            })
            result = predict_from_physics(inconsistent)
            self.assertEqual(result.status, "unavailable")
            self.assertEqual(result.reason_code, LIVE_TIME_TO_TCA_INVALID_REASON)
            self.assertIsNone(result.prediction)

    def test_unavailable_esa_result_serializes_separately_from_anomaly_result(self) -> None:
        ml = predict_from_physics(
            _physics(time_to_tca_days=1.0),
            artifact_path=self.artifact_path,
            metadata_path=self.metadata_path,
        )
        anomaly = OrbitalAnomalyResult(status="available", anomaly_score=0.9, classification="unusual")
        ml_payload = ml.model_dump(mode="json")
        anomaly_payload = anomaly.model_dump(mode="json")
        self.assertEqual(ml_payload["status"], "unavailable")
        self.assertEqual(ml_payload["reason_code"], LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON)
        self.assertIsNone(ml_payload["prediction"])
        self.assertEqual(anomaly_payload["anomaly_score"], 0.9)
        self.assertNotIn("prediction", anomaly_payload)

    def test_unverified_live_prediction_is_withheld_without_changing_physics_or_pc(self) -> None:
        physics = _physics()
        before = physics.model_dump(mode="json")
        ml_result = predict_from_physics(physics, artifact_path=self.artifact_path, metadata_path=self.metadata_path)
        after = physics.model_dump(mode="json")
        self.assertEqual(ml_result.status, "unavailable")
        self.assertEqual(ml_result.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertIsNone(ml_result.prediction)
        self.assertIn("not a calibrated probability or Foster Pc", ml_result.feature_schema["exponentiated_event_risk_display"])
        self.assertIn("unverified", ml_result.feature_schema["live_feature_semantics_compatibility"])
        self.assertFalse(ml_result.features_imputed)
        self.assertEqual(ml_result.provenance["source_physics_event_id"], physics.event_id)
        self.assertEqual(ml_result.provenance["live_feature_semantics_compatibility"], "unverified")
        self.assertEqual(before, after)

    def test_eligible_physics_event_does_not_invoke_estimator_without_verified_feature_semantics(self) -> None:
        _load_artifact.cache_clear()
        bundle, metadata, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)
        estimator = bundle["primary_model"]
        with patch("app.ai.inference._load_artifact", return_value=(bundle, metadata, None)):
            with patch.object(estimator, "predict", wraps=estimator.predict) as predict:
                result = predict_from_physics(_physics())
        predict.assert_not_called()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertIsNone(result.prediction)

    def test_ineligible_physics_event_is_unavailable_with_reason_without_inference(self) -> None:
        _load_artifact.cache_clear()
        bundle, metadata, failure = _load_artifact(str(self.artifact_path), str(self.metadata_path))
        self.assertIsNone(failure)
        estimator = bundle["primary_model"]
        invalid = _physics().model_copy(update={"status": "invalid", "tca_status": "invalid"})
        with patch("app.ai.inference._load_artifact", return_value=(bundle, metadata, None)):
            with patch.object(estimator, "predict", wraps=estimator.predict) as predict:
                result = predict_from_physics(invalid)
        predict.assert_not_called()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "PHYSICS_ENCOUNTER_UNAVAILABLE")
        self.assertIsNone(result.prediction)
        self.assertIsNone(result.validation_metrics)

    def test_comparison_marks_both_outputs_not_comparable(self) -> None:
        ml_result = predict_from_physics(_physics(), artifact_path=self.artifact_path, metadata_path=self.metadata_path)
        pc_result = CollisionProbabilityResult(
            status="available",
            event_id="CA-TEST",
            pc=1e-7,
            provenance=Provenance(source="test method", source_type="derived"),
        )
        comparison = compare_ml_and_physics(ml_result, pc_result)
        self.assertEqual(comparison.status, "unavailable")
        self.assertEqual(comparison.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertIsNone(comparison.consistency)
        self.assertEqual(comparison.validation_claim, "none")

    def test_ml_event_risk_is_not_comparable_to_geometry_when_pc_is_unavailable(self) -> None:
        ml_result = predict_from_physics(_physics(), artifact_path=self.artifact_path, metadata_path=self.metadata_path)
        comparison = compare_ml_and_physics(ml_result, None)
        self.assertEqual(comparison.status, "unavailable")
        self.assertEqual(comparison.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertFalse(comparison.physics_pc_available)


@unittest.skipUnless(HAS_SKLEARN and ARTIFACT_PATH.is_file() and METADATA_PATH.is_file(), "trained optional model artifact is unavailable")
class ShippedArtifactIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(_load_artifact.cache_clear)

    def test_saved_model_loads_and_attaches_to_stage2a_without_changing_physics(self) -> None:
        physics = _physics()
        before = physics.model_dump(mode="json")
        result = predict_from_physics(physics)
        self.assertEqual(model_status()["status"], "unavailable")
        self.assertEqual(model_status()["artifact_status"], "available")
        self.assertEqual(model_status()["reason_code"], LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertEqual(model_status()["feature_compatibility_status"], "unverified")
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.model_name, model_status()["model_name"])
        self.assertIsNone(result.prediction)
        self.assertEqual(result.reason_code, LIVE_FEATURE_COMPATIBILITY_REASON)
        self.assertEqual(result.provenance["source_physics_event_id"], physics.event_id)
        self.assertEqual(result.model_version, "2.0.0")
        self.assertEqual(result.provenance["live_feature_semantics_compatibility"], "unverified")
        _, metadata, failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
        self.assertIsNone(failure)
        self.assertEqual(metadata["validation_candidate_selected"], "ridge")
        self.assertFalse(metadata["mission_split_overlap"])
        self.assertEqual(metadata["metrics"]["test"]["ridge_baseline"]["test_event_count"], 3832)
        self.assertEqual(before, physics.model_dump(mode="json"))


def _physics(time_to_tca_days: float = 2.0) -> PhysicsResult:
    tca_epoch = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    horizon_start = tca_epoch - timedelta(days=time_to_tca_days)
    return PhysicsResult(
        event_id="CA-TEST",
        status="valid",
        applicability="within_configured_screening_horizon",
        provenance=Provenance(
            source="test Stage 2A result",
            source_type="live",
            method="SGP4 TEME trajectory screening",
            method_version="1.0",
            validity_status="valid",
        ),
        object_primary_id="10001",
        object_secondary_id="10002",
        screening_horizon_start=horizon_start.isoformat(),
        screening_horizon_end=(horizon_start + timedelta(days=1)).isoformat(),
        tca_status="valid",
        state_information={"source_frame": "TEME", "position_units": "km", "velocity_units": "km/s"},
        tca=ScientificField(status="available", value=tca_epoch.isoformat(), units="UTC"),
        miss_distance=ScientificField(status="available", value=3.0, units="km"),
        relative_position_at_tca=ScientificField(status="available", value=[1.0, 2.0, 2.0], units="km"),
        relative_velocity_at_tca=ScientificField(status="available", value=[0.0, 3.0, 4.0], units="km/s"),
        relative_speed_at_tca=ScientificField(status="available", value=5.0, units="km/s"),
        primary_state_at_tca={
            "object_id": "10001",
            "epoch": tca_epoch.isoformat(),
            "position_km": [7000.0, 0.0, 0.0],
            "velocity_km_s": [0.0, 7.5, 0.0],
            "frame": "TEME",
        },
    )


def _write_training_zip(path: Path, *, include_leak_fields: bool) -> None:
    columns = list(REQUIRED_COLUMNS)
    if include_leak_fields:
        columns += ["mission_id", "max_risk_estimate", "max_risk_scaling", "t_sigma_r", "mahalanobis_distance"]
    rows = [
        ["0", "2", "-8", "1", "2", "1", "0", "0", "0", "0", "0"],
        ["0", "1", "-7", "1", "2", "1", "0", "0", "0", "0", "0"],
        ["1", "3", "-9", "1", "2", "1", "0", "0", "0", "0", "0"],
        ["1", "2", "-8", "1", "2", "1", "0", "0", "0", "0", "0"],
        ["1", "1", "-6", "1", "2", "1", "0", "0", "0", "0", "0"],
        ["2", "1", "-10", "1", "2", "1", "0", "0", "0", "0", "0"],
    ]
    if include_leak_fields:
        rows = [row + ["999", "999", "999", "999", "999"] for row in rows]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("train_data.csv", buffer.getvalue())


def _write_test_model(artifact_path: Path, metadata_path: Path) -> None:
    import joblib
    import sklearn
    from sklearn.dummy import DummyRegressor

    model = DummyRegressor(strategy="constant", constant=-6.0)
    model.fit(np.zeros((2, len(FEATURE_NAMES))), np.array([-6.0, -6.0]))
    joblib.dump({
        "primary_model": model,
        "baseline_model": model,
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "target_definition": "final event risk in log10 space, selected from the latest CDM (minimum time_to_tca; last occurrence breaks ties)",
    }, artifact_path)
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps({
        "model_name": "ORION ESA event final log10-risk estimator",
        "model_version": "2.0.0",
        "dataset_name": "synthetic unit-test fixture only",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": {"time_to_tca_days": "day", "miss_distance_m": "m", "relative_speed_m_s": "m/s", "relative_position_r_m": "m", "relative_position_t_m": "m", "relative_position_n_m": "m", "relative_velocity_r_m_s": "m/s", "relative_velocity_t_m_s": "m/s", "relative_velocity_n_m_s": "m/s"},
        "target_column": "risk",
        "target_definition": "final event risk in log10 space, selected from the latest CDM (minimum time_to_tca; last occurrence breaks ties)",
        "target_units": "log10 risk",
        "dataset_sha256": "test-fixture-hash",
        "artifact_sha256": digest,
        "package_versions": {"scikit_learn": sklearn.__version__},
        "metrics": {"test": {"hist_gradient_boosting": {"mae_log10": 0.0}}},
    }), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
