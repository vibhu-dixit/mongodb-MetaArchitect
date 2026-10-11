# HarnessEvolve: Returns Decision Simulator

**Date:** 2026-10-11

## Purpose

Replace the paper-trading story with a returns and refund operations simulation. The demo should make recursive harnessing visible: a fixed agent makes avoidable policy mistakes, Raindrop exposes where and why those mistakes happened, and an adaptive harness uses that diagnostic evidence to improve its next attempt. MongoDB Atlas supplies the synthetic order and shipment records and keeps the harness version lineage. Refund actions are simulated and never call a payment provider.

The episode builder is the scenario creation mechanism. The product story is an agent resolving return cases accurately and safely.

## Success criteria

- Before a run begins, the dashboard shows no case activity or simulated decisions.
- Start Demo runs the fixed and adaptive harnesses against the same deterministic cases.
- The fixed agent has a clear, attributable failure, such as approving a refund without the required delivery evidence.
- Raindrop displays trace events and failure diagnoses that identify the missed evidence or policy check and explain the impact.
- The adaptive harness receives those findings, proposes bounded manifest changes, and replays all cases.
- The UI makes differences visible through case decisions, evidence consulted, policy violations, simulated customer outcomes, evaluator checks, and Atlas generation.
- The active Atlas version changes only when the candidate passes every required case and regression check.
- No real refund or payment endpoint exists.

## Demo cases

Use a small, fixed set of synthetic order records with no personal data:

1. **Eligible return:** the request is within policy and shipment evidence is complete; approve a simulated refund.
2. **Delivery dispute:** tracking says delivered but proof is missing; request evidence or hold the refund rather than approving immediately.
3. **Late return with defect exception:** the normal window elapsed, but a documented defect exception applies; approve only after checking the exception evidence.

Each case defines the expected safe decision and required evidence. Cases are replayed unchanged for both harnesses and every candidate. The fixed manifest starts with incomplete context and weak rules so at least one mistake is deterministic and understandable. The adaptive manifest can gain Atlas lookup tools, evidence-preserving context, and decision guardrails.

## Architecture and behavior

- Replace the BTC scenarios and trading tools in `harness_evolve.py` with refund cases, an explicit tool allow-list, and simulator-only actions. Candidate manifests remain validated data; generated code is never executed.
- Store the synthetic order, shipment, and policy fixtures in a dedicated `refund_cases` collection in the configured `harness_evolve` Atlas database. Seed by stable case IDs with idempotent upserts so repeated demos use the same records. Read those records through the agent's Atlas tools. Keep action outcomes in the run result; do not write refund/payment mutations into an external system.
- Keep version lineage in `harness_versions` and active pointer in `harness_state`. Promotion remains gated on all case checks. Failed candidates remain inspectable without changing the active pointer.
- For every agent episode, send the decision context, tool calls, expected-vs-actual evaluation findings, and reason codes to Raindrop. Query the configured Raindrop failure Signal where credentials are available and pass returned diagnostic context to the optimizer. Also pass current run's evaluator findings directly, so optimization still receives actionable evidence if the Signal query is unavailable. The dashboard labels which source supplied each diagnosis and surfaces telemetry/query errors without blocking the local simulation. Include the Raindrop Query client in the standard package install.
- Existing OpenRouter model configuration, local CLI entry points, loopback-only web server, and server-side secret handling stay in place.

## Dashboard

Replace chart-first market panels with a polished operations workbench:

- A clear returns-operations header and Start Demo control, with Atlas, model, and Raindrop status.
- Two equal comparison panels for Fixed Harness and Raindrop-Guided Harness. Before Start Demo, both show a neutral empty state.
- During a run, each panel shows the same case queue, current case, decision state, ordered evidence/tool activity, and simulated result. Use distinct fixed/adaptive accent colors and live progress without charting financial candles.
- After a run, show case-by-case decision comparison, policy/evidence checks, simulated refunds held or approved, Raindrop's root-cause findings, manifest changes, and promotion outcome.
- Retain an event feed and Atlas lineage, but rename their labels to explain their role in the new scenario.
- Responsive layout, keyboard-operable controls, reduced-motion support, and explicit simulated-action labels remain required.

## Evaluation and safety

Evaluation is deterministic and separate from the language model. Per case it checks the selected decision, whether required evidence was read, prohibited actions, and concise reason-code coverage. Overall promotion requires all safety-critical checks to pass and the eligible and documented-exception cases to be handled correctly. A candidate cannot pass by refusing every refund: at least the eligible and exception cases must be approved, and the unsupported delivery dispute must be held or escalated.

Atlas records contain synthetic IDs and fixtures only. Simulated refund tools return a local settled/held result and cannot issue money. The browser never receives credentials. The server remains loopback-only. Missing Raindrop credentials or query support is reported as degraded telemetry; it does not silently imply Raindrop supplied a diagnosis.

## Scope

In scope: scenario fixtures, Atlas case reads and idempotent fixture seeding, agent tools and evaluation, Raindrop diagnostic feedback, optimizer guidance, Atlas lineage, full dashboard copy/layout update, and setup documentation.

Out of scope: payment processor integration, real customer data, production order access, live ecommerce APIs, generalized simulation authoring, and a reusable multi-domain workflow builder.

## Acceptance checks

1. A fresh dashboard shows no pre-run decisions or case events.
2. Start Demo runs both sides on identical Atlas-backed fixtures and visibly streams both traces.
3. The baseline fails a known evidence/policy check and the adaptive side receives its diagnosis from Raindrop when Signal query is configured.
4. The optimizer's inputs include specific failure reasons and the source of each finding.
5. A candidate that refuses all actions cannot pass; a passing candidate handles eligible, disputed, and exception cases correctly.
6. Candidate promotion changes only the active harness pointer after all evaluation gates pass.
7. Repeated fixture seeding does not create duplicate cases, and no simulated action reaches a payment system.
8. Raindrop outage/query failure is visible and safely falls back to local evaluator findings.
9. The CLI, Atlas lineage, server-side secret handling, and loopback restriction still work.
10. The dashboard remains usable on desktop and narrow layouts with keyboard navigation and reduced motion.
