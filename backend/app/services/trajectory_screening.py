from __future__ import annotations

import hashlib
import itertools
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Callable, Iterable

import numpy as np
from sgp4.api import Satrec, SatrecArray, SGP4_ERRORS, WGS72, jday

from app.ai.comparison import compare_ml_and_physics
from app.ai.inference import predict_from_physics
from app.ai.anomaly import predict_orbital_anomaly
from app.ai.collision_models import assess_collision_ai
from app.models import (
    ComparisonResult,
    ConjunctionAssessmentEvent,
    MLResult,
    ObjectSummary,
    PhysicsResult,
    Provenance,
    ScientificField,
    SpaceObject,
)
from app.services.ai_risk_prioritization import assess_live_geometry, rank_screening_events
from app.services.tle_provider import TleRecord, _valid_tle_record, satellite_from_record
from app.services.collision_probability import calculate_foster_2d
from app.services.object_classification import pair_type_for
from app.services.review_priority import classify_review_priority
from app.services.automatic_research_pc import assess_automatic_research_pc


METHOD = "SGP4 TEME trajectory screening with bounded subdivision and golden-section TCA refinement"
METHOD_VERSION = "1.2"
DEFAULT_HORIZON_HOURS = 24.0
DEFAULT_SAMPLE_STEP_SECONDS = 60
DEFAULT_SCREENING_THRESHOLD_KM = 25.0
MAX_RELATIVE_SPEED_BOUND_KM_S = 30.0
MAX_SAMPLE_EPOCHS = 10_000
MAX_CANDIDATE_PAIRS = 80_000
MAX_CANDIDATE_MINIMA = 2_000_000
MAX_LOCAL_MINIMA_PER_PAIR = 128
TCA_TIME_TOLERANCE_SECONDS = 0.01
TCA_NEIGHBOR_CHECK_SECONDS = 0.1
TCA_MAX_ITERATIONS = 80
TCA_REFINEMENT_SUBDIVISIONS = 16
TCA_MAX_REFINEMENT_BASINS = 4
# Below one micrometre, distance variation across the bracket is treated as
# numerically indistinguishable for TCA uniqueness at SGP4 double precision.
FLAT_DISTANCE_TOLERANCE_KM = 1e-9
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StateVector:
    position_km: tuple[float, float, float]
    velocity_km_s: tuple[float, float, float]


@dataclass(frozen=True)
class ClosestApproachSolution:
    status: str
    offset_seconds: float | None = None
    miss_distance_km: float | None = None
    relative_position_km: tuple[float, float, float] | None = None
    relative_velocity_km_s: tuple[float, float, float] | None = None
    primary_state: StateVector | None = None
    secondary_state: StateVector | None = None
    iterations: int = 0
    final_bracket_width_seconds: float | None = None
    neighbor_check_passed: bool = False
    reason_code: str | None = None


@dataclass
class _Track:
    record: TleRecord
    obj: SpaceObject
    satellite: Satrec
    propagation_errors: set[int] = field(default_factory=set)
    maximum_sampled_speed_km_s: float = 0.0
    altitude_range_km: tuple[float, float] | None = None


@dataclass
class _CandidateTracker:
    pair: tuple[int, int]
    max_minima: int = MAX_LOCAL_MINIMA_PER_PAIR
    last_index: int | None = None
    first_sample: tuple[int, float] | None = None
    second_sample: tuple[int, float] | None = None
    previous_previous: tuple[int, float] | None = None
    previous: tuple[int, float] | None = None
    segment_length: int = 0
    local_minima: list[tuple[int, float]] = field(default_factory=list)
    truncated: bool = False

    def add(self, sample_index: int, distance_km: float) -> None:
        if self.last_index is not None and sample_index != self.last_index + 1:
            self._finish_segment()
        sample = (sample_index, distance_km)
        if self.segment_length == 0:
            self.first_sample = sample
        elif self.segment_length == 1:
            self.second_sample = sample
        elif self.previous_previous is not None and self.previous is not None:
            before = self.previous_previous[1]
            current = self.previous[1]
            if current < before and current <= distance_km:
                self._append_minimum(self.previous)
        self.previous_previous = self.previous
        self.previous = sample
        self.last_index = sample_index
        self.segment_length += 1

    def finish(self) -> list[tuple[int, float]]:
        self._finish_segment()
        return self.local_minima

    def _finish_segment(self) -> None:
        if not self.segment_length:
            return
        first = self.first_sample
        last = self.previous
        if self.segment_length == 1 and first is not None:
            self._append_minimum(first)
        elif self.segment_length >= 2:
            # A segment starts/ends at the broad-phase radius boundary. Treat its
            # endpoint as a candidate only when the sampled distance is lowest.
            if first is not None and self.second_sample is not None and first[1] <= self.second_sample[1]:
                self._append_minimum(first)
            if self.previous_previous is not None and last is not None and last[1] < self.previous_previous[1]:
                self._append_minimum(last)
        self.first_sample = None
        self.second_sample = None
        self.previous_previous = None
        self.previous = None
        self.segment_length = 0

    def _append_minimum(self, sample: tuple[int, float]) -> None:
        if len(self.local_minima) >= self.max_minima:
            self.truncated = True
            return
        if all(existing[0] != sample[0] for existing in self.local_minima):
            self.local_minima.append(sample)


@dataclass(frozen=True)
class ScreeningRun:
    events: list[ConjunctionAssessmentEvent]
    summary: dict


class _PropagationFailure(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def minimize_relative_distance(
    primary_state_at: Callable[[float], StateVector],
    secondary_state_at: Callable[[float], StateVector],
    *,
    lower_offset_seconds: float,
    upper_offset_seconds: float,
    horizon_start_offset_seconds: float = 0.0,
    horizon_end_offset_seconds: float | None = None,
    time_tolerance_seconds: float = TCA_TIME_TOLERANCE_SECONDS,
    neighbor_check_seconds: float = TCA_NEIGHBOR_CHECK_SECONDS,
    max_iterations: int = TCA_MAX_ITERATIONS,
) -> ClosestApproachSolution:
    """Minimize propagated relative separation inside a bounded time interval.

    State callbacks accept seconds from a common UTC origin and must return TEME
    position (km) and velocity (km/s) at that same instant.
    """
    if not all(math.isfinite(v) for v in (lower_offset_seconds, upper_offset_seconds, time_tolerance_seconds)):
        return ClosestApproachSolution(status="invalid", reason_code="non_finite_solver_input")
    if lower_offset_seconds > upper_offset_seconds or time_tolerance_seconds <= 0 or max_iterations < 1:
        return ClosestApproachSolution(status="invalid", reason_code="invalid_solver_interval")
    horizon_end = upper_offset_seconds if horizon_end_offset_seconds is None else horizon_end_offset_seconds
    if lower_offset_seconds < horizon_start_offset_seconds or upper_offset_seconds > horizon_end:
        return ClosestApproachSolution(status="invalid", reason_code="solver_interval_outside_horizon")

    evaluation_cache: dict[
        float,
        tuple[float, StateVector, StateVector, tuple[float, float, float], tuple[float, float, float]],
    ] = {}

    def evaluate(offset: float) -> tuple[float, StateVector, StateVector, tuple[float, float, float], tuple[float, float, float]]:
        cached = evaluation_cache.get(offset)
        if cached is not None:
            return cached
        primary = primary_state_at(offset)
        secondary = secondary_state_at(offset)
        _validate_state(primary)
        _validate_state(secondary)
        relative_position = tuple(secondary.position_km[i] - primary.position_km[i] for i in range(3))
        relative_velocity = tuple(secondary.velocity_km_s[i] - primary.velocity_km_s[i] for i in range(3))
        distance = math.sqrt(sum(value * value for value in relative_position))
        if not math.isfinite(distance):
            raise _PropagationFailure("non_finite_relative_state")
        result = distance, primary, secondary, relative_position, relative_velocity
        evaluation_cache[offset] = result
        return result

    if lower_offset_seconds == upper_offset_seconds:
        try:
            result = evaluate(lower_offset_seconds)
        except _PropagationFailure as exc:
            return ClosestApproachSolution(status="invalid", reason_code=exc.reason_code)
        except Exception:
            return ClosestApproachSolution(status="invalid", reason_code="state_evaluation_failed")
        is_boundary = (
            abs(lower_offset_seconds - horizon_start_offset_seconds) <= time_tolerance_seconds
            or abs(lower_offset_seconds - horizon_end) <= time_tolerance_seconds
        )
        return _solution_from_evaluation("boundary" if is_boundary else "valid", lower_offset_seconds, result, 0, 0.0, True)

    left, right = lower_offset_seconds, upper_offset_seconds
    try:
        # A fixed 16-interval scan detects multiple resolved basins before
        # golden-section refinement, which assumes a unimodal bracket.
        probe_offsets = [
            left + (right - left) * index / TCA_REFINEMENT_SUBDIVISIONS
            for index in range(TCA_REFINEMENT_SUBDIVISIONS + 1)
        ]
        probe_distances = [evaluate(offset)[0] for offset in probe_offsets]
        if max(probe_distances) - min(probe_distances) <= FLAT_DISTANCE_TOLERANCE_KM:
            return ClosestApproachSolution(
                status="invalid",
                miss_distance_km=min(probe_distances),
                final_bracket_width_seconds=right - left,
                reason_code="non_unique_tca_flat_distance",
            )
        basin_indices = _sampled_minimum_indices(probe_distances)
        # A minimum at an artificial bracket endpoint is not evidence of a
        # horizon minimum. Candidate brackets are centered on sampled minima;
        # only the actual screening-horizon endpoints may legitimately be
        # minima at the edge of the interval. Keeping artificial edge basins
        # can make their failed neighbor check invalidate a separate, valid
        # basin in the same bracket.
        last_probe_index = len(probe_offsets) - 1
        basin_indices = [
            index for index in basin_indices
            if (index != 0 or left == horizon_start_offset_seconds)
            and (index != last_probe_index or right == horizon_end)
        ]
        if not basin_indices:
            return ClosestApproachSolution(
                status="invalid",
                reason_code="no_local_minimum_in_interval",
            )
        if len(basin_indices) > TCA_MAX_REFINEMENT_BASINS:
            return ClosestApproachSolution(
                status="invalid",
                reason_code="tca_refinement_basin_limit_exceeded",
            )
    except _PropagationFailure as exc:
        return ClosestApproachSolution(status="invalid", reason_code=exc.reason_code)
    except Exception:
        return ClosestApproachSolution(status="invalid", reason_code="state_evaluation_failed")
    try:
        solutions: list[ClosestApproachSolution] = []
        for basin_index in basin_indices:
            basin_left = probe_offsets[max(0, basin_index - 1)]
            basin_right = probe_offsets[min(len(probe_offsets) - 1, basin_index + 1)]
            basin_probe_offsets = (
                basin_left,
                basin_left + (basin_right - basin_left) * 0.25,
                (basin_left + basin_right) / 2.0,
                basin_left + (basin_right - basin_left) * 0.75,
                basin_right,
            )
            basin_probe_distances = [evaluate(offset)[0] for offset in basin_probe_offsets]
            if max(basin_probe_distances) - min(basin_probe_distances) <= FLAT_DISTANCE_TOLERANCE_KM:
                solutions.append(ClosestApproachSolution(
                    status="invalid",
                    miss_distance_km=min(basin_probe_distances),
                    final_bracket_width_seconds=basin_right - basin_left,
                    reason_code="non_unique_tca_flat_distance",
                ))
                continue
            solutions.append(_refine_unimodal_basin(
                evaluate,
                basin_left,
                basin_right,
                golden_ratio=(math.sqrt(5.0) - 1.0) / 2.0,
                horizon_start=horizon_start_offset_seconds,
                horizon_end=horizon_end,
                time_tolerance=time_tolerance_seconds,
                neighbor_check_seconds=neighbor_check_seconds,
                max_iterations=max_iterations,
            ))

        failures = [solution for solution in solutions if solution.status == "invalid"]
        successful = [solution for solution in solutions if solution.status != "invalid"]
        if failures:
            other_failures = [item for item in failures if item.reason_code != "non_unique_tca_flat_distance"]
            if other_failures:
                return other_failures[0]
            flat_distances = [
                item.miss_distance_km for item in failures
                if item.reason_code == "non_unique_tca_flat_distance" and item.miss_distance_km is not None
            ]
            best_success = min(
                successful,
                key=lambda item: item.miss_distance_km if item.miss_distance_km is not None else math.inf,
            ) if successful else None
            best_success_distance = (
                best_success.miss_distance_km
                if best_success is not None and best_success.miss_distance_km is not None
                else math.inf
            )
            if flat_distances and min(flat_distances) <= best_success_distance + FLAT_DISTANCE_TOLERANCE_KM:
                return ClosestApproachSolution(
                    status="invalid",
                    miss_distance_km=min(flat_distances),
                    reason_code="non_unique_tca_flat_distance",
                )
            if best_success is None:
                return failures[0]
            return best_success
        best_distance = min(
            item.miss_distance_km for item in successful if item.miss_distance_km is not None
        )
        equally_best = [
            item for item in successful
            if item.miss_distance_km is not None
            and item.miss_distance_km <= best_distance + FLAT_DISTANCE_TOLERANCE_KM
        ]
        if len(equally_best) > 1:
            return ClosestApproachSolution(
                status="invalid",
                miss_distance_km=best_distance,
                reason_code="non_unique_tca_multiple_minima",
            )
        return min(successful, key=lambda item: (
            item.miss_distance_km if item.miss_distance_km is not None else math.inf,
            item.offset_seconds if item.offset_seconds is not None else 0.0,
        ))
    except _PropagationFailure as exc:
        return ClosestApproachSolution(status="invalid", reason_code=exc.reason_code)
    except Exception:
        return ClosestApproachSolution(status="invalid", reason_code="state_evaluation_failed")


def screen_tle_records(
    records: list[TleRecord],
    objects: list[SpaceObject],
    *,
    start_utc: datetime | None = None,
    horizon_hours: float = DEFAULT_HORIZON_HOURS,
    sample_step_seconds: int = DEFAULT_SAMPLE_STEP_SECONDS,
    screening_threshold_km: float = DEFAULT_SCREENING_THRESHOLD_KM,
    unavailable_objects: Iterable[object] = (),
    max_candidate_pairs: int = MAX_CANDIDATE_PAIRS,
    max_candidate_minima: int = MAX_CANDIDATE_MINIMA,
    include_synthetic_test_records: bool = False,
) -> ScreeningRun:
    """Screen common-time SGP4 TEME trajectories for close approaches.

    The broad phase is a time-sampled spatial hash. Its search radius expands the
    event threshold by a configured relative-speed bound times half a sample
    interval. This bounds candidate generation without evaluating every catalog
    pair. Any resource cap or incomplete SGP4 track makes the run partial.
    """
    stage2a_started = time.perf_counter()
    stage_timings = {
        "track_preparation_seconds": 0.0,
        "sampled_trajectory_propagation_seconds": 0.0,
        "spatial_hash_construction_seconds": 0.0,
        "neighbor_comparison_seconds": 0.0,
        "candidate_minimum_detection_seconds": 0.0,
        "close_approach_refinement_seconds": 0.0,
        "physics_event_construction_seconds": 0.0,
        "ml_inference_seconds": 0.0,
        "orbital_anomaly_assessment_seconds": 0.0,
    }
    perf_counts = {
        "spatial_hash_cells": 0,
        "neighbor_cell_lookups": 0,
        "raw_candidate_comparisons": 0,
        "scalar_refinement_sgp4_evaluations": 0,
        "ml_inference_calls": 0,
        "orbital_anomaly_assessments": 0,
        "orbital_anomaly_predictions_produced": 0,
    }
    start = start_utc or datetime.now(timezone.utc)
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start_utc must be a timezone-aware UTC datetime")
    start = start.astimezone(timezone.utc)
    if not math.isfinite(horizon_hours) or horizon_hours <= 0:
        raise ValueError("horizon_hours must be finite and greater than zero")
    if not isinstance(sample_step_seconds, int) or sample_step_seconds <= 0:
        raise ValueError("sample_step_seconds must be a positive integer")
    if not math.isfinite(screening_threshold_km) or screening_threshold_km <= 0:
        raise ValueError("screening_threshold_km must be finite and greater than zero")
    if max_candidate_pairs < 1 or max_candidate_minima < 1:
        raise ValueError("candidate limits must be positive")

    duration_seconds = horizon_hours * 3600.0
    requested_sample_count = math.ceil(duration_seconds / sample_step_seconds) + 1
    sample_epoch_cap_reached = requested_sample_count > MAX_SAMPLE_EPOCHS
    sample_count = min(requested_sample_count, MAX_SAMPLE_EPOCHS)
    end = start + timedelta(seconds=duration_seconds)
    sampled_duration_seconds = min(duration_seconds, (sample_count - 1) * sample_step_seconds)
    times = [start + timedelta(seconds=min(index * sample_step_seconds, sampled_duration_seconds)) for index in range(sample_count)]
    if not sample_epoch_cap_reached and times[-1] != end:
        times.append(end)
    offsets = [(time - start).total_seconds() for time in times]
    max_gap_seconds = max((offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1)), default=0.0)
    broad_phase_radius_km = screening_threshold_km + MAX_RELATIVE_SPEED_BOUND_KM_S * max_gap_seconds / 2.0

    stage_started = time.perf_counter()
    tracks, rejected = _prepare_tracks(records, objects, unavailable_objects, include_synthetic_test_records)
    # Orbital radial ranges are a cheap necessary-condition filter for a close
    # approach. Keep a generous 100 km margin for perturbations and model error.
    for track in tracks:
        semi_major_axis_km = float(track.satellite.a) * 6378.135
        eccentricity = float(track.satellite.ecco)
        track.altitude_range_km = (
            semi_major_axis_km * (1.0 - eccentricity) - 6378.135,
            semi_major_axis_km * (1.0 + eccentricity) - 6378.135,
        )
    # Give scarce candidate-pair slots first to the requested 700–1000 km
    # shells and debris/rocket-body groups. The broad-phase and physics are
    # unchanged; this only makes deterministic track traversal priority-aware.
    def pair_budget_priority(track: _Track) -> tuple[int, str]:
        radial_range = track.altitude_range_km or (math.inf, -math.inf)
        target_shell = radial_range[1] >= 700.0 and radial_range[0] <= 1000.0
        debris_group = track.obj.category in {"debris", "rocket_body"}
        tier = 0 if target_shell and debris_group else 1 if target_shell else 2 if debris_group else 3
        return tier, track.obj.id
    tracks.sort(key=pair_budget_priority)
    stage_timings["track_preparation_seconds"] = time.perf_counter() - stage_started
    summary = {
        "status": "partial" if sample_epoch_cap_reached else "unavailable" if not tracks else "valid",
        "screening_status": "partial" if sample_epoch_cap_reached else "unavailable" if not tracks else "valid",
        "coverage_status": "partial" if sample_epoch_cap_reached else "failed" if not tracks else "complete",
        "reason_code": "sample_epoch_limit_reached" if sample_epoch_cap_reached else "no_usable_tle_tracks" if not tracks else None,
        "partial_reasons": ["sample_epoch_limit_reached"] if sample_epoch_cap_reached else [],
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "screening_horizon_start": _iso(start),
        "screening_horizon_end": _iso(end),
        "horizon_hours": horizon_hours,
        "requested_horizon_hours": horizon_hours,
        "effective_horizon_hours": horizon_hours,
        "sample_step_seconds": sample_step_seconds,
        "requested_sample_step_seconds": sample_step_seconds,
        "effective_sample_step_seconds": sample_step_seconds,
        "sample_epoch_count": len(times),
        "requested_sample_epoch_count": requested_sample_count,
        "sampled_coverage_end": _iso(times[-1]),
        "screening_threshold_km": screening_threshold_km,
        "requested_screening_threshold_km": screening_threshold_km,
        "effective_screening_threshold_km": screening_threshold_km,
        "synthetic_test_inputs_included": include_synthetic_test_records,
        "broad_phase_search_radius_km": broad_phase_radius_km,
        "maximum_relative_speed_bound_km_s": MAX_RELATIVE_SPEED_BOUND_KM_S,
        "frame": "TEME",
        "time_scale": "UTC calendar input converted to split Julian date for SGP4; no TEME frame transform",
        "position_units": "km",
        "velocity_units": "km/s",
        "gravity_model": "WGS72",
        "propagator": "python-sgp4 SGP4/SDP4",
        "propagator_version": _sgp4_version(),
        "candidate_generation_method": "per-epoch 3-D spatial hash with adjacent-cell lookup and speed-bound-expanded radius",
        "candidate_generation_complexity": "O(N*T + Q) expected; Q is local spatial-neighbor checks; dense-cell worst case can approach O(N^2*T), guarded by explicit pair/minimum caps",
        "candidate_pair_limit": max_candidate_pairs,
        "candidate_minimum_limit": max_candidate_minima,
        "local_minima_per_pair_limit": MAX_LOCAL_MINIMA_PER_PAIR,
        "tca_refinement_subdivisions_per_bracket": TCA_REFINEMENT_SUBDIVISIONS,
        "tca_refinement_basin_limit_per_bracket": TCA_MAX_REFINEMENT_BASINS,
        "sample_epoch_limit": MAX_SAMPLE_EPOCHS,
        "valid_track_count": len(tracks),
        "rejected_object_count": len(rejected),
        "rejected_objects": rejected[:100],
        "sgp4_error_object_count": 0,
        "candidate_pair_count": 0,
        "candidate_pairs": 0,
        "candidate_local_minimum_count": 0,
        "refinement_count": 0,
        "refinements": 0,
        "close_approach_count": 0,
        "physical_events": 0,
        "invalid_assessment_count": 0,
        "candidate_limit_reached": False,
        "candidate_pair_limit_reached": False,
        "candidate_minimum_limit_reached": False,
        "local_minima_per_pair_limit_reached": False,
        "sample_epoch_limit_reached": sample_epoch_cap_reached,
        "caps_hit": ["sample_epoch_limit"] if sample_epoch_cap_reached else [],
        "completeness_claim": "conditional on the selected catalog, configured relative-speed bound, SGP4 validity, horizon, sampling interval, and resource limits; partial status is used when a known limit or input/propagation issue restricts coverage",
    }
    if not tracks:
        return ScreeningRun(events=[], summary=summary)

    track_array = SatrecArray([track.satellite for track in tracks])
    candidate_trackers: dict[tuple[int, int], _CandidateTracker] = {}
    broad_phase_comparisons = 0
    candidate_limit_reached = False
    candidate_pair_limit_reached = False
    julian_dates = [_julian_parts(time) for time in times]
    batch_size = 128
    sampled_stage_started = time.perf_counter()
    for batch_start in range(0, len(times), batch_size):
        batch_end = min(len(times), batch_start + batch_size)
        jd = np.asarray([julian_dates[i][0] for i in range(batch_start, batch_end)], dtype=float)
        fr = np.asarray([julian_dates[i][1] for i in range(batch_start, batch_end)], dtype=float)
        stage_started = time.perf_counter()
        errors, positions, velocities = track_array.sgp4(jd, fr)
        stage_timings["sampled_trajectory_propagation_seconds"] += time.perf_counter() - stage_started
        for local_index, sample_index in enumerate(range(batch_start, batch_end)):
            sample_errors = errors[:, local_index]
            for track_index in np.flatnonzero(sample_errors):
                tracks[int(track_index)].propagation_errors.add(int(sample_errors[track_index]))
            position = positions[:, local_index, :]
            velocity = velocities[:, local_index, :]
            finite = np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
            invalid_finite = np.flatnonzero((sample_errors == 0) & ~finite)
            for track_index in invalid_finite:
                tracks[int(track_index)].propagation_errors.add(-1)
            valid_indices = np.flatnonzero((sample_errors == 0) & finite)
            if len(valid_indices):
                sampled_speeds = np.linalg.norm(velocity[valid_indices], axis=1)
                for track_index, speed in zip(valid_indices, sampled_speeds):
                    tracks[int(track_index)].maximum_sampled_speed_km_s = max(
                        tracks[int(track_index)].maximum_sampled_speed_km_s,
                        float(speed),
                    )
            buckets: dict[tuple[int, int, int], list[int]] = {}
            for i_raw in valid_indices:
                i = int(i_raw)
                p = position[i]
                hash_stage_started = time.perf_counter()
                cell = tuple(math.floor(float(component) / broad_phase_radius_km) for component in p)
                stage_timings["spatial_hash_construction_seconds"] += time.perf_counter() - hash_stage_started
                stage_started = time.perf_counter()
                for neighbor_offset in itertools.product((-1, 0, 1), repeat=3):
                    neighbor = tuple(cell[axis] + neighbor_offset[axis] for axis in range(3))
                    perf_counts["neighbor_cell_lookups"] += 1
                    for j in buckets.get(neighbor, ()):
                        broad_phase_comparisons += 1
                        perf_counts["raw_candidate_comparisons"] += 1
                        delta = p - position[j]
                        distance = float(np.linalg.norm(delta))
                        if distance > broad_phase_radius_km or tracks[i].obj.id == tracks[j].obj.id:
                            continue
                        first_range = tracks[i].altitude_range_km
                        second_range = tracks[j].altitude_range_km
                        if first_range and second_range:
                            radial_gap = max(first_range[0] - second_range[1], second_range[0] - first_range[1], 0.0)
                            if radial_gap > screening_threshold_km + 100.0:
                                continue
                        pair = (j, i)
                        tracker = candidate_trackers.get(pair)
                        if tracker is None:
                            if len(candidate_trackers) >= max_candidate_pairs:
                                candidate_limit_reached = True
                                candidate_pair_limit_reached = True
                                continue
                            tracker = _CandidateTracker(pair=pair)
                            candidate_trackers[pair] = tracker
                        tracker.add(sample_index, distance)
                stage_timings["neighbor_comparison_seconds"] += time.perf_counter() - stage_started
                stage_started = time.perf_counter()
                buckets.setdefault(cell, []).append(i)
                stage_timings["spatial_hash_construction_seconds"] += time.perf_counter() - stage_started
            perf_counts["spatial_hash_cells"] += len(buckets)

        logger.info(
            "Stage 2A coarse sampling progress: epochs=%d/%d cells=%d neighbor_lookups=%d raw_comparisons=%d elapsed_seconds=%.3f",
            batch_end,
            len(times),
            perf_counts["spatial_hash_cells"],
            perf_counts["neighbor_cell_lookups"],
            perf_counts["raw_candidate_comparisons"],
            time.perf_counter() - sampled_stage_started,
        )

    for track in tracks:
        # 30 km/s is the broad-phase relative-speed bound. A catalog track
        # outside half of it invalidates the bound instead of being hidden.
        if _track_max_speed_exceeded(track, times, MAX_RELATIVE_SPEED_BOUND_KM_S / 2.0):
            track.propagation_errors.add(-2)

    stage_started = time.perf_counter()
    candidate_minima: list[tuple[float, int, tuple[int, int], int]] = []
    local_minima_limit_reached = False
    for pair, tracker in candidate_trackers.items():
        for sample_index, distance in tracker.finish():
            candidate_minima.append((distance, sample_index, pair, sample_index))
        local_minima_limit_reached = local_minima_limit_reached or tracker.truncated
    candidate_limit_reached = candidate_limit_reached or local_minima_limit_reached
    candidate_minima.sort(key=lambda item: (item[0], tracks[item[2][0]].obj.id, tracks[item[2][1]].obj.id, item[1]))
    minima_truncated = len(candidate_minima) > max_candidate_minima
    if minima_truncated:
        candidate_minima = candidate_minima[:max_candidate_minima]
    candidate_limit_reached = candidate_limit_reached or minima_truncated
    stage_timings["candidate_minimum_detection_seconds"] = time.perf_counter() - stage_started

    try:
        sgp4_version = package_version("sgp4")
    except PackageNotFoundError:  # pragma: no cover - dependency is required by the backend
        sgp4_version = "unknown"
    events: dict[str, ConjunctionAssessmentEvent] = {}
    refinement_count = 0
    for _, sample_index, pair, _ in candidate_minima:
        primary_track, secondary_track = tracks[pair[0]], tracks[pair[1]]
        pair_errors = sorted(primary_track.propagation_errors | secondary_track.propagation_errors)
        if pair_errors:
            reason = _pair_error_reason(pair_errors)
            event_started = time.perf_counter()
            ml_before_event = stage_timings["ml_inference_seconds"]
            invalid_event = _invalid_assessment(
                primary_track,
                secondary_track,
                start,
                end,
                screening_threshold_km,
                reason,
                stage_timings=stage_timings,
                perf_counts=perf_counts,
            )
            stage_timings["physics_event_construction_seconds"] += max(
                0.0,
                time.perf_counter() - event_started - (stage_timings["ml_inference_seconds"] - ml_before_event),
            )
            events[invalid_event.id] = invalid_event
            continue

        # These pairs are already known to be indistinguishable under SGP4.
        # Keep an explicit invalid assessment, but do not refine a TCA that the
        # input elements cannot physically resolve.
        if primary_track.record.input_hash == secondary_track.record.input_hash:
            invalid_reason = "duplicate_tle_state_for_distinct_catalog_ids"
        elif _same_propagation_parameters(primary_track.satellite, secondary_track.satellite):
            invalid_reason = "identical_propagation_parameters_for_distinct_catalog_ids"
        else:
            invalid_reason = None
        if invalid_reason:
            invalid_event = _invalid_assessment(
                primary_track, secondary_track, start, end, screening_threshold_km,
                invalid_reason,
                stage_timings=stage_timings, perf_counts=perf_counts,
            )
            events[invalid_event.id] = invalid_event
            continue

        bracket_left_index = max(0, sample_index - 1)
        bracket_right_index = min(len(times) - 1, sample_index + 1)
        primary_state = _state_callback(primary_track, start, perf_counts)
        secondary_state = _state_callback(secondary_track, start, perf_counts)
        refinement_started = time.perf_counter()
        solution = minimize_relative_distance(
            primary_state,
            secondary_state,
            lower_offset_seconds=offsets[bracket_left_index],
            upper_offset_seconds=offsets[bracket_right_index],
            horizon_start_offset_seconds=0.0,
            horizon_end_offset_seconds=duration_seconds,
        )
        stage_timings["close_approach_refinement_seconds"] += time.perf_counter() - refinement_started
        refinement_count += 1
        if solution.status == "invalid":
            event_started = time.perf_counter()
            ml_before_event = stage_timings["ml_inference_seconds"]
            invalid_event = _invalid_assessment(
                primary_track,
                secondary_track,
                start,
                end,
                screening_threshold_km,
                solution.reason_code or "tca_refinement_failed",
                known_miss_distance_km=(
                    solution.miss_distance_km
                    if solution.reason_code in {"non_unique_tca_flat_distance", "non_unique_tca_multiple_minima"}
                    else None
                ),
                candidate_identity=(
                    f"samples-{bracket_left_index}-{sample_index}-{bracket_right_index}"
                    f"-epochs-{_iso(start + timedelta(seconds=offsets[bracket_left_index]))}"
                    f"-{_iso(start + timedelta(seconds=offsets[bracket_right_index]))}"
                ),
                stage_timings=stage_timings,
                perf_counts=perf_counts,
            )
            stage_timings["physics_event_construction_seconds"] += max(
                0.0,
                time.perf_counter() - event_started - (stage_timings["ml_inference_seconds"] - ml_before_event),
            )
            events[invalid_event.id] = invalid_event
            continue
        if solution.miss_distance_km is None or solution.offset_seconds is None:
            continue
        if solution.miss_distance_km > screening_threshold_km:
            continue
        if solution.miss_distance_km == 0.0 and math.sqrt(sum(v * v for v in solution.relative_velocity_km_s or ())) == 0.0:
            invalid_event = _invalid_assessment(
                primary_track, secondary_track, start, end, screening_threshold_km,
                "degenerate_zero_relative_state",
                stage_timings=stage_timings, perf_counts=perf_counts,
            )
            events[invalid_event.id] = invalid_event
            continue
        tca = start + timedelta(seconds=solution.offset_seconds)
        event_started = time.perf_counter()
        ml_before_event = stage_timings["ml_inference_seconds"]
        assessment = _valid_assessment(
            primary_track,
            secondary_track,
            start,
            end,
            tca,
            screening_threshold_km,
            solution,
            sgp4_version,
            stage_timings=stage_timings,
            perf_counts=perf_counts,
        )
        stage_timings["physics_event_construction_seconds"] += max(
            0.0,
            time.perf_counter() - event_started - (stage_timings["ml_inference_seconds"] - ml_before_event),
        )
        events[assessment.id] = assessment

    output_events = sorted(
        events.values(),
        key=lambda event: (
            event.physics_result.tca.value or "9999",
            event.physics_result.miss_distance.value if event.physics_result.miss_distance.value is not None else math.inf,
            event.id,
        ),
    )
    # This summary is a count of distinct invalid records returned, matching
    # event-ID deduplication and the payload consumers see.
    invalid_count = sum(event.physics_result.status == "invalid" for event in output_events)
    all_track_errors = sum(1 for track in tracks if track.propagation_errors)
    # Invalid candidate assessments remain part of the complete result set;
    # they describe individual pair validity, not interrupted screening.
    incomplete_inputs = bool(rejected) or all_track_errors > 0
    run_status = "partial" if candidate_limit_reached or incomplete_inputs or sample_epoch_cap_reached else "valid"
    partial_reasons = []
    if candidate_limit_reached:
        partial_reasons.append("candidate_pair_or_minimum_limit_reached")
    if rejected:
        partial_reasons.append("catalog_objects_rejected")
    if all_track_errors:
        partial_reasons.append("sgp4_track_propagation_errors")
    if sample_epoch_cap_reached:
        partial_reasons.append("sample_epoch_limit_reached")
    caps_hit = []
    if candidate_pair_limit_reached:
        caps_hit.append("candidate_pair_limit")
    if minima_truncated:
        caps_hit.append("candidate_minimum_limit")
    if local_minima_limit_reached:
        caps_hit.append("local_minima_per_pair_limit")
    if sample_epoch_cap_reached:
        caps_hit.append("sample_epoch_limit")
    summary.update(
        {
            "status": run_status,
            "reason_code": ";".join(partial_reasons) if partial_reasons else None,
            "partial_reasons": partial_reasons,
            "coverage_status": "partial" if run_status == "partial" else "complete",
            "sgp4_error_object_count": all_track_errors,
            "sgp4_errors_by_object": [
                {"object_id": track.obj.id, "error_codes": sorted(track.propagation_errors)}
                for track in tracks if track.propagation_errors
            ][:100],
            "candidate_pair_count": len(candidate_trackers),
            "candidate_pairs": len(candidate_trackers),
            "candidate_local_minimum_count": len(candidate_minima),
            "broad_phase_neighbor_comparisons": broad_phase_comparisons,
            "refinement_count": refinement_count,
            "refinements": refinement_count,
            "close_approach_count": sum(1 for event in output_events if event.physics_result.status in {"valid", "boundary"}),
            "physical_events": sum(1 for event in output_events if event.physics_result.status in {"valid", "boundary"}),
            "invalid_assessment_count": invalid_count,
            "assessment_diagnostic_codes": ["invalid_assessments_generated"] if invalid_count else [],
            "candidate_limit_reached": candidate_limit_reached,
            "candidate_pair_limit_reached": candidate_pair_limit_reached,
            "candidate_minimum_limit_reached": minima_truncated,
            "local_minima_per_pair_limit_reached": local_minima_limit_reached,
            "sample_epoch_limit_reached": sample_epoch_cap_reached,
            "caps_hit": caps_hit,
            "screening_status": run_status,
        }
    )
    summary["performance"] = {
        "timings_seconds": stage_timings,
        "counts": {
            "objects_processed": len(tracks),
            "sample_epochs": len(times),
            **perf_counts,
            "raw_candidate_comparisons": broad_phase_comparisons,
            "candidate_minima": len(candidate_minima),
            "refinement_calls": refinement_count,
            "final_reported_events": len(output_events),
        },
        "total_stage_2a_seconds": time.perf_counter() - stage2a_started,
        "timing_status": "complete",
    }
    return ScreeningRun(events=rank_screening_events(output_events), summary=summary)


def _prepare_tracks(
    records: list[TleRecord],
    objects: list[SpaceObject],
    unavailable_objects: Iterable[object],
    include_synthetic_test_records: bool = False,
) -> tuple[list[_Track], list[dict[str, str]]]:
    object_by_id = {obj.id: obj for obj in objects if obj.provenance.validity_status == "valid"}
    rejected: list[dict[str, str]] = []
    unavailable_ids: set[str] = set()
    grouped: dict[str, list[TleRecord]] = {}
    for record in records:
        allowed_types = {"live", "fallback"} | ({"synthetic"} if include_synthetic_test_records else set())
        if record.source_type not in allowed_types:
            rejected.append({"object_id": _catalog_id(record), "reason_code": "non_physical_source_not_screened"})
            continue
        object_id = _catalog_id(record)
        if not object_id:
            rejected.append({"object_id": "", "reason_code": "missing_catalog_id"})
            continue
        grouped.setdefault(object_id, []).append(record)
    for unavailable in unavailable_objects:
        provenance = getattr(unavailable, "provenance", None)
        unavailable_id = str(getattr(unavailable, "id", ""))
        unavailable_ids.add(unavailable_id)
        rejected.append(
            {
                "object_id": unavailable_id,
                "reason_code": str(getattr(provenance, "reason_code", None) or "source_state_unavailable"),
            }
        )

    tracks: list[_Track] = []
    for object_id in sorted(grouped):
        same_id = grouped[object_id]
        hashes = {record.propagation_input_hash for record in same_id}
        if len(hashes) > 1:
            rejected.append({"object_id": object_id, "reason_code": "duplicate_object_id_conflicting_tles"})
            continue
        record = sorted(same_id, key=lambda item: (0 if item.source_type == "live" else 1, item.source_group))[0]
        obj = object_by_id.get(object_id)
        if obj is None:
            if object_id not in unavailable_ids:
                rejected.append({"object_id": object_id, "reason_code": "no_valid_current_sgp4_state"})
            continue
        try:
            if not _valid_tle_record(record):
                raise ValueError(f"invalid {record.source_format} fields")
            if record.omm_fields is None:
                if not record.line1.startswith("1 ") or not record.line2.startswith("2 "):
                    raise ValueError("invalid TLE line numbers")
                if record.line1[2:7] != record.line2[2:7]:
                    raise ValueError("TLE catalog identifiers do not match")
            satellite = satellite_from_record(record)
        except Exception:
            rejected.append({"object_id": object_id, "reason_code": "invalid_omm" if record.omm_fields is not None else "invalid_tle"})
            continue
        tracks.append(_Track(record=record, obj=obj, satellite=satellite))
    unique_rejected = {
        (item["object_id"], item["reason_code"]): item
        for item in rejected
    }
    return tracks, list(unique_rejected.values())


def _catalog_id(record: TleRecord) -> str:
    return record.catalog_id or ""


def _same_propagation_parameters(first: Satrec, second: Satrec) -> bool:
    """True only when independent Satrec objects encode the same propagator inputs."""
    fields = ("epochyr", "epochdays", "ndot", "nddot", "bstar", "inclo", "nodeo", "ecco", "argpo", "mo", "no_kozai")
    return all(getattr(first, field) == getattr(second, field) for field in fields)


def _state_callback(track: _Track, origin: datetime, perf_counts: dict | None = None) -> Callable[[float], StateVector]:
    def state_at(offset_seconds: float) -> StateVector:
        if perf_counts is not None:
            perf_counts["scalar_refinement_sgp4_evaluations"] += 1
        epoch = origin + timedelta(seconds=offset_seconds)
        jd, fr = _julian_parts(epoch)
        error, position, velocity = track.satellite.sgp4(jd, fr)
        if error:
            description = SGP4_ERRORS.get(error, "unknown SGP4 error")
            raise _PropagationFailure(f"sgp4_error_{error}:{description}")
        state = StateVector(tuple(float(v) for v in position), tuple(float(v) for v in velocity))
        _validate_state(state)
        return state

    return state_at


def _track_max_speed_exceeded(track: _Track, times: list[datetime], max_individual_speed: float) -> bool:
    # The speed bound is checked from the object summaries' common-time states
    # only indirectly; the full sampled vectors are checked in the bulk pass
    # below via the track's transient maximum.
    return getattr(track, "maximum_sampled_speed_km_s", 0.0) > max_individual_speed


def _valid_assessment(
    primary_track: _Track,
    secondary_track: _Track,
    horizon_start: datetime,
    horizon_end: datetime,
    tca: datetime,
    threshold_km: float,
    solution: ClosestApproachSolution,
    sgp4_version: str,
    *,
    stage_timings: dict | None = None,
    perf_counts: dict | None = None,
) -> ConjunctionAssessmentEvent:
    assert solution.miss_distance_km is not None
    assert solution.relative_position_km is not None
    assert solution.relative_velocity_km_s is not None
    assert solution.primary_state is not None and solution.secondary_state is not None
    primary, secondary = primary_track.obj, secondary_track.obj
    event_id = _event_id(primary_track, secondary_track, tca)
    relative_position = solution.relative_position_km
    relative_velocity = solution.relative_velocity_km_s
    miss_distance = solution.miss_distance_km
    relative_speed = math.sqrt(sum(v * v for v in relative_velocity))
    radial_rate = (
        sum(relative_position[i] * relative_velocity[i] for i in range(3)) / miss_distance
        if miss_distance > 0.0 else None
    )
    transverse_speed = (
        math.sqrt(max(0.0, relative_speed * relative_speed - radial_rate * radial_rate))
        if radial_rate is not None else None
    )
    provenance = _pair_provenance(primary_track, secondary_track, tca, "valid" if solution.status == "valid" else "boundary", sgp4_version)
    physics = PhysicsResult(
        event_id=event_id,
        status=solution.status,  # type: ignore[arg-type]
        applicability="within_configured_screening_horizon; boundary" if solution.status == "boundary" else "within_configured_screening_horizon",
        provenance=provenance,
        object_primary_id=primary.id,
        object_secondary_id=secondary.id,
        screening_horizon_start=_iso(horizon_start),
        screening_horizon_end=_iso(horizon_end),
        screening_threshold_km=threshold_km,
        tca_status=solution.status,  # type: ignore[arg-type]
        state_information={
            "source_frame": "TEME",
            "target_frame": "TEME",
            "transformation_applied": False,
            "time_scale": "UTC calendar input converted to split Julian date for SGP4",
            "gravity_model": "WGS72",
            "propagator": "python-sgp4 SGP4/SDP4",
            "propagator_version": sgp4_version,
            "position_units": "km",
            "velocity_units": "km/s",
        },
        tca=ScientificField(status="available", value=_iso(tca), units="UTC", method=METHOD, method_version=METHOD_VERSION),
        miss_distance=ScientificField(status="available", value=miss_distance, units="km", method=METHOD, method_version=METHOD_VERSION),
        relative_position_at_tca=ScientificField(status="available", value=list(relative_position), units="km", method=METHOD, method_version=METHOD_VERSION),
        relative_velocity_at_tca=ScientificField(status="available", value=list(relative_velocity), units="km/s", method=METHOD, method_version=METHOD_VERSION),
        relative_speed_at_tca=ScientificField(status="available", value=relative_speed, units="km/s", method=METHOD, method_version=METHOD_VERSION),
        primary_state_at_tca=_state_payload(primary_track, tca, solution.primary_state),
        secondary_state_at_tca=_state_payload(secondary_track, tca, solution.secondary_state),
        encounter_geometry={
            "relative_speed_km_s": relative_speed,
            "radial_rate_km_s": radial_rate,
            "transverse_speed_km_s": transverse_speed,
            "relative_vector_convention": "secondary minus primary",
            "frame": "TEME",
        },
        convergence={
            "method": "16-interval bounded subdivision with per-basin golden-section refinement of Euclidean relative distance",
            "subdivisions_per_bracket": TCA_REFINEMENT_SUBDIVISIONS,
            "basin_limit_per_bracket": TCA_MAX_REFINEMENT_BASINS,
            "iterations": solution.iterations,
            "time_tolerance_seconds": TCA_TIME_TOLERANCE_SECONDS,
            "final_bracket_width_seconds": solution.final_bracket_width_seconds,
            "neighbor_check_seconds": TCA_NEIGHBOR_CHECK_SECONDS,
            "neighbor_check_passed": solution.neighbor_check_passed,
            "bracket_origin": "coarse sampled local minimum and adjacent sample epochs",
        },
        reason_codes=["horizon_boundary_solution"] if solution.status == "boundary" else [],
    )
    collision_probability = calculate_foster_2d(
        event_id=event_id,
        object_1_id=primary.id,
        object_2_id=secondary.id,
        tca_utc=_iso(tca),
        position_1_km=solution.primary_state.position_km,
        velocity_1_km_s=solution.primary_state.velocity_km_s,
        position_2_km=solution.secondary_state.position_km,
        velocity_2_km_s=solution.secondary_state.velocity_km_s,
        state_frame="TEME",
        tca_status=solution.status,
    )
    ml_started = time.perf_counter()
    ml_result = predict_from_physics(physics)
    if stage_timings is not None:
        stage_timings["ml_inference_seconds"] += time.perf_counter() - ml_started
    if perf_counts is not None:
        perf_counts["ml_inference_calls"] += 1
    anomaly_started = time.perf_counter()
    anomaly_result = predict_orbital_anomaly(physics)
    if stage_timings is not None:
        stage_timings["orbital_anomaly_assessment_seconds"] += time.perf_counter() - anomaly_started
    if perf_counts is not None:
        perf_counts["orbital_anomaly_assessments"] += 1
        perf_counts["orbital_anomaly_predictions_produced"] += anomaly_result.status == "available"
    comparison_result = compare_ml_and_physics(ml_result, collision_probability)
    review_priority = classify_review_priority(
        physics, ml_status=ml_result.status, pc_status=collision_probability.status,
    )
    automatic_research_pc_assessment = assess_automatic_research_pc(
        physics, collision_probability, review_priority,
        primary=_object_summary(primary), secondary=_object_summary(secondary),
    )
    collision_ai_assessment = assess_collision_ai(ConjunctionAssessmentEvent(
        id=event_id, primary=_object_summary(primary), secondary=_object_summary(secondary),
        obj_a=_object_summary(primary), obj_b=_object_summary(secondary),
        pair_type=_pair_type(primary, secondary), provenance=provenance,
        physics_result=physics, collision_probability=collision_probability,
        automatic_research_pc_assessment=automatic_research_pc_assessment,
        review_priority=review_priority,
    ))
    ai_risk_assessment = assess_live_geometry(physics)
    return ConjunctionAssessmentEvent(
        id=event_id,
        primary=_object_summary(primary),
        secondary=_object_summary(secondary),
        obj_a=_object_summary(primary),
        obj_b=_object_summary(secondary),
        pair_type=_pair_type(primary, secondary),
        provenance=provenance,
        physics_result=physics,
        collision_probability=collision_probability,
        automatic_research_pc_assessment=automatic_research_pc_assessment,
        collision_ai_assessment=collision_ai_assessment,
        ml_result=ml_result,
        anomaly_result=anomaly_result,
        comparison_result=comparison_result,
        review_priority=review_priority,
        ai_risk_assessment=ai_risk_assessment,
    )


def _invalid_assessment(
    primary_track: _Track,
    secondary_track: _Track,
    horizon_start: datetime,
    horizon_end: datetime,
    threshold_km: float,
    reason_code: str,
    *,
    known_miss_distance_km: float | None = None,
    candidate_identity: str | None = None,
    stage_timings: dict | None = None,
    perf_counts: dict | None = None,
) -> ConjunctionAssessmentEvent:
    primary, secondary = primary_track.obj, secondary_track.obj
    invalid_identity = f"invalid:{reason_code}"
    if candidate_identity is not None:
        invalid_identity = f"{invalid_identity}:{candidate_identity}"
    event_id = _event_id(primary_track, secondary_track, invalid_identity)
    provenance = _pair_provenance(primary_track, secondary_track, None, "invalid", _sgp4_version())
    provenance.reason_code = reason_code
    physics = PhysicsResult(
        event_id=event_id,
        status="invalid",
        applicability=(
            (
                "distance variation across bounded refinement probes is within the flat-distance tolerance; "
                "the minimum probe distance is retained, but no unique TCA or TCA-dependent state is identified"
                if reason_code == "non_unique_tca_flat_distance"
                else "multiple separated refined minima have indistinguishable miss distances; the minimum distance is retained, but no unique TCA is identified"
            )
            if known_miss_distance_km is not None
            else "pair propagation or TCA refinement failed; no horizon minimum is asserted"
        ),
        provenance=provenance,
        object_primary_id=primary.id,
        object_secondary_id=secondary.id,
        screening_horizon_start=_iso(horizon_start),
        screening_horizon_end=_iso(horizon_end),
        screening_threshold_km=threshold_km,
        tca_status="unavailable" if known_miss_distance_km is not None else "invalid",
        tca=ScientificField(
            status="unavailable" if known_miss_distance_km is not None else "invalid",
            reason_code=reason_code,
        ),
        miss_distance=ScientificField(
            status="available" if known_miss_distance_km is not None else "invalid",
            value=known_miss_distance_km,
            units="km" if known_miss_distance_km is not None else None,
            method=METHOD if known_miss_distance_km is not None else None,
            method_version=METHOD_VERSION if known_miss_distance_km is not None else None,
            reason_code=None if known_miss_distance_km is not None else reason_code,
        ),
        relative_position_at_tca=ScientificField(reason_code=reason_code),
        relative_velocity_at_tca=ScientificField(reason_code=reason_code),
        relative_speed_at_tca=ScientificField(reason_code=reason_code),
        reason_codes=[reason_code],
    )
    collision_probability = calculate_foster_2d(
        event_id=event_id,
        object_1_id=primary.id,
        object_2_id=secondary.id,
        tca_utc=None,
        tca_status=physics.tca_status,
    )
    ml_started = time.perf_counter()
    ml_result = predict_from_physics(physics)
    if stage_timings is not None:
        stage_timings["ml_inference_seconds"] += time.perf_counter() - ml_started
    if perf_counts is not None:
        perf_counts["ml_inference_calls"] += 1
    anomaly_started = time.perf_counter()
    anomaly_result = predict_orbital_anomaly(physics)
    if stage_timings is not None:
        stage_timings["orbital_anomaly_assessment_seconds"] += time.perf_counter() - anomaly_started
    if perf_counts is not None:
        perf_counts["orbital_anomaly_assessments"] += 1
        perf_counts["orbital_anomaly_predictions_produced"] += anomaly_result.status == "available"
    comparison_result = compare_ml_and_physics(ml_result, collision_probability)
    return ConjunctionAssessmentEvent(
        id=event_id,
        primary=_object_summary(primary),
        secondary=_object_summary(secondary),
        obj_a=_object_summary(primary),
        obj_b=_object_summary(secondary),
        pair_type=_pair_type(primary, secondary),
        provenance=provenance,
        physics_result=physics,
        collision_probability=collision_probability,
        ml_result=ml_result,
        anomaly_result=anomaly_result,
        comparison_result=comparison_result,
        review_priority=classify_review_priority(
            physics, ml_status=ml_result.status, pc_status=collision_probability.status,
        ),
    )


def _pair_provenance(
    primary_track: _Track,
    secondary_track: _Track,
    epoch: datetime | None,
    status: str,
    sgp4_version: str,
) -> Provenance:
    primary, secondary = primary_track.obj.provenance, secondary_track.obj.provenance
    pair_hash = _pair_input_hash(primary_track, secondary_track)
    input_types = {primary.source_type, secondary.source_type}
    source_type = "synthetic" if "synthetic" in input_types else "derived"
    return Provenance(
        source=f"paired TLE inputs: {primary.source}; {secondary.source}",
        source_type=source_type,  # type: ignore[arg-type]
        source_timestamp=max(filter(None, (primary.source_timestamp, secondary.source_timestamp)), default=None),
        propagation_epoch=_iso(epoch) if epoch else None,
        reference_frame="TEME",
        units={"position": "km", "velocity": "km/s", "miss_distance": "km", "relative_speed": "km/s"},
        input_hash=pair_hash,
        source_record={
            "primary": primary.source_record,
            "secondary": secondary.source_record,
        },
        propagator="python-sgp4 SGP4/SDP4",
        propagator_version=sgp4_version,
        propagator_configuration={
            "gravity_model": "WGS72",
            "frame_transform": "none; both objects propagated in TEME",
            "inputs": [
                {"object_id": primary_track.obj.id, "source_type": primary.source_type, "element_epoch": primary.element_epoch, "input_hash": primary.input_hash},
                {"object_id": secondary_track.obj.id, "source_type": secondary.source_type, "element_epoch": secondary.element_epoch, "input_hash": secondary.input_hash},
            ],
        },
        method=METHOD,
        method_version=METHOD_VERSION,
        validity_status=status,  # type: ignore[arg-type]
        is_synthetic=primary.is_synthetic or secondary.is_synthetic,
        is_fallback=primary.is_fallback or secondary.is_fallback,
    )


def _state_payload(track: _Track, epoch: datetime, state: StateVector) -> dict:
    source = track.obj.provenance.model_copy(deep=True)
    source.propagation_epoch = _iso(epoch)
    source.reference_frame = "TEME"
    source.units = {"position": "km", "velocity": "km/s"}
    source.validity_status = "valid"
    return {
        "object_id": track.obj.id,
        "epoch": _iso(epoch),
        "position_km": list(state.position_km),
        "velocity_km_s": list(state.velocity_km_s),
        "frame": "TEME",
        "provenance": source.model_dump(mode="json"),
    }


def _object_summary(obj: SpaceObject) -> ObjectSummary:
    return ObjectSummary(
        id=obj.id,
        name=obj.name,
        category=obj.category,
        object_type=obj.object_type,
        source_classification=obj.source_classification,
        classification_source=obj.classification_source,
        band=obj.band,
        orbit_type=obj.orbit_type,
        altitude_km=obj.altitude_km,
        inclination_deg=obj.inclination_deg,
        velocity_kms=obj.velocity_kms,
        heuristic_risk_score=obj.heuristic_risk_score,
        heuristic_forecast_score=obj.heuristic_forecast_score,
        provenance=obj.provenance.model_copy(deep=True),
        heuristic_score_provenance=obj.heuristic_score_provenance.model_copy(deep=True),
    )


def _pair_type(primary: SpaceObject, secondary: SpaceObject) -> str:
    return pair_type_for(primary.object_type, secondary.object_type)


def _pair_input_hash(primary_track: _Track, secondary_track: _Track) -> str:
    payload = "|".join(
        (
            "ORION-TRAJECTORY-EVENT-V1",
            f"{primary_track.obj.id}:{primary_track.record.input_hash}",
            f"{secondary_track.obj.id}:{secondary_track.record.input_hash}",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event_id(primary_track: _Track, secondary_track: _Track, identity_time: datetime | str) -> str:
    # Canonical UTC ISO time preserves Python datetime's microsecond precision
    # and avoids using a binary float's string representation as identity.
    stable_time_key = identity_time if isinstance(identity_time, str) else _iso(identity_time)
    identity = f"{_pair_input_hash(primary_track, secondary_track)}|{stable_time_key}|{METHOD_VERSION}"
    return f"CA-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20].upper()}"


def _julian_parts(epoch: datetime) -> tuple[float, float]:
    utc = epoch.astimezone(timezone.utc)
    return jday(
        utc.year,
        utc.month,
        utc.day,
        utc.hour,
        utc.minute,
        utc.second + utc.microsecond / 1_000_000.0,
    )


def _iso(epoch: datetime | None) -> str | None:
    if epoch is None:
        return None
    return epoch.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _validate_state(state: StateVector) -> None:
    values = (*state.position_km, *state.velocity_km_s)
    if len(state.position_km) != 3 or len(state.velocity_km_s) != 3 or not all(math.isfinite(value) for value in values):
        raise _PropagationFailure("non_finite_state")


def _solution_from_evaluation(
    status: str,
    offset: float,
    evaluation: tuple[float, StateVector, StateVector, tuple[float, float, float], tuple[float, float, float]],
    iterations: int,
    final_width: float,
    neighbor_check: bool,
) -> ClosestApproachSolution:
    distance, primary, secondary, relative_position, relative_velocity = evaluation
    return ClosestApproachSolution(
        status=status,
        offset_seconds=offset,
        miss_distance_km=distance,
        relative_position_km=relative_position,
        relative_velocity_km_s=relative_velocity,
        primary_state=primary,
        secondary_state=secondary,
        iterations=iterations,
        final_bracket_width_seconds=final_width,
        neighbor_check_passed=neighbor_check,
    )


def _sampled_minimum_indices(distances: list[float]) -> list[int]:
    """Return bounded-grid local-minimum indices, merging sampled plateaus."""
    candidates = []
    for index, value in enumerate(distances):
        before = distances[index - 1] if index > 0 else math.inf
        after = distances[index + 1] if index + 1 < len(distances) else math.inf
        if value <= before and value <= after:
            candidates.append(index)
    if not candidates:
        return [min(range(len(distances)), key=distances.__getitem__)]
    groups: list[list[int]] = [[candidates[0]]]
    for index in candidates[1:]:
        if index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return [min(group, key=lambda index: (distances[index], index)) for group in groups]


def _refine_unimodal_basin(
    evaluate: Callable,
    left: float,
    right: float,
    *,
    golden_ratio: float,
    horizon_start: float,
    horizon_end: float,
    time_tolerance: float,
    neighbor_check_seconds: float,
    max_iterations: int,
) -> ClosestApproachSolution:
    """Golden-section refine one basin isolated by the bounded probes."""
    if left == right:
        return ClosestApproachSolution(status="invalid", reason_code="invalid_refinement_basin")
    initial_width = right - left
    x1 = right - golden_ratio * (right - left)
    x2 = left + golden_ratio * (right - left)
    f1, f2 = evaluate(x1)[0], evaluate(x2)[0]
    iterations = 0
    while right - left > time_tolerance and iterations < max_iterations:
        if f1 <= f2:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden_ratio * (right - left)
            f1 = evaluate(x1)[0]
        else:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden_ratio * (right - left)
            f2 = evaluate(x2)[0]
        iterations += 1
    if right - left > time_tolerance:
        return ClosestApproachSolution(
            status="invalid",
            iterations=iterations,
            final_bracket_width_seconds=right - left,
            reason_code="tca_refinement_did_not_converge",
        )
    trial_offsets = {left, right, x1, x2, (left + right) / 2.0}
    evaluated = [(offset, evaluate(offset)) for offset in sorted(trial_offsets)]
    tca_offset, best = min(evaluated, key=lambda item: (item[1][0], item[0]))
    check_offset = min(
        neighbor_check_seconds,
        max(time_tolerance * 2, initial_width / 100.0),
    )
    neighbor_values = []
    for neighbor in (tca_offset - check_offset, tca_offset + check_offset):
        if horizon_start <= neighbor <= horizon_end:
            neighbor_values.append(evaluate(neighbor)[0])
    neighbor_ok = all(best[0] <= value + 1e-7 for value in neighbor_values)
    if not neighbor_ok:
        return ClosestApproachSolution(
            status="invalid",
            iterations=iterations,
            final_bracket_width_seconds=right - left,
            neighbor_check_passed=False,
            reason_code="tca_neighbor_verification_failed",
        )
    boundary = (
        abs(tca_offset - horizon_start) <= time_tolerance
        or abs(tca_offset - horizon_end) <= time_tolerance
    )
    return _solution_from_evaluation(
        "boundary" if boundary else "valid",
        tca_offset,
        best,
        iterations,
        right - left,
        neighbor_ok,
    )


def _pair_error_reason(codes: list[int]) -> str:
    if -1 in codes:
        return "non_finite_state"
    if -2 in codes:
        return "relative_speed_bound_exceeded"
    code = next((value for value in codes if value > 0), None)
    if code is not None:
        description = SGP4_ERRORS.get(code, "unknown SGP4 error")
        return f"sgp4_error_{code}:{description}"
    return "pair_propagation_incomplete"


def _sgp4_version() -> str:
    try:
        return package_version("sgp4")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"
