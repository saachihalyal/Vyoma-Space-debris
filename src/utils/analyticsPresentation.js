export function forecastHourLabel(point, index) {
  const hour = Number(point?.hour);
  return Number.isFinite(hour) && hour >= 0 ? `+${hour}h` : `T${index + 1}`;
}

export function proxyPriorityClassIndex(risk) {
  const value = String(risk || "low").toLowerCase();
  if (value === "low" || value === "safe") return 0.05;
  if (value === "moderate" || value === "medium") return 0.25;
  if (value === "elevated") return 0.45;
  if (value === "high") return 0.7;
  if (value === "critical") return 0.9;
  if (value === "extreme") return 1.0;
  return 0.05;
}
