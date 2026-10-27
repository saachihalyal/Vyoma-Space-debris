const DEG = Math.PI / 180;

function gmstRadians(epoch) {
  const date = new Date(epoch);
  if (!Number.isFinite(date.getTime())) return null;
  const jd = date.getTime() / 86400000 + 2440587.5;
  const t = (jd - 2451545.0) / 36525;
  const degrees = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - t * t * t / 38710000;
  return ((degrees % 360) + 360) % 360 * DEG;
}

export function commonCatalogEpoch(objects = []) {
  const epochs = [...new Set(objects.map((object) => object?.provenance?.propagation_epoch).filter(Boolean))];
  if (epochs.length !== 1) return null;
  const [epoch] = epochs;
  return objects.every((object) => object?.provenance?.reference_frame === "TEME"
    && object?.provenance?.propagation_epoch === epoch
    && Array.isArray(object.position) && object.position.length === 3
    && object.position.every(Number.isFinite)) ? epoch : null;
}

export function catalogPositionToLatLon(position, epoch) {
  const theta = gmstRadians(epoch);
  if (theta == null || !Array.isArray(position) || position.length !== 3 || !position.every(Number.isFinite)) return null;
  const [x, y, z] = position;
  const ecefX = Math.cos(theta) * x + Math.sin(theta) * y;
  const ecefY = -Math.sin(theta) * x + Math.cos(theta) * y;
  const norm = Math.hypot(ecefX, ecefY, z);
  if (!(norm > 6378)) return null;
  return { latitude: Math.asin(z / norm) / DEG, longitude: Math.atan2(ecefY, ecefX) / DEG };
}

export function catalogDensityGroup(object) {
  const category = String(object?.category || "").toLowerCase();
  if (category === "debris") return "debris";
  if (["active", "payload", "satellite"].includes(category)) return "satellites";
  return "other";
}

export function buildCatalogDensityBins(objects = [], epoch, filter = "both", binDegrees = 10) {
  const bins = new Map();
  for (const object of objects) {
    const group = catalogDensityGroup(object);
    if (filter !== "both" && group !== filter) continue;
    const point = catalogPositionToLatLon(object?.position, epoch);
    if (!point) continue;
    const lonIndex = Math.min(360 / binDegrees - 1, Math.floor((point.longitude + 180) / binDegrees));
    const latIndex = Math.min(180 / binDegrees - 1, Math.floor((point.latitude + 90) / binDegrees));
    const key = `${latIndex}:${lonIndex}`;
    const bin = bins.get(key) || { latitudeIndex: latIndex, longitudeIndex: lonIndex, count: 0 };
    bin.count += 1;
    bins.set(key, bin);
  }
  return [...bins.values()];
}

function objectId(object) {
  return object?.id ?? object?.norad_id ?? object?.noradId ?? object?.catalog_id ?? null;
}

export function buildCloseApproachMarkers(objects = [], events = [], epoch) {
  const objectPositions = new Map(objects.map((object) => [String(objectId(object)), catalogPositionToLatLon(object?.position, epoch)]));
  return events.flatMap((event) => {
    const primary = event?.primary || event?.obj_a || {};
    const secondary = event?.secondary || event?.obj_b || {};
    const first = objectPositions.get(String(objectId(primary)));
    const second = objectPositions.get(String(objectId(secondary)));
    if (!first || !second) return [];
    const a = [Math.cos(first.latitude * DEG) * Math.cos(first.longitude * DEG), Math.sin(first.latitude * DEG), Math.cos(first.latitude * DEG) * Math.sin(first.longitude * DEG)];
    const b = [Math.cos(second.latitude * DEG) * Math.cos(second.longitude * DEG), Math.sin(second.latitude * DEG), Math.cos(second.latitude * DEG) * Math.sin(second.longitude * DEG)];
    const midpoint = a.map((value, index) => value + b[index]);
    const norm = Math.hypot(...midpoint);
    if (!(norm > 1e-8)) return [];
    const label = event?.name || `${primary.name || primary.object_name || objectId(primary) || "Object"} / ${secondary.name || secondary.object_name || objectId(secondary) || "Object"}`;
    return [{ id: event.id || `${objectId(primary)}-${objectId(secondary)}`, label, latitude: Math.asin(midpoint[1] / norm) / DEG, longitude: Math.atan2(midpoint[2], midpoint[0]) / DEG }];
  });
}
