"""Metrics for event-held-out regression and high-risk triage."""

from __future__ import annotations

import math

import numpy as np

from app.ai import HIGH_RISK_THRESHOLD_LOG10


def calculate_metrics(y_true, y_pred) -> dict[str, float | None]:
    from scipy.stats import spearmanr
    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        mean_absolute_error,
        mean_squared_error,
        precision_score,
        r2_score,
        recall_score,
    )

    truth = np.asarray(y_true, dtype=float)
    prediction = np.asarray(y_pred, dtype=float)
    if truth.ndim != 1 or prediction.shape != truth.shape or not len(truth):
        raise ValueError("Metric inputs must be non-empty, aligned one-dimensional arrays")
    if not np.isfinite(truth).all() or not np.isfinite(prediction).all():
        raise ValueError("Metric inputs must be finite")
    true_high_risk = truth >= HIGH_RISK_THRESHOLD_LOG10
    predicted_high_risk = prediction >= HIGH_RISK_THRESHOLD_LOG10
    positive_count = int(true_high_risk.sum())
    true_positive_count = int(np.logical_and(true_high_risk, predicted_high_risk).sum())
    false_positive_count = int(np.logical_and(~true_high_risk, predicted_high_risk).sum())
    false_negative_count = int(np.logical_and(true_high_risk, ~predicted_high_risk).sum())
    correlation = (
        spearmanr(truth, prediction).statistic
        if len(truth) >= 2 and np.ptp(truth) > 0.0 and np.ptp(prediction) > 0.0
        else float("nan")
    )
    pr_auc = average_precision_score(true_high_risk, prediction) if positive_count else float("nan")
    return {
        "mae_log10": float(mean_absolute_error(truth, prediction)),
        "rmse_log10": float(math.sqrt(mean_squared_error(truth, prediction))),
        "r2": float(r2_score(truth, prediction)) if len(truth) >= 2 else None,
        "spearman_correlation": float(correlation) if math.isfinite(float(correlation)) else None,
        "high_risk_precision": float(precision_score(true_high_risk, predicted_high_risk, zero_division=0)),
        "high_risk_recall": float(recall_score(true_high_risk, predicted_high_risk, zero_division=0)),
        "high_risk_f1": float(f1_score(true_high_risk, predicted_high_risk, zero_division=0)),
        "high_risk_pr_auc_average_precision": float(pr_auc) if math.isfinite(float(pr_auc)) else None,
        "high_risk_threshold_log10": HIGH_RISK_THRESHOLD_LOG10,
        "high_risk_test_events": positive_count,
        "predicted_high_risk_events": int(predicted_high_risk.sum()),
        "true_positive_high_risk_events": true_positive_count,
        "false_positive_high_risk_events": false_positive_count,
        "false_negative_high_risk_events": false_negative_count,
        "test_event_count": int(len(truth)),
    }
