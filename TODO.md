# Show in Globe — Correct Implementation

## Root Cause Analysis
1. SelectedBeacon has its OWN elapsedRef (starts at 0 on mount), while InstancedMesh uses SatelliteField's elapsedRef (accumulated since mount) → positions diverge
2. CameraFocusController calculates position with elapsedSeconds=0 via orbitPositionTo, while instances use elapsedRef.current → camera looks at wrong place
3. OrbitControls.target not updated → camera fights controls
4. Hardcoded 3.5 offset regardless of orbital radius → wrong zoom for LEO vs GEO
5. Filtered objects invisible even when selected

## Architecture
Create ONE canonical position written by SatelliteField every frame, read by SelectedBeacon and CameraFocusController.

```
SatelliteField.useFrame
  → elapsedRef.current += delta
  → compute selectedObjectWorldPosition with SAME elapsedRef.current
  → write to shared mutable Vector3
        ↓
        ├── SelectedBeacon reads position (no own calculation)
        ├── CameraFocusController reads position (updates camera + controls.target)
```

## Steps

- [x] Step 1: Create `src/components/Scene/positionSharing.js` — shared mutable Vector3
- [x] Step 2: Modify `src/components/Scene/SatelliteField.jsx`
  - Import shared position
  - Force selected object into visible list (bypass filters)
  - In useFrame, write selected object's canonical position BEFORE instance updates
  - Fix SelectedBeacon to read from shared position instead of own calculation
  - Enhance selected object visual prominence (bigger scale, brighter glow)
- [x] Step 3: Modify `src/components/Scene/SSAScene.jsx`
  - Import shared position
  - Rewrite CameraFocusController:
    - Read from selectedObjectWorldPosition
    - Update both camera.position and controls.target in sync
    - Dynamic focus distance based on orbital radius
    - Temporarily disable autoRotate during animation
    - Smooth interpolation for both camera and controls
- [x] Step 4: Fix App.jsx VisualizationPage — persist localEventId so download report button works after pendingEventId is cleared
- [ ] Step 5: Test — verify ring centered on satellite, camera focuses, controls work
- [ ] Step 6: Performance check — no per-frame state updates, no duplicate calculations

# ✅ Maneuver Page Fix — Local Fallback Optimizer

## Problem
Maneuver page showed `"..."` placeholders when backend was offline because `getManeuver(LOCAL-X)` fails → returns `null` → ManeuverPage shows empty state.

## Fix
- [x] Added `computeLocalManeuver(event)` function with full local Foster 2D Pc calculator and iterative delta-V search
- [x] Updated maneuver `useEffect` to fall back to local computation when backend API is unavailable
- [x] Mirrors backend `optimize_maneuver()` logic exactly (same numerical integration, search parameters, fuel calculation)

