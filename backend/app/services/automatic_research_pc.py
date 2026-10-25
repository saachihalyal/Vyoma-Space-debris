"""Automatic, explicitly prior-based research Pc for valid SGP4 encounters.

This estimate is deliberately separate from the event-specific CDM/Foster result.
The ESA challenge archive supplies population distributions, not live TLE
covariance truth. The conversion to RTN, diagonal covariance and size priors
are declared assumptions and travel with every result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.models import AutomaticResearchPcAssessment, CollisionProbabilityResult, ObjectSummary, PhysicsResult, ReviewPriority
from app.services.collision_probability import CovarianceInput, HardBodyRadiusInput, calculate_foster_2d
from app.services.probability_classification import classify_orion_physics_pc


METHOD_NAME = "ORION TLE-age baseline Foster 2D research estimate"
METHOD_VERSION = "2.0.0"
LOG10_PC_FLOOR = float(os.getenv("ORION_LOG10_PC_FLOOR", "-30"))
DEFAULT_COVARIANCE_POLICY = "tle_age_baseline"
COVARIANCE_POLICIES = {
    "esa_population_prior": "ESA Kelvins population-prior covariance (TLE-derived state; unvalidated mapping)",
    "tle_age_baseline": "TLE-age position-sigma baseline (0.1/0.5/0.2 km plus 0.1/1.5/0.2 km/day)",
    "tle_age_baseline_2x": "2x TLE-age position-sigma baseline",
}
PRIOR_PATH = Path(__file__).resolve().parents[1] / "ai" / "artifacts" / "esa_research_uncertainty_prior_v1.json"
DEFAULT_CONFIG: dict[str, Any] = {
    "age_inflation_per_day": 0.05,
    "age_inflation_cap": 10.0,
    "band_sigma_multiplier": {"LEO": 1.0, "MEO": 1.25, "GEO": 1.5, "HEO": 1.5},
    "eccentricity_sigma_multiplier": 1.0,
    "bstar_sigma_multiplier": 0.25,
    "bstar_reference_abs": 0.0001,
}
SIGMA_KEYS = ("sigma_r_m", "sigma_t_m", "sigma_n_m", "sigma_rdot_m_s", "sigma_tdot_m_s", "sigma_ndot_m_s")
# Assumed equivalent spherical hard-body radii, in km. These are conservative
# project priors for recognizable large objects, not authenticated dimensions.
OBJECT_SIZE_HBR_OVERRIDE_TABLE = {
    "ISS": {"radius_km": 0.050, "match": "exact International Space Station name"},
    "ISS (ZARYA)": {"radius_km": 0.015, "match": "named ISS module"},
    "ISS (ZVEZDA)": {"radius_km": 0.015, "match": "named ISS module"},
    "ISS (NAUKA)": {"radius_km": 0.015, "match": "named ISS module"},
    "ISS (POISK)": {"radius_km": 0.010, "match": "named ISS module"},
    "ISS (RASSVET)": {"radius_km": 0.010, "match": "named ISS module"},
    "ISS (UNITY)": {"radius_km": 0.012, "match": "named ISS module"},
    "ISS (DESTINY)": {"radius_km": 0.012, "match": "named ISS module"},
    "ISS (HARMONY)": {"radius_km": 0.012, "match": "named ISS module"},
    "ISS (COLUMBUS)": {"radius_km": 0.012, "match": "named ISS module"},
    "ISS (KIBO)": {"radius_km": 0.012, "match": "named ISS module"},
    "ISS (TRANQUILITY)": {"radius_km": 0.012, "match": "named ISS module"},
    "HUBBLE SPACE TELESCOPE": {"radius_km": 0.007, "match": "known large observatory"},
    "ENVISAT": {"radius_km": 0.013, "match": "known large Earth-observation spacecraft"},
    "TERRA": {"radius_km": 0.012, "match": "known large Earth-observation spacecraft"},
    "AQUA": {"radius_km": 0.012, "match": "known large Earth-observation spacecraft"},
}
logger = logging.getLogger(__name__)


class MissingPriorData(ValueError):
    pass


def assess_automatic_research_pc(
    physics: PhysicsResult,
    collision_probability: CollisionProbabilityResult | None,
    review_priority: ReviewPriority,
    primary: ObjectSummary | None = None,
    secondary: ObjectSummary | None = None,
    *,
    covariance_scale: float = 1.0,
    hbr_scale: float = 1.0,
    covariance_policy: str | None = None,
    fixed_covariance_inputs: tuple[CovarianceInput, CovarianceInput] | None = None,
    fixed_hbr_km: float | None = None,
) -> AutomaticResearchPcAssessment:
    selected_policy = covariance_policy or os.getenv("ORION_RESEARCH_PC_COVARIANCE_POLICY", DEFAULT_COVARIANCE_POLICY)
    if selected_policy not in COVARIANCE_POLICIES:
        selected_policy = "invalid"
    geometry_band = {"CRITICAL": "1", "HIGH": "2", "MEDIUM": "3", "LOW": "4"}.get(review_priority.category, "unclassified")
    shared = {
        "method_name": ("ORION ESA population-prior Foster 2D research estimate"
                        if selected_policy == "esa_population_prior" else METHOD_NAME),
        "method_version": METHOD_VERSION,
        "covariance_policy_id": selected_policy,
        "covariance_policy_name": COVARIANCE_POLICIES.get(selected_policy, "Unsupported covariance policy"),
        "geometry_review_category": review_priority.category,
        "geometry_review_policy_version": review_priority.policy_version,
        "ranking_basis": f"Geometry review band {geometry_band} under {review_priority.policy_version}; geometry-only queue rank, separate from Pc",
    }
    if physics.status != "valid" or physics.tca_status != "valid":
        return AutomaticResearchPcAssessment(
            status="not_applicable", quality_status="not_assessed", reason_codes=["VALID_INTERIOR_TCA_REQUIRED"],
            reason_message="This event has no valid interior TCA; the ESA-prior estimate is only evaluated for valid in-window encounters.",
            sensitivity_status="not_applicable", sensitivity_reason="Only valid interior-TCA events are assessed.", **shared,
        )

    event_pc_matches = (
        collision_probability is not None and collision_probability.status == "available"
        and collision_probability.event_id == physics.event_id
        and isinstance(collision_probability.pc, (int, float)) and not isinstance(collision_probability.pc, bool)
        and math.isfinite(collision_probability.pc) and 0.0 < collision_probability.pc <= 1.0
    )
    if event_pc_matches:
        return AutomaticResearchPcAssessment(
            status="event_specific_foster_available", quality_status="validated_event_inputs",
            reason_message="A validated event-specific Foster Pc is available; an ESA-prior substitute was intentionally not generated.",
            covariance_method="Validated event-matched covariance; see collision_probability provenance.",
            hbr_method="Validated event-matched HBR; see collision_probability provenance.",
            sensitivity_status="not_applicable",
            sensitivity_reason="The separate event-specific Foster result is authoritative; no prior estimate replaces it.",
            assumptions=["See event-matched covariance, HBR, frame, epoch and independence provenance on collision_probability."],
            **shared,
        )

    if primary is None or secondary is None:
        return _unavailable(shared, "OBJECT_PROVENANCE_UNAVAILABLE")
    if (isinstance(covariance_scale, bool) or not isinstance(covariance_scale, (int, float))
            or not math.isfinite(covariance_scale) or covariance_scale <= 0
            or isinstance(hbr_scale, bool) or not isinstance(hbr_scale, (int, float))
            or not math.isfinite(hbr_scale) or hbr_scale <= 0):
        return _unavailable(shared, "INVALID_RESEARCH_SCENARIO_SCALE")
    if selected_policy == "invalid":
        return _unavailable(shared, "UNSUPPORTED_COVARIANCE_POLICY")
    try:
        prior = json.loads(PRIOR_PATH.read_text(encoding="utf-8"))
        config = _config()
        tca = _parse_utc(physics.tca.value if physics.tca else None)
        state1 = physics.primary_state_at_tca
        state2 = physics.secondary_state_at_tca
        if tca is None or state1 is None or state2 is None:
            return _unavailable(shared, "TCA_STATE_UNAVAILABLE")
        states = (_state(state1, primary.id, tca), _state(state2, secondary.id, tca))
        roles = (_prior_role(primary), _prior_role(secondary))
        object_specs = [
            _object_prior(prior, config, obj, role, tca)
            for obj, role in zip((primary, secondary), roles)
        ]
        if any(spec is None for spec in object_specs):
            return _unavailable(shared, "PRIOR_INPUTS_UNAVAILABLE")
        specs = [spec for spec in object_specs if spec is not None]
        size_overrides = [_object_size_hbr_override(obj) for obj in (primary, secondary)]
        hbr_source = "assumed_object_size_override" if any(item is not None for item in size_overrides) else "esa_population_span_prior"
        hbr_provenance = {
            "source": hbr_source,
            "units": "km",
            "combined_radius_rule": "sum of per-object assumed equivalent-sphere radii",
            "objects": {
                obj.id: ({"name": obj.name, **override} if override is not None else {
                    "name": obj.name, "source": "ESA Kelvins span prior", "assumption": "span diameter divided by two"
                }) for obj, override in zip((primary, secondary), size_overrides)
            },
            "assumption": "Object sizes are assumptions for research Pc and are not authenticated dimensions or measured HBR.",
        }
        event_id = physics.event_id
        values: list[tuple[float | None, float, float]] = []
        central_plane_terms = None
        central_covariance_matrix_sha256: list[str] = []
        if fixed_covariance_inputs is not None and (
            len(fixed_covariance_inputs) != 2 or fixed_hbr_km is None
            or not math.isfinite(float(fixed_hbr_km)) or float(fixed_hbr_km) <= 0
            or [item.object_id for item in fixed_covariance_inputs] != [primary.id, secondary.id]
        ):
            return _unavailable(shared, "FIXED_COMPARISON_UNCERTAINTY_INVALID")
        for quantile in ("p10", "p50", "p90"):
            if fixed_covariance_inputs is not None:
                covariances = [_retarget_covariance(item, tca) for item in fixed_covariance_inputs]
            elif selected_policy == "esa_population_prior":
                covariances = [
                    _covariance(obj.id, tca, state, spec[0], quantile, spec[2] * covariance_scale, spec[4])
                    for obj, state, spec in zip((primary, secondary), states, specs)
                ]
            else:
                baseline_multiplier = 2.0 if selected_policy == "tle_age_baseline_2x" else 1.0
                covariances = [
                    _tle_age_position_covariance(obj.id, obj, tca, state, baseline_multiplier * covariance_scale, selected_policy)
                    for obj, state in zip((primary, secondary), states)
                ]
            object_radii_km = [
                override["radius_km"] if override is not None else spec[3][quantile] / 1000.0
                for override, spec in zip(size_overrides, specs)
            ]
            hbr_km = float(fixed_hbr_km) if fixed_covariance_inputs is not None else sum(object_radii_km) * hbr_scale
            result = _calculate(physics, primary.id, secondary.id, tca, states, covariances, hbr_km, hbr_source, hbr_provenance)
            if quantile == "p50":
                central_plane_terms = _encounter_plane_terms(physics, covariances, states)
                central_covariance_matrix_sha256 = [
                    hashlib.sha256(np.asarray(item.matrix, dtype=np.float64).tobytes()).hexdigest()
                    for item in covariances
                ]
            if result.status == "available" and result.pc is not None and result.pc > 0:
                log_pc = math.log(float(result.pc))
            elif result.status == "available" and result.pc == 0 or result.reason_codes == ["NUMERICAL_FAILURE"]:
                log_pc = _log_foster_pc(physics, covariances, states, hbr_km)
                if not math.isfinite(log_pc) or log_pc > 1e-12:
                    return _unavailable(shared, "FOSTER_PRIOR_CALCULATION_NUMERICAL_FAILURE", prior, config)
            else:
                return _unavailable(shared, "FOSTER_PRIOR_CALCULATION_" + (result.reason_codes[0] if result.reason_codes else "FAILED"), prior, config)
            min_log = math.log(float.fromhex("0x0.0000000000001p-1022"))
            numeric_pc = math.exp(log_pc) if log_pc >= min_log else None
            values.append((numeric_pc, hbr_km, log_pc))

        central_pc, central_hbr, central_log_pc = values[1]
        negligible = central_log_pc / math.log(10.0) < LOG10_PC_FLOOR
        floor_pc = f"< 1e{LOG10_PC_FLOOR:g}"
        floor_percent = f"< 1e{LOG10_PC_FLOOR + 2:g}"
        # Recompute a compact 3x3 sensitivity grid. Covariance and HBR are
        # both changed through the same physics calculator; taking logs
        # before deriving the bounds avoids Pc underflow in the tails.
        sensitivity_logs: list[float] = []
        covariance_sensitivity_scales = (0.5, 1.0, 3.0)
        hbr_sensitivity_scales = (0.75, 1.0, 1.5)
        for sensitivity_covariance_scale in covariance_sensitivity_scales:
            if fixed_covariance_inputs is not None:
                sensitivity_covariances = [
                    _scale_covariance_input(_retarget_covariance(item, tca), sensitivity_covariance_scale)
                    for item in fixed_covariance_inputs
                ]
            elif selected_policy == "esa_population_prior":
                sensitivity_covariances = [
                    _covariance(obj.id, tca, state, spec[0], "p50", spec[2] * sensitivity_covariance_scale, spec[4])
                    for obj, state, spec in zip((primary, secondary), states, specs)
                ]
            else:
                baseline_multiplier = 2.0 if selected_policy == "tle_age_baseline_2x" else 1.0
                sensitivity_covariances = [
                    _tle_age_position_covariance(obj.id, obj, tca, state,
                                                 baseline_multiplier * sensitivity_covariance_scale, selected_policy)
                    for obj, state in zip((primary, secondary), states)
                ]
            for sensitivity_hbr_scale in hbr_sensitivity_scales:
                scenario_hbr_km = central_hbr * sensitivity_hbr_scale
                scenario_result = _calculate(
                    physics, primary.id, secondary.id, tca, states,
                    sensitivity_covariances, scenario_hbr_km, hbr_source, hbr_provenance,
                )
                if scenario_result.status == "available" and scenario_result.pc is not None and scenario_result.pc > 0:
                    sensitivity_logs.append(math.log(float(scenario_result.pc)))
                elif scenario_result.status == "available" and scenario_result.pc == 0 or scenario_result.reason_codes == ["NUMERICAL_FAILURE"]:
                    sensitivity_logs.append(_log_foster_pc(physics, sensitivity_covariances, states, scenario_hbr_km))
                else:
                    return _unavailable(shared, "FOSTER_SENSITIVITY_CALCULATION_" + (scenario_result.reason_codes[0] if scenario_result.reason_codes else "FAILED"), prior, config)
        hbr_quantiles = {quantile: value[1] for quantile, value in zip(("p10", "p50", "p90"), values)}
        sensitivity_reason = (
            "Bounds are recomputed across covariance multipliers 0.5x, 1x, and 3x and HBR multipliers 0.75x, 1x, and 1.5x. "
            "They are the minimum and maximum of configured what-if combinations, not a statistical confidence interval."
        )
        source_hash = hashlib.sha256(PRIOR_PATH.read_bytes()).hexdigest()
        age_days = [spec[4] for spec in specs]
        assumptions = [
            "This is a prior-based research estimate, not an event-specific or operationally validated Pc.",
            ("ESA Kelvins CDM-derived population p10/p50/p90 component sigmas are used as per-object priors; they are not live-object measurements."
             if selected_policy == "esa_population_prior" else
             "The selected TLE-age covariance is a configured uncertainty model, not measured object-specific covariance."),
            "ESA r/t/n sigma labels are mapped to local RTN at TCA, then rotated to TEME using each propagated SGP4 state; this frame interpretation is an explicit model assumption.",
            "Covariance is diagonal in RTN; ESA correlations and cross-object covariance are unavailable and omitted.",
            "The covariance is assigned at TCA; no covariance propagation from TLE epoch is performed.",
            "ESA target/chaser roles are mapped from ORION object class: active/payload to target; debris/rocket body/unknown to chaser.",
            "ESA span inputs are treated as diameters and converted to radius; this is an assumed size mapping, not authenticated object dimensions.",
            "Object covariances are assumed independent for the Foster relative covariance.",
            "Sensitivity bounds are recalculated over covariance scales 0.5x, 1x, and 3x and HBR scales 0.75x, 1x, and 1.5x in the log-Pc domain; they are not confidence bounds.",
            f"Scenario covariance multiplier: {covariance_scale:g}; scenario HBR multiplier: {hbr_scale:g}. Both are explicit research-scenario controls, not measured inputs.",
            "When a result is below binary64's representable range, the same Foster disk integral is evaluated in log space and reported in scientific notation rather than substituted with zero.",
        ]
        if fixed_covariance_inputs is not None:
            assumptions.extend([
                "Maneuver comparison reuses the baseline event's TEME covariance matrices numerically unchanged at candidate TCA; only the mean relative state changes.",
                "Maneuver comparison holds the baseline event's combined HBR fixed; sensitivity scales are what-if variations around that shared baseline.",
            ])
        return AutomaticResearchPcAssessment(
            status="prior_based_research_estimate", quality_status="prior_based_unvalidated",
            estimated_pc=central_pc, estimated_pc_scientific=(floor_pc if negligible else _scientific(central_log_pc)),
            log10_pc=central_log_pc / math.log(10.0), negligible=negligible,
            percentage=(central_pc * 100.0 if central_pc is not None else None),
            percentage_scientific=(floor_percent if negligible else _scientific(central_log_pc + math.log(100.0))),
            risk_assessment=classify_orion_physics_pc(
                central_pc, "research_pc", log10_pc=central_log_pc / math.log(10.0),
            ),
            lower_sensitivity_pc=(math.exp(min(sensitivity_logs)) if min(sensitivity_logs) >= min_log else None),
            upper_sensitivity_pc=(math.exp(max(sensitivity_logs)) if max(sensitivity_logs) >= min_log else None),
            lower_sensitivity_pc_scientific=(floor_pc if min(sensitivity_logs) / math.log(10.0) < LOG10_PC_FLOOR else _scientific(min(sensitivity_logs))),
            upper_sensitivity_pc_scientific=(floor_pc if max(sensitivity_logs) / math.log(10.0) < LOG10_PC_FLOOR else _scientific(max(sensitivity_logs))),
            hbr_km=central_hbr, hbr_sensitivity_km=[central_hbr * 0.75, central_hbr * 1.5],
            encounter_plane_sigma_min_km=(central_plane_terms or {}).get("sigma_min_km"),
            encounter_plane_sigma_max_km=(central_plane_terms or {}).get("sigma_max_km"),
            miss_sigma_ratio=(central_plane_terms or {}).get("miss_sigma_ratio"),
            covariance_method=("Fixed baseline-event TEME covariance reused numerically at candidate TCA for a maneuver comparison."
                               if fixed_covariance_inputs is not None else
                               "ESA Kelvins component-wise population covariance prior; diagonal local RTN assigned at TCA and rotated to TEME; configured age, orbit-band, eccentricity and BSTAR scale factors."
                               if selected_policy == "esa_population_prior" else
                               f"{COVARIANCE_POLICIES[selected_policy]} assigned in RTN at TCA and rotated to TEME; no covariance propagation is performed."),
            hbr_method=("Documented assumed object-size HBR override where matched; remaining object uses ESA span prior. No dimension is authenticated."
                        if any(item is not None for item in size_overrides) else
                        "ESA target/chaser span population prior by ORION object class; assumed span diameter converted to a per-object radius and combined; not an authenticated object dimension."),
            hbr_source=hbr_source, hbr_provenance={**hbr_provenance, "combined_hbr_km": central_hbr, "combined_hbr_by_esa_span_quantile_km": hbr_quantiles},
            covariance_frame="TEME", covariance_epoch_utc=tca.isoformat(),
            sensitivity_status="available",
            sensitivity_reason=sensitivity_reason,
            reason_codes=[], assumptions=assumptions,
            provenance={
                "source": prior.get("source_archive"), "source_archive_sha256": prior.get("source_archive_sha256"),
                "prior_artifact": str(PRIOR_PATH.name), "prior_artifact_sha256": source_hash,
                "prior_model_version": prior.get("model_version"), "role_by_object": {primary.id: roles[0], secondary.id: roles[1]},
                "tca_utc": tca.isoformat(), "covariance_frame": "TEME", "covariance_assignment_epoch": "TCA",
                "covariance_independence_assumed": True, "configuration": config,
                "scenario_covariance_scale": float(covariance_scale), "scenario_hbr_scale": float(hbr_scale),
                "fixed_comparison_uncertainty": fixed_covariance_inputs is not None,
                "fixed_baseline_hbr_km": float(fixed_hbr_km) if fixed_covariance_inputs is not None else None,
                "fixed_covariance_matrix_sha256": [
                    hashlib.sha256(np.asarray(item.matrix, dtype=np.float64).tobytes()).hexdigest()
                    for item in fixed_covariance_inputs
                ] if fixed_covariance_inputs is not None else [],
                "central_covariance_matrix_sha256": central_covariance_matrix_sha256,
                "sensitivity_covariance_scales": list(covariance_sensitivity_scales),
                "sensitivity_hbr_scales": list(hbr_sensitivity_scales),
                "object_metadata": {obj.id: {"band": obj.band, "category": obj.category, "tle_age_days": age}
                                    for obj, age in zip((primary, secondary), age_days)},
                "scenario_quantiles": ["p10", "p50", "p90"],
                "covariance_policy_id": selected_policy,
                "covariance_policy_name": COVARIANCE_POLICIES[selected_policy],
                "covariance_policy_options": COVARIANCE_POLICIES,
                "tle_age_sigma_model_km": {"radial": [0.1, 0.1], "in_track": [0.5, 1.5], "cross_track": [0.2, 0.2], "age_epoch": "TCA"},
                "quadrature_relative_tolerance": 1e-6,
                "log_domain_fallback": "same Foster circular Gaussian integral, used only when probability-domain Foster quadrature fails",
            }, **shared,
        )
    except MissingPriorData as exc:
        return _unavailable(shared, str(exc), prior if "prior" in locals() else None, config if "config" in locals() else None)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, np.linalg.LinAlgError) as exc:
        logger.exception("Prior-based research Pc failed for event %s", physics.event_id)
        return _unavailable(shared, f"PRIOR_ASSESSMENT_ERROR_{type(exc).__name__}")


def _calculate(physics, id1, id2, tca, states, covariances, hbr_km, hbr_source="esa_population_span_prior", hbr_provenance=None):
    return calculate_foster_2d(
        event_id=physics.event_id, object_1_id=id1, object_2_id=id2, tca_utc=tca.isoformat(),
        position_1_km=states[0][0], velocity_1_km_s=states[0][1],
        position_2_km=states[1][0], velocity_2_km_s=states[1][1], state_frame="TEME",
        tca_status="valid", covariance_1=covariances[0], covariance_2=covariances[1],
        hbr=HardBodyRadiusInput(
            value_km=hbr_km, source="configured", source_type="derived",
            description="Combined assumed object-size / ESA span HBR prior; not an authenticated object dimension",
        ), assume_independent_covariances=True, relative_tolerance=1e-6, max_quadrature_order=2048,
    )


def _tle_age_position_covariance(object_id, obj, tca, state, scale=1.0, policy_id="tle_age_baseline"):
    age = _tle_age_days(obj, tca)
    sigmas_km = np.asarray([
        0.1 + 0.1 * age,
        0.5 + 1.5 * age,
        0.2 + 0.2 * age,
    ], dtype=float) * float(scale)
    if not np.isfinite(sigmas_km).all() or np.any(sigmas_km <= 0):
        raise ValueError("TLE-age sigma invalid")
    r = np.asarray(state[0], dtype=float)
    v = np.asarray(state[1], dtype=float)
    rnorm = float(np.linalg.norm(r))
    h = np.cross(r, v)
    hnorm = float(np.linalg.norm(h))
    if not math.isfinite(rnorm) or rnorm <= 1e-12 or not math.isfinite(hnorm) or hnorm <= 1e-12:
        raise ValueError("invalid propagated state for RTN covariance frame")
    rhat = r / rnorm
    nhat = h / hnorm
    that = np.cross(nhat, rhat)
    rotation = np.column_stack((rhat, that, nhat))
    matrix = rotation @ np.diag(sigmas_km**2) @ rotation.T
    return CovarianceInput(
        object_id=object_id, frame="TEME", epoch=tca.isoformat(), matrix=matrix,
        units={"position": "km^2"}, source=COVARIANCE_POLICIES[policy_id],
        source_type="derived", is_synthetic=False,
    )


def maneuver_baseline_covariances(physics: PhysicsResult, primary: ObjectSummary, secondary: ObjectSummary, scale: float = 1.0, policy_id: str = DEFAULT_COVARIANCE_POLICY):
    """Build the maneuver comparison covariance once at the selected event TCA."""
    tca = _parse_utc(physics.tca.value if physics.tca else None)
    if tca is None or physics.primary_state_at_tca is None or physics.secondary_state_at_tca is None:
        raise ValueError("MANEUVER_BASELINE_COVARIANCE_INPUT_UNAVAILABLE")
    states = (_state(physics.primary_state_at_tca, primary.id, tca), _state(physics.secondary_state_at_tca, secondary.id, tca))
    if policy_id not in COVARIANCE_POLICIES:
        raise ValueError("MANEUVER_FIXED_COVARIANCE_POLICY_UNSUPPORTED")
    if policy_id == "esa_population_prior":
        prior = json.loads(PRIOR_PATH.read_text(encoding="utf-8"))
        config = _config()
        objects = (primary, secondary)
        specs = [_object_prior(prior, config, obj, _prior_role(obj), tca) for obj in objects]
        if any(spec is None for spec in specs):
            raise ValueError("MANEUVER_FIXED_COVARIANCE_PRIOR_UNAVAILABLE")
        covariances = tuple(
            _covariance(obj.id, tca, state, spec[0], "p50", spec[2] * float(scale), spec[4])
            for obj, state, spec in zip(objects, states, specs)
        )
    else:
        policy_scale = float(scale) * (2.0 if policy_id == "tle_age_baseline_2x" else 1.0)
        covariances = tuple(
            _tle_age_position_covariance(obj.id, obj, tca, state, policy_scale, policy_id)
            for obj, state in zip((primary, secondary), states)
        )
    return covariances


def _retarget_covariance(covariance: CovarianceInput, tca: datetime) -> CovarianceInput:
    return CovarianceInput(
        object_id=covariance.object_id, frame=covariance.frame, epoch=tca.isoformat(),
        matrix=np.asarray(covariance.matrix, dtype=float).copy(), units=covariance.units,
        source="Frozen selected-event baseline TEME covariance for maneuver comparison",
        source_type="derived", source_timestamp=covariance.source_timestamp,
        input_hash=covariance.input_hash, is_synthetic=covariance.is_synthetic,
        validity_status=covariance.validity_status,
    )


def _scale_covariance_input(covariance: CovarianceInput, scale: float) -> CovarianceInput:
    return CovarianceInput(
        object_id=covariance.object_id, frame=covariance.frame, epoch=covariance.epoch,
        matrix=np.asarray(covariance.matrix, dtype=float) * float(scale) ** 2,
        units=covariance.units, source=covariance.source, source_type=covariance.source_type,
        source_timestamp=covariance.source_timestamp, input_hash=covariance.input_hash,
        is_synthetic=covariance.is_synthetic, validity_status=covariance.validity_status,
    )


def _encounter_plane_terms(physics, covariances, states):
    r1, v1 = states[0]
    r2, v2 = states[1]
    relative_position = r2 - r1
    relative_velocity = v2 - v1
    speed = float(np.linalg.norm(relative_velocity))
    if speed <= 1e-8:
        return None
    ev = relative_velocity / speed
    transverse = relative_position - float(np.dot(relative_position, ev)) * ev
    if np.linalg.norm(transverse) > 1e-9:
        e1 = transverse / np.linalg.norm(transverse)
    else:
        axis = np.eye(3)[int(np.argmin(np.abs(ev)))]
        e1 = axis - float(np.dot(axis, ev)) * ev
        e1 /= np.linalg.norm(e1)
    e2 = np.cross(ev, e1)
    e2_norm = float(np.linalg.norm(e2))
    if not math.isfinite(e2_norm) or e2_norm <= 1e-12:
        return None
    e2 /= e2_norm
    plane = np.vstack((e1, e2))
    covariance = np.asarray(covariances[0].matrix)[:3, :3] + np.asarray(covariances[1].matrix)[:3, :3]
    encounter_cov = plane @ covariance @ plane.T
    eigenvalues, eigenvectors = np.linalg.eigh((encounter_cov + encounter_cov.T) * 0.5)
    if not np.isfinite(eigenvalues).all() or np.min(eigenvalues) <= 0:
        return None
    miss = eigenvectors.T @ (plane @ relative_position)
    sigma_x, sigma_y = math.sqrt(float(eigenvalues[0])), math.sqrt(float(eigenvalues[1]))
    maha_squared = float(np.sum((miss**2) / eigenvalues))
    if not math.isfinite(maha_squared):
        return None
    return {
        "sigma_min_km": sigma_x, "sigma_max_km": sigma_y,
        "miss_km": float(np.linalg.norm(miss)),
        "miss_sigma_ratio": math.sqrt(max(0.0, maha_squared)),
        "maha_squared": maha_squared,
        "mean": miss,
    }


def _log_foster_pc(physics, covariances, states, hbr_km):
    """Log-domain Foster evaluation, with a checked small-disc asymptote."""
    terms = _encounter_plane_terms(physics, covariances, states)
    if terms is None or hbr_km <= 0:
        return float("nan")
    sigma_x, sigma_y = terms["sigma_min_km"], terms["sigma_max_km"]
    maha = terms["miss_sigma_ratio"]
    scaled_radius = hbr_km / min(sigma_x, sigma_y)
    # When the disk is small relative to the Gaussian scale even at the
    # displaced density, its density is effectively constant over the disk.
    if maha >= 8.0 and scaled_radius * (1.0 + maha) <= 0.02:
        return _small_hbr_log_pc(terms, hbr_km)
    return _integrate_log_disk(terms["mean"], sigma_x, sigma_y, hbr_km)


def _small_hbr_log_pc(terms, hbr_km):
    """Small-disc Gaussian-density limit in natural-log probability space."""
    return (2.0 * math.log(hbr_km) - math.log(2.0)
            - math.log(terms["sigma_min_km"]) - math.log(terms["sigma_max_km"])
            - 0.5 * terms["maha_squared"])


def _integrate_log_disk(mean, sigma_x, sigma_y, radius, tolerance=1e-6, max_order=4096):
    previous = None
    order = 32
    log_norm = 0.5 * math.log(2.0 * math.pi)
    while order <= max_order:
        nodes, weights = np.polynomial.legendre.leggauss(order)
        theta = (nodes + 1.0) * (math.pi / 2.0)
        theta_weights = weights * (math.pi / 2.0)
        values = []
        for angle, weight in zip(theta, theta_weights):
            cosine, sine = math.cos(float(angle)), math.sin(float(angle))
            x = float(mean[0]) + radius * cosine
            half_y = radius * sine
            lower = (float(mean[1]) - half_y) / sigma_y
            upper = (float(mean[1]) + half_y) / sigma_y
            log_y = _log_normal_interval(lower, upper)
            if log_y == float("-inf") or sine <= 0 or weight <= 0:
                continue
            values.append(
                math.log(float(weight))
                - 0.5 * (x / sigma_x) ** 2 - math.log(sigma_x) - log_norm
                + log_y + math.log(radius) + math.log(sine)
            )
        if not values:
            return float("-inf")
        largest = max(values)
        estimate = largest + math.log(sum(math.exp(value - largest) for value in values))
        if previous is not None:
            delta = estimate - previous
            if abs(delta) < 0.5 and abs(math.expm1(delta)) <= tolerance:
                return estimate
        previous = estimate
        order *= 2
    return float("nan")


def _log_normal_interval(lower, upper):
    if upper <= lower:
        return float("-inf")
    if lower >= 0:
        return _log_difference(_log_normal_survival(lower), _log_normal_survival(upper))
    if upper <= 0:
        return _log_difference(_log_normal_survival(-upper), _log_normal_survival(-lower))
    probability = 0.5 * (math.erf(upper / math.sqrt(2.0)) - math.erf(lower / math.sqrt(2.0)))
    return math.log(probability) if probability > 0 else float("-inf")


def _log_normal_survival(value):
    if value < 8.0:
        return math.log(0.5 * math.erfc(value / math.sqrt(2.0)))
    inverse_square = 1.0 / (value * value)
    series = 1.0 - inverse_square + 3.0 * inverse_square**2 - 15.0 * inverse_square**3 + 105.0 * inverse_square**4
    return -0.5 * value * value - math.log(value) - 0.5 * math.log(2.0 * math.pi) + math.log(series)


def _log_difference(log_a, log_b):
    if log_a == float("-inf"):
        return float("-inf")
    if log_b == float("-inf"):
        return log_a
    if log_b >= log_a:
        return float("-inf")
    return log_a + math.log1p(-math.exp(log_b - log_a))


def _scientific(log_value):
    log10_value = log_value / math.log(10.0)
    exponent = math.floor(log10_value)
    mantissa = 10.0 ** (log10_value - exponent)
    return f"{mantissa:.6g}e{exponent:+d}"


def _covariance(object_id, tca, state, role_fields, quantile, multiplier, age_days):
    sigmas = np.asarray([role_fields[key][quantile] for key in SIGMA_KEYS], dtype=float) * multiplier
    if sigmas.shape != (6,) or not np.isfinite(sigmas).all() or np.any(sigmas <= 0):
        raise ValueError("prior sigma invalid")
    local = np.diag(sigmas**2)
    r = np.asarray(state[0], dtype=float)
    v = np.asarray(state[1], dtype=float)
    r_norm = float(np.linalg.norm(r))
    if not math.isfinite(r_norm) or r_norm <= 1e-12:
        raise ValueError("invalid propagated position for RTN frame")
    rhat = r / r_norm
    nhat = np.cross(r, v)
    n_norm = float(np.linalg.norm(nhat))
    if not math.isfinite(n_norm) or n_norm <= 1e-12:
        raise ValueError("degenerate propagated state for RTN frame")
    nhat = nhat / n_norm
    that = np.cross(nhat, rhat)
    rotation = np.column_stack((rhat, that, nhat))
    transform = np.zeros((6, 6), dtype=float)
    transform[:3, :3] = rotation
    transform[3:, 3:] = rotation
    units_transform = np.diag([1 / 1000.0] * 3 + [1 / 1000.0] * 3)
    matrix = units_transform @ transform @ local @ transform.T @ units_transform
    return CovarianceInput(
        object_id=object_id, frame="TEME", epoch=tca.isoformat(), matrix=matrix,
        units={"position": "km^2", "velocity": "km^2/s^2", "position_velocity_cross": "km^2/s"},
        source="ESA Kelvins CDM population prior mapped to RTN and rotated at TCA",
        source_type="derived", is_synthetic=True,
    )


def _object_prior(prior, config, obj, role, tca):
    role_fields = prior["roles"][role]["fields"]
    age = _tle_age_days(obj, tca)
    age_factor = min(config["age_inflation_cap"], 1.0 + config["age_inflation_per_day"] * age)
    band_factor = float(config["band_sigma_multiplier"].get(obj.band, 1.0))
    eccentricity = abs(float((obj.provenance.source_record or {}).get("parsed_propagation_parameters", {}).get("ecco", 0.0)))
    bstar = abs(float((obj.provenance.source_record or {}).get("parsed_propagation_parameters", {}).get("bstar", 0.0)))
    factor = age_factor * band_factor * (1.0 + float(config["eccentricity_sigma_multiplier"]) * eccentricity)
    if config["bstar_reference_abs"] > 0:
        factor *= 1.0 + float(config["bstar_sigma_multiplier"]) * min(bstar / float(config["bstar_reference_abs"]), config["age_inflation_cap"])
    span = role_fields["span_diameter_m"]
    half_diameters = {q: float(span[q]) / 2.0 for q in ("p10", "p50", "p90")}
    return role_fields, role, factor, half_diameters, age


def _prior_role(obj):
    return "esa_target" if obj.category in {"active", "payload", "station"} else "esa_chaser"


def _object_size_hbr_override(obj):
    name = " ".join((obj.name or "").upper().split())
    entry = OBJECT_SIZE_HBR_OVERRIDE_TABLE.get(name)
    if entry is None:
        return None
    return {
        "radius_km": float(entry["radius_km"]),
        "source": "ORION documented object-size assumption table",
        "table_key": name,
        "match": entry["match"],
    }


def _tle_age_days(obj, tca):
    record = obj.provenance.source_record or {}
    parameters = record.get("parsed_propagation_parameters", {})
    epoch = None
    if parameters.get("epochyr") is not None and parameters.get("epochdays") is not None:
        year = int(parameters["epochyr"])
        year += 1900 if year >= 57 else 2000
        epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(parameters["epochdays"]) - 1.0)
    if epoch is None:
        omm = record.get("omm_fields") or {}
        epoch = _parse_utc(omm.get("EPOCH") or omm.get("epoch"))
    if epoch is None:
        line1 = record.get("normalized_line1") or record.get("original_line1")
        if isinstance(line1, str) and len(line1) >= 32:
            year = int(line1[18:20])
            year += 1900 if year >= 57 else 2000
            epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(line1[20:32]) - 1.0)
    if epoch is None:
        raise MissingPriorData("TLE_ELEMENT_EPOCH_UNAVAILABLE")
    return max(0.0, (tca - epoch).total_seconds() / 86400.0)


def _state(payload, object_id, tca):
    if payload.get("object_id") != object_id or payload.get("frame") != "TEME" or _parse_utc(payload.get("epoch")) != tca:
        raise ValueError("event state identity, frame or epoch mismatch")
    position = np.asarray(payload.get("position_km"), dtype=float)
    velocity = np.asarray(payload.get("velocity_km_s"), dtype=float)
    if position.shape != (3,) or velocity.shape != (3,) or not np.isfinite(position).all() or not np.isfinite(velocity).all():
        raise ValueError("event state malformed")
    return position, velocity


def _config():
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.getenv("ORION_RESEARCH_PC_PRIOR_CONFIG"):
        override = json.loads(os.environ["ORION_RESEARCH_PC_PRIOR_CONFIG"])
        if not isinstance(override, dict):
            raise ValueError("prior config override must be an object")
        config.update(override)
    return config


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _unavailable(shared, reason, prior=None, config=None):
    return AutomaticResearchPcAssessment(
        status="not_estimable", quality_status="insufficient_inputs", reason_codes=[reason],
        reason_message=_unavailable_reason_message(reason),
        sensitivity_status="not_available", sensitivity_reason="The prior-based calculation did not produce a valid numerical Foster result.",
        assumptions=["No Pc value is substituted when event geometry or prior inputs fail validation."],
        provenance={"prior_model_version": (prior or {}).get("model_version"), "configuration": config}, **shared,
    )


def _unavailable_reason_message(reason: str) -> str:
    explanations = {
        "OBJECT_PROVENANCE_UNAVAILABLE": "Object provenance is missing, so the ESA population-prior inputs cannot be mapped to both event objects.",
        "TCA_STATE_UNAVAILABLE": "The event does not contain valid same-epoch TEME position and velocity states for both objects at TCA.",
        "PRIOR_INPUTS_UNAVAILABLE": "The ESA population prior does not contain supported uncertainty and size inputs for this object pair.",
        "FOSTER_PRIOR_CALCULATION_NUMERICAL_FAILURE": "The assumption-based Foster calculation failed its numerical checks for all supported prior scenarios.",
        "TLE_ELEMENT_EPOCH_UNAVAILABLE": "A TLE element epoch is missing, so the prior uncertainty age adjustment cannot be calculated.",
        "VALID_INTERIOR_TCA_REQUIRED": "This event has no valid interior TCA; the ESA-prior estimate is only evaluated for valid in-window encounters.",
    }
    if reason.startswith("FOSTER_PRIOR_CALCULATION_"):
        calculation_reason = reason.removeprefix("FOSTER_PRIOR_CALCULATION_")
        return f"The prior-based Foster calculation could not complete: {calculation_reason.lower().replace('_', ' ')}."
    if reason.startswith("PRIOR_ASSESSMENT_ERROR_"):
        error_type = reason.removeprefix("PRIOR_ASSESSMENT_ERROR_")
        return f"Research Pc inputs failed validation ({error_type}); no numerical estimate was produced."
    return explanations.get(reason, f"Research Pc could not be calculated because {reason.lower().replace('_', ' ')}.")
