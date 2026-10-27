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
  return <group>
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
      return <mesh key={object.id} position={[ecefX / norm * radius, z / norm * radius, ecefY / norm * radius]}>
        <sphereGeometry args={[object.category === "debris" ? 0.035 : 0.045, 8, 8]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>;
    })}
  </group>;
}

export function SmartFilterGlobe({ title, objects = [], propagationEpoch = null }) {
  const epochs = [...new Set(objects.map((o) => o.provenance?.propagation_epoch).filter(Boolean))];
  const epoch = propagationEpoch || (epochs.length === 1 ? epochs[0] : null);
  const valid = Boolean(epoch) && (objects.length === 0 || (objects.every((o) => o.provenance?.reference_frame === "TEME" && o.provenance?.propagation_epoch === epoch && Array.isArray(o.position) && o.position.length === 3 && o.position.every(Number.isFinite))));
  return <div className="smart-globe-panel">
    <div className="smart-globe-title">{title} · {objects.length.toLocaleString()} objects</div>
    {valid ? <Canvas className="smart-filter-canvas" dpr={[1, 1.5]} camera={{ position: [0, 1.1, 8.2], fov: 40, near: 0.1, far: 40 }}>
      <color attach="background" args={["#030a16"]} /><ambientLight intensity={0.72} /><directionalLight position={[6, 5, 7]} intensity={2.1} />
      <Earth freezeRotation /><CatalogMarkers objects={objects} propagationEpoch={epoch} /><OrbitControls enablePan={false} minDistance={5.2} maxDistance={13} autoRotate autoRotateSpeed={0.24} />
    </Canvas> : <div className="smart-globe-unavailable">Earth view unavailable: no common-epoch propagated TEME position data for this snapshot.</div>}
    <div className="smart-globe-legend"><span><i className="active-marker" /> Satellite (working spacecraft)</span><span><i className="debris-marker" /> Debris</span><span><i className="rocket-marker" /> Rocket body</span><span><i className="unknown-marker" /> Other / unknown</span><small>SGP4 snapshot, TEME → pseudo-Earth-fixed by GMST. Orbit radius compressed for display; procedural land is illustrative, not geographic; no future trajectory shown.</small></div>
  </div>;
}
