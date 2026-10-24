# Identity Audit and Fix — Implementation Tracking

## Root Cause Summary

1. **No canonical identity model** — Every component reconstructs identity independently
2. **Name-based classification** — `category_from_record()` uses string matching on names
3. **Fallback data loses real identities** — Generic "SSA TRACK" has no relationship to catalog
4. **No type display in UI** — ObjectPair/EventList never show ACTIVE_SATELLITE vs SPACE_DEBRIS
5. **Backend supplement creates mixed identities** — Synthetic objects mixed with real catalog objects
6. **Same-name fragments paired** — COSMOS 2251 DEB × COSMOS 2251 DEB (different IDs, same name)
7. **Show in Globe ID lookup can fail** — No fallback preservation of unresolved IDs

## Implementation Phases

### Phase 1: Canonical Identity Model
- [x] Create `src/utils/identityModel.js`

### Phase 2: Fix Backend Identity Pipeline
- [x] Fix `backend/app/services/orbit.py` — proper category_from_record
- [x] Fix `backend/app/services/conjunction.py` — type-aware pairing + object_type in summary
- [x] Fix `src/data/fallbackData.js` — realistic identities

### Phase 3: Fix Frontend Conjunction Pipeline
- [x] Fix `src/App.jsx` buildLocalConjunctions — use identity model, validate pairs
- [x] Fix `src/App.jsx` imports — add identityModel imports

### Phase 4: Fix UI Components
- [x] Fix `src/App.jsx` — EventList display with types and IDs
- [x] Fix `src/App.jsx` — ObjectPair display with types and IDs
- [x] Fix `src/App.jsx` — CollisionPage title with types and IDs
- [x] Fix `src/App.jsx` — CollisionPage ObjectPair pass onShowInGlobe with correct identity
- [x] Fix `src/components/UI/AnalyticsPanel.jsx` — cross-verify identity via resolveObjectIdentity

### Phase 5: Add Validation Layer
- [x] Fix `src/utils/objectClassification.js` — validateEvent, validateAndFilterEvents
- [x] Fix `src/styles.css` — add object-type-badge styles

### Phase 6: Show in Globe Fix
- [ ] Fix `src/components/Scene/SSAScene.jsx` — identity metadata in positionSharing
- [ ] Fix `src/components/Scene/positionSharing.js` — add identity metadata

### Phase 7: Testing
- [ ] Test satellite vs debris
- [ ] Test rocket body vs satellite
- [ ] Test similar names (IRIDIUM 33 vs IRIDIUM 33 DEB)
- [ ] Test multiple Show in Globe selections
- [ ] Test switching between collision events

