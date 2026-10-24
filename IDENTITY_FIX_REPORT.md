# Identity Fix Report

## Root Cause Analysis

After tracing one object end-to-end through the entire data pipeline, here are the exact root causes of identity inconsistency:

### Root Cause 1: No Canonical Identity Model (CRITICAL)

There was **no single authoritative object representation** used throughout the application. Each component reconstructed identity independently:

| Component | How it determined identity |
|-----------|---------------------------|
| Backend `_object_summary()` | `id`, `name`, `category` from SpaceObject |
| Frontend `EventList` | `event.primary.name`, `event.secondary.name` (no IDs or types displayed) |
| Frontend `ObjectPair` | `object.name`, `object.band`, `object.orbit_type` (no type at all) |
| `AnalyticsPanel` | `getObjectTypeLabel(object)` — heuristic-based |
| `SatelliteField` | `object.category` for rendering visuals |
| `CollisionPage` title | `event.primary.name` vs `event.secondary.name` (no IDs or types) |

**No two components used the same function to determine object type.** The backend didn't emit an `object_type` field, and the frontend had no authoritative type resolution.

### Root Cause 2: Name-Based Classification in Backend (CRITICAL)

In `orbit.py`: `category_from_record()` classified by substring matching on the name:

```python
if "deb" in lowered or "debris" in lowered: return "debris"
```

This means:
- "IRIDIUM 33 DEB" → debris ✓
- "IRIDIUM 33" (the ACTUAL active satellite) → also gets defaulted to "debris" if the name happens to contain "deb" from source_group

More problematically, objects that don't match any debris/rocket substring default to `"active"`, silently misclassifying any actual debris without "deb" in the name.

### Root Cause 3: Backend Supplement Creates Mixed/Generic Identities

When real TLE propagation yields fewer objects than needed, `build_synthetic_objects()` in `orbit.py` creates objects with:
- IDs like `SYN-00042` 
- Names like `"SSA OBJECT 00042"` or `"DEBRIS FIELD 00042"`

These have NO relationship to the real catalog. The backend then generates conjunction events pairing real catalog objects with synthetic ones, creating nonsensical pairs like:
```
SSA OBJECT 00472 vs SSA OBJECT 00533
```

### Root Cause 4: FallbackData.js Had No Realistic Identity Model

The fallback data generator created only generic names:
- `"DEBRIS VECTOR 0001"` (no relation to any real debris family)
- `"SSA TRACK 0001"` (no relation to any real satellite)

These generic names provided no way to distinguish satellite from debris, and no NORAD-like IDs.

### Root Cause 5: No Type Display in Conjunction UI

`ObjectPair` and `EventList` displayed only names — never the object type (ACTIVE_SATELLITE vs SPACE_DEBRIS). Users had no way to visually verify whether a pair was:
- satellite vs debris (the primary use case)
- debris vs debris
- satellite vs satellite

### Root Cause 6: "Same-Name" Pairs (COSMOS 2251 DEB × COSMOS 2251 DEB)

This is **NOT** a self-pair. When the catalog contains multiple fragments from the same debris event, each fragment has:
- **Different NORAD ID** (e.g., 33772, 34420)
- **Same descriptive name** (e.g., "IRIDIUM 33 DEB", "COSMOS 2251 DEB")

The system correctly pairs different IDs, but the UI shows the same name on both sides, making it LOOK like a self-pair. The fix is to **always display the ID alongside the name**.

### Root Cause 7: Show in Globe Lookup Could Silently Fail

When `pendingFocusId` is passed to `VisualizationPage`, it searches `snapshot.objects` for a match. If the catalog refreshed (new session) and IDs changed, no match would be found — and no fallback was provided. The selection would silently fail.

---

## Data Flow Trace: IRIDIUM 33 vs IRIDIUM 33 DEB 001

### BEFORE FIX

```
RAW DATA (CelesTrak/Fallback)
  → TLE Record: name="IRIDIUM 33", source_group="stations" → category="active" by default
  → TLE Record: name="IRIDIUM 33 DEB 001", source_group="iridium_debris" → category="debris"
  ↓
Backend _object_summary():
  → primary: { id="24793", name="IRIDIUM 33", category="active" } — NO object_type field
  → secondary: { id="33772", name="IRIDIUM 33 DEB 001", category="debris" } — NO object_type field
  ↓
Frontend API receives:
  → event.primary.name = "IRIDIUM 33"
  → event.secondary.name = "IRIDIUM 33 DEB 001"
  ↓
CollisionPage title: "IRIDIUM 33 vs IRIDIUM 33 DEB 001" ← looks fine, no IDs or types
ObjectPair: shows names only, no type badges
EventList: shows names only, no types or IDs
AnalyticsPanel: independently calls getObjectTypeLabel() which does name heuristic
SatelliteField: uses category="active"/"debris" for rendering ← DIFFERENT from AnalyticsPanel!
  ↓
Show in Globe: matches by ID "24793" in catalog → found → correct (if catalog has it)
  OR: ID "24793" not found → SILENT FAILURE (nothing happens)
```

### AFTER FIX

```
RAW DATA (CelesTrak/Fallback)
  → TLE Record: name="IRIDIUM 33", source_group="stations" → category="active" (known satellite groups)
  → TLE Record: name="IRIDIUM 33 DEB 001", source_group="iridium_debris" → category="debris" (known debris source)
  ↓
Backend _object_summary():
  → primary: { id="24793", name="IRIDIUM 33", category="active", object_type="ACTIVE_SATELLITE" }
  → secondary: { id="33772", name="IRIDIUM 33 DEB 001", category="debris", object_type="SPACE_DEBRIS" }
  ↓
Frontend identityModel.buildCanonicalIdentity():
  → Reads object_type field FIRST → resolves ACTIVE_SATELLITE / SPACE_DEBRIS
  → Falls back to category → falls back to name heuristics
  ↓
CollisionPage title: 
  "IRIDIUM 33 · ID: 24793 vs IRIDIUM 33 DEB 001 · ID: 33772"
  Description: "ACTIVE SATELLITE vs SPACE DEBRIS — SATELLITE vs DEBRIS"
  ↓
ObjectPair: 
  [ACTIVE SATELLITE badge] IRIDIUM 33 · ID: 24793
  [SPACE DEBRIS badge] IRIDIUM 33 DEB 001 · ID: 33772
  ↓
EventList:
  IRIDIUM 33 · ID: 24793
  IRIDIUM 33 DEB 001 · ID: 33772 | Pc 1.234e-6
  ACTIVE SATELLITE vs SPACE DEBRIS
  ↓
AnalyticsPanel:
  Uses buildCanonicalIdentity() → same type as CollisionAnalysis
  Cross-verifies against catalog via resolveById()
  ↓
SatelliteField:
  Same catalog object → same category → consistent rendering
  ↓
Show in Globe:
  resolveById(pendingId, catalog) → returns identity from canonical lookup
  If not found → returns unresolved identity (not silent substitute)
```

---

## Canonical Identity Model

Created `src/utils/identityModel.js` with the canonical representation:

```javascript
{
  id: string,            // stable NORAD/catalog ID
  name: string,          // human-readable name
  objectType: string,    // ACTIVE_SATELLITE | SPACE_DEBRIS | ROCKET_BODY | FRAGMENT | UNKNOWN
  displayType: string,   // "ACTIVE SATELLITE" | "SPACE DEBRIS" | etc.
  catalogClassification: string,  // raw category field
  orbitalData: { ... },  // band, orbit_type, altitude, inclination, velocity, etc.
}
```

Key functions:
- `buildCanonicalIdentity(raw)` — produces ONE authoritative identity from any source
- `resolveById(id, catalog)` — safe catalog lookup that returns unresolved identity on failure (not silent substitute)
- `getPairType(primary, secondary)` — determines actual pair type
- `isSatelliteDebrisPair(primary, secondary)` — checks primary use case
- `validateEventIdentities(event, catalog)` — validates identity integrity for events

---

## Object Type Classification Source

Classification priority (in `resolveObjectType()`):
1. **`object_type` field** (most authoritative — now emitted by backend)
2. **`category` field** mapped through `categoryToObjectType()` 
3. **TLE source group** (for backend: "iridium_debris" → debris, "stations" → active)
4. **Name-based heuristics** (last resort, only when above are unavailable)

For the backend `category_from_record()` in `orbit.py`:
1. Source group check first (debris source = debris, known satellite groups = active)
2. Name check for rocket body
3. Name check for debris
4. Default to active (only for satellites without clear markers)

---

## Validation Added

In `src/utils/objectClassification.js`:

| Check | Rule | Action |
|-------|------|--------|
| primary exists | Must have primary | Reject |
| secondary exists | Must have secondary | Reject |
| primary.id exists | Must have ID | Reject |
| secondary.id exists | Must have ID | Reject |
| primary.id !== secondary.id | Must be different objects | Reject |
| Same memory reference | primary !== secondary | Reject |
| Same name, different IDs | Warning, not rejection | Log |
| Same object_type | Informational | Log |

---

## Files Modified

| File | Change |
|------|--------|
| `src/utils/identityModel.js` | **NEW** — Canonical identity model |
| `src/utils/objectClassification.js` | Enhanced validation, identity checks |
| `src/App.jsx` | buildLocalConjunctions uses identity model; EventList shows types+IDs; ObjectPair shows type badges; CollisionPage title shows IDs+types; **Added `computeLocalManeuver()` fallback for when backend maneuver API is unavailable** |
| `src/components/UI/AnalyticsPanel.jsx` | Uses buildCanonicalIdentity(); cross-verifies with catalog |
| `src/data/fallbackData.js` | Realistic names (IRIDIUM 33 DEB 001, etc.), NORAD-like IDs, object_type field |
| `src/styles.css` | Added .object-type-badge styles for ACTIVE_SATELLITE, SPACE_DEBRIS, ROCKET_BODY, FRAGMENT |
| `backend/app/services/orbit.py` | Fixed category_from_record() to use source group as primary classifier |
| `backend/app/services/conjunction.py` | Added object_type field to _object_summary() |

## Maneuver Page Fix

### Problem
When the FastAPI backend is not running (local/fallback mode), the Maneuver page showed only `"..."` placeholders because `getManeuver(LOCAL-1, {...})` fails with a 404 (since `LOCAL-1` only exists on the frontend). The `getStructured()` catch handler returns `{ data: null }`, and `setManeuver(null)` causes the ManeuverPage to show empty values.

### Root Cause
The original `useEffect` for maneuver fetching had no fallback:
```javascript
useEffect(() => {
  if (!selectedEvent?.id) return undefined;
  const controller = new AbortController();
  getManeuver(selectedEvent.id, { signal: controller.signal }).then(setManeuver).catch(() => setManeuver(null));
  return () => controller.abort();
}, [selectedEvent]);
```
When the backend is offline, `getManeuver` catches the error via `getStructured()` and returns `{ data: null }`. The `.then(setManeuver)` receives `null`, and the ManeuverPage shows all `"..."` placeholders.

### Fix
1. **Added `computeLocalManeuver(event)` function** that mirrors the backend `optimize_maneuver` logic:
   - Local Foster 2D Pc calculator (same numerical integration as backend)
   - Iterative delta-V search (same 700-step, 0.01 m/s increment search as backend)
   - Fuel calculation using rocket equation (same mass, Isp constants)
   - Burn direction logic (same inclination threshold)
   - Burn time computation (same 45-min-from-now / TCA-2h logic)
   - Returns matching backend schema (`delta_v_m_s`, `fuel_cost_kg`, `probability_before/after`, etc.)

2. **Updated the maneuver useEffect** to fall back to `computeLocalManeuver()` when:
   - Backend returns `null`/empty data
   - Backend API call throws an exception
   - The event has valid primary/secondary objects to compute from

### Data Flow
```
selectedEvent changes
  → fetchManeuver(event.id) called
    → Backend online? → getManeuver API → setManeuver(result) ← real backend data
    → Backend offline? → computeLocalManeuver(event) → setManeuver(local) ← computed locally
    → No event data? → setManeuver(null) ← ManeuverPage shows "..."
```

---

## Display Format

### Collision Analysis page header:
```
IRIDIUM 33 · ID: 24793 vs IRIDIUM 33 DEB 001 · ID: 33772
ACTIVE SATELLITE vs SPACE DEBRIS — SATELLITE vs DEBRIS
```

### Object Information cards:
```
[ACTIVE SATELLITE] IRIDIUM 33 · ID: 24793
LEO | Polar LEO
780.00 km | 86.4 deg | 7.45 km/s
[Pin Watchlist] [Show in Globe]

[SPACE DEBRIS] IRIDIUM 33 DEB 001 · ID: 33772
LEO | Polar LEO
810.00 km | 86.7 deg | 7.38 km/s
[Pin Watchlist] [Show in Globe]
```

### Event list rows:
```
[HIGH] IRIDIUM 33 · ID: 24793
       IRIDIUM 33 DEB 001 · ID: 33772 | Pc 1.234e-3
       ACTIVE SATELLITE vs SPACE DEBRIS
```

### Analytics Panel title:
```
ACTIVE SATELLITE | 24793
IRIDIUM 33
```

---

## Key Identity Integrity Rules Enforced

1. `primary.id !== secondary.id` — never pair an object with itself
2. `primary.id → primary.name` — name is derived from ID, not independent
3. `primary.id → primary.objectType` — type is derived from catalog metadata, not name heuristic
4. Same object has same type in ALL components (Collision Analysis, Globe, Analytics Panel, Reports)
5. If an ID cannot be resolved → unresolved identity is shown (not silent substitution)
6. No array index used as identity
7. No display name used as identity
8. No fallback lookup silently substitutes another object

