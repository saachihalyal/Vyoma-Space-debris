const finite = (...values) => values.find((value) => Number.isFinite(value));

export function catalogHoverDetails(object) {
  const altitude = finite(object?.altitude_km, object?.orbit?.altitude_km);
  const inclination = finite(object?.inclination_deg, object?.orbit?.inclination_deg);
  const speed = finite(object?.velocity_kms, object?.orbit?.velocity_kms, object?.orbit?.speed_km_s);
  return {
    name: object?.name || "Unnamed catalog object",
    catalogId: object?.id || "Unavailable",
    classification: object?.object_type || object?.classification || object?.category || "Unavailable",
    altitude: altitude == null ? "Unavailable" : `${altitude.toFixed(1)} km`,
    inclination: inclination == null ? "Unavailable" : `${inclination.toFixed(2)}°`,
    speed: speed == null ? "Unavailable" : `${speed.toFixed(3)} km/s`,
  };
}
