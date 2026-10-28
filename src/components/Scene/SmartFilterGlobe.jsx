import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Earth } from "./Earth";

function gmstRadians(utc) {
  const date = new Date(utc);
  if (!Number.isFinite(date.getTime())) return null;
  const jd = date.getTime() / 86400000 + 2440587.5;
  const t = (jd - 2451545.0) / 36525;
  const degrees = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - t * t * t / 38710000;
  return ((degrees % 360) + 360) % 360 * Math.PI / 180;
}

function CatalogMarkers({ objects, propagationEpoch }) {
  const epochs = [...new Set(objects.map((o) => o.provenance?.propagation_epoch).filter(Boolean))];
  const epoch = propagationEpoch || (epochs.length === 1 ? epochs[0] : null);
  const theta = epoch ? gmstRadians(epoch) : null;
  if (theta == null || objects.some((o) => o.provenance?.reference_frame !== "TEME" || !Array.isArray(o.position) || o.position.length !== 3 || !o.position.every(Number.isFinite))) return null;
  const duplicateSlots = new Map();
  return <group renderOrder={3}>
    {objects.map((object) => {
      const [x, y, z] = object.position;
      // Rotate the snapshot TEME vector into the pseudo-Earth-fixed frame at its propagation epoch.
      const ecefX = Math.cos(theta) * x + Math.sin(theta) * y;
      const ecefY = -Math.sin(theta) * x + Math.cos(theta) * y;
      const norm = Math.hypot(ecefX, ecefY, z);
      if (!(norm > 6378)) return null;
      // Orbit radius is intentionally compressed so LEO through GEO remain legible.
      const radius = 2.18 + Math.min(0.95, Math.log1p(norm - 6378) / Math.log1p(40000) * 0.95);
      const color = object.category === "debris" ? "#070a10" : object.category === "rocket_body" ? "#ffd166" : object.category === "active" || object.category === "payload" ? "#ffffff" : "#8bd5ff";
      const positionKey = `${x.toFixed(3)}:${y.toFixed(3)}:${z.toFixed(3)}`;
      const slot = duplicateSlots.get(positionKey) || 0;
      duplicateSlots.set(positionKey, slot + 1);
      // Identical propagated records would otherwise occupy one pixel. This small
      // display-only ring preserves the payload position while exposing each record.
      const spread = slot ? 0.13 + 0.08 * Math.floor((slot - 1) / 6) : 0;
      const angle = slot * 2.399963229728653;
      const base = [ecefX / norm * radius, z / norm * radius, ecefY / norm * radius];
      return <mesh key={`${object.id}-${slot}`} renderOrder={3} position={[base[0] + Math.cos(angle) * spread, base[1] + Math.sin(angle) * spread, base[2]]}>
        <sphereGeometry args={[object.category === "debris" ? 0.06 : 0.07, 8, 8]} />
        <meshBasicMaterial color={color} toneMapped={false} depthTest={false} depthWrite={false} />
      </mesh>;
    })}
  </group>;
}

export function SmartFilterGlobe({ title, objects = [], propagationEpoch = null }) {
  const epochs = [...new Set(objects.map((o) => o.provenance?.propagation_epoch).filter(Boolean))];
  const epoch = propagationEpoch || (epochs.length === 1 ? epochs[0] : null);
  const valid = Boolean(epoch) && (objects.length === 0 || (objects.every((o) => o.provenance?.reference_frame === "TEME" && o.provenance?.propagation_epoch === epoch && Array.isArray(o.position) && o.position.length === 3 && o.position.every(Number.isFinite))));
  const renderable = valid ? objects.filter((object) => Array.isArray(object.position) && object.position.length === 3 && object.position.every(Number.isFinite)) : [];
  return <div className="smart-globe-panel" data-rendered-count={renderable.length}>
    <div className="smart-globe-title">{title} · {objects.length.toLocaleString()} objects</div>
    {valid ? <Canvas className="smart-filter-canvas" dpr={[1, 1.5]} camera={{ position: [0, 1.1, 8.2], fov: 40, near: 0.1, far: 40 }}>
      <color attach="background" args={["#030a16"]} /><ambientLight intensity={0.72} /><directionalLight position={[6, 5, 7]} intensity={2.1} />
      <Earth freezeRotation /><CatalogMarkers objects={renderable} propagationEpoch={epoch} /><OrbitControls enablePan={false} minDistance={5.2} maxDistance={13} autoRotate autoRotateSpeed={0.24} />
    </Canvas> : <div className="smart-globe-unavailable">Earth view unavailable: no common-epoch propagated TEME position data for this snapshot.</div>}
    <div className="smart-globe-legend"><span><i className="active-marker" /> Satellite (working spacecraft)</span><span><i className="debris-marker" /> Debris</span><span><i className="rocket-marker" /> Rocket body</span><span><i className="unknown-marker" /> Other / unknown</span><small>SGP4 snapshot, TEME → pseudo-Earth-fixed by GMST. Orbit radius compressed for display; procedural land is illustrative, not geographic; no future trajectory shown.</small></div>
  </div>;
}
