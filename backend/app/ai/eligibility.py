"""Shared input eligibility protocol for ESA event-risk evaluation."""

from __future__ import annotations

import math
from numbers import Real
from typing import Iterable

import numpy as np

from app.ai import HIGH_RISK_THRESHOLD_LOG10


MIN_INPUT_TIME_TO_TCA_DAYS = 2.0
LIVE_TIME_TO_TCA_INVALID_REASON = "ESA_INPUT_TIME_TO_TCA_UNAVAILABLE_OR_INVALID"
LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON = "ESA_INPUT_TIME_TO_TCA_BELOW_MINIMUM"


def live_time_to_tca_ineligibility_reason(value: object) -> str | None:
    """Return a stable reason unless a live numeric day value meets ESA eligibility."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return LIVE_TIME_TO_TCA_INVALID_REASON
    days = float(value)
    if not math.isfinite(days) or days < 0.0:
        return LIVE_TIME_TO_TCA_INVALID_REASON
    if days < MIN_INPUT_TIME_TO_TCA_DAYS:
        return LIVE_TIME_TO_TCA_BELOW_MINIMUM_REASON
    return None


def prepare_eligible_splits(
    X: np.ndarray,
    y: np.ndarray,
    groups: Iterable[str],
    split_event_ids: dict[str, set[str]],
) -> dict[str, dict]:
    """Select eligible row indices and per-split counts without splitting events.

    All rows at or beyond the inclusive two-day boundary are available for
    training. Validation and test callers can use ``latest_indices`` to score
    one closest-to-TCA eligible row per event. An event with no eligible row
    is excluded; no ineligible-row fallback is made.
    """
    features = np.asarray(X, dtype=float)
    targets = np.asarray(y, dtype=float)
    event_groups = np.asarray(list(groups), dtype=object)
    if features.ndim != 2 or features.shape[1] < 1:
        raise ValueError("X must be a two-dimensional matrix with time_to_tca_days in column 0")
    if targets.ndim != 1 or event_groups.ndim != 1 or len(features) != len(targets) or len(features) != len(event_groups):
        raise ValueError("X, y, and groups must contain the same number of aligned rows")

    overlap = set()
    seen: set[str] = set()
    for event_ids in split_event_ids.values():
        current = {str(event_id) for event_id in event_ids}
        overlap.update(seen & current)
        seen.update(current)
    if overlap:
        raise ValueError(f"Event IDs overlap across splits: {sorted(overlap)[:5]}")

    rows_by_event: dict[str, list[int]] = {}
    for index, (row, event_id) in enumerate(zip(features, event_groups)):
        if np.isfinite(row[0]) and row[0] >= MIN_INPUT_TIME_TO_TCA_DAYS:
            rows_by_event.setdefault(str(event_id), []).append(index)

    prepared: dict[str, dict] = {}
    for split_name, split_ids in split_event_ids.items():
        split_ids = {str(event_id) for event_id in split_ids}
        eligible_ids = sorted(split_ids & rows_by_event.keys())
        row_indices = [index for event_id in eligible_ids for index in rows_by_event[event_id]]
        latest_indices = {
            event_id: min(rows_by_event[event_id], key=lambda index: (features[index, 0], -index))
            for event_id in eligible_ids
        }
        latest_targets = [targets[latest_indices[event_id]] for event_id in eligible_ids]
        positive_count = int(sum(value >= HIGH_RISK_THRESHOLD_LOG10 for value in latest_targets))
        prepared[split_name] = {
            "event_ids": eligible_ids,
            "row_indices": row_indices,
            "latest_indices": latest_indices,
            "total_event_count": len(split_ids),
            "eligible_event_count": len(eligible_ids),
            "excluded_event_count": len(split_ids) - len(eligible_ids),
            "eligible_row_count": len(row_indices),
            "high_risk_event_count": positive_count,
            "low_risk_event_count": len(eligible_ids) - positive_count,
        }
    return prepared


def require_scorable_population(split_name: str, split: dict) -> None:
    """Reject populations too small or single-class for the published metrics."""
    if split["eligible_event_count"] < 2:
        raise ValueError(
            f"{split_name} split has only {split['eligible_event_count']} eligible events; "
            "at least 2 are required to compute evaluation metrics"
        )
    if split["high_risk_event_count"] == 0 or split["low_risk_event_count"] == 0:
        raise ValueError(
            f"{split_name} split must contain at least one high-risk and one low-risk "
            "eligible event to compute the reported classification metrics"
        )
