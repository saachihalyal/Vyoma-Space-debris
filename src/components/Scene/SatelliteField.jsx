import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { BAND_COLORS, degToRad, orbitPhase, orbitPositionTo } from "../../utils/orbitalMath";
import { getVisualizationCategory } from "../../utils/objectClassification.js";
import { selectedObjectWorldPosition, setHasSelectedObject } from "./positionSharing";

const tempObject = new THREE.Object3D();
const tempColor = new THREE.Color();
const tempVector = new THREE.Vector3();
const visualCategory = (object) => getVisualizationCategory(object);
const objectTypeColor = (category) => category === "active" ? "#ffffff" : category === "debris" ? "#000000" : category === "rocket_body" ? "#ffd166" : "#8bd5ff";

function safeNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function formatPct(p) {
  const n = Number(p);
  if (!Number.isFinite(n)) return null;
  return `${Math.round(n * 100)}%`;
}

function riskLabelFromSeverity(severity) {
  const s = (severity ?? "").toString().toLowerCase();
  if (s.includes("very")) return "Very Low";
  if (s.includes("low")) return "Low";
  if (s.includes("moderate") || s.includes("med")) return "Moderate";
  if (s.includes("elevated")) return "Elevated";
  if (s.includes("high")) return "High";
  if (s.includes("critical")) return "Critical";
  if (s.includes("extreme")) return "Extreme";
  return (severity ?? "Unknown").toString();
}

function regionLabelFromBand(band) {
  const s = (band ?? "").toString().toLowerCase();
  if (s.includes("leo")) return "LEO";
  if (s.includes("meo")) return "MEO";
  if (s.includes("geo")) return "GEO";
  if (s.includes("heo")) return "HEO";
  return band ? String(band) : null;
}

function safeToFixed(n, digits) {
  const x = safeNum(n);
  if (x === undefined) return null;
  return x.toFixed(digits);
}

function applyOrbitTransform(object, elapsedSeconds, forecastHours, scale) {
  orbitPositionTo(tempVector, object.orbit, elapsedSeconds, forecastHours);
  tempObject.position.copy(tempVector);
  tempObject.rotation.set(
    degToRad(object.orbit?.inclination_deg || 0) * 0.72,
    orbitPhase(object.orbit, elapsedSeconds, forecastHours) + Math.PI / 2,
    degToRad(object.orbit?.raan_deg || 0)
  );
  tempObject.scale.setScalar(scale);
  tempObject.updateMatrix();
}

function markInstanceUpdates(...meshes) {
  for (const mesh of meshes) {
    if (!mesh) continue;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) {
      mesh.instanceColor.needsUpdate = true;
    } else {
      const count = mesh.count || 0;
      if (count > 0) {
        const colors = new Float32Array(count * 3);
        colors.fill(1);
        mesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);
        mesh.instanceColor.needsUpdate = true;
      }
    }
  }
}

/**
 * SelectedBeacon — reads the CANONICAL position from positionSharing.js
 * instead of calculating its own position independently.
 * This guarantees the ring is exactly at the same position as the rendered instance.
 */
function SelectedBeacon() {
  const groupRef = useRef();
  const rotationRef = useRef(0);

  useFrame((_, delta) => {
    rotationRef.current += delta * 1.8;
    if (!groupRef.current) return;
    // Copy the EXACT canonical position that SatelliteField writes every frame
    groupRef.current.position.copy(selectedObjectWorldPosition);
    groupRef.current.rotation.y = rotationRef.current;
  });

  return (
    <group ref={groupRef}>
      {/* Outer ring beacon */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.24, 0.008, 8, 48]} />
        <meshBasicMaterial
          color="#ff00aa"
          transparent
          opacity={0.85}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      {/* Inner ring */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.14, 0.005, 8, 32]} />
        <meshBasicMaterial
          color="#ff69b4"
          transparent
          opacity={0.6}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      {/* Brighter point light for better visibility */}
      <pointLight color="#ff00aa" intensity={3.0} distance={2.5} />
    </group>
  );
}

export function SatelliteField({ objects, filters, forecastHours, selectedObject, highlightedObjectIds = [], onSelectObject, onHoverObject }) {
  const { camera } = useThree();

  const activeBodyRef = useRef();
  const activePanelRef = useRef();
  const activeGlowRef = useRef();
  const debrisCoreRef = useRef();
  const debrisGlowRef = useRef();

  const clusterGlowRef = useRef();
  const clusterCoreRef = useRef();

  const elapsedRef = useRef(0);


  const visible = useMemo(() => {
    const base = (objects || []).filter((object) => {
      const categoryVisible = visualCategory(object) === "debris" ? filters.debris : filters.active;
      return categoryVisible && filters[object.band];
    });
    // If selectedObject is not in the filtered list (e.g., hidden by filters),
    // force-include it so the selected object remains visible.
    const forceIncluded = [selectedObject, ...(highlightedObjectIds || []).map((id) => objects.find((object) => object.id === id))]
      .filter((object) => object && !base.some((visibleObject) => visibleObject.id === object.id));
    return forceIncluded.length ? [...base, ...forceIncluded] : base;
  }, [objects, filters, selectedObject, highlightedObjectIds]);
  const highlightedIds = useMemo(() => new Set([selectedObject?.id, ...(highlightedObjectIds || [])].filter(Boolean)), [selectedObject?.id, highlightedObjectIds]);

  const activeObjects = useMemo(() => visible.filter((object) => visualCategory(object) !== "debris"), [visible]);
  const debrisObjects = useMemo(() => visible.filter((object) => visualCategory(object) === "debris"), [visible]);

  // Zoom-aware clutter management (renders fewer instances when camera is far).
  const densityMode = useMemo(() => {
    const dist = camera ? camera.position.length() : 12;
    if (dist < 10) return "detailed";
    if (dist < 16) return "balanced";
    return "compact";
  }, [camera]);

  const filteredActiveObjects = useMemo(() => {
    if (densityMode === "detailed") return activeObjects;
    const max = densityMode === "balanced" ? 160 : 90;
    const sorted = [...activeObjects].sort((a, b) => (b.heuristic_risk_score ?? 0) - (a.heuristic_risk_score ?? 0));
    const selected = activeObjects.filter((object) => highlightedIds.has(object.id));
    return [...new Map([...sorted.slice(0, Math.min(max, sorted.length)), ...selected].map((object) => [object.id, object])).values()];
  }, [activeObjects, densityMode, highlightedIds]);

  const filteredDebrisObjects = useMemo(() => {
    if (densityMode === "detailed") return debrisObjects;
    const max = densityMode === "balanced" ? 190 : 110;
    const sorted = [...debrisObjects].sort((a, b) => (b.heuristic_debris_pressure_score ?? 0) - (a.heuristic_debris_pressure_score ?? 0));
    const selected = debrisObjects.filter((object) => highlightedIds.has(object.id));
    return [...new Map([...sorted.slice(0, Math.min(max, sorted.length)), ...selected].map((object) => [object.id, object])).values()];
  }, [debrisObjects, densityMode, highlightedIds]);

  const clusterKeyOf = (o) => {
    const category = visualCategory(o);
    const band = o.band ?? "unknown";
    const inc = safeNum(o.orbit?.inclination_deg) ?? 0;
    const raan = safeNum(o.orbit?.raan_deg) ?? 0;

    const incBin = Math.round(inc / 4) * 4;
    const raanBin = Math.round(raan / 18) * 18;

    return `${category}|${band}|i${incBin}|raan${raanBin}`;
  };

  const clusters = useMemo(() => {
    // Build coarse clusters from the *currently rendered* sets to avoid heavy work.
    // Cluster representative = highest intensity object in that cluster.
    const all = [...filteredActiveObjects, ...filteredDebrisObjects];

    const map = new Map();
    for (const o of all) {
      const key = clusterKeyOf(o);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(o);
    }

    const list = [];
    for (const [key, arr] of map.entries()) {
      if (!arr.length) continue;
      const category = visualCategory(arr[0]);
      const band = arr[0].band ?? "unknown";
      const isDebris = category === "debris";

      const scored = arr
        .map((o) => {
          const intensity = isDebris ? safeNum(o.heuristic_debris_pressure_score) ?? 0 : safeNum(o.heuristic_risk_score) ?? 0;
          return { o, intensity };
        })
        .sort((a, b) => b.intensity - a.intensity);

      const repr = scored[0]?.o ?? arr[0];
      const count = arr.length;
      const avgRisk = isDebris
        ? (scored.slice(0, Math.min(20, scored.length)).reduce((s, x) => s + (x.intensity ?? 0), 0) / Math.min(20, scored.length))
        : (scored.slice(0, Math.min(20, scored.length)).reduce((s, x) => s + (x.intensity ?? 0), 0) / Math.min(20, scored.length));

      list.push({ key, repr, category, band, count, avgRisk });
    }

    // Keep top clusters by avgRisk so the chart stays readable.
    list.sort((a, b) => (b.avgRisk ?? 0) - (a.avgRisk ?? 0));
    return list.slice(0, densityMode === "detailed" ? 18 : 24);
  }, [filteredActiveObjects, filteredDebrisObjects, densityMode]);

  const updateClustersInstances = (glowMesh, coreMesh) => {
    if (!glowMesh || !coreMesh) return;

    const count = clusters.length;
    glowMesh.count = Math.max(1, count);
    coreMesh.count = Math.max(1, count);

    for (let i = 0; i < count; i += 1) {
      const c = clusters[i];
      const o = c.repr;

      const intensity = c.category === "debris" ? safeNum(o.heuristic_debris_pressure_score) ?? 0 : safeNum(o.heuristic_risk_score) ?? 0;
      const emphasis = c.category === "debris" ? 0.9 + Math.min(1.5, intensity * 1.25) : 0.95 + Math.min(1.5, intensity * 1.35);

      // Use representative object orbit to position cluster glyph.
      applyOrbitTransform(o, elapsedRef.current, forecastHours, emphasis);

      // Cluster glyph shape: use sphere for glow and smaller core.
      const baseScale = 0.11 + Math.min(1.2, c.count * 0.014) + Math.min(0.9, intensity * 0.35);
      tempObject.scale.setScalar(baseScale);
      tempObject.updateMatrix();

      glowMesh.setMatrixAt(i, tempObject.matrix);
      coreMesh.setMatrixAt(i, tempObject.matrix);

      const isDebris = c.category === "debris";
      const baseColor = new THREE.Color(objectTypeColor(c.category));

      const glowCol = baseColor.clone().multiplyScalar(0.42 + Math.min(1, intensity) * 1.2);
      const coreCol = baseColor.clone().multiplyScalar(0.55 + Math.min(1, intensity) * 1.35);

      glowMesh.setColorAt(i, glowCol);
      coreMesh.setColorAt(i, coreCol);

      // Slight pulse via scale multiplier on the instance itself (no animation curves).
      tempObject.scale.setScalar(baseScale * (1 + Math.min(0.15, intensity * 0.08)));
      tempObject.updateMatrix();
      glowMesh.setMatrixAt(i, tempObject.matrix);
      coreMesh.setMatrixAt(i, tempObject.matrix);
    }

    markInstanceUpdates(glowMesh, coreMesh);
  };

  const updateSatelliteInstances = (bodyMesh, panelMesh, glowMesh, objs) => {
    if (!bodyMesh || !panelMesh || !glowMesh) return;

    for (let i = 0; i < objs.length; i += 1) {
      const object = objs[i];
      const p = safeNum(object.heuristic_risk_score) ?? 0;
      const isSelected = highlightedIds.has(object.id);

      // Selected satellite gets larger scale and much brighter glow
      const selectedScale = isSelected ? 1.4 : 1.0;
      const emphasis = (0.95 + Math.min(1, p) * 1.35) * selectedScale;
      applyOrbitTransform(object, elapsedRef.current, forecastHours, emphasis);

      bodyMesh.setMatrixAt(i, tempObject.matrix);
      panelMesh.setMatrixAt(i, tempObject.matrix);

      tempColor.set(objectTypeColor(visualCategory(object)));
      bodyMesh.setColorAt(i, tempColor);
      panelMesh.setColorAt(i, tempColor);

      // Glow: selected → much bigger, stronger magenta glow
      const glowScale = (1.05 + Math.min(1, p) * 1.5) * (isSelected ? 2.5 : 1.0);
      tempObject.scale.setScalar(glowScale);
      tempObject.updateMatrix();
      glowMesh.setMatrixAt(i, tempObject.matrix);

      const glowIntensity = isSelected ? 1.5 : (0.6 + Math.min(1, p) * 0.9);
      const glowCol = new THREE.Color(objectTypeColor(visualCategory(object))).multiplyScalar(glowIntensity);
      glowMesh.setColorAt(i, glowCol);
    }

    markInstanceUpdates(bodyMesh, panelMesh, glowMesh);
  };

  const updateDebrisInstances = (coreMesh, glowMesh, objs) => {
    if (!coreMesh || !glowMesh) return;

    for (let i = 0; i < objs.length; i += 1) {
      const object = objs[i];
      const d = safeNum(object.heuristic_debris_pressure_score) ?? 0;
      const isSelected = highlightedIds.has(object.id);

      // Selected debris gets larger scale
      const selectedScale = isSelected ? 1.6 : 1.0;
      const emphasis = (0.82 + d * 1.25) * selectedScale;
      applyOrbitTransform(object, elapsedRef.current, forecastHours, emphasis);

      tempObject.rotation.x += i * 0.19;
      tempObject.rotation.z += i * 0.13;
      tempObject.updateMatrix();

      coreMesh.setMatrixAt(i, tempObject.matrix);

      if (isSelected) {
        // Selected debris → magenta
        const magenta = new THREE.Color(objectTypeColor(visualCategory(object)));
        coreMesh.setColorAt(i, magenta);
      } else {
        // Unselected debris → green from palette
        const col = new THREE.Color(objectTypeColor(visualCategory(object)));
        const coreCol = col.clone().multiplyScalar(0.95 + d * 0.4);
        coreMesh.setColorAt(i, coreCol);
      }

      const glowScale = isSelected ? 1.12 : 1.1;
      tempObject.scale.setScalar(glowScale);
      tempObject.updateMatrix();

      glowMesh.setMatrixAt(i, tempObject.matrix);

      if (isSelected) {
        glowMesh.setColorAt(i, new THREE.Color("#cbd5e1"));
      } else {
        glowMesh.setColorAt(i, new THREE.Color("#cbd5e1"));
      }
    }

    markInstanceUpdates(coreMesh, glowMesh);
  };

  useFrame((_, delta) => {
    elapsedRef.current += delta;

    // ── Canonical selected-object position ──────────────────────────
    // Compute ONCE here using the SAME elapsedRef.current and forecastHours
    // that will be used to render the instances below.
    // This is the SINGLE source of truth for the selected object's position.
    if (selectedObject && selectedObject.orbit) {
      orbitPositionTo(selectedObjectWorldPosition, selectedObject.orbit, elapsedRef.current, forecastHours);
      setHasSelectedObject(true);
    } else {
      setHasSelectedObject(false);
    }

    // Cluster glyphs (non-interactive): provides higher-level orbital activity context.
    updateClustersInstances(clusterGlowRef.current, clusterCoreRef.current);

    updateSatelliteInstances(activeBodyRef.current, activePanelRef.current, activeGlowRef.current, filteredActiveObjects);
    updateDebrisInstances(debrisCoreRef.current, debrisGlowRef.current, filteredDebrisObjects);
  });

  const handleActiveClick = (event) => {
    event.stopPropagation();
    const item = filteredActiveObjects[event.instanceId];
    if (item) onSelectObject(item);
  };

  const handleDebrisClick = (event) => {
    event.stopPropagation();
    const item = filteredDebrisObjects[event.instanceId];
    if (item) onSelectObject(item);
  };

  const handleActiveHover = (event) => {
    const idx = event.instanceId;
    if (idx == null) return;
    const object = filteredActiveObjects[idx] || null;
    onHoverObject?.(object ? { object, x: event.nativeEvent?.clientX, y: event.nativeEvent?.clientY } : null);
  };

  const handleDebrisHover = (event) => {
    const idx = event.instanceId;
    if (idx == null) return;
    const object = filteredDebrisObjects[idx] || null;
    onHoverObject?.(object ? { object, x: event.nativeEvent?.clientX, y: event.nativeEvent?.clientY } : null);
  };

  return (
    <>
      <group>
        {/* Cluster glyph layer (non-interactive): rendered behind individuals */}
        <instancedMesh
          ref={clusterGlowRef}
          key={`cluster-glow-${clusters.length}-${densityMode}`}
          args={[undefined, undefined, Math.max(1, clusters.length)]}
          frustumCulled={false}
          raycast={false}
        >
          <sphereGeometry args={[0.028, 10, 10]} />
          <meshBasicMaterial
            transparent
            opacity={0.18}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            toneMapped={false}
            vertexColors
          />
        </instancedMesh>

        <instancedMesh
          ref={clusterCoreRef}
          key={`cluster-core-${clusters.length}-${densityMode}`}
          args={[undefined, undefined, Math.max(1, clusters.length)]}
          frustumCulled={false}
          raycast={false}
        >
          <sphereGeometry args={[0.016, 8, 8]} />
          <meshBasicMaterial transparent opacity={0.72} toneMapped={false} depthWrite={false} vertexColors />
        </instancedMesh>

        <instancedMesh
          ref={activeGlowRef}
          key={`active-glow-${filteredActiveObjects.length}-${densityMode}`}
          args={[undefined, undefined, filteredActiveObjects.length]}
          frustumCulled={false}
          onClick={handleActiveClick}
          onPointerOver={(e) => {
            e.stopPropagation();
            handleActiveHover(e);
          }}
          onPointerOut={(e) => {
            e.stopPropagation();
            onHoverObject?.(null);
          }}
        >
          <sphereGeometry args={[0.14, 12, 12]} />
          <meshBasicMaterial
            vertexColors
            transparent
            opacity={0.52}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            depthTest={false}
            toneMapped={false}
          />
        </instancedMesh>

        <instancedMesh
          ref={activePanelRef}
          key={`active-panels-${filteredActiveObjects.length}-${densityMode}`}
          args={[undefined, undefined, filteredActiveObjects.length]}
          frustumCulled={false}
          onClick={handleActiveClick}
          onPointerOver={(e) => {
            e.stopPropagation();
            handleActiveHover(e);
          }}
          onPointerOut={(e) => {
            e.stopPropagation();
            onHoverObject?.(null);
          }}
        >
          <boxGeometry args={[0.19, 0.022, 0.06]} />
          <meshBasicMaterial vertexColors transparent opacity={1} depthTest={false} toneMapped={false} />
        </instancedMesh>

        <instancedMesh
          ref={activeBodyRef}
          key={`active-body-${filteredActiveObjects.length}-${densityMode}`}
          args={[undefined, undefined, filteredActiveObjects.length]}
          frustumCulled={false}
          onClick={handleActiveClick}
          onPointerOver={(e) => {
            e.stopPropagation();
            handleActiveHover(e);
          }}
          onPointerOut={(e) => {
            e.stopPropagation();
            onHoverObject?.(null);
          }}
        >
          <boxGeometry args={[0.075, 0.075, 0.095]} />
          <meshBasicMaterial vertexColors transparent opacity={1} depthTest={false} toneMapped={false} />
        </instancedMesh>

        <instancedMesh
          ref={debrisGlowRef}
          key={`debris-glow-${filteredDebrisObjects.length}-${densityMode}`}
          args={[undefined, undefined, filteredDebrisObjects.length]}
          frustumCulled={false}
          onClick={handleDebrisClick}
          onPointerOver={(e) => {
            e.stopPropagation();
            handleDebrisHover(e);
          }}
          onPointerOut={(e) => {
            e.stopPropagation();
            onHoverObject?.(null);
          }}
        >
          <sphereGeometry args={[0.037, 12, 12]} />
          <meshBasicMaterial
            vertexColors
            transparent opacity={0.95} depthWrite={false}
            toneMapped={false}
          />
        </instancedMesh>

        <instancedMesh
          ref={debrisCoreRef}
          key={`debris-core-${filteredDebrisObjects.length}-${densityMode}`}
          args={[undefined, undefined, filteredDebrisObjects.length]}
          frustumCulled={false}
          onClick={handleDebrisClick}
          onPointerOver={(e) => {
            e.stopPropagation();
            handleDebrisHover(e);
          }}
          onPointerOut={(e) => {
            e.stopPropagation();
            onHoverObject?.(null);
          }}
        >
          <sphereGeometry args={[0.032, 12, 12]} />
          <meshBasicMaterial vertexColors transparent opacity={0.96} toneMapped={false} />
        </instancedMesh>

        {selectedObject ? <SelectedBeacon /> : null}
      </group>

    </>
  );
}
