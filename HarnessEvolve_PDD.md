# Project Design Document: HarnessEvolve

## Goal

HarnessEvolve demonstrates recursive agent improvement using simulated returns decisions. A fixed agent reviews cases with a deliberately incomplete harness. Raindrop captures its traces and findings; the optimizer changes the harness manifest, and a deterministic evaluator replays every case before an Atlas version can become active.

## Demo use case: returns and refund operations

The deterministic Atlas fixtures include:

- **Eligible return:** within the standard return window with complete shipment proof; approve a simulated refund.
- **Delivery dispute:** tracking says delivered, but proof of delivery is missing; hold or request evidence.
- **Defect exception:** outside the standard window, but a verified defect qualifies under the documented exception; approve a simulated refund.

Both the fixed control and adaptive harness use the same model and Atlas records. The fixed rules treat a delivered scan as sufficient and omit the policy lookup. The evaluator checks each expected decision and required evidence. A candidate cannot pass by refusing all requests: it must approve the eligible and exception cases and hold/escalate the unsupported dispute. The optimizer can make up to three bounded proposals.

All records are synthetic. A decision is stored in the run output as a simulation; no production order or payment system is connected.

## Architecture

1. The local browser dashboard sends a run request to a loopback-only Python HTTP server.
2. The server runs the existing HarnessEvolve flow in a background thread and returns progress for UI polling.
3. Atlas holds stable synthetic case fixtures in `refund_cases`, version lineage in `harness_versions`, and the active pointer in `harness_state`. Fixture setup uses idempotent upserts.
4. The active manifest defines agent rules, context, guardrails, and allow-listed tools for reading the order, shipment evidence, and policy. `submit_case_decision` records only a local simulated decision.
5. The evaluator emits case-level root causes for missed evidence, incorrect decisions, and missing submissions. Raindrop receives episode/tool/evaluation/diagnosis/proposal/promotion events. An optional Signal query retrieves semantically similar prior failure examples for optimizer context; local evaluator findings remain available if the query or telemetry is down.
6. OpenRouter proposes validated manifest data only. A candidate replaces the Atlas active pointer only after every decision and evidence gate passes.

## Dashboard experience

The dashboard is a dark returns-operations workbench. It shows connection status, active generation, and a Start Demo action. Paired fixed/adaptive panels begin empty and then show the same ordered case queue, evidence lookups, simulated decisions, checks, and activity traces. The adaptive panel also shows Raindrop coaching evidence and manifest changes. A trace feed displays run events; Atlas lineage shows active and rejected versions. Layout is responsive, keyboard accessible, and supports reduced motion. All simulated actions are labeled.

## Setup and operation

Requires Python 3.10+. Configure `OPENROUTER_API_KEY`, `MONGO_URI`, and preferably `RAINDROP_API_KEY` in `.env`. `MONGO_DATABASE` defaults to `harness_evolve`; `RAINDROP_PROJECT_ID` is optional. To retrieve Signal examples, set `RAINDROP_QUERY_API_KEY` plus `RAINDROP_FAILURE_SIGNAL_ID`.

Double-click `start_dashboard.bat` to open the local UI. CLI fallbacks remain: `python harness_evolve.py demo` and `python harness_evolve.py status`.

## Safety and scope

- No payment provider or production order API is called.
- Atlas case fixtures contain synthetic IDs and sample records only.
- Agent tools are explicit and allow-listed. Generated code is never executed.
- The browser never receives credentials; the dashboard binds to loopback.
- Promotion is gated on all required case checks; failed candidates do not replace the active pointer.
- Out of scope: real customer data, actual refunds, live ecommerce APIs, public deployment, accounts, and generalized scenario authoring.
