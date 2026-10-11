# HarnessEvolve: Paper-Trading Harness and Local Control Room

> Superseded by [`2026-10-11-refund-operations-harness-design.md`](2026-10-11-refund-operations-harness-design.md). Retained as a historical design record.

**Date:** 2026-10-11

## Purpose and success criteria

HarnessEvolve demonstrates recursive harnessing: an agent’s tools, rules, context policy, and risk guardrails adapt from observed failure, then a regression evaluator decides whether the candidate version becomes active. The demo uses a simulated crypto paper trader and a local browser dashboard so the full loop is understandable without running commands during a presentation.

Success means a presenter can launch the local dashboard, start a deterministic paper-market episode, observe a baseline failure, see the optimizer propose structural harness changes, inspect Raindrop traces and Atlas lineage, and see a candidate promoted only after passing both a failure replay and a control case. The loop uses OpenRouter for model calls and Raindrop for observability. No live exchange integration or real order placement is in scope.

## User and constraints

The user is preparing a short hackathon demo for the Recursive Harnessing prompt and values technical depth, a visible Raindrop role, clear before/after behavior, and an interface that can be operated without a terminal. Existing Python CLI behavior and MongoDB Atlas version history remain available. Runtime configuration remains in the local .env; API keys are never returned to browser code.

## Demo scenario

A deterministic synthetic BTC market replays a false breakout during a volatility spike. Harness v1 has basic price and momentum context but lacks portfolio exposure and volatility tools or an explicit risk budget, so the simulated trader enters too aggressively and breaches the scenario drawdown threshold. A separate control replay contains a genuine trend continuation under normal volatility.

The optimizer receives the failed evaluation and proposes changes to the manifest, such as granting volatility and portfolio-risk tools, preserving recent volatility and exposure in context, and adding bounded position-size / drawdown guardrails. The candidate is re-run against both episodes. Promotion requires risk constraints to pass on both, correct restraint during the false breakout, and participation in the control trend; a failed candidate stays in Atlas history while the prior active version remains unchanged. All positions and fills are simulated against fixed data. The demo must label results as paper trading and must not request exchange credentials.

## Architecture and data flow

- Keep the existing harness_evolve.py as the shared domain layer for manifests, the agent, optimizer, evaluator, Raindrop instrumentation, and Atlas persistence; update the scenario and its allow-listed tools for paper trading.
- Add a small local web server and a single-page dashboard. The browser calls local endpoints to read status/history and start a run. Server-side code owns all model, Raindrop, and Mongo access. The run endpoint returns a run identifier; the UI polls for progress/results so the long model/evaluation cycle does not block a browser request.
- Reuse Atlas harness_versions and harness_state collections. Store scenario evaluation, mutation details, promotion decision, and paper portfolio metrics with each candidate. Never switch the active pointer until the existing promotion gate passes.
- Emit Raindrop spans/events for each paper-trader episode, tool call, optimizer proposal, evaluation, and promotion decision. If telemetry is unavailable, the run may proceed with a visible degraded-telemetry status; Raindrop remains a first-class part of the normal demo.
- Keep CLI demo and status working as alternate operator entry points.

## Dashboard experience

The dashboard opens to an operator’s control room, with the active harness generation and connection status, a clear Run evolution action, and a synthetic BTC market/equity visualization. During a run it presents the failure evidence, candidate manifest diff, evaluation results for failure and control episodes, Raindrop event trail, and final promoted/rejected state. A lineage view makes the active version and rejected candidates legible. Layout is responsive and keyboard accessible; the visual direction is a restrained OLED dark operations interface with warm neutral text, a sharp lime/amber risk signal palette, generous spacing, and custom CSS motion. No generic admin-template layout or remote icon dependency.

## Safety and validation boundaries

- There are no exchange clients, exchange API keys, live order routes, or real-money actions.
- The only market inputs are fixed local scenario fixtures; no network market feed is needed for the deterministic demo.
- Tool access is an explicit allow-list of read-only scenario tools and a simulator-only paper-order tool. Manifest validation bounds tool names, risk parameters, and context policy. Generated code is never executed.
- Dashboard binds to loopback by default. Secret values are not exposed through status endpoints or HTML.
- Promotion is atomic with respect to the active pointer: evaluation must pass before the pointer changes. Failed candidates are retained for inspection.
- UI errors identify missing configuration and external dependency failures without displaying secrets.

## Scope and delivery boundary

In scope: the paper-trading scenario and evaluators, manifest/tool validation, OpenRouter optimizer integration, Raindrop trace coverage, Atlas lineage/promotion, a local dashboard with run progress and results, setup/launch documentation, and a Windows double-click launcher where compatible.

Out of scope: live trading, exchange credentials, real-time market feeds, portfolio advice, user accounts, public deployment, multi-user access control, custom indicator builders, and a generic strategy backtester.

## Acceptance checks

1. Existing CLI demo and status entry points remain available.
2. A browser can launch an evolution run and render progress/result without access to .env secrets.
3. A deterministic false-breakout replay fails the initial risk policy, while the control replay encodes a legitimate trend continuation.
4. The optimizer can propose bounded manifest changes including tool access, context policy, rules, and guardrails; invalid tool names or out-of-range risk settings are rejected.
5. A candidate promotes only after all failure and control criteria pass; otherwise the active Atlas version does not change and the rejected candidate remains visible.
6. Normal runs produce Raindrop spans/events for agent/tool/evolution/evaluation decisions; missing telemetry is clearly surfaced.
7. The dashboard clearly labels every trade and equity figure as simulated paper trading and works at narrow and desktop widths with keyboard-operable controls.
8. Documentation explains local setup, dashboard launch, required keys, paper-only behavior, and CLI fallback.
