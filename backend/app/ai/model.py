"""Small, deterministic scikit-learn model definitions for Stage 3."""

from __future__ import annotations


def build_baseline_model(random_seed: int = 42):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=1.0, solver="lsqr")),
    ])


def build_primary_model(random_seed: int = 42):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("histgradientboostingregressor", HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.1,
            max_iter=200,
            max_leaf_nodes=31,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=random_seed,
        )),
    ])
