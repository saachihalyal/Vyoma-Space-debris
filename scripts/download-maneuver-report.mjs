import fs from "node:fs/promises";
const eventId = "CDM-008e1a98c04bf9b076ae16f3";
const params = new URLSearchParams({ event_id: eventId, maneuvering_object_id: "000020580", burn_lead_seconds: "5400", direction: "along_track+", delta_v_m_s: "0.05" });
const response = await fetch(`http://127.0.0.1:8001/api/collision-probability/reference-cases/nasa-cara-foster-2d/maneuver-report.pdf?${params}`);
if (!response.ok) throw new Error(`Report request failed: ${response.status} ${await response.text()}`);
await fs.mkdir("output/pdf", { recursive: true });
await fs.writeFile("output/pdf/vyoma-maneuver-report.pdf", Buffer.from(await response.arrayBuffer()));
console.log(JSON.stringify({ status: response.status, type: response.headers.get("content-type"), bytes: (await fs.stat("output/pdf/vyoma-maneuver-report.pdf")).size }));
