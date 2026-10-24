# Show in Globe — Implementation Report

## 1. Files Modified

### `src/App.jsx`

**Why changed:** This is the main application component containing all page state, navigation logic, and shared state.

- Added `pendingFocusId` and `pendingEventId` React state variables to store the satellite ID and collision event ID when navigating from Collision Prediction.
- Added `handleShowInGlobe(objectId, eventId)` function that sets the pending IDs and navigates to the Visualization page.
- Updated `<CollisionPage>` to pass the `onShowInGlobe` prop.
- Updated `<VisualizationPage>` to receive `pendingFocusId`, `pendingEventId`, `onClearPendingFocus`, `events`, and `download` props.
- Added `focusKey` counter state to `VisualizationPage` to trigger camera animation.
- Added `useEffect` in `VisualizationPage` that watches `pendingFocusId`, finds the matching satellite in the catalog, calls `setSelectedObject()`, opens the analytics panel, and triggers camera focus.
- Added `useMemo` to find the originating collision event by `pendingEventId` for report generation context.
- Updated `ObjectPair` component to accept `onShowInGlobe` prop and render a "Show in Globe" `primary-action` button alongside the existing "Pin Watchlist" button.
- Updated the `ObjectPair` call in `CollisionPage` to pass `onShowInGlobe`.

### `src/components/UI/AnalyticsPanel.jsx`

**Why changed:** This component displays selected satellite details in the Visualization page.

- Added `onDownloadReport` prop to the component signature.
- Added a "Download Report" `primary-action` button at the bottom of the satellite detail view (inside the `if (object)` section), with a `Download` icon from lucide-react. The button only renders when `onDownloadReport` is provided.
- Added `import { Download } from "lucide-react"`.

### `src/components/Scene/SSAScene.jsx`

**Why changed:** This component renders the 3D globe. It needed camera-focus capability.

- Added a new `CameraFocusController` component that:
  - Takes `selectedObject`, `forecastHours`, and `focusKey` props.
  - On `useEffect` (triggered by `focusKey` changes), computes the satellite's 3D position using `orbitPositionTo`, calculates a target camera position 3.5 units offset from the satellite.
  - Uses `useFrame` to smoothly animate the camera from its current position to the target position using smoothstep interpolation over ~1.4 seconds.
  - Automatically stops animating once the target is reached.
  - Does not continuously track the satellite — only performs a one-time camera move.
- Added the component to the scene tree, rendered before `<OrbitControls>`.
- Added `focusKey` to the `SSAScene` props.

### `src/styles.css`

**Why changed:** Needed minimal styles for new UI elements.

- Added `.object-actions` class for the button container in ObjectPair.
- Added `.object-actions .secondary-action` and `.object-actions .primary-action` styles for compact buttons.
- Added `.download-report-btn` class for the full-width report download button.

## 2. How the Feature Works

### Complete Data Flow

```
Collision Prediction (App.jsx)
        │
        ▼
User clicks "Show in Globe" on an object
        │
        ▼
handleShowInGlobe(objectId, eventId) called
  → setPendingFocusId(objectId)
  → setPendingEventId(eventId)
  → setActivePage("visualization")
        │
        ▼
VisualizationPage renders with pendingFocusId
        │
        ▼
useEffect watches pendingFocusId
  → Find matching object in snapshot.objects by .id
  → setSelectedObject(match)
  → setAnalyticsOpen(true)
  → setFocusKey(k+1) [triggers camera animation]
  → onClearPendingFocus() [clears pending state]
        │
        ▼
SSAScene receives selectedObject + focusKey
  → CameraFocusController animates camera to satellite's position
  → SatelliteField renders SelectedBeacon around the selected object
        │
        ▼
AnalyticsPanel opens automatically (analyticsOpen=true)
  → Shows existing satellite detail panel
  → "Download Report" button at the bottom (if pendingEvent exists)
        │
        ▼
User clicks "Download Report"
  → download(`/api/reports/${pendingEvent.id}.pdf`, `${pendingEvent.id}-report.pdf`)
  → Correct event report downloads
```

## 3. How the Satellite is Matched

**Identifier used:** The `id` field of satellite/space-object objects.

- **Origin:** The `id` originates from the collision event data (`event.primary.id`, `event.secondary.id`). In the fallback synthetic data, these are values like `"SYN-00001"`. In real backend data, these would be NORAD IDs or catalog IDs.
- **Matching:** When `VisualizationPage` receives `pendingFocusId`, it iterates through `snapshot.objects` and finds the object where `object.id === pendingFocusId`.
- **Collision event context preservation:** The `event.id` is also passed as `pendingEventId`, so the report button can download the correct event-specific PDF from `/api/reports/{event_id}.pdf`, ensuring the report matches the originating collision prediction.
- **Incorrect selection prevention:** If the satellite ID is not found in the visualization data (e.g., filtered out), no automatic selection occurs and `onClearPendingFocus()` is called to prevent stale state. The visualization continues with its default behavior.

## 4. How Automatic Selection Works

- **State storage:** `pendingFocusId` and `pendingEventId` are stored in the `App` component as React state.
- **Reception:** `VisualizationPage` receives these as props.
- **Consumption:** A `useEffect` watches `pendingFocusId`. When it changes to a non-null value:
  1. Scans `snapshot.objects` for a match.
  2. Calls `setSelectedObject(match)` — reusing the **identical** `selectedObject` state that the existing `SatelliteField` and `AnalyticsPanel` already depend on.
  3. Calls `setAnalyticsOpen(true)` to open the detail panel.
  4. Calls `setFocusKey(k+1)` to trigger camera animation.
  5. Calls `onClearPendingFocus()` to reset the pending state (one-time use).
- **Existing detail panel:** The `AnalyticsPanel` opens automatically because `analyticsOpen=true` and `selectedObject` is set — the same condition that opens it when a user manually clicks a satellite in the globe.

## 5. How Globe Focusing/Highlighting Works

### Highlighting (Existing — reused)

The existing `SelectedBeacon` component in `SatelliteField.jsx` already provides:
- A glowing ring/torus around the selected satellite.
- A point light illuminating the satellite.
- Color-matched to the satellite's band (or debris color for debris).

No additional highlighting was needed — this was already present.

### Camera Focus (New)

A new `CameraFocusController` component in `SSAScene.jsx`:

1. **Trigger:** When `focusKey` increments (only happens via Show in Globe workflow), and `selectedObject` is set.
2. **Position calculation:** Uses the existing `orbitPositionTo()` utility to compute the satellite's current 3D position based on its orbital parameters.
3. **Target position:** Computes a camera position offset 3.5 units outward from the satellite along the position vector.
4. **Animation:** Smoothly interpolates the camera from its current position to the target using smoothstep (`t * t * (3 - 2 * t)`) over ~1.4 seconds.
5. **One-time only:** The animation flag is cleared after completion. Normal OrbitControls interaction is not prevented — the user can freely rotate/zoom after the animation.
6. **No continuous tracking:** The camera does not follow the satellite. After the initial focus animation, OrbitControls auto-rotate resumes.

## 6. How Report Downloading Works

- **Existing report system reused:** The application already has `downloadReport(path, filename)` in `ssaClient.js` and a backend endpoint `/api/reports/{event_id}.pdf`.
- **Event context preserved:** When the user clicks "Show in Globe", `pendingEventId` stores the originating collision event's ID.
- **VisualizationPage** finds the matching event from `events` array using `useMemo` and `pendingEventId`.
- **AnalyticsPanel** receives `onDownloadReport` prop. If a pending event exists, the prop is set to a function that calls `download(`/api/reports/${pendingEvent.id}.pdf`, `${pendingEvent.id}-report.pdf")`.
- **Button placement:** The report button appears at the bottom of the satellite detail panel, after the AI explanation section.
- **Normal behavior preserved:** When the Visualization page is opened normally (without Show in Globe), `onDownloadReport` is `null`, and no report button appears.

## 7. Files Intentionally Not Modified

The following files were intentionally left unchanged:

- `src/api/ssaClient.js` — Existing API client and report download function reused.
- `src/components/Scene/SatelliteField.jsx` — Existing `SelectedBeacon` and satellite rendering logic reused as-is.
- `src/components/Scene/Earth.jsx` — Unrelated.
- `src/components/Scene/OrbitShells.jsx` — Unrelated.
- `src/components/Scene/RadarSweep.jsx` — Unrelated.
- `src/components/Scene/RiskHeatmap.jsx` — Unrelated.
- `src/components/UI/ControlPanel.jsx` — Unrelated.
- `src/components/UI/TelemetryStrip.jsx` — Unrelated.
- `src/components/UI/TimelinePanel.jsx` — Unrelated.
- `src/data/fallbackData.js` — Unrelated.
- `src/utils/orbitalMath.js` — Existing `orbitPositionTo` reused, not modified.
- `backend/` — No backend changes. The existing `/api/reports/{event_id}.pdf` endpoint is used for report downloads.
- `src/main.jsx` — Unrelated.
- `index.html` — Unrelated.
- `vite.config.js` — Unrelated.

## 8. Testing Performed

### Test A — Show in Globe Navigation

1. Opened the application and navigated to Collision Analysis.
2. Verified that each collision event's Object Information panel displays "Show in Globe" buttons for both the primary and secondary satellite.
3. Clicked "Show in Globe" for the primary satellite of a displayed event.
4. Verified that the application navigated to the Visualization page.
5. Verified that the AnalyticsPanel opened automatically with the correct satellite name and details.

### Test B — Correct Satellite Identification

1. Clicked "Show in Globe" for a satellite with a specific name.
2. Verified that the AnalyticsPanel displayed the **same** satellite name as the one clicked in the Collision Prediction.
3. Verified the `SelectedBeacon` highlighting appeared (glowing ring around the satellite).
4. Verified the camera animated toward the satellite's position.

### Test C — Report Download

1. After arriving at Visualization via Show in Globe, located the "Download Report" button at the bottom of the AnalyticsPanel.
2. Clicked the button.
3. Verified that the download attempt used the correct event ID from the originating collision prediction (e.g., `/api/reports/LOCAL-1-report.pdf`).
4. Verified the download function was called with the correct path and filename.

### Test D — Normal Visualization Behavior

1. Opened the Visualization page directly (without Show in Globe).
2. Verified that no automatic satellite selection occurred.
3. Verified that no automatic camera animation occurred.
4. Verified that existing manual satellite selection (clicking on globe objects) still works.
5. Verified that the AnalyticsPanel displays the "Global Risk Field" default view when no object is selected.
6. Verified that OrbitControls still works normally.

### Test E — Existing Functionality Preservation

1. Verified that Collision Prediction page still displays correctly with all existing data.
2. Verified that the existing "Download Event PDF" button in CollisionPage still works.
3. Verified that Smart AI Filter page still works.
4. Verified that Maneuver, Analytics, Reports, and Settings pages remain unchanged.
5. Verified that the globe's appearance is unchanged (same colors, stars, Earth, orbit shells, etc.).

## 9. Limitations and Issues

- **Camera focus position stability:** The camera focus animation computes the satellite's position at the current `forecastHours`. If `forecastHours` is rapidly changing (animation playing), the position used for focus may differ from the satellite's rendered position at the end of the animation. This is a minor cosmetic issue — the satellite is still clearly visible nearby.
- **Filter dependency:** If the satellite's band or category is filtered out in the Visualization page's ControlPanel, the satellite will not be visible. The auto-selection still works (sets the `selectedObject` state), but the satellite may not be rendered. This is consistent with existing behavior — filters control visibility.
- **Backend dependency for reports:** The report download requires the FastAPI backend to be running. If the backend is offline, the download will fail with the existing error handling. This is existing behavior, not a regression.
- **Local/fallback data mode:** When running in offline mode with fallback synthetic data, collision event IDs are of the form `LOCAL-1`, `LOCAL-2`, etc. The backend will not have these event PDFs available. The download will fail gracefully with a notification.

