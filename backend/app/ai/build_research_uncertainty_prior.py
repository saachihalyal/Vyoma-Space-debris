"""Rebuild the versioned, empirical summary priors from ESA's bundled archive.

Run from backend with ``python -m app.ai.build_research_uncertainty_prior``.
The output summarizes ESA CDM covariance sigmas and algorithm size inputs; it
is a population prior and is not a calibration of CelesTrak TLE errors.
"""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np


BACKEND = Path(__file__).resolve().parents[2]
ARCHIVE = BACKEND / "ml_data" / "train_data.zip"
OUTPUT = Path(__file__).resolve().parent / "artifacts" / "esa_research_uncertainty_prior_v1.json"
TARGET_FIELDS = {
    "sigma_r_m": "t_sigma_r",
    "sigma_t_m": "t_sigma_t",
    "sigma_n_m": "t_sigma_n",
    "sigma_rdot_m_s": "t_sigma_rdot",
    "sigma_tdot_m_s": "t_sigma_tdot",
    "sigma_ndot_m_s": "t_sigma_ndot",
    "span_diameter_m": "t_span",
}
CHASER_FIELDS = {name: column.replace("t_", "c_", 1) for name, column in TARGET_FIELDS.items()}


def _summarize(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "sample_count": int(array.size),
        "p10": float(np.quantile(array, 0.10)),
        "p50": float(np.quantile(array, 0.50)),
        "p90": float(np.quantile(array, 0.90)),
    }


def build() -> dict:
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    groups = {"esa_target": {key: [] for key in TARGET_FIELDS}, "esa_chaser": {key: [] for key in CHASER_FIELDS}}
    with zipfile.ZipFile(ARCHIVE) as archive:
        csv_name = next(name for name in archive.namelist() if name.endswith(".csv"))
        with archive.open(csv_name) as byte_stream:
            rows = csv.DictReader((line.decode("utf-8") for line in byte_stream))
            for row in rows:
                for role, fields in (("esa_target", TARGET_FIELDS), ("esa_chaser", CHASER_FIELDS)):
                    for output_name, column in fields.items():
                        try:
                            value = float(row[column])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if np.isfinite(value) and value > 0:
                            groups[role][output_name].append(value)

    unit_map = {
        "sigma_r_m": "m", "sigma_t_m": "m", "sigma_n_m": "m",
        "sigma_rdot_m_s": "m/s", "sigma_tdot_m_s": "m/s", "sigma_ndot_m_s": "m/s",
        "span_diameter_m": "m",
    }
    result = {
        "model_name": "ORION ESA CDM population uncertainty and size prior",
        "model_version": "1.0.0",
        "source_archive": "backend/ml_data/train_data.zip",
        "source_archive_sha256": digest,
        "source_csv_member": csv_name,
        "summary_method": "component-wise p10/p50/p90 from all positive finite rows; no covariance correlations are carried into this prior",
        "roles": {
            role: {
                "fields": {
                    name: {**_summarize(values), "units": unit_map[name]}
                    for name, values in fields.items()
                }
            }
            for role, fields in groups.items()
        },
        "limitations": [
            "ESA values are CDM-derived population priors and are not measured uncertainty for any live ORION TLE object.",
            "Component correlations are omitted; the covariance prior is diagonal in the object's local RTN position/velocity ordering.",
            "The challenge target/chaser population differs from the live TLE catalog; no calibration or coverage validation against live TLE truth is claimed.",
            "ESA span is a collision-risk algorithm size input, not an authenticated physical dimension for a live object.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
