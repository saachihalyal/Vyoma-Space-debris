# ORION SSA Demo and Evidence Checklist

## Claims supported by the current implementation

- Stage 2A screens the selected catalog snapshot with SGP4 trajectories in TEME and reports event validity, method, source provenance, sampling, coverage counts, caps, and partial reasons.
- Stage 2B exposes a research Foster 2D Pc calculation when its explicit covariance, hard-body radius, frame, epoch, and state inputs pass validation. TLE-only records normally leave Pc unavailable with reasons; unavailable Pc is not zero.
- Maneuver Analysis evaluates bounded two-body simulations from the exact stored physical event and job. It separates the Stage 2A reference, zero-burn simulation, physics candidates, and optional simulator surrogate, with event/job identity attached.
- Physical event PDFs are generated from the selected stored job/event. The generic event PDF route is reserved for explicitly typed screening proxies.
- Smart Filter applies transparent heuristic rules to the review view and keeps unresolved values conservative. Its results do not change the physical screening catalog.
- ESA event-risk inference, orbital anomaly scoring, physical screening, Pc, proxy ranking, and maneuver simulation are separate outputs with separate meanings.

## Claims to avoid

- Operational collision warnings, operational readiness, industry certification, or validated safety decisions.
- Calibrated collision probability from TLE elements alone, or interpreting unavailable Pc as zero.
- Optimal or flight-ready maneuver recommendations, fuel savings, or probability-of-collision reduction.
- A measured Smart Filter workload/safety reduction or reduction in physical conjunctions.
- ESA event-risk output as Pc, a calibrated probability, or a live-feature validation result.
- Treating simulator-surrogate ranks as measured maneuver outcomes or as the source of physical candidate ordering.

## Re-run checks

From the repository root in PowerShell:

```powershell
Push-Location backend
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
Pop-Location
npm test
npm run build
```

For focused report and identity checks:

```powershell
Push-Location backend
.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_report_status.py tests/test_screening_jobs.py tests/test_archived_job_restore.py -q
Pop-Location
```

These commands use installed project dependencies; they do not install packages or trigger a live long-horizon screen.

## Known limitations

- Browser E2E verification is **BLOCKED / not run** in this project phase.
- Large-catalog, long-horizon screening performance remains unbenchmarked; fixture-scale timings are not a scale guarantee.
- On the mission-grouped ESA held-out test, the fixed log-risk threshold detected 0 of 145 high-risk labels. Historical/live feature equivalence is unestablished; this signal is not operationally validated.
- The maneuver simulator is a bounded two-body RK4 research model. J2, drag, third bodies, covariance propagation, burn execution error, attitude, and propulsion constraints are omitted.
- The optional maneuver ranker uses synthetic simulator labels, scores only generated candidates, and did not outperform the minimum-delta-v baseline in its held-out synthetic test.
- Smart Filter reduction in review workload or risk has not been measured; the UI exposes the applied heuristic rules and reductions remain unquantified.
- Live TLE inputs do not supply covariance or measured hard-body radius, so normal live Pc assessments are unavailable. Imported/user-assumed scenarios retain their separate provenance and assumptions.

## Evidence and method references

- [Screening method and coverage semantics](CONJUNCTION_SCREENING_METHOD.md)
- [Job lifecycle, identity, archive, and report semantics](SCREENING_JOB_LIFECYCLE.md)
- [Physics data model and source limitations](PHYSICS_DATA_MODEL.md)
- [Foster Pc method and applicability](COLLISION_PROBABILITY_METHODS.md)
- [Hybrid system status and feature boundaries](HYBRID_SYSTEM_STATUS.md)
- [Stage 3 ESA risk model card](STAGE3_ML_MODEL_CARD.md)
- [Maneuver surrogate model card](MANEUVER_AI_MODEL_CARD.md)
- [Review-priority policy](REVIEW_PRIORITY_POLICY.md)
