import { getObjectTypeCode } from "./objectClassification.js";

/**
 * identityModel.js
 *
 * CANONICAL OBJECT IDENTITY MODEL for the ORION SSA platform.
 *
 * THIS IS THE SINGLE AUTHORITATIVE REPRESENTATION for every space object
 * throughout the application. Every component MUST use this model.
 *
 * No component shall independently reconstruct:
 * - object name
 * - object type / classification
 * - object ID
 * - orbital data
 *
 * Identity Integrity Rule:
 *   primary.id → primary.name
 *   primary.id → primary.objectType
 *   primary.id → primary.orbitalData
 *
 *   secondary.id → secondary.name
 *   secondary.id → secondary.objectType
 *   secondary.id → secondary.orbitalData
 *
 * Every event must have:
 *   primary.id !== secondary.id
 *
 * Never use array index as identity.
 * Never use display name as identity.
 * Never let a fallback lookup silently substitute another object.
 * If an ID cannot be resolved, report the error instead of using another object.
 */

// ─── Object Type Constants ────────────────────────────────────────────────────

export const OBJECT_TYPE = Object.freeze({
  ACTIVE_SATELLITE: "ACTIVE_SATELLITE",
  SPACE_DEBRIS: "SPACE_DEBRIS",
  ROCKET_BODY: "ROCKET_BODY",
  SPACE_STATION: "SPACE_STATION",
  FRAGMENT: "FRAGMENT",
  UNKNOWN: "UNKNOWN",
});

export const OBJECT_TYPE_DISPLAY = Object.freeze({
  [OBJECT_TYPE.ACTIVE_SATELLITE]: "ACTIVE SATELLITE",
  [OBJECT_TYPE.SPACE_DEBRIS]: "SPACE DEBRIS",
  [OBJECT_TYPE.ROCKET_BODY]: "ROCKET BODY",
  [OBJECT_TYPE.SPACE_STATION]: "STATION MODULE",
  [OBJECT_TYPE.FRAGMENT]: "FRAGMENT",
  [OBJECT_TYPE.UNKNOWN]: "UNKNOWN / OTHER",
});

// ─── Pair Type Constants ──────────────────────────────────────────────────────

export const PAIR_TYPE = Object.freeze({
  ACTIVE_DEBRIS: "SATELLITE vs DEBRIS",
  ACTIVE_ROCKET: "SATELLITE vs ROCKET BODY",
  ACTIVE_ACTIVE: "SATELLITE vs SATELLITE",
  DEBRIS_DEBRIS: "DEBRIS vs DEBRIS",
  ROCKET_DEBRIS: "DEBRIS vs ROCKET BODY",
  ROCKET_ROCKET: "ROCKET BODY vs ROCKET BODY",
  UNKNOWN: "UNKNOWN PAIR TYPE",
});

// ─── Object Type Resolution ───────────────────────────────────────────────────

/**
 * Resolve the canonical object type from catalog metadata.
 *
 * Priority:
 * 1. `object_type` field (if present and non-empty)
 * 2. `category` field mapped through authoritative mapping
 * 3. Name-based heuristics (only as last resort)
 *
 * @param {Object} raw — Raw catalog entry with any available fields
 * @returns {string} One of OBJECT_TYPE.*
 */
export function resolveObjectType(raw) {
  return getObjectTypeCode(raw);
}

/**
 * Get the human-readable display label for an object type.
 */
export function getDisplayType(objectType) {
  return OBJECT_TYPE_DISPLAY[objectType] || OBJECT_TYPE_DISPLAY[OBJECT_TYPE.UNKNOWN];
}

/**
 * Get the display label from a raw object.
 */
export function resolveDisplayType(raw) {
  const type = resolveObjectType(raw);
  return getDisplayType(type);
}

/**
 * Get the CSS-safe type key for a raw object.
 */
export function resolveTypeKey(raw) {
  const type = resolveObjectType(raw);
  return type.toLowerCase().replace(/_/g, "-");
}

// ─── Pair Type Resolution ─────────────────────────────────────────────────────

/**
 * Determine the pair type for a collision event.
 */
export function getPairType(primary, secondary) {
  const pType = resolveObjectType(primary);
  const sType = resolveObjectType(secondary);
  const labels = {
    [OBJECT_TYPE.ACTIVE_SATELLITE]: "SATELLITE",
    [OBJECT_TYPE.SPACE_DEBRIS]: "DEBRIS",
    [OBJECT_TYPE.ROCKET_BODY]: "ROCKET BODY",
    [OBJECT_TYPE.SPACE_STATION]: "STATION",
    [OBJECT_TYPE.FRAGMENT]: "DEBRIS",
    [OBJECT_TYPE.UNKNOWN]: "UNKNOWN",
  };
  const order = { SATELLITE: 0, STATION: 1, DEBRIS: 2, "ROCKET BODY": 3, UNKNOWN: 4 };
  const first = labels[pType] || "UNKNOWN";
  const second = labels[sType] || "UNKNOWN";
  return [first, second].sort((a, b) => order[a] - order[b]).join(" vs ");
}

/**
 * Check whether a pair is satellite-vs-debris (the primary use case).
 */
export function isSatelliteDebrisPair(primary, secondary) {
  const pairType = getPairType(primary, secondary);
  return pairType === PAIR_TYPE.ACTIVE_DEBRIS;
}

// ─── Identity Resolution ──────────────────────────────────────────────────────

/**
 * Build a canonical identity object from raw catalog data.
 *
 * This is the ONE function that produces the authoritative identity.
 *
 * @param {Object} raw — Raw object data from catalog, API, or fallback
 * @returns {CanonicalObject} — Normalized identity object
 */
export function buildCanonicalIdentity(raw) {
  if (!raw) {
    return createUnresolvedIdentity(null, "No data provided");
  }

  const id = raw.id || raw.norad_id || "";
  const name = raw.name || raw.object_name || "UNKNOWN";

  // Resolve type from authoritative source
  const objectType = resolveObjectType(raw);
  const displayType = getDisplayType(objectType);

  // Determine catalog classification for display
  const catalogClassification = raw.source_classification || raw.class || raw.object_type || raw.category || "UNKNOWN / OTHER";

  // Collect orbital data
  const orbitalData = {
    band: raw.band || "UNKNOWN",
    orbit_type: raw.orbit_type || raw.orbitType || "UNKNOWN",
    altitude_km: raw.altitude_km || raw.altitude || 0,
    inclination_deg: raw.inclination_deg || raw.inclination || 0,
    velocity_kms: raw.velocity_kms || raw.velocity || 0,
    heuristic_risk_score: raw.heuristic_risk_score ?? null,
    heuristic_debris_pressure_score: raw.heuristic_debris_pressure_score ?? null,
    heuristic_forecast_score: raw.heuristic_forecast_score ?? null,
  };

  // Validation
  if (!id) {
    console.warn(`[IdentityModel] Object has no ID: name="${name}"`);
  }

  return Object.freeze({
    id,
    name,
    objectType,
    displayType,
    catalogClassification,
    orbitalData,
  });
}

/**
 * Create an unresolved/unknown identity object.
 * Used when an object cannot be found by ID.
 * This preserves the ID and shows it rather than silently substituting.
 */
export function createUnresolvedIdentity(id, reason) {
  if (reason) {
    console.error(`[IdentityModel] UNRESOLVED OBJECT: ID="${id}", reason="${reason}"`);
  }
  return Object.freeze({
    id: id || "UNRESOLVED",
    name: id ? `UNRESOLVED (${id})` : "UNKNOWN OBJECT",
    objectType: OBJECT_TYPE.UNKNOWN,
    displayType: getDisplayType(OBJECT_TYPE.UNKNOWN),
    catalogClassification: "unresolved",
    orbitalData: {
      band: "UNKNOWN",
      orbit_type: "UNKNOWN",
      altitude_km: 0,
      inclination_deg: 0,
      velocity_kms: 0,
      heuristic_risk_score: null,
      heuristic_debris_pressure_score: null,
      heuristic_forecast_score: null,
    },
    unresolved: true,
    unresolvedReason: reason || "Object not found in catalog",
  });
}

/**
 * Resolve a canonical object identity from a catalog by ID.
 * This is the SAFE lookup — it returns an unresolved identity if not found,
 * rather than silently substituting another object.
 *
 * @param {string} id — The ID to look up
 * @param {Array} catalog — Array of catalog objects
 * @param {Object} options — Options
 * @param {boolean} options.suppressErrors — Don't log errors for unresolved lookups
 * @returns {CanonicalObject} — Resolved or unresolved identity
 */
export function resolveById(id, catalog, options = {}) {
  if (!id) {
    return createUnresolvedIdentity(null, "No ID provided");
  }

  if (!catalog || !Array.isArray(catalog) || catalog.length === 0) {
    return createUnresolvedIdentity(id, "Catalog is empty or not available");
  }

  // Exact ID match — this is the ONLY allowed lookup method
  const found = catalog.find((obj) => {
    const candidateId = obj.id || obj.norad_id || "";
    return String(candidateId) === String(id);
  });

  if (found) {
    return buildCanonicalIdentity(found);
  }

  // NOT FOUND — return unresolved identity, do NOT substitute
  if (!options.suppressErrors) {
    console.warn(`[IdentityModel] Object ID "${id}" not found in catalog. Returning unresolved identity.`);
  }
  return createUnresolvedIdentity(id, `ID "${id}" not found in catalog`);
}

/**
 * Validate a collision event's identity integrity.
 * Returns null if valid, or an error message if invalid.
 */
export function validateEventIdentities(event, catalog) {
  if (!event) return "Event is null";

  const primary = event.primary || event.obj_a;
  const secondary = event.secondary || event.obj_b;

  if (!primary) return "Event has no primary object";
  if (!secondary) return "Event has no secondary object";

  const pId = primary.id || "";
  const sId = secondary.id || "";

  // 1. Both must have IDs
  if (!pId) return "Primary object has no ID";
  if (!sId) return "Secondary object has no ID";

  // 2. IDs must be different
  if (String(pId) === String(sId)) {
    return `SELF-PAIR: primary.id === secondary.id (both are "${pId}")`;
  }

  // 3. Names must not be accidentally identical
  if (primary.name && secondary.name && primary.name === secondary.name && pId !== sId) {
    console.warn(`[IdentityModel] Warning: Different IDs (${pId}, ${sId}) but same name "${primary.name}". This may indicate missing identity data.`);
  }

  // 4. Resolve both against catalog
  const pIdentity = resolveById(pId, catalog, { suppressErrors: true });
  const sIdentity = resolveById(sId, catalog, { suppressErrors: true });

  // 5. Validate type consistency (if catalog available)
  if (!pIdentity.unresolved && !sIdentity.unresolved) {
    if (pIdentity.objectType === OBJECT_TYPE.UNKNOWN) {
      console.warn(`[IdentityModel] Primary object "${pId}" has unresolved type`);
    }
    if (sIdentity.objectType === OBJECT_TYPE.UNKNOWN) {
      console.warn(`[IdentityModel] Secondary object "${sId}" has unresolved type`);
    }
  }

  return null; // valid
}

/**
 * Get a display string for the pair type classification.
 */
export function getPairTypeLabel(primary, secondary) {
  const pairType = getPairType(primary, secondary);
  return pairType;
}

/**
 * Format an object's identity for compact display.
 */
export function formatObjectIdentity(obj) {
  const identity = obj.objectType ? obj : buildCanonicalIdentity(obj);
  return `${identity.displayType}\n${identity.name} · ID: ${identity.id}`;
}

// ─── Operational Priority ─────────────────────────────────────────────────────

/**
 * Pair-type priority multipliers for operational ranking.
 *
 * These deterministic pair-type multipliers only order heuristic review items.
 *
 * Priority tiers (higher = more operationally important):
 *   1.0+ = ACTIVE SATELLITE ↔ DEBRIS (primary use case)
 *   0.8  = ACTIVE SATELLITE ↔ ROCKET_BODY
 *   0.6  = ACTIVE SATELLITE ↔ ACTIVE_SATELLITE
 *   0.4  = DEBRIS ↔ ROCKET_BODY
 *   0.2  = DEBRIS ↔ DEBRIS
 *   0.1  = ROCKET_BODY ↔ ROCKET_BODY
 *   0.0  = UNKNOWN
 */
export const PAIR_PRIORITY_MULTIPLIER = Object.freeze({
  [PAIR_TYPE.ACTIVE_DEBRIS]: 1.0,
  [PAIR_TYPE.ACTIVE_ROCKET]: 0.8,
  [PAIR_TYPE.ACTIVE_ACTIVE]: 0.6,
  [PAIR_TYPE.ROCKET_DEBRIS]: 0.4,
  [PAIR_TYPE.DEBRIS_DEBRIS]: 0.2,
  [PAIR_TYPE.ROCKET_ROCKET]: 0.1,
  [PAIR_TYPE.UNKNOWN]: 0.0,
});

/**
 * Category labels for grouping events in the UI.
 */
export const PAIR_CATEGORY_LABEL = Object.freeze({
  [PAIR_TYPE.ACTIVE_DEBRIS]: "Primary Operational Risks",
  [PAIR_TYPE.ACTIVE_ROCKET]: "Secondary Operational Risks",
  [PAIR_TYPE.ACTIVE_ACTIVE]: "Other Conjunctions",
  [PAIR_TYPE.ROCKET_DEBRIS]: "Other Conjunctions",
  [PAIR_TYPE.DEBRIS_DEBRIS]: "Other Conjunctions",
  [PAIR_TYPE.ROCKET_ROCKET]: "Other Conjunctions",
  [PAIR_TYPE.UNKNOWN]: "Unclassified",
});

/**
 * Compute a deterministic heuristic score for screening-proxy review order.
 * It does not use Pc, encounter-relative velocity, miss distance, or ML output.
 *
 * @param {Object} event - Collision event with primary, secondary, etc.
 * @returns {number} Heuristic review score (0-100)
 */
export function computeOperationalPriority(event) {
  if (!event) return 0;

  const primary = event.primary || event.obj_a;
  const secondary = event.secondary || event.obj_b;
  if (!primary || !secondary) return 0;

  // Determine the pair type
  const pairType = getPairType(primary, secondary);
  const typeMultiplier = PAIR_PRIORITY_MULTIPLIER[pairType] || 0;

  // If pair type is unknown, use minimal priority
  if (typeMultiplier === 0) return 0;

  const riskScore = Number(event.risk_score);
  if (!Number.isFinite(riskScore)) return 0;
  const boundedScore = Math.max(0, Math.min(1, riskScore));
  return Math.round(Math.max(0, Math.min(100, (0.8 * boundedScore + 0.2 * typeMultiplier) * 100)));
}

/**
 * Get the operational category label for an event.
 */
export function getEventCategoryLabel(event) {
  if (!event) return "Unclassified";
  const primary = event.primary || event.obj_a;
  const secondary = event.secondary || event.obj_b;
  if (!primary || !secondary) return "Unclassified";
  const pairType = getPairType(primary, secondary);
  return PAIR_CATEGORY_LABEL[pairType] || "Unclassified";
}

/**
 * Check if an event belongs to the primary operational risk category.
 */
export function isPrimaryOperationalRisk(event) {
  if (!event) return false;
  const primary = event.primary || event.obj_a;
  const secondary = event.secondary || event.obj_b;
  if (!primary || !secondary) return false;
  return isSatelliteDebrisPair(primary, secondary);
}

// ─── Internal Helpers ─────────────────────────────────────────────────────────


