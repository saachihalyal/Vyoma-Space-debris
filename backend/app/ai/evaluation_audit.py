"""Read-only audit of the ESA challenge's two-day input restriction.

Run from ``backend`` with the optional ML dependencies installed:
``python -m app.ai.evaluation_audit``.

This module never fits or writes a model. It keeps the shipped event split,
filters each event's pre-final CDMs to the challenge input window, reports
simple training-label baselines, and scores the shipped artifact only as a
diagnostic because that artifact was trained with ineligible rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

from app.ai import DATASET_NAME, HIGH_RISK_THRESHOLD_LOG10, MODEL_NAME, MODEL_VERSION
from app.ai.eligibility import prepare_eligible_splits, require_scorable_population
from app.ai.inference import ARTIFACT_PATH, METADATA_PATH, _load_artifact
from app.ai.training import DATA_PATH, SEED, _sha256_file, read_esa_training_data, split_event_ids
from app.ai.validation import calculate_metrics


def select_eligible_latest_indices(X: np.ndarray, groups: Iterable[str]) -> dict[str, int]:
    """Select each event's closest-to-TCA pre-final CDM at least two days out.

    X/groups contain only earlier rows; the final CDM is the target source and
    is excluded by ``read_esa_training_data``. The 2.0-day boundary is
    inclusive: the ESA test-data description excludes rows *within* two days.
    A last-row tie break matches the original source-row ordering policy.
    """
    values = np.asarray(X, dtype=float)
    event_groups = list(groups)
    if values.ndim != 2 or values.shape[0] != len(event_groups) or values.shape[1] < 1:
        raise ValueError("X and groups must be aligned rows with a time_to_tca feature")
    prepared = prepare_eligible_splits(
        values, np.zeros(len(event_groups), dtype=float), event_groups,
        {"all": {str(event_id) for event_id in event_groups}},
    )
    return prepared["all"]["latest_indices"]


def split_group_ids(group_ids: Iterable[str], seed: int = SEED) -> dict[str, set[str]]:
    """Deterministic 70/15/15 split of group IDs (missions), without overlap."""
    shuffled = sorted(set(group_ids))
    random.Random(seed).shuffle(shuffled)
    train_end = int(0.70 * len(shuffled))
    validation_end = train_end + int(0.15 * len(shuffled))
    return {
        "train": set(shuffled[:train_end]),
        "validation": set(shuffled[train_end:validation_end]),
        "test": set(shuffled[validation_end:]),
    }


def read_event_missions(zip_path: Path = DATA_PATH) -> dict[str, set[str]]:
    """Read mission IDs per event without extracting or retaining CSV rows."""
    missions: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(zip_path) as archive:
        candidates = [item.filename for item in archive.infolist() if item.filename.endswith("train_data.csv")]
        if len(candidates) != 1:
            raise ValueError(f"Expected one train_data.csv in the ESA archive; found {len(candidates)}")
        with archive.open(candidates[0], "r") as binary_csv:
            reader = csv.reader(io.TextIOWrapper(binary_csv, encoding="utf-8-sig", newline=""))
            header = next(reader, None)
            if not header or "event_id" not in header or "mission_id" not in header:
                raise ValueError("ESA training CSV must contain event_id and mission_id columns")
            event_index, mission_index = header.index("event_id"), header.index("mission_id")
            for row in reader:
                if len(row) <= max(event_index, mission_index):
                    continue
                event_id, mission_id = row[event_index].strip(), row[mission_index].strip()
                if event_id and mission_id:
                    missions[event_id].add(mission_id)
    return dict(missions)


def build_audit_report(
    zip_path: Path = DATA_PATH,
    *,
    include_saved_artifact_diagnostic: bool = True,
) -> dict:
    """Build eligible-population counts and an explicitly qualified artifact diagnostic.

    This function never fits or writes a model. When requested, it scores the
    verified saved artifact on one eligible input per held-out event. Tests can
    set ``include_saved_artifact_diagnostic=False`` to exercise report assembly
    without loading or invoking any estimator.
    """
    data = read_esa_training_data(zip_path)
    original_splits = split_event_ids(data.event_ids, SEED)
    eligible_splits = prepare_eligible_splits(data.X, data.y, data.groups, original_splits)
    eligible_ids = set().union(*(set(split["event_ids"]) for split in eligible_splits.values()))
    latest_eligible_indices = {
        event_id: index
        for split in eligible_splits.values()
        for event_id, index in split["latest_indices"].items()
    }

    def labels(split_name: str) -> np.ndarray:
        split = eligible_splits[split_name]
        return np.asarray([data.y[split["latest_indices"][event_id]] for event_id in split["event_ids"]], dtype=float)

    split_report: dict[str, dict] = {}
    for name in ("train", "validation", "test"):
        split = eligible_splits[name]
        targets = labels(name)
        split_report[name] = {
            "total_events": split["total_event_count"],
            "eligible_events": split["eligible_event_count"],
            "excluded_events_without_eligible_input": split["excluded_event_count"],
            "eligible_input_rows": split["eligible_row_count"],
            "high_risk_events": split["high_risk_event_count"],
            "low_risk_events": split["low_risk_event_count"],
            "high_risk_prevalence": float(split["high_risk_event_count"] / len(targets)) if len(targets) else None,
            "target_median_log10": float(np.median(targets)) if len(targets) else None,
            "target_mean_log10": float(np.mean(targets)) if len(targets) else None,
        }

    training_rows = eligible_splits["train"]["row_indices"]
    total_training_rows = int(np.isin(data.groups, list(original_splits["train"])).sum())
    ineligible_training_rows = total_training_rows - len(training_rows)
    current_split_hashes = {
        name: hashlib.sha256("\n".join(sorted(event_ids)).encode("utf-8")).hexdigest()
        for name, event_ids in original_splits.items()
    }
    current_dataset_sha256 = _sha256_file(zip_path)

    protocol_metrics: dict = {"status": "unavailable", "reason_code": None, "metrics": {}}
    X_test: np.ndarray | None = None
    y_test: np.ndarray | None = None
    try:
        for name in ("train", "validation", "test"):
            require_scorable_population(name, eligible_splits[name])
        y_train, y_test = labels("train"), labels("test")
        test_ids = eligible_splits["test"]["event_ids"]
        test_indices = [eligible_splits["test"]["latest_indices"][event_id] for event_id in test_ids]
        X_test = data.X[test_indices]
        baselines = {
            name: calculate_metrics(y_test, np.full(len(y_test), constant, dtype=float))
            for name, constant in (("train_mean", float(np.mean(y_train))), ("train_median", float(np.median(y_train))))
        }
        protocol_metrics = {"status": "available", "reason_code": None, "metrics": baselines}
    except ValueError as exc:
        protocol_metrics["reason_code"] = "ELIGIBLE_POPULATION_NOT_SCORABLE"
        protocol_metrics["reason"] = str(exc)

    shipped_diagnostic: dict = {
        "status": "unavailable",
        "reason_code": "ARTIFACT_DIAGNOSTIC_NOT_REQUESTED" if not include_saved_artifact_diagnostic else None,
        "evidence_source": "none",
        "metrics": None,
    }
    if include_saved_artifact_diagnostic:
        primary, metadata, artifact_failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
        failure = artifact_failure or _validate_artifact_protocol(
            metadata,
            expected_artifact_sha256=_sha256_file(ARTIFACT_PATH) if ARTIFACT_PATH.is_file() else None,
            expected_dataset_sha256=current_dataset_sha256,
            expected_split_hashes=current_split_hashes,
            total_training_rows=total_training_rows,
            eligible_training_rows=len(training_rows),
            ineligible_training_rows=ineligible_training_rows,
        )
        if failure:
            shipped_diagnostic["reason_code"] = failure
        elif protocol_metrics["status"] != "available":
            shipped_diagnostic["reason_code"] = protocol_metrics["reason_code"]
            shipped_diagnostic["reason"] = protocol_metrics.get("reason")
        else:
            try:
                predictions = primary["primary_model"].predict(X_test)
                artifact_protocol = _artifact_training_protocol(
                    metadata,
                    total_training_rows=total_training_rows,
                    eligible_training_rows=len(training_rows),
                    ineligible_training_rows=ineligible_training_rows,
                )
                shipped_diagnostic = {
                    "status": "legacy_unfiltered_artifact_scored_on_eligible_inputs" if artifact_protocol == "legacy_unfiltered" else "eligible_input_diagnostic_corrected_artifact",
                    "training_population": "legacy unfiltered pre-final rows, including inputs under 2.0 days" if artifact_protocol == "legacy_unfiltered" else "eligible pre-final inputs (time_to_tca_days >= 2.0)",
                    "evaluation_population": "one closest-to-TCA eligible pre-final input per held-out event",
                    "evidence_source": "verified_saved_artifact_scoring",
                    "artifact_sha256": metadata["artifact_sha256"],
                    "dataset_sha256": current_dataset_sha256,
                    "metrics": calculate_metrics(y_test, predictions),
                }
            except Exception:
                shipped_diagnostic.update({"reason_code": "SAVED_ARTIFACT_DIAGNOSTIC_FAILED", "reason": "Verified artifact scoring or metric calculation failed."})

    mission_ids_by_event = read_event_missions(zip_path)
    mission_counts = {event_id: len(mission_ids_by_event.get(event_id, set())) for event_id in eligible_ids}
    exactly_one_mission = {event_id for event_id, count in mission_counts.items() if count == 1}
    mission_split = split_group_ids(
        mission_id
        for event_id in exactly_one_mission
        for mission_id in mission_ids_by_event[event_id]
    )
    mission_report = {
        "eligible_events": len(eligible_ids),
        "events_with_exactly_one_mission": len(exactly_one_mission),
        "events_with_no_mission": sum(count == 0 for count in mission_counts.values()),
        "events_with_multiple_missions": sum(count > 1 for count in mission_counts.values()),
        "unique_missions": sum(len(values) for values in mission_split.values()),
        "split_mission_counts": {name: len(ids) for name, ids in mission_split.items()},
        "split_event_counts": {},
    }
    for name, missions in mission_split.items():
        event_ids = sorted(
            event_id for event_id in exactly_one_mission
            if next(iter(mission_ids_by_event[event_id])) in missions
        )
        targets = np.asarray([data.y[latest_eligible_indices[event_id]] for event_id in event_ids], dtype=float)
        mission_report["split_event_counts"][name] = {
            "missions": len(missions),
            "events": len(event_ids),
            "high_risk_events": int(np.sum(targets >= HIGH_RISK_THRESHOLD_LOG10)),
        }

    return {
        "input_eligibility": {
            "rule": "Training uses all pre-final rows where time_to_tca_days >= 2.0; validation/test use the closest-to-TCA eligible pre-final row per event.",
            "boundary": "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days.",
            "target": "Unchanged risk from the final/latest CDM, selected by minimum time_to_tca; later file occurrence breaks ties.",
            "eligible_events": len(eligible_ids),
            "forecastable_events": len(data.event_ids),
            "events_without_eligible_input": len(set(data.event_ids) - eligible_ids),
            "eligible_event_split_preserves_original_event_assignments": True,
        },
        "split": split_report,
        "corrected_protocol_baseline_metrics": protocol_metrics,
        "legacy_or_corrected_artifact_diagnostic": shipped_diagnostic,
        "artifact_training_compatibility": {
            "training_event_level_isolation_preserved": True,
            "ineligible_training_rows_in_shipped_training_split": ineligible_training_rows,
            "eligible_training_rows_under_corrected_protocol": len(training_rows),
            "total_shipped_training_rows": total_training_rows,
            "fully_corrected_training_protocol": ineligible_training_rows == 0,
        },
        "mission_grouped_feasibility": mission_report,
        "model_fit_or_artifact_write_performed": False,
    }


def _artifact_training_protocol(
    metadata: dict,
    *,
    total_training_rows: int,
    eligible_training_rows: int,
    ineligible_training_rows: int,
) -> str | None:
    protocol = metadata.get("eligible_input_protocol")
    if protocol is None:
        return (
            "legacy_unfiltered"
            if ineligible_training_rows > 0 and metadata.get("train_forecast_example_count") == total_training_rows
            else None
        )
    if not isinstance(protocol, dict):
        return None
    minimum = protocol.get("minimum_time_to_tca_days_inclusive")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or float(minimum) != 2.0:
        return None
    if protocol.get("training_rows") != "all eligible pre-final CDMs within each training event":
        return None
    if protocol.get("validation_test_rows") != "closest-to-TCA eligible pre-final CDM per event":
        return None
    if ineligible_training_rows != 0 or metadata.get("train_forecast_example_count") != eligible_training_rows:
        return None
    return "eligible"


def _validate_artifact_protocol(
    metadata: dict | None,
    *,
    expected_artifact_sha256: str | None,
    expected_dataset_sha256: str,
    expected_split_hashes: dict[str, str],
    total_training_rows: int,
    eligible_training_rows: int,
    ineligible_training_rows: int,
) -> str | None:
    if not isinstance(metadata, dict):
        return "ARTIFACT_METADATA_UNAVAILABLE"
    if metadata.get("model_name") != MODEL_NAME or metadata.get("model_version") != MODEL_VERSION:
        return "ARTIFACT_MODEL_IDENTITY_MISMATCH"
    if metadata.get("dataset_name") != DATASET_NAME:
        return "ARTIFACT_DATASET_IDENTITY_MISMATCH"
    if (
        metadata.get("target_column") != "risk"
        or metadata.get("target_units") != "log10 risk"
        or metadata.get("high_risk_threshold_log10") != HIGH_RISK_THRESHOLD_LOG10
    ):
        return "ARTIFACT_TARGET_PROTOCOL_MISMATCH"
    artifact_hash = metadata.get("artifact_sha256")
    if not expected_artifact_sha256 or artifact_hash != expected_artifact_sha256:
        return "ARTIFACT_SHA256_MISMATCH"
    if metadata.get("dataset_sha256") != expected_dataset_sha256:
        return "ARTIFACT_DATASET_SHA256_MISMATCH"
    if metadata.get("event_split_hashes_sha256") != expected_split_hashes:
        return "ARTIFACT_EVENT_SPLIT_MISMATCH"
    if _artifact_training_protocol(
        metadata,
        total_training_rows=total_training_rows,
        eligible_training_rows=eligible_training_rows,
        ineligible_training_rows=ineligible_training_rows,
    ) is None:
        return "ARTIFACT_TRAINING_PROTOCOL_UNVERIFIED"
    return None


def eligible_legacy_diagnostic_summary(audit_report: dict | None, *, expected_artifact_sha256: str | None = None) -> str:
    """Format only verified saved-artifact diagnostics for the eligible test population."""
    unavailable = "Eligible-input artifact diagnostic: unavailable; not recomputed for this report."
    if not isinstance(audit_report, dict):
        return unavailable
    diagnostic = audit_report.get("legacy_or_corrected_artifact_diagnostic")
    eligibility = audit_report.get("input_eligibility")
    test_split = (audit_report.get("split") or {}).get("test")
    if not isinstance(diagnostic, dict) or not isinstance(eligibility, dict) or not isinstance(test_split, dict):
        return unavailable
    if diagnostic.get("evidence_source") != "verified_saved_artifact_scoring":
        return unavailable
    if diagnostic.get("status") != "legacy_unfiltered_artifact_scored_on_eligible_inputs":
        return unavailable
    if diagnostic.get("training_population") != "legacy unfiltered pre-final rows, including inputs under 2.0 days":
        return unavailable
    if diagnostic.get("evaluation_population") != "one closest-to-TCA eligible pre-final input per held-out event":
        return unavailable
    if not expected_artifact_sha256 or diagnostic.get("artifact_sha256") != expected_artifact_sha256:
        return unavailable
    if eligibility.get("boundary") != "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days.":
        return unavailable
    metrics = diagnostic.get("metrics")
    if not isinstance(metrics, dict):
        return unavailable
    high_risk = metrics.get("high_risk_test_events")
    detected = metrics.get("true_positive_high_risk_events")
    if (not isinstance(high_risk, int) or isinstance(high_risk, bool) or
            not isinstance(detected, int) or isinstance(detected, bool) or
            high_risk != test_split.get("high_risk_events") or
            high_risk != test_split.get("eligible_events") - test_split.get("low_risk_events") or
            metrics.get("test_event_count") != test_split.get("eligible_events") or
            detected < 0 or detected > high_risk):
        return unavailable
    return (
        f"Eligible-input legacy artifact diagnostic: {detected}/{high_risk} high-risk detected; not corrected-protocol metrics."
    )
    def labels(split_name: str) -> np.ndarray:
        split = eligible_splits[split_name]
        return np.asarray([data.y[split["latest_indices"][event_id]] for event_id in split["event_ids"]], dtype=float)

    split_report = {}
    for name in ("train", "validation", "test"):
        split = eligible_splits[name]
        targets = labels(name)
        split_report[name] = {
            "total_events": split["total_event_count"],
            "eligible_events": split["eligible_event_count"],
            "excluded_events_without_eligible_input": split["excluded_event_count"],
            "eligible_input_rows": split["eligible_row_count"],
            "high_risk_events": split["high_risk_event_count"],
            "low_risk_events": split["low_risk_event_count"],
            "high_risk_prevalence": float(split["high_risk_event_count"] / len(targets)) if len(targets) else None,
            "target_median_log10": float(np.median(targets)) if len(targets) else None,
            "target_mean_log10": float(np.mean(targets)) if len(targets) else None,
        }

    training_rows = eligible_splits["train"]["row_indices"]
    total_training_rows = int(np.isin(data.groups, list(original_splits["train"])).sum())
    ineligible_training_rows = total_training_rows - len(training_rows)
    primary, metadata, artifact_failure = _load_artifact(str(ARTIFACT_PATH), str(METADATA_PATH))
    protocol_metrics: dict = {"status": "unavailable", "reason": None}
    try:
        for name in ("train", "validation", "test"):
            require_scorable_population(name, eligible_splits[name])
        y_train, y_test = labels("train"), labels("test")
        test_ids = eligible_splits["test"]["event_ids"]
        X_test = data.X[[eligible_splits["test"]["latest_indices"][event_id] for event_id in test_ids]]
        baselines = {
            name: calculate_metrics(y_test, np.full(len(y_test), constant, dtype=float))
            for name, constant in (("train_mean", float(np.mean(y_train))), ("train_median", float(np.median(y_train))))
        }
        protocol_metrics = {"status": "available", "metrics": baselines}
    except ValueError as exc:
        protocol_metrics["reason"] = str(exc)

    if artifact_failure:
        shipped_diagnostic = {"status": "unavailable", "reason_code": artifact_failure}
    elif protocol_metrics["status"] != "available":
        shipped_diagnostic = {"status": "unavailable", "reason": protocol_metrics["reason"]}
    else:
        artifact_has_eligibility_protocol = bool(metadata.get("eligible_input_protocol"))
        predictions = primary["primary_model"].predict(X_test)
        shipped_diagnostic = {
            "status": "eligible_input_diagnostic_corrected_artifact" if artifact_has_eligibility_protocol else "legacy_unfiltered_artifact_scored_on_eligible_inputs",
            "training_population": "eligible two-day inputs" if artifact_has_eligibility_protocol else "legacy unfiltered pre-final rows, including inputs under 2.0 days",
            "interpretation": "Eligible-input diagnostic only; filtering evaluation inputs does not correct legacy training." if not artifact_has_eligibility_protocol else "Eligible-input metrics do not by themselves establish model validity.",
            "artifact_sha256": metadata.get("artifact_sha256"),
            "metrics": calculate_metrics(y_test, predictions),
        }

    mission_ids_by_event = read_event_missions(zip_path)
    mission_counts = {event_id: len(mission_ids_by_event.get(event_id, set())) for event_id in eligible_ids}
    exactly_one_mission = {event_id for event_id, count in mission_counts.items() if count == 1}
    mission_split = split_group_ids(
        mission_id
        for event_id in exactly_one_mission
        for mission_id in mission_ids_by_event[event_id]
    )
    mission_report = {
        "eligible_events": len(eligible_ids),
        "events_with_exactly_one_mission": len(exactly_one_mission),
        "events_with_no_mission": sum(count == 0 for count in mission_counts.values()),
        "events_with_multiple_missions": sum(count > 1 for count in mission_counts.values()),
        "unique_missions": sum(len(values) for values in mission_split.values()),
        "split_mission_counts": {name: len(ids) for name, ids in mission_split.items()},
        "split_event_counts": {},
    }
    for name, missions in mission_split.items():
        event_ids = sorted(
            event_id for event_id in exactly_one_mission
            if next(iter(mission_ids_by_event[event_id])) in missions
        )
        targets = np.asarray([data.y[latest_eligible_indices[event_id]] for event_id in event_ids], dtype=float)
        mission_report["split_event_counts"][name] = {
            "missions": len(missions),
            "events": len(event_ids),
            "high_risk_events": int(np.sum(targets >= HIGH_RISK_THRESHOLD_LOG10)),
        }

    return {
        "input_eligibility": {
            "rule": "Training uses all pre-final rows where time_to_tca_days >= 2.0; validation/test use the closest-to-TCA eligible pre-final row per event.",
            "boundary": "Inclusive at exactly 2.0 days; ESA documentation excludes CDMs within two days.",
            "target": "Unchanged risk from the final/latest CDM, selected by minimum time_to_tca; later file occurrence breaks ties.",
            "eligible_events": len(eligible_ids),
            "forecastable_events": len(data.event_ids),
            "events_without_eligible_input": len(set(data.event_ids) - eligible_ids),
            "eligible_event_split_preserves_original_event_assignments": True,
        },
        "split": split_report,
        "corrected_protocol_baseline_metrics": protocol_metrics,
        "legacy_or_corrected_artifact_diagnostic": shipped_diagnostic,
        "artifact_training_compatibility": {
            "training_event_level_isolation_preserved": True,
            "ineligible_training_rows_in_shipped_training_split": ineligible_training_rows,
            "eligible_training_rows_under_corrected_protocol": len(training_rows),
            "total_shipped_training_rows": total_training_rows,
            "fully_corrected_training_protocol": ineligible_training_rows == 0,
        },
        "mission_grouped_feasibility": mission_report,
        "model_fit_or_artifact_write_performed": False,
    }


if __name__ == "__main__":
    print(json.dumps(build_audit_report(), indent=2, sort_keys=True))
