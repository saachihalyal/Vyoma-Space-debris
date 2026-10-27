import { Canvas } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useMemo, useState } from "react";
import * as THREE from "three";
import { buildCatalogDensityBins, buildCloseApproachMarkers, commonCatalogEpoch } from "../../utils/catalogDensity";
import { Earth } from "./Earth";

function surfacePoint(latitude, longitude, radius) {
  const lat = latitude * Math.PI / 180;
  const lon = longitude * Math.PI / 180;
  return [radius * Math.cos(lat) * Math.cos(lon), radius * Math.sin(lat), radius * Math.cos(lat) * Math.sin(lon)];
}

function DensityLayer({ bins }) {
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const meshes = useMemo(() => bins.map((bin) => {
    const geometry = new THREE.BufferGeometry();
    const segments = 4;
    const lat0 = -90 + bin.latitudeIndex * 10;
    const lon0 = -180 + bin.longitudeIndex * 10;
    const vertices = [];
    const indices = [];
    for (let y = 0; y <= segments; y += 1) {
      for (let x = 0; x <= segments; x += 1) {
        vertices.push(...surfacePoint(lat0 + 10 * y / segments, lon0 + 10 * x / segments, 2.075));
      }
    }
    for (let y = 0; y < segments; y += 1) for (let x = 0; x < segments; x += 1) {
      const a = y * (segments + 1) + x;
      const b = a + 1;
      const c = a + segments + 1;
      const d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    return { geometry, count: bin.count };
  }), [bins]);
  return <group>{meshes.map(({ geometry, count }, index) => <mesh key={index} geometry={geometry}>
    <meshBasicMaterial color={new THREE.Color("#164bff").lerp(new THREE.Color("#ff2638"), Math.log1p(count) / Math.log1p(maxCount))} transparent opacity={0.82} side={THREE.DoubleSide} depthWrite={false} toneMapped={false} />
  </mesh>)}</group>;
}

function ApproachMarkers({ markers }) {
  const [hovered, setHovered] = useState(null);
  return <group>{markers.map((marker) => <mesh key={marker.id} position={surfacePoint(marker.latitude, marker.longitude, 2.105)} onPointerOver={(event) => { event.stopPropagation(); setHovered(marker.id); }} onPointerOut={() => setHovered(null)}>
    <sphereGeometry args={[0.026, 10, 10]} /><meshBasicMaterial color="#fff2a8" toneMapped={false} />
    {hovered === marker.id && <Html distanceFactor={10} position={[0, 0.06, 0]}><div className="catalog-event-tooltip">{marker.label}</div></Html>}
  </mesh>)}</group>;
}

export function CatalogDensityGlobe({ objects = [], events = [] }) {
  const [filter, setFilter] = useState("both");
  const epoch = commonCatalogEpoch(objects);
  const bins = useMemo(() => epoch ? buildCatalogDensityBins(objects, epoch, filter) : [], [objects, epoch, filter]);
  const markers = useMemo(() => epoch ? buildCloseApproachMarkers(objects, events, epoch) : [], [objects, events, epoch]);
  const filteredCount = bins.reduce((sum, bin) => sum + bin.count, 0);
  return <div className="catalog-density-panel">
    <div className="catalog-density-controls" role="group" aria-label="Catalog object type">
      {[ ["satellites", "Satellites"], ["debris", "Debris"], ["both", "Both"] ].map(([value, label]) => <button type="button" key={value} className={filter === value ? "active" : ""} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
      <span>{filteredCount.toLocaleString()} positioned objects</span>
    </div>
    {epoch ? <Canvas className="catalog-density-canvas" dpr={[1, 1.5]} camera={{ position: [0, 1, 8.2], fov: 40, near: 0.1, far: 40 }}>
      <color attach="background" args={["#030a16"]} /><ambientLight intensity={0.72} /><directionalLight position={[6, 5, 7]} intensity={2.1} />
      <Earth freezeRotation /><DensityLayer bins={bins} /><ApproachMarkers markers={markers} /><OrbitControls enablePan={false} minDistance={5.2} maxDistance={13} autoRotate autoRotateSpeed={0.2} />
    </Canvas> : <div className="catalog-density-unavailable">Common-epoch SGP4 positions are not available for this catalog snapshot.</div>}
    <div className="catalog-density-legend"><span>Object density</span><i /><small>Fewer objects</small><small>More objects</small><b>●</b><small>Saved close approach pair midpoint</small></div>
    {epoch && <p className="catalog-density-caption">SGP4 catalog epoch: {epoch}. Event markers use the saved pair members’ propagated positions at this catalog epoch.</p>}
  </div>;
}
