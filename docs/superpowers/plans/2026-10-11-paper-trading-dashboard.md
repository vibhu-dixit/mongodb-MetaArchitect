# Paper-Trading Dashboard Implementation Plan

> Superseded by [`2026-10-11-returns-simulator.md`](2026-10-11-returns-simulator.md). Retained as a historical plan.

> **For agentic workers:** Implement task-by-task in this session; preserve the existing CLI as a fallback.

**Goal:** Turn HarnessEvolve into a local browser demo that evolves a simulated crypto-trading harness and promotes only candidates that pass risk and control evaluations.

**Architecture:** Keep the existing Python module as the domain and persistence layer, change its deterministic incident fixture to two paper-market episodes, and add a loopback-only standard-library HTTP server with a background run and status polling. Serve a single responsive dashboard that calls only local endpoints; secrets, OpenRouter, Raindrop, and Atlas remain server-side.

**Tech Stack:** Python 3.10+, current OpenAI-compatible OpenRouter client, current Raindrop SDK, PyMongo Atlas, Python standard-library HTTP server, HTML/CSS/vanilla JavaScript.

**Spec:** docs/superpowers/specs/2026-10-11-paper-trading-dashboard-design.md

## Global Constraints

- Simulated trades only; do not add exchange clients, live order endpoints, or exchange credentials.
- Use deterministic local market fixtures; no live market feed.
- Validate manifest tool access and bounded risk parameters before execution.
- Keep API keys on the server and bind the dashboard to loopback by default.
- Promote only after the failure replay and control replay pass; retain rejected versions in Atlas.
- Keep the existing demo and status CLI commands usable.
- Make Raindrop tracing visible in the normal run and surface degraded telemetry when unavailable.

## Review Focus

- Malformed or optimizer-invented tools/risk settings: reject before execution or persistence.
- Concurrent/repeated dashboard starts: allow only one active evolution run and report the current run.
- OpenRouter, Raindrop, or Atlas configuration failure: return a useful UI status without leaking secrets.
- Candidate failure or process interruption: leave the active Atlas pointer unchanged.
- Narrow viewport or keyboard-only use: keep all run/status controls reachable and legible.

---

### Task 1: Replace the incident fixture with a bounded paper-trading harness

**Files:**
- Modify: harness_evolve.py
- Modify: README.md

**Interfaces:**
- Preserve current main(), demo(), status(), manifest validation, Telemetry, and Atlas persistence entry points.
- Add allow-listed scenario tools for deterministic market/volatility/exposure reads and simulator-only paper orders.
- Evaluation result must include per-episode checks and simulated portfolio metrics used by promotion.

- [x] Define fixed false-breakout and normal-trend control fixtures, including the risk threshold and expected actions.
- [x] Replace incident-specific tool schemas, prompts, baseline manifest, optimizer feedback, and evaluator checks with the paper-trading equivalents.
- [x] Extend manifest validation for the bounded paper risk parameters while keeping unknown fields/tools rejected.
- [x] Ensure each candidate is replayed against both fixtures and the active pointer changes only when both pass.

### Task 2: Add a local dashboard server and run state

**Files:**
- Create: dashboard_server.py
- Modify: harness_evolve.py

**Interfaces:**
- GET /api/status returns active harness summary, dependency readiness, lineage, and current run state with secrets omitted.
- POST /api/run starts one background evolution and returns a run ID; a duplicate request returns the existing run state without starting another.
- GET /api/run returns state/progress/results for the active run.
- GET / serves static dashboard assets.

- [x] Implement the loopback-bound ThreadingHTTPServer and JSON request handlers using the existing harness domain functions.
- [x] Run the long evolution flow in a background thread and expose stage progress/results to polling clients.
- [x] Sanitize status/error payloads so credentials and environment values never enter browser responses.
- [x] Add the dashboard command to the existing CLI entry point without changing demo/status behavior.

### Task 3: Build the presenter-facing dashboard

**Files:**
- Create: harness_evolve_ui/index.html
- Create: harness_evolve_ui/styles.css
- Create: harness_evolve_ui/app.js
- Modify: dashboard_server.py

**Interfaces:**
- Use the dashboard server routes defined in Task 2; do not call external APIs from the browser.
- Display scenario episodes, portfolio metrics, manifest changes, per-case evaluation, promotion outcome, lineage, and telemetry state.

- [x] Build a responsive OLED-dark control room with a clear paper-trading label, active generation, connection status, and Run evolution pill button.
- [x] Draw the deterministic price/equity history with inline SVG or canvas and show the false-breakout and control episodes distinctly.
- [x] Poll run state and render progress, candidate manifest diff, checks, paper metrics, Raindrop event trail, and promoted/rejected state.
- [x] Add keyboard focus, accessible names, responsive one-column mobile layout, and restrained transform/opacity motion.

### Task 4: Make startup and presentation straightforward

**Files:**
- Create: start_dashboard.bat
- Modify: README.md
- Modify: .env.example

- [x] Add a Windows launcher that starts the dashboard and opens the local URL without printing environment secrets.
- [x] Document dependencies, required environment variables, launch steps, Atlas persistence, Raindrop visibility, CLI fallback, and simulated-only scope.
- [x] Confirm the README and example environment keys match the server and existing package configuration.

## Completion Notes

No new automated test suite is planned. Do not claim the application is runtime-verified unless the user asks for a run/verification pass.
