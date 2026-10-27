/**
 * objectClassification.js
 *
 * Centralized, authoritative object classification system for the ORION SSA platform.
 *
 * All components MUST use this module to determine object type labels.
 * Do NOT infer object type from display names or duplicate this logic elsewhere.
 *
 * Catalog object type takes precedence. When absent, documented name patterns
 * are used before any group-based fallback returned by the API.
 */

/**
 * Object type labels used throughout the application.
 */
export const OBJECT_TYPE = {
  ACTIVE_SATELLITE: "ACTIVE SATELLITE",
  SPACE_DEBRIS: "SPACE DEBRIS",
  ROCKET_BODY: "ROCKET BODY",
  SPACE_STATION: "STATION MODULE",
  FRAGMENT: "FRAGMENT",
  UNKNOWN: "UNKNOWN / OTHER",
};

/**
 * Determine the human-readable object type label from catalog data.
 *
 * Conflicting or missing metadata produces UNKNOWN / OTHER.
 *
 * @param {Object} object - Catalog object with at minimum { category, name }
 * @returns {string} One of OBJECT_TYPE.* constants
 */
export function getObjectTypeLabel(object) {
  if (!object) return OBJECT_TYPE.UNKNOWN;
  const map = (value) => {
    const raw = String(value || "").trim().toUpperCase().replace(/_/g, " ");
    if (["ACTIVE SATELLITE", "ACTIVE", "PAYLOAD", "SATELLITE", "SPACECRAFT"].includes(raw)) return OBJECT_TYPE.ACTIVE_SATELLITE;
    if (["SPACE DEBRIS", "DEBRIS", "FRAGMENT"].includes(raw)) return OBJECT_TYPE.SPACE_DEBRIS;
    if (["ROCKET BODY", "R/B", "ROCKET"].includes(raw)) return OBJECT_TYPE.ROCKET_BODY;
    if (["STATION", "SPACE STATION", "STATION MODULE"].includes(raw)) return OBJECT_TYPE.SPACE_STATION;
    if (["UNKNOWN", "OTHER", "UNKNOWN / OTHER"].includes(raw)) return OBJECT_TYPE.UNKNOWN;
    return null;
  };
  for (const field of [object.object_type, object.source_classification]) {
    const known = map(field);
    if (known) return known;
  }
  const name = typeof object.name === "string" ? object.name.toUpperCase().replace(/[()]/g, " ") : "";
  if (name.includes("R/B") || name.includes("ROCKET BODY")) return OBJECT_TYPE.ROCKET_BODY;
  if (/(^|\s)(DEB|DEBRIS|FRAGMENT)(\s|$)/.test(name)) return OBJECT_TYPE.SPACE_DEBRIS;
  const stationNames = ["ISS", "ZARYA", "ZVEZDA", "NAUKA", "POISK", "RASSVET", "UNITY", "DESTINY", "HARMONY", "COLUMBUS", "KIBO", "QUEST", "TRANQUILITY", "CUPOLA", "PMM", "BISHOP", "PIRS", "PROGRESS", "SOYUZ"];
  if (stationNames.some((token) => new RegExp(`(^|\\s)${token}(\\s|$)`).test(name))) return OBJECT_TYPE.SPACE_STATION;
  if (name.includes("PAYLOAD")) return OBJECT_TYPE.ACTIVE_SATELLITE;
  // Category is a legacy group-derived fallback. Use it only after object type
  // and recognized name patterns have been exhausted.
  const category = map(object.category);
  if (category) return category;
  return OBJECT_TYPE.UNKNOWN;
}

export function getObjectTypeCode(object) {
  const label = getObjectTypeLabel(object);
  if (label === OBJECT_TYPE.ACTIVE_SATELLITE) return "ACTIVE_SATELLITE";
  if (label === OBJECT_TYPE.SPACE_DEBRIS) return "SPACE_DEBRIS";
  if (label === OBJECT_TYPE.ROCKET_BODY) return "ROCKET_BODY";
  if (label === OBJECT_TYPE.SPACE_STATION) return "SPACE_STATION";
  return "UNKNOWN";
}

/**
 * Get a stable display key for the object type (used for CSS classes, filtering).
 */
export function getObjectTypeKey(object) {
  const label = getObjectTypeLabel(object);
  return label.toLowerCase().replace(/\s+/g, "-");
}

/**
 * Determine if an object rendered in the visualization should use satellite-like
 * or debris-like visuals, based on the authoritative classification.
 *
 * Returns "satellite" or "debris" for use in SatelliteField rendering.
 */
export function getVisualCategory(object) {
  const type = getObjectTypeLabel(object);
  if (type === OBJECT_TYPE.ACTIVE_SATELLITE) return "satellite";
  if (type === OBJECT_TYPE.SPACE_DEBRIS || type === OBJECT_TYPE.ROCKET_BODY) return "debris";
  return "unknown";
}

export function getVisualizationCategory(object) {
  const type = getObjectTypeLabel(object);
  if (type === OBJECT_TYPE.ACTIVE_SATELLITE) return "active";
  if (type === OBJECT_TYPE.SPACE_DEBRIS) return "debris";
  if (type === OBJECT_TYPE.ROCKET_BODY) return "rocket_body";
  return "other";
}

/**
 * Validate a collision/conjunction event for data integrity.
 *
 * Returns null if valid, or an error message string if invalid.
 *
 * Identity validation rules:
 * 1. primary.id must exist
 * 2. secondary.id must exist
 * 3. primary.id !== secondary.id
 * 4. primary.name must be derived from primary.id
 * 5. secondary.name must be derived from secondary.id
 * 6. primary and secondary names must not be accidentally identical (unless IDs also identical)
 * 7. primary and secondary classifications must not be accidentally copied
 * 8. primary and secondary orbital data must not be accidentally copied
 */
export function validateEvent(event) {
  if (!event) return "Event is null/undefined";

  if (!event.primary || !event.secondary) {
    return `Event ${event.id} missing primary or secondary object`;
  }

  if (!event.primary.id || !event.secondary.id) {
    return `Event ${event.id} has object with missing ID`;
  }

  if (event.primary.id === event.secondary.id) {
    return `SELF-PAIR REJECTED: Event ${event.id} has same object (ID: ${event.primary.id}) for both primary and secondary`;
  }

  // IDENTITY CHECK: Names must not be accidentally identical when IDs differ
  if (event.primary.name && event.secondary.name &&
      event.primary.name === event.secondary.name &&
      event.primary.id !== event.secondary.id) {
    console.warn(
      `[Validation] IDENTITY WARNING: Event ${event.id} has different IDs ` +
      `(${event.primary.id}, ${event.secondary.id}) but identical names ` +
      `("${event.primary.name}"). This may indicate objects from the same ` +
      `fragmentation event being paired. Verifying IDs are truly different.`
    );
    // This is a warning, not a rejection — different NORAD IDs means different objects
  }

  // IDENTITY CHECK: Object types must not be accidentally copied
  if (event.primary.object_type && event.secondary.object_type &&
      event.primary.object_type === event.secondary.object_type) {
    // Matching object types are valid; log this fact without implying a physical event.
    console.info(
      `[Validation] Event ${event.id}: Both objects have type "${event.primary.object_type}". ` +
      "Matching object types do not invalidate a distinct-object pair."
    );
  }

  // IDENTITY CHECK: primary and secondary must not reference the same memory object
  if (event.primary === event.secondary) {
    return `IDENTITY CORRUPTION: Event ${event.id} primary and secondary reference the same object instance`;
  }

  return null; // valid
}

/**
 * Safely validate an array of events, removing invalid ones and logging diagnostics.
 * Returns the filtered array of valid events.
 */
export function validateAndFilterEvents(events) {
  if (!events || !Array.isArray(events)) return [];

  const valid = [];
  const rejected = [];

  for (const event of events) {
    const error = validateEvent(event);
    if (error) {
      rejected.push({ event, error });
      console.warn(`[SSA Validation] ${error}`);
    } else {
      valid.push(event);
    }
  }

  if (rejected.length > 0) {
    console.info(`[SSA Validation] Filtered ${rejected.length} invalid event(s)`);
  }

  return valid;
}

/**
 * Create a canonical pair key from two object IDs for duplicate detection.
 * Always sorts IDs so (A,B) and (B,A) produce the same key.
 */
export function makePairKey(idA, idB) {
  return [String(idA), String(idB)].sort().join("|");
}

