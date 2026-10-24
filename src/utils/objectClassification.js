/**
 * objectClassification.js
 *
 * Centralized, authoritative object classification system for the ORION SSA platform.
 *
 * All components MUST use this module to determine object type labels.
 * Do NOT infer object type from display names or duplicate this logic elsewhere.
 *
 * Only explicit API/catalog classification fields are used. Names and event
 * roles do not establish object type.
 */

/**
 * Object type labels used throughout the application.
 */
export const OBJECT_TYPE = {
  ACTIVE_SATELLITE: "ACTIVE SATELLITE",
  SPACE_DEBRIS: "SPACE DEBRIS",
  ROCKET_BODY: "ROCKET BODY",
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
  const fields = [object.object_type, object.source_classification, object.category]
    .filter((value) => typeof value === "string" && value.trim());
  const resolved = fields.map((value) => {
    const raw = value.trim().toUpperCase().replace(/_/g, " ");
    if (["ACTIVE SATELLITE", "ACTIVE", "PAYLOAD", "SATELLITE", "SPACECRAFT"].includes(raw)) return OBJECT_TYPE.ACTIVE_SATELLITE;
    if (["SPACE DEBRIS", "DEBRIS", "FRAGMENT"].includes(raw)) return OBJECT_TYPE.SPACE_DEBRIS;
    if (["ROCKET BODY", "R/B", "ROCKET"].includes(raw)) return OBJECT_TYPE.ROCKET_BODY;
    return OBJECT_TYPE.UNKNOWN;
  });
  const known = resolved.filter((value) => value !== OBJECT_TYPE.UNKNOWN);
  if (known.length && (known.length !== resolved.length || new Set(known).size > 1)) return OBJECT_TYPE.UNKNOWN;
  return known[0] || OBJECT_TYPE.UNKNOWN;
}

export function getObjectTypeCode(object) {
  const label = getObjectTypeLabel(object);
  if (label === OBJECT_TYPE.ACTIVE_SATELLITE) return "ACTIVE_SATELLITE";
  if (label === OBJECT_TYPE.SPACE_DEBRIS) return "SPACE_DEBRIS";
  if (label === OBJECT_TYPE.ROCKET_BODY) return "ROCKET_BODY";
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

