const finite = (value) => typeof value === "number" && Number.isFinite(value);

export function buildResearchPcHeatmap(events = [], { xBins = 8, yBins = 6, maxMagnitude = 30 } = {}) {
  const physical = events.filter((event) => event?.result_kind === "physics_assessment");
  const valid = physical.filter((event) => event?.physics_result?.status === "valid" && event?.physics_result?.tca_status === "valid");
  const plotted = valid.map((event) => {
    const log10Pc = event?.automatic_research_pc_assessment?.log10_pc;
    const altitudeRaw = event?.primary?.altitude_km;
    const speedRaw = event?.primary?.velocity_kms;
    const altitude = altitudeRaw == null || altitudeRaw === "" ? NaN : Number(altitudeRaw);
    const speed = speedRaw == null || speedRaw === "" ? NaN : Number(speedRaw);
    if (!finite(log10Pc) || log10Pc > 0 || !Number.isFinite(altitude) || !Number.isFinite(speed)) return null;
    return { event, altitude, speed, magnitude: Math.min(maxMagnitude, Math.max(0, -log10Pc)) };
  }).filter(Boolean);
  const altitudes = plotted.map((item) => item.altitude);
  const speeds = plotted.map((item) => item.speed);
  const minAltitude = altitudes.length ? Math.min(...altitudes) : 0;
  const maxAltitude = altitudes.length ? Math.max(...altitudes) : 1;
  const minSpeed = speeds.length ? Math.min(...speeds) : 0;
  const maxSpeed = speeds.length ? Math.max(...speeds) : 1;
  const cells = Array.from({ length: xBins * yBins }, (_, index) => ({ x: index % xBins, y: Math.floor(index / xBins), sum: 0, count: 0 }));
  for (const item of plotted) {
    const x = Math.min(xBins - 1, Math.floor(((item.altitude - minAltitude) / Math.max(Number.EPSILON, maxAltitude - minAltitude)) * xBins));
    const y = Math.min(yBins - 1, Math.floor(((item.speed - minSpeed) / Math.max(Number.EPSILON, maxSpeed - minSpeed)) * yBins));
    const cell = cells[y * xBins + x];
    cell.sum += item.magnitude;
    cell.count += 1;
  }
  return {
    metric: `clipped -log10 Pc (0 to ${maxMagnitude}; research Pc)`,
    plottedCount: plotted.length,
    excludedCount: events.length - plotted.length,
    minAltitude, maxAltitude, minSpeed, maxSpeed,
    cells: cells.map(({ sum, ...cell }) => ({ ...cell, value: cell.count ? sum / cell.count : null })),
  };
}
