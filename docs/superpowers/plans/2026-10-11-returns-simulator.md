# Returns Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the BTC trading demo with a simulated returns decision harness where Atlas provides case data, Raindrop diagnoses failures, and the adaptive harness improves before promotion.

**Architecture:** Keep the existing loopback dashboard/server and versioned manifest flow. Replace trading domain data/tools/evaluation in `harness_evolve.py`, add Atlas-backed synthetic case seeding and Raindrop diagnostic feedback, then replace candlestick UI with paired case queues and evidence/decision traces.

**Tech Stack:** Python 3.10+, MongoDB Atlas via PyMongo, OpenRouter via OpenAI-compatible client, Raindrop analytics/query clients, vanilla HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-11-refund-operations-harness-design.md`

## Global Constraints

- Refund actions are simulated and never call a payment provider.
- Atlas records contain synthetic IDs and fixtures only; stable case IDs make fixture seeding idempotent.
- The active Atlas version changes only after every safety and regression check passes.
- Candidate manifests remain validated data; generated code is never executed.
- Raindrop diagnostics and local evaluation findings are source-labelled; Signal failure cannot imply a Raindrop diagnosis.
- Browser code never receives credentials; server binds only to loopback.
- Keep existing CLI commands, OpenRouter configuration, and version lineage collections.

## Review Focus

- Malformed or incomplete Atlas case records must fail safely rather than trigger an unsafe simulated refund; pin with case-tool validation checks.
- A delivery dispute with missing proof must not be refunded; pin with the evaluator decision check.
- Refusing every case must fail promotion; pin with eligible and exception-case checks.
- Raindrop Signal query errors or absent configuration must use local findings and label the source; pin with feedback-source checks.
- Repeated fixture setup must not duplicate cases; pin with stable-ID upsert behavior.

---

### Task 1: Refund case domain and evaluator

**Files:**
- Modify: `harness_evolve.py`

**Interfaces:**
- Produces `REFUND_CASES`, `KNOWN_TOOLS`, `BASELINE`, `validate_manifest(value)`, Atlas case fixture seeding, case tools, `evaluate(episodes, manifest)`, and `run_evolution(progress, event_sink)` results containing per-case decisions, evidence, checks, diagnoses, attempts, and promotion.
- Retains `connect_atlas()` version/state collections and `save_and_promote(...)` atomic active-pointer gate.

- [ ] Define three deterministic cases: eligible return, delivery dispute without proof, and late return with documented defect exception. Use stable synthetic case IDs and no personal data.
- [ ] Replace trading tools with Atlas-backed order/shipping/policy lookups plus a local-only simulated decision/refund action. Enforce manifest tool allow-list and validate case fields before use.
- [ ] Seed `refund_cases` using stable-ID upserts in the configured database; retrieve the seeded cases for all run episodes.
- [ ] Replace trading evaluator with per-case expected decision, required evidence, prohibited-action, and reason checks. Require approvals for eligible and documented-exception cases and a hold/escalation for the unsupported dispute.
- [ ] Send traces and evaluation reason codes to Raindrop. Feed explicit local diagnoses plus optional Signal query findings into optimizer proposals and label their source in events/results.
- [ ] Replace old baseline migration text/IDs and optimizer guidance with refund-domain wording; preserve Atlas history and existing promotion gate.
- [ ] Keep demo/status CLI behavior and return output fields needed by the dashboard.

### Task 2: Returns operations dashboard

**Files:**
- Modify: `harness_evolve_ui/index.html`
- Modify: `harness_evolve_ui/app.js`
- Modify: `harness_evolve_ui/styles.css`

**Interfaces:**
- Consumes the unchanged `/api/status` and `/api/run` endpoints and the refund-domain progress/events/results from Task 1.
- Produces paired fixed/adaptive case views, source-labelled Raindrop diagnoses, case outcome comparison, manifest diff, Raindrop event feed, and Atlas lineage.

- [ ] Replace trading title, hero, market/chart DOM, financial labels, and footer with returns-operations language and explicit simulated-action labels.
- [ ] Render both panels empty before a run and show the same ordered cases with live decisions/evidence/traces after Start Demo.
- [ ] Show per-case outcome and policy/evidence checks; show Raindrop diagnosis and whether it came from Signal or local evaluation findings.
- [ ] Retain adaptive manifest diff, evaluation status, trace delivery state, and Atlas lineage using the new decision terminology.
- [ ] Keep layout responsive, keyboard-operable, and reduced-motion aware; remove candlestick drawing and trading-only rendering paths.

### Task 3: Documentation and product copy

**Files:**
- Modify: `README.md`
- Modify: `HarnessEvolve_PDD.md`
- Modify: `pyproject.toml`

- [ ] Replace paper-trading setup and demo narrative with the Atlas-backed returns simulator and synthetic-only actions.
- [ ] Document Raindrop trace delivery, optional Signal query configuration, and local-evaluator fallback.
- [ ] Update package description and CLI help strings to the new use case.
- [ ] Scan user-facing copy and docs for stale BTC, candle, P&L, trading, exchange, and paper-order language.

## Execution notes

- Workspace has no `.git` metadata, so worktree creation, ledger scripts, and commits are unavailable.
- Per task, use focused static/manual inspection only; do not add or run tests unless the user requests testing or verification.
