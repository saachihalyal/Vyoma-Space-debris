import fs from "node:fs/promises";
const outputs = [
  ["http://127.0.0.1:8001/api/collision-probability/reference-cases/nasa-cara-foster-2d/assessment.pdf", "output/pdf/vyoma-collision-report.pdf"],
  ["http://127.0.0.1:8001/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver-report.pdf?event_id=CDM-008e1a98c04bf9b076ae16f3&maneuvering_object_id=000020580&burn_lead_seconds=5400&direction=along_track%2B&delta_v_m_s=0.05", "output/pdf/vyoma-maneuver-report.pdf"],
];
await fs.mkdir("output/pdf", { recursive: true });
for (const [url, path] of outputs) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status} ${await response.text()}`);
  await fs.writeFile(path, Buffer.from(await response.arrayBuffer()));
  console.log(`${path}: ${response.status}, ${(await fs.stat(path)).size} bytes`);
}
