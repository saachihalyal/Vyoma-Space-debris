# Heatmap + Scatter Plot Redesign TODO (Viz-only)

## Step 1: Inspect existing visualization code
- [x] Identify Heatmap component: `src/components/Scene/RiskHeatmap.jsx`
- [x] Identify Scatter plot component: `src/components/Scene/SatelliteField.jsx` (3D scatter of objects)

## Step 2: Heatmap redesign (viz-only)
- [ ] Improve scientific risk-band styling using `cell.severity`
- [ ] Use `cell.probability` as primary intensity wherever available
- [ ] Incorporate `debris_density` / `untracked_density` only as secondary emphasis when present
- [ ] Add richer hover/click tooltip content without fabricating missing fields
- [ ] Add light orbital context cues (LEO/MEO/GEO) only if dataset fields support it

## Step 3: Scatter plot redesign (viz-only)
- [ ] Improve multi-dimensional encoding using existing object fields
- [ ] Risk-classify colors via closest existing severity/risk field if present; otherwise keep existing band coloring but enhance emphasis by `collision_probability`
- [ ] Reduce clutter using grouping by `band` + `category` (zoom-aware if feasible)
- [ ] Add improved hover/click tooltip content (omit missing fields gracefully)
- [ ] Stronger selection highlight for `selectedObject`

## Step 4: Performance & stability
- [ ] Ensure instanced rendering remains performant (avoid heavy per-frame loops)
- [ ] Ensure no crashes when optional fields are missing

## Step 5: Manual verification
- [ ] Only `RiskHeatmap.jsx` and `SatelliteField.jsx` changed
- [ ] Visuals are larger, readable, and presentation-quality
- [ ] Tooltips/legends are helpful and non-technical friendly
