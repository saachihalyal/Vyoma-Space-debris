# ORION SSA - STANDING RULES (read every task)

Project: ORION SSA, a final-year project on AI-based space debris collision prediction with heat map analysis. Extend the existing code. Do not rewrite working parts.

## Environment (fixed)

* Repo root: outputs\space-debris-ssa-platform. Branch: feature/orion-completion. Do not change branch.
* Backend: http://127.0.0.1:8001 (FastAPI, backend\.venv). Frontend: http://127.0.0.1:5173 (Vite + React).
* Start/stop: scripts\start-dev.ps1 and scripts\stop-dev.ps1. Check GET /api/version matches git rev-parse --short HEAD. A stale server gave false results before.
* Data sources: CelesTrak, user uploads, saved snapshots. Do not use Space-Track anywhere.

## Rules

1. At the start of each task run git log --oneline -5 and git status --short. Read STATUS.md and ORION_TASKS.md.
2. Do ONE task from ORION_TASKS.md, report, and wait for me to say "next".
3. Never run git reset --hard, git clean, git checkout ., or force push. Never delete uncommitted work. Commit only the files you changed, with a clear message.
4. Do not use browser or computer-use tools. I will send screenshots.
5. Run tests and builds with output redirected to a log file and a 10-minute timeout, then read the log (for example: ... > backend-tests.log 2>&1). If a command runs longer, stop it and report. Do not download large files or add heavy dependencies.
6. Do not open or print files under backend/exports, backend/ml_data, or docs/evidence. They are large.
7. Never invent numbers, metrics, test results, or "verified in the browser". Print real command output. If you cannot do something, say so.
8. Keep Pc channels separate: source_reported_pc, event_specific_foster_pc, research_pc (assumed inputs), AI predictions, rule-based review priority. A rule-based score is never "AI". Research Pc is never "operational". Risk class words (Low/Medium/High) belong only to the Pc-based class.
9. Never show a dash or "Unavailable" for a value the documented model can calculate. Invalid input gets a specific reason code and a plain-language message.
10. Training and scenario generation run offline through scripts, never during a user request.

## Key numbers

* Default uncertainty for TLE-derived states: radial 0.1 + 0.1*age, in-track 0.5 + 1.5*age, cross-track 0.2 + 0.2*age (km, age in days at TCA). Alternatives stay selectable and labelled.
* Pc floor -30 on log10. Below it display "< 1e-30 (negligible)", score 0, class Low; keep the exact log10 in details.
* Score: clip((log10 Pc + 12) / 10 * 100, 0, 100). Classes: High >= 1e-4, Medium >= 1e-7, else Low. Project policy, not universal standards.
* Fuel: dm = m*(1 - exp(-dv/(Isp*g0))), g0 = 9.80665, defaults 500 kg and 220 s labelled "estimated from default assumptions".

## State

* Done and committed: environment and launcher; covariance policy comparison and TLE-age default; log-domain Pc and display floor; exact-Pc ranking; encounter groups; HBR size overrides; invalid-event reasons; report provenance fields. Backend 334 tests pass, frontend 186 pass.
* Not done: retraining of all AI models (current models were trained on old absurd targets), maneuver fixes, UI redesign, reports and upload polish, final documentation.
