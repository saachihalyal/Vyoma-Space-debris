from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from app.ai import DATASET_NAME, MODEL_NAME, MODEL_VERSION
from app.ai import HIGH_RISK_THRESHOLD_LOG10
from app.ai.eligibility import prepare_eligible_splits, require_scorable_population
from app.ai.evaluation_audit import (
    _validate_artifact_protocol,
    build_audit_report,
    eligible_legacy_diagnostic_summary,
    select_eligible_latest_indices,
    split_group_ids,
)
from app.ai.training import TrainingData


class ESAEvaluationProtocolTests(unittest.TestCase):
    def test_fixture_metrics_and_mismatched_diagnostics_remain_unavailable(self) -> None:
        report = {
            "input_eligibility": {"boundary": "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days."},
            "split": {"test": {"eligible_events": 60, "high_risk_events": 51, "low_risk_events": 9}},
            "legacy_or_corrected_artifact_diagnostic": {
                "status": "legacy_unfiltered_artifact_scored_on_eligible_inputs",
                "training_population": "legacy unfiltered pre-final rows, including inputs under 2.0 days",
                "evaluation_population": "one closest-to-TCA eligible pre-final input per held-out event",
                "evidence_source": "fixture_only",
                "artifact_sha256": "artifact-hash",
                "metrics": {"high_risk_test_events": 51, "true_positive_high_risk_events": 0, "test_event_count": 60},
            },
        }
        summary = eligible_legacy_diagnostic_summary(report, expected_artifact_sha256="artifact-hash")
        self.assertIn("unavailable", summary)
        self.assertNotIn("0/51", summary)
        self.assertIn("unavailable", eligible_legacy_diagnostic_summary(None))
        self.assertIn("unavailable", eligible_legacy_diagnostic_summary(report, expected_artifact_sha256="other-artifact"))
        corrected = {**report, "legacy_or_corrected_artifact_diagnostic": {
            **report["legacy_or_corrected_artifact_diagnostic"],
            "status": "eligible_input_diagnostic_corrected_artifact",
        }}
        self.assertIn("unavailable", eligible_legacy_diagnostic_summary(corrected))

    def test_fixture_only_metrics_cannot_be_formatted_as_observed_artifact_results(self) -> None:
        report = {
            "input_eligibility": {"boundary": "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days."},
            "split": {"test": {"eligible_events": 2, "high_risk_events": 1, "low_risk_events": 1}},
            "legacy_or_corrected_artifact_diagnostic": {
                "status": "legacy_unfiltered_artifact_scored_on_eligible_inputs",
                "training_population": "legacy unfiltered pre-final rows, including inputs under 2.0 days",
                "evaluation_population": "one closest-to-TCA eligible pre-final input per held-out event",
                "evidence_source": "fixture_only",
                "artifact_sha256": "fixture-hash",
                "metrics": {"high_risk_test_events": 1, "true_positive_high_risk_events": 0, "test_event_count": 2},
            },
        }
        self.assertIn("unavailable", eligible_legacy_diagnostic_summary(report, expected_artifact_sha256="fixture-hash"))

    def test_artifact_identity_dataset_and_protocol_must_match(self) -> None:
        metadata = {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "dataset_name": DATASET_NAME,
            "target_column": "risk",
            "target_units": "log10 risk",
            "high_risk_threshold_log10": HIGH_RISK_THRESHOLD_LOG10,
            "artifact_sha256": "artifact-hash",
            "dataset_sha256": "dataset-hash",
            "event_split_hashes_sha256": {"train": "train-hash", "validation": "validation-hash", "test": "test-hash"},
            "train_forecast_example_count": 20,
        }
        valid_args = {
            "metadata": metadata,
            "expected_artifact_sha256": "artifact-hash",
            "expected_dataset_sha256": "dataset-hash",
            "expected_split_hashes": metadata["event_split_hashes_sha256"],
            "total_training_rows": 20,
            "eligible_training_rows": 10,
            "ineligible_training_rows": 10,
        }
        self.assertIsNone(_validate_artifact_protocol(**valid_args))
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "expected_artifact_sha256": "stale-hash"}), "ARTIFACT_SHA256_MISMATCH")
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "expected_dataset_sha256": "other-dataset"}), "ARTIFACT_DATASET_SHA256_MISMATCH")
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "metadata": {**metadata, "model_version": "stale"}}), "ARTIFACT_MODEL_IDENTITY_MISMATCH")
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "expected_split_hashes": {"train": "other", "validation": "validation-hash", "test": "test-hash"}}), "ARTIFACT_EVENT_SPLIT_MISMATCH")

        corrected = {
            **metadata,
            "eligible_input_protocol": {
                "minimum_time_to_tca_days_inclusive": 2.0,
                "training_rows": "all eligible pre-final CDMs within each training event",
                "validation_test_rows": "closest-to-TCA eligible pre-final CDM per event",
            },
            "train_forecast_example_count": 10,
        }
        self.assertIsNone(_validate_artifact_protocol(**{**valid_args, "metadata": corrected, "ineligible_training_rows": 0}))
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "metadata": corrected}), "ARTIFACT_TRAINING_PROTOCOL_UNVERIFIED")
        bad_boundary = {**corrected, "eligible_input_protocol": {**corrected["eligible_input_protocol"], "minimum_time_to_tca_days_inclusive": 1.999}}
        self.assertEqual(_validate_artifact_protocol(**{**valid_args, "metadata": bad_boundary, "ineligible_training_rows": 0}), "ARTIFACT_TRAINING_PROTOCOL_UNVERIFIED")

    def test_build_audit_report_returns_deterministic_eligible_population_counts(self) -> None:
        data = TrainingData(
            X=np.asarray([[1.999], [2.0], [3.0], [2.5], [1.999], [2.0], [4.0], [3.0]], dtype=float),
            y=np.asarray([-5.0, -5.0, -5.0, -8.0, -5.0, -5.0, -8.0, -8.0]),
            groups=np.asarray(["train-a", "train-a", "train-a", "train-b", "train-c", "val-a", "val-b", "test-b"], dtype=object),
            latest_forecast_indices={},
            event_ids=["train-a", "train-b", "train-c", "val-a", "val-b", "test-a", "test-b"],
            summary={},
        )
        splits = {"train": {"train-a", "train-b", "train-c"}, "validation": {"val-a", "val-b"}, "test": {"test-a", "test-b"}}
        mission_ids = {event_id: {f"mission-{event_id}"} for event_id in data.event_ids}
        with patch("app.ai.evaluation_audit.read_esa_training_data", return_value=data), \
             patch("app.ai.evaluation_audit.split_event_ids", return_value=splits), \
             patch("app.ai.evaluation_audit.read_event_missions", return_value=mission_ids), \
             patch("app.ai.evaluation_audit._sha256_file", return_value="fixture-dataset-hash"):
            first = build_audit_report(include_saved_artifact_diagnostic=False)
            second = build_audit_report(include_saved_artifact_diagnostic=False)

        self.assertIsInstance(first, dict)
        self.assertEqual(first, second)
        self.assertEqual(first["split"]["train"]["total_events"], 3)
        self.assertEqual(first["split"]["train"]["eligible_events"], 2)
        self.assertEqual(first["split"]["train"]["excluded_events_without_eligible_input"], 1)
        self.assertEqual(first["split"]["train"]["eligible_input_rows"], 3)
        self.assertEqual(first["split"]["train"]["high_risk_events"], 1)
        self.assertEqual(first["split"]["validation"]["eligible_events"], 2)
        self.assertEqual(first["split"]["test"]["eligible_events"], 1)
        self.assertEqual(first["input_eligibility"]["events_without_eligible_input"], 2)
        self.assertEqual(first["corrected_protocol_baseline_metrics"]["status"], "unavailable")
        self.assertEqual(first["corrected_protocol_baseline_metrics"]["reason_code"], "ELIGIBLE_POPULATION_NOT_SCORABLE")
        self.assertEqual(first["legacy_or_corrected_artifact_diagnostic"]["reason_code"], "ARTIFACT_DIAGNOSTIC_NOT_REQUESTED")
        self.assertFalse(first["model_fit_or_artifact_write_performed"])

    def test_selects_closest_pre_final_cdm_at_or_beyond_two_days(self) -> None:
        X = np.asarray([[1.999], [4.0], [2.0], [2.0], [2.001], [0.5], [np.nan]])
        groups = ["event-a", "event-a", "event-a", "event-a", "event-a", "event-b", "event-c"]

        selected = select_eligible_latest_indices(X, groups)

        # The cutoff is inclusive; equal-time ties resolve to the later source row.
        self.assertEqual(selected, {"event-a": 3})

    def test_eligibility_counts_include_all_rows_and_exclude_events_without_fallback(self) -> None:
        X = np.asarray([[1.999], [2.0], [2.5], [1.0], [3.0], [2.0]])
        y = np.asarray([-5.0, -5.0, -5.0, -8.0, -8.0, -6.0])
        groups = ["train-a", "train-a", "train-a", "train-b", "test-a", "test-b"]
        splits = {"train": {"train-a", "train-b"}, "validation": set(), "test": {"test-a", "test-b"}}

        prepared = prepare_eligible_splits(X, y, groups, splits)

        train = prepared["train"]
        self.assertEqual(train["event_ids"], ["train-a"])
        self.assertEqual(train["row_indices"], [1, 2])
        self.assertEqual(train["latest_indices"], {"train-a": 1})
        self.assertEqual(train["eligible_event_count"], 1)
        self.assertEqual(train["excluded_event_count"], 1)
        self.assertEqual(train["eligible_row_count"], 2)
        self.assertEqual(train["high_risk_event_count"], 1)
        self.assertEqual(train["low_risk_event_count"], 0)
        self.assertEqual(prepared["validation"]["eligible_event_count"], 0)
        self.assertEqual(prepared["test"]["eligible_event_count"], 2)
        self.assertEqual(prepared["test"]["high_risk_event_count"], 1)

    def test_overlapping_event_assignments_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap across splits"):
            prepare_eligible_splits(
                np.asarray([[2.0], [3.0]]), np.asarray([-8.0, -7.0]), ["event-a", "event-a"],
                {"train": {"event-a"}, "test": {"event-a"}},
            )

    def test_insufficient_or_single_class_population_has_explicit_error(self) -> None:
        one = {"eligible_event_count": 1, "high_risk_event_count": 1, "low_risk_event_count": 0}
        with self.assertRaisesRegex(ValueError, "at least 2"):
            require_scorable_population("test", one)
        single_class = {"eligible_event_count": 3, "high_risk_event_count": 3, "low_risk_event_count": 0}
        with self.assertRaisesRegex(ValueError, "high-risk and one low-risk"):
            require_scorable_population("test", single_class)

    def test_invalid_alignment_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned rows"):
            select_eligible_latest_indices(np.asarray([[2.0], [3.0]]), ["only-one"])

    def test_mission_group_split_is_deterministic_and_disjoint(self) -> None:
        first = split_group_ids([f"mission-{index}" for index in range(20)], seed=42)
        second = split_group_ids([f"mission-{index}" for index in range(20)], seed=42)

        self.assertEqual(first, second)
        self.assertEqual({key: len(value) for key, value in first.items()}, {
            "train": 14, "validation": 3, "test": 3,
        })
        self.assertFalse(first["train"] & first["validation"])
        self.assertFalse(first["train"] & first["test"])
        self.assertFalse(first["validation"] & first["test"])


if __name__ == "__main__":
    unittest.main()
