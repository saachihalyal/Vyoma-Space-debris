export const COLLISION_INVALID_ASSESSMENT_LABEL = "Invalid physics assessments in full screening result (not qualifying close approaches)";

export const PHYSICS_REASON_EXPLANATIONS = Object.freeze({
  identical_propagation_parameters_for_distinct_catalog_ids: "Different catalog IDs have identical propagation parameters, so the objects cannot be distinguished reliably.",
  duplicate_tle_state_for_distinct_catalog_ids: "Different catalog IDs contain duplicate TLE states; this pair is ambiguous.",
  degenerate_zero_relative_state: "The relative position or velocity is degenerate, so a unique close approach cannot be calculated.",
  no_local_minimum_in_interval: "No local minimum in separation was found inside the screening window.",
  tca_refinement_basin_limit_exceeded: "The TCA refinement reached its configured search limit before finding a reliable minimum.",
  non_unique_tca_flat_distance: "Separation is too flat around the minimum to identify one unique TCA.",
  non_unique_tca_multiple_minima: "Multiple candidate minima prevent selecting one unique TCA.",
  non_finite_state: "The propagated position or velocity contains an invalid numeric value.",
});

export function explainPhysicsReason(code) {
  const known = PHYSICS_REASON_EXPLANATIONS[code];
  if (known) return known;
  if (/^SGP4/i.test(String(code))) return "Orbit propagation failed for this object under the reported SGP4 conditions.";
  return "The trajectory assessment failed a validation or numerical check; inspect the reason code and source record.";
}

export const COLLISION_PAIR_FILTERS = Object.freeze([
  { value: "all", label: "All pair types" },
  { value: "SATELLITE vs SATELLITE", label: "Active satellite vs active satellite" },
  { value: "SATELLITE vs DEBRIS", label: "Active satellite vs debris" },
  { value: "DEBRIS vs DEBRIS", label: "Debris vs debris" },
  { value: "SATELLITE vs ROCKET BODY", label: "Active satellite vs rocket body" },
  { value: "DEBRIS vs ROCKET BODY", label: "Debris vs rocket body" },
  { value: "ROCKET BODY vs ROCKET BODY", label: "Rocket body vs rocket body" },
  { value: "SATELLITE vs UNKNOWN", label: "Active satellite vs unknown" },
  { value: "DEBRIS vs UNKNOWN", label: "Debris vs unknown" },
  { value: "ROCKET BODY vs UNKNOWN", label: "Rocket body vs unknown" },
  { value: "UNKNOWN vs UNKNOWN", label: "Unknown vs unknown" },
]);

// Keep the event rows and their displayed count in step; screening can return
// more than 100 events when its configured object limit permits it.
export function getCollisionEventsForDisplay(events) {
  return Array.isArray(events) ? events : [];
}

export function filterCollisionEvents(events, {
  physicalOnly = true,
  pairFilter = "all",
  statusFilter = "all",
  priorityFilter = "all",
  quantityFilter = "all",
  minimumMiss = "",
  maximumMiss = "",
  fromTca = "",
  toTca = "",
} = {}) {
  return getCollisionEventsForDisplay(events).filter((item) => {
    const physics = item?.physics_result || {};
    const tca = physics.tca?.status === "available" ? Date.parse(physics.tca.value) : NaN;
    const miss = physics.miss_distance?.status === "available" ? Number(physics.miss_distance.value) : NaN;
    if (physicalOnly && item?.result_kind !== "physics_assessment") return false;
    if (!matchesCollisionPairFilter(item, pairFilter)) return false;
    // “All statuses” must actually include invalid assessments. They remain
    // visible for diagnosis and are excluded from ranking by rankCollisionEvents.
    if (statusFilter !== "all" && (physics.status || "unavailable") !== statusFilter) return false;
    if (!matchesReviewPriorityFilter(item, priorityFilter)) return false;
    if (quantityFilter === "geometry" && !(physics.tca?.status === "available" && physics.miss_distance?.status === "available")) return false;
    if (quantityFilter === "relative_velocity" && physics.relative_velocity_at_tca?.status !== "available") return false;
    if (quantityFilter === "pc" && item?.collision_probability?.status !== "available") return false;
    if (minimumMiss !== "" && (!Number.isFinite(miss) || miss < Number(minimumMiss))) return false;
    if (maximumMiss !== "" && (!Number.isFinite(miss) || miss > Number(maximumMiss))) return false;
    if (fromTca && (!Number.isFinite(tca) || tca < Date.parse(`${fromTca}T00:00:00Z`))) return false;
    if (toTca && (!Number.isFinite(tca) || tca >= Date.parse(`${toTca}T00:00:00Z`) + 86400000)) return false;
    return true;
  });
}

function validPc(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

export function collisionEventPriority(event) {
  const pc = event?.collision_probability;
  if (pc?.status === "available" && pc?.event_id === event?.id && validPc(pc.pc) && pc.pc > 0) {
    return { tier: 0, value: pc.pc, label: "Computed Pc", basis: `${pc.method || "Foster 2D"} value; higher Pc ranks earlier.` };
  }
  const sourcePc = event?.source_reported_pc ?? pc?.source_reported_pc;
  const sourceEventId = event?.source_reported_event_id ?? pc?.source_reported_event_id;
  if (sourceEventId === event?.id && validPc(sourcePc)) {
    return { tier: 1, value: sourcePc, label: "Source-reported Pc", basis: "Source-reported value; displayed separately from Vyoma-computed Pc." };
  }
  const geometry = event?.review_priority;
  const geometryOrder = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
  if (geometry?.status === "classified" && Object.hasOwn(geometryOrder, geometry.category)) {
    const missFraction = geometry.criteria?.miss_distance_fraction;
    return {
      tier: 3,
      value: geometryOrder[geometry.category],
      tieBreak: Number.isFinite(missFraction) && missFraction >= 0 ? missFraction : Number.POSITIVE_INFINITY,
      label: "Geometry review priority",
      basis: geometry.explanation || "Vyoma geometry-only review priority; not a collision-risk classification.",
    };
  }
  return { tier: 4, value: Number.POSITIVE_INFINITY, label: "Unclassified", basis: geometry?.explanation || "Required evidence for priority is unavailable." };
}

export function rankCollisionEvents(events) {
  return getCollisionEventsForDisplay(events)
    .filter((event) => !(event?.result_kind === "physics_assessment" && event?.physics_result?.status === "invalid"))
    .slice().sort((left, right) => {
    const a = collisionEventPriority(left);
    const b = collisionEventPriority(right);
    if (a.tier !== b.tier) return a.tier - b.tier;
    if (a.value !== b.value) return a.tier <= 1 ? b.value - a.value : a.value - b.value;
    if (a.tier === 3 && a.tieBreak !== b.tieBreak) return a.tieBreak - b.tieBreak;
    return String(left?.id || "").localeCompare(String(right?.id || ""));
    });
}

// This is an AI feature-unusualness order, never a collision-risk order.
// Ranking is relative to the same returned screening result and requires
// event-bound anomaly provenance plus a finite score.
export function rankOrbitalAnomalyEvents(events) {
  const eligible = getCollisionEventsForDisplay(events).filter((event) => (
    event?.result_kind === "physics_assessment"
    && event?.physics_result?.status === "valid"
    && event?.anomaly_result?.status === "available"
    && event?.anomaly_result?.provenance?.source_physics_event_id === event?.id
    && Number.isFinite(event?.anomaly_result?.anomaly_score)
    && event.anomaly_result.anomaly_score >= 0
    && event.anomaly_result.anomaly_score <= 1
  ));
  eligible.sort((left, right) => (
    right.anomaly_result.anomaly_score - left.anomaly_result.anomaly_score
    || String(left.id).localeCompare(String(right.id))
  ));
  return new Map(eligible.map((event, index) => [event.id, {
    rank: index + 1,
    count: eligible.length,
    score: event.anomaly_result.anomaly_score,
    model_name: event.anomaly_result.model_name,
    model_version: event.anomaly_result.model_version,
  }]));
}

export function searchAndSortCollisionEvents(events, query = "", sort = "research_pc") {
  const needle = String(query || "").trim().toLocaleLowerCase();
  const filtered = getCollisionEventsForDisplay(events).filter((event) => {
    if (!needle) return true;
    const fields = [
      event?.id, event?.primary?.id, event?.primary?.name, event?.primary?.object_type,
      event?.secondary?.id, event?.secondary?.name, event?.secondary?.object_type,
      event?.pair_type,
    ];
    return fields.some((value) => String(value || "").toLocaleLowerCase().includes(needle));
  });
  const tca = (event) => {
    const value = event?.physics_result?.tca;
    if (value?.status !== "available" || typeof value.value !== "string") return NaN;
    return Date.parse(value.value);
  };
  const miss = (event) => {
    const value = event?.physics_result?.miss_distance;
    if (value?.status !== "available" || value.value == null || typeof value.value === "boolean") return NaN;
    const numericValue = Number(value.value);
    return Number.isFinite(numericValue) ? numericValue : NaN;
  };
  const exactLogPc = (event) => {
    const assessment = event?.automatic_research_pc_assessment;
    return event?.physics_result?.status === "valid" && event?.physics_result?.tca_status === "valid"
      && Number.isFinite(assessment?.log10_pc) ? assessment.log10_pc : NaN;
  };
  const missSigma = (event) => Number.isFinite(event?.automatic_research_pc_assessment?.miss_sigma_ratio)
    ? event.automatic_research_pc_assessment.miss_sigma_ratio : Number.POSITIVE_INFINITY;
  return filtered.sort((left, right) => {
    if (sort === "research_pc") {
      const a = exactLogPc(left);
      const b = exactLogPc(right);
      const aValid = Number.isFinite(a);
      const bValid = Number.isFinite(b);
      if (aValid !== bValid) return aValid ? -1 : 1;
      if (aValid && a !== b) return b - a;
      if (aValid && missSigma(left) !== missSigma(right)) return missSigma(left) - missSigma(right);
      const leftBoundary = left?.physics_result?.tca_status === "boundary";
      const rightBoundary = right?.physics_result?.tca_status === "boundary";
      if (leftBoundary !== rightBoundary) return leftBoundary ? 1 : -1;
      return String(left?.id || "").localeCompare(String(right?.id || ""));
    }
    if (sort === "evidence_priority") {
      const a = collisionEventPriority(left);
      const b = collisionEventPriority(right);
      if (a.tier !== b.tier) return a.tier - b.tier;
      if (a.value !== b.value) return a.tier <= 1 ? b.value - a.value : a.value - b.value;
      if (a.tier === 3 && a.tieBreak !== b.tieBreak) return a.tieBreak - b.tieBreak;
      return String(left?.id || "").localeCompare(String(right?.id || ""));
    }
    const a = sort === "miss_nearest" ? miss(left) : tca(left);
    const b = sort === "miss_nearest" ? miss(right) : tca(right);
    const aValid = Number.isFinite(a);
    const bValid = Number.isFinite(b);
    if (aValid !== bValid) return aValid ? -1 : 1;
    if (aValid && a !== b) return sort === "miss_nearest" ? a - b : a - b;
    return String(left?.id || "").localeCompare(String(right?.id || ""));
  });
}

export function screeningAssessmentCounts(screening = {}, returnedRecordCount = 0, returnedInvalidCount = 0) {
  const total = Number.isInteger(screening.assessment_record_count)
    ? screening.assessment_record_count
    : returnedRecordCount;
  const returned = Number.isInteger(screening.returned_assessment_record_count)
    ? screening.returned_assessment_record_count
    : returnedRecordCount;
  const invalidTotal = Number.isInteger(screening.invalid_assessment_count)
    ? screening.invalid_assessment_count
    : null;
  return {
    total,
    returned,
    invalidTotal,
    returnedInvalid: returnedInvalidCount,
    truncated: screening.assessment_records_truncated === true
      || screening.assessment_response_limit_reached === true
      || returned < total,
  };
}
import { getPairType } from "./identityModel.js";


export function matchesCollisionPairFilter(event, pairFilter) {
  if (pairFilter === "all") return true;
  const pairType = event?.pair_type || getPairType(event?.primary, event?.secondary);
  return pairType === pairFilter;
}

export function matchesReviewPriorityFilter(event, priorityFilter) {
  if (priorityFilter === "all") return true;
  if (event?.result_kind !== "physics_assessment") return false;
  return (event.review_priority?.category || "UNCLASSIFIED") === priorityFilter;
}
