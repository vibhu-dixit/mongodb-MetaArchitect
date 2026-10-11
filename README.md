# HarnessEvolve

HarnessEvolve demonstrates recursive harnessing through simulated returns operations. A fixed agent and a Raindrop-guided harness review the same synthetic cases. Atlas stores the case fixtures and harness version lineage; Raindrop captures traces, diagnoses repeated failures, and can return Signal examples to guide the optimizer. A candidate becomes active only after it passes every case and safety check.

## The demo

The three cases cover an eligible return, a delivery dispute with missing proof, and a late return covered by a documented defect exception. The baseline harness is intentionally weak: it treats a delivered scan as sufficient and skips a policy lookup. The optimizer receives case-level findings and Raindrop feedback, proposes bounded changes to its available tools, evidence rules, context, or decision guardrails, then replays every case. It cannot pass by holding all refunds: supported eligible and exception cases must be approved, while the unsupported delivery dispute must be held or escalated.

Refund decisions are local simulations. The app has no payment processor client, production order connection, real customer records, or money movement endpoint. Atlas fixtures use synthetic IDs in the configured `harness_evolve.refund_cases` collection and are inserted idempotently by stable case ID.

## Setup

Requires Python 3.10+. Install from this folder:

    python -m pip install -e .

Configure these values in `.env`:

    OPENROUTER_API_KEY=...
    MONGO_URI=mongodb+srv://...
    RAINDROP_API_KEY=...

The Raindrop SDKs are included in the standard install. To retrieve prior failure examples from a Raindrop Signal, configure its Query API key and Signal ID:

    RAINDROP_QUERY_API_KEY=...
    RAINDROP_FAILURE_SIGNAL_ID=...

The keys stay on the server and are never sent to the browser.

Optional settings:

    OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct
    MONGO_DATABASE=harness_evolve
    RAINDROP_PROJECT_ID=your-project-slug

## Open the dashboard

Double-click `start_dashboard.bat`. It starts the local server and opens http://localhost:3000. Keep the launched window open while presenting; closing it stops the dashboard. The server binds only to loopback.

You can also start it in PowerShell:

    python harness_evolve.py dashboard

Start Demo runs the three Atlas cases in order. The fixed control keeps the original rules; the adaptive side starts from the same weak harness, applies each case lesson in sequence, and replays all three cases before promotion. The dashboard follows the active case and shows each diagnosis, lesson, tool trace, final score, and manifest change. Model requests time out after 45 seconds; a failed replay cannot be promoted. Rejected versions remain in `harness_versions`; `harness_state` continues pointing to the last active version.

## CLI fallback

    python harness_evolve.py demo
    python harness_evolve.py status

`demo` and `status` remain available if the browser UI is unavailable.
