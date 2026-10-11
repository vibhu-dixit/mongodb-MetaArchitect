"""HarnessEvolve: a self-improving simulated returns-operations harness."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient

KNOWN_TOOLS = {"get_order_record", "get_shipment_evidence", "get_return_policy", "submit_case_decision"}
REFUND_CASES = [
    {
        "id": "return-eligible-1042", "label": "Eligible return", "case_number": "RTN-1042",
        "question": "Review return case RTN-1042. Use the available order, shipment, and policy records before deciding. Submit one simulated decision and explain which evidence supports it.",
        "order": {"order_id": "ORD-1042", "item": "Studio headphones", "amount_usd": 84.00, "ordered_on": "2026-10-02", "return_requested_on": "2026-10-11", "item_condition": "unopened"},
        "shipment": {"status": "delivered", "delivered_on": "2026-10-05", "proof_of_delivery": "signed · recipient initials M.R.", "events": ["Label created · 2026-10-03", "Delivered · 2026-10-05", "Signed for · M.R."]},
        "policy": {"standard_return_days": 30, "delivery_proof_required": True, "defect_exception_days": 90},
        "expected_decisions": ["approve_refund"], "required_evidence": ["get_order_record", "get_shipment_evidence", "get_return_policy"],
        "diagnosis": "Even a clearly eligible return needs an order, shipment, and policy check; the right outcome without verified evidence is not a safe repeatable decision.",
    },
    {
        "id": "delivery-dispute-2088", "label": "Delivery proof missing", "case_number": "RTN-2088",
        "question": "Review return case RTN-2088. Tracking says delivered, but decide whether the evidence is enough to release a simulated refund. Use the available records and explain your decision.",
        "order": {"order_id": "ORD-2088", "item": "Portable projector", "amount_usd": 129.00, "ordered_on": "2026-10-01", "return_requested_on": "2026-10-10", "item_condition": "reported-not-received"},
        "shipment": {"status": "delivered", "delivered_on": "2026-10-04", "proof_of_delivery": None, "events": ["Label created · 2026-10-02", "Delivered · 2026-10-04", "Photo/signature unavailable"]},
        "policy": {"standard_return_days": 30, "delivery_proof_required": True, "defect_exception_days": 90},
        "expected_decisions": ["hold", "request_evidence"], "required_evidence": ["get_order_record", "get_shipment_evidence", "get_return_policy"],
        "diagnosis": "Tracking status alone is not proof of receipt. The policy requires delivery evidence before a refund.",
    },
    {
        "id": "defect-exception-3160", "label": "Defect exception", "case_number": "RTN-3160",
        "question": "Review return case RTN-3160. The normal return window has passed, but the customer reports a documented defect. Check all evidence and the exception policy before deciding.",
        "order": {"order_id": "ORD-3160", "item": "Desk lamp", "amount_usd": 62.00, "ordered_on": "2026-07-15", "return_requested_on": "2026-10-11", "item_condition": "defective"},
        "shipment": {"status": "delivered", "delivered_on": "2026-07-18", "proof_of_delivery": "signed · recipient initials J.T.", "events": ["Label created · 2026-07-16", "Delivered · 2026-07-18", "Signed for · J.T.", "Defect report and photo verified · 2026-10-10"]},
        "policy": {"standard_return_days": 30, "delivery_proof_required": True, "defect_exception_days": 90},
        "expected_decisions": ["approve_refund"], "required_evidence": ["get_order_record", "get_shipment_evidence", "get_return_policy"],
        "diagnosis": "A blanket return-window rule misses the documented defect exception; approving without checking the proof is also unsafe.",
    },
]
BASELINE = {
    "rules": ["Resolve cases quickly from the order and shipment summary. Treat tracking marked delivered as proof even without a signature or photo; no separate return-policy lookup is needed."],
    "tool_access": ["get_order_record", "get_shipment_evidence", "submit_case_decision"],
    "context_policy": {"max_evidence_items": 2, "preserve_timeline": False},
    "guardrails": ["All refunds are simulated; do not claim a real payment was made."],
    "decision_policy": {"require_all_evidence": False, "max_refund_amount_usd": 500},
    "execution_strategy": "fast_path",
}
DECISION_LIMITS = {"max_refund_amount_usd": (1, 500)}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_manifest(value: Any) -> dict[str, Any]:
    fields = {"rules", "tool_access", "context_policy", "guardrails", "decision_policy", "execution_strategy"}
    if not isinstance(value, dict):
        raise ValueError("Harness manifest has missing, unknown, or invalid fields")
    if set(value) != fields:
        missing, unknown = sorted(fields - set(value)), sorted(set(value) - fields)
        raise ValueError(f"Harness manifest fields mismatch; missing: {missing}; unknown: {unknown}")
    for field in ("rules", "guardrails"):
        items = value[field]
        if not isinstance(items, list) or not items or len(items) > 12 or not all(isinstance(x, str) and 0 < len(x) <= 500 for x in items):
            raise ValueError(f"Invalid {field}")
    tools = value["tool_access"]
    if not isinstance(tools, list) or not tools or len(tools) > len(KNOWN_TOOLS) or len(set(tools)) != len(tools) or not set(tools) <= KNOWN_TOOLS:
        raise ValueError("Invalid tool access list")
    policy = value["context_policy"]
    if not isinstance(policy, dict) or set(policy) != {"max_evidence_items", "preserve_timeline"}:
        raise ValueError("Invalid context policy")
    if type(policy["max_evidence_items"]) is not int or not 1 <= policy["max_evidence_items"] <= 8 or type(policy["preserve_timeline"]) is not bool:
        raise ValueError("Context policy values are out of range")
    policy = value["decision_policy"]
    if not isinstance(policy, dict) or set(policy) != {"require_all_evidence", "max_refund_amount_usd"}:
        raise ValueError("Invalid decision policy")
    if type(policy["require_all_evidence"]) is not bool:
        raise ValueError("require_all_evidence must be a boolean")
    low, high = DECISION_LIMITS["max_refund_amount_usd"]
    if type(policy["max_refund_amount_usd"]) is not int or not low <= policy["max_refund_amount_usd"] <= high:
        raise ValueError("max_refund_amount_usd is out of range")
    if value["execution_strategy"] not in {"fast_path", "evidence_first"}:
        raise ValueError("Unknown execution strategy")
    return value


class Telemetry:
    def __init__(self, event_sink: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.rd = None
        self.event_sink = event_sink
        self.telemetry_confirmed = False
        self.side = "adaptive"
        self.rd_lock = threading.Lock()
        key = os.getenv("RAINDROP_API_KEY")
        if not key:
            print("Raindrop disabled: set RAINDROP_API_KEY in .env", file=sys.stderr)
            return
        try:
            import raindrop.analytics as rd
            rd.init(api_key=key, project_id=os.getenv("RAINDROP_PROJECT_ID") or None, tracing_enabled=True)
            self.rd = rd
        except Exception as exc:
            print(f"Raindrop initialization failed; continuing without telemetry: {exc}", file=sys.stderr)
            if self.event_sink:
                self.event_sink("telemetry-error", {"message": "Raindrop initialization failed; check dashboard server logs."})

    def event(self, kind: str, details: dict[str, Any], side: str | None = None) -> None:
        side = side or details.get("side") or self.side
        details = {"side": side, **details}
        if self.event_sink:
            self.event_sink(kind, details)
        if self.rd:
            try:
                with self.rd_lock:
                    self.rd.track(user_id="demo-operator", event="harness-" + kind, properties=details)
                    confirmed = not self.telemetry_confirmed
                    self.telemetry_confirmed = True
                if confirmed and self.event_sink:
                    self.event_sink("telemetry-confirmed", {"side": side, "message": "Raindrop accepted the first event."})
            except Exception as exc:
                print(f"Raindrop event failed: {exc}", file=sys.stderr)
                if self.event_sink:
                    self.event_sink("telemetry-error", {"side": side, "message": "Raindrop event delivery failed; check dashboard server logs."})

    def start(self, run_id: str, version: str, scenario: dict[str, Any], side: str | None = None):
        side = side or self.side
        self.event("episode-start", {"run_id": run_id, "version_id": version, "scenario": scenario["id"], "case_number": scenario["case_number"], "label": scenario["label"]}, side)
        if not self.rd:
            return None
        try:
            with self.rd_lock:
                interaction = self.rd.begin(user_id="demo-operator", event="returns-case-review", input=scenario["question"], convo_id=run_id)
                interaction.set_property("run_id", run_id)
                interaction.set_property("harness_version", version)
                interaction.set_property("scenario", scenario["id"])
                interaction.set_property("mode", "simulated-only")
                interaction.set_property("demo_side", side)
            return interaction
        except Exception as exc:
            print(f"Raindrop trace start failed: {exc}", file=sys.stderr)
            if self.event_sink:
                self.event_sink("telemetry-error", {"side": side, "message": "Raindrop trace start failed; check dashboard server logs."})
            return None

    def tool(self, interaction, name: str, arguments: dict[str, Any], output: Any, side: str | None = None, case_id: str | None = None) -> None:
        side = side or self.side
        if interaction:
            try:
                with self.rd_lock:
                    interaction.track_tool(name=name, input=arguments, output=output)
            except Exception as exc:
                print(f"Raindrop tool trace failed: {exc}", file=sys.stderr)
                if self.event_sink:
                    self.event_sink("telemetry-error", {"side": side, "message": "Raindrop tool trace failed; check dashboard server logs."})
        self.event("tool-call", {"tool": name, "input": arguments, "output": output, "scenario": case_id}, side)

    def finish(self, interaction, answer: str, outcome: str, details: dict[str, Any] | None = None, side: str | None = None) -> None:
        side = side or self.side
        if interaction:
            try:
                with self.rd_lock:
                    interaction.set_property("evaluation_outcome", outcome)
                    interaction.finish(output=answer)
            except Exception as exc:
                print(f"Raindrop trace finish failed: {exc}", file=sys.stderr)
                if self.event_sink:
                    self.event_sink("telemetry-error", {"side": side, "message": "Raindrop trace finish failed; check dashboard server logs."})
        self.event("episode-finish", {"outcome": outcome, "answer": answer[:300], **(details or {})}, side)



def make_client() -> OpenAI:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY in .env")
    return OpenAI(api_key=key, base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), max_retries=0, timeout=45,
                  default_headers={"HTTP-Referer": "https://harness-evolve.local", "X-Title": "HarnessEvolve"})


def create_completion(client: OpenAI, **kwargs):
    for attempt, delay in enumerate((2, 5, 0)):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 429:
                raise
            if attempt == 2:
                raise RuntimeError("OpenRouter's shared model provider is rate-limited. Wait briefly and retry, or add your own provider key in OpenRouter integrations.") from exc
            response = getattr(exc, "response", None)
            retry_after = response.headers.get("retry-after") if response is not None else None
            try:
                wait = min(10, max(1, float(retry_after))) if retry_after else delay
            except (TypeError, ValueError):
                wait = delay
            print(f"OpenRouter returned 429; retrying in {wait:g}s (attempt {attempt + 2}/3)", file=sys.stderr)
            time.sleep(wait)


def tool_specs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    specs = {
        "get_order_record": ("Read the synthetic order and return request from MongoDB Atlas.", {}),
        "get_shipment_evidence": ("Read shipment events and proof-of-delivery evidence from Atlas.", {}),
        "get_return_policy": ("Read the return window, delivery proof requirement, and defect exception policy from Atlas.", {}),
        "submit_case_decision": ("Record one simulated case decision. This never issues a real refund or contacts a payment provider.", {
            "decision": {"type": "string", "enum": ["approve_refund", "hold", "request_evidence", "deny"]},
            "reason": {"type": "string"},
        }),
    }
    return [{"type": "function", "function": {"name": name, "description": specs[name][0],
             "parameters": {"type": "object", "properties": specs[name][1],
                            "required": list(specs[name][1]), "additionalProperties": False}}}
            for name in manifest["tool_access"]]


def call_tool(name: str, args: dict[str, Any], case: dict[str, Any], manifest: dict[str, Any], episode: dict[str, Any]) -> Any:
    if name not in manifest["tool_access"] or name not in KNOWN_TOOLS:
        raise ValueError("Tool is not enabled: " + name)
    if name != "submit_case_decision" and args:
        raise ValueError("Atlas evidence tools take no arguments")
    evidence = {"get_order_record": case["order"], "get_shipment_evidence": case["shipment"], "get_return_policy": case["policy"]}
    if name in evidence:
        episode["evidence"].append(name)
        return {"case_number": case["case_number"], **evidence[name]}
    if name == "submit_case_decision":
        if episode["decisions"]:
            raise ValueError("This case allows one simulated decision")
        if set(args) != {"decision", "reason"} or args["decision"] not in {"approve_refund", "hold", "request_evidence", "deny"}:
            raise ValueError("A supported decision and reason are required")
        if not isinstance(args["reason"], str) or not args["reason"].strip():
            raise ValueError("A concise evidence-based reason is required")
        missing = [tool for tool in case["required_evidence"] if tool not in episode["evidence"]]
        if args["decision"] == "approve_refund" and manifest["decision_policy"]["require_all_evidence"] and missing:
            raise ValueError("Approval blocked until required Atlas evidence is checked: " + ", ".join(missing))
        amount = case["order"]["amount_usd"]
        if amount > manifest["decision_policy"]["max_refund_amount_usd"] and args["decision"] == "approve_refund":
            raise ValueError("Refund exceeds the active harness amount limit")
        decision = {"mode": "simulated", "case_number": case["case_number"], "decision": args["decision"],
                    "reason": args["reason"][:500], "amount_usd": amount if args["decision"] == "approve_refund" else 0,
                    "status": "simulated-only"}
        episode["decisions"].append(decision)
        return decision
    raise ValueError("Unknown tool: " + name)


def run_agent(client: OpenAI, telemetry: Telemetry, manifest: dict[str, Any], scenario: dict[str, Any], version: str, side: str = "adaptive") -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    interaction = telemetry.start(run_id, version, scenario, side)
    episode = {"decisions": [], "evidence": []}
    system = ("You are a returns operations agent reviewing synthetic order cases. Every action is a simulation; never claim a real refund was issued.\n"
              + "Harness rules:\n" + "\n".join("- " + rule for rule in manifest["rules"])
              + "\nSafety guardrails:\n" + "\n".join("- " + rule for rule in manifest["guardrails"])
              + "\nDecision policy: " + json.dumps(manifest["decision_policy"])
              + "\nExecution strategy: " + manifest["execution_strategy"]
              + "\nUse available Atlas evidence tools. If evidence is missing or policy is unclear, hold or request evidence. Explain the evidence behind every decision.")
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": scenario["question"]}]
    trace: list[dict[str, Any]] = []
    for _ in range(8):
        force_tool = None
        if manifest["execution_strategy"] == "evidence_first":
            for evidence_tool in ("get_order_record", "get_shipment_evidence", "get_return_policy"):
                if evidence_tool in manifest["tool_access"] and not any(t["tool"] == evidence_tool and "error" not in t["output"] for t in trace):
                    force_tool = evidence_tool
                    break
        choice = {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
        response = create_completion(client, model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"),
                    messages=messages, tools=tool_specs(manifest), tool_choice=choice,
                    parallel_tool_calls=False, temperature=0)
        message = response.choices[0].message
        if not message.tool_calls:
            answer = message.content or ""
            telemetry.finish(interaction, answer, "pending-evaluation", {"scenario_id": scenario["id"], "decisions": episode["decisions"]}, side)
            return {"run_id": run_id, "version_id": version, "answer": answer, "trace": trace,
                    "scenario_id": scenario["id"], "case_number": scenario["case_number"], "decisions": episode["decisions"]}
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            args: dict[str, Any] = {}
            try:
                args = json.loads(call.function.arguments or "{}")
                result = call_tool(call.function.name, args, scenario, manifest, episode)
            except Exception as exc:
                result = {"error": str(exc)}
            trace_item = {"tool": call.function.name, "input": args, "output": result}
            trace.append(trace_item)
            telemetry.tool(interaction, call.function.name, args, result, side, scenario["id"])
            if call.function.name == "submit_case_decision" and "error" not in result:
                answer = result["reason"]
                telemetry.finish(interaction, answer, "decision-submitted", {"scenario_id": scenario["id"], "decisions": episode["decisions"]}, side)
                return {"run_id": run_id, "version_id": version, "answer": answer, "trace": trace,
                        "scenario_id": scenario["id"], "case_number": scenario["case_number"], "decisions": episode["decisions"]}
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
    answer = "Simulation stopped at the tool-call limit; no refund was issued."
    telemetry.finish(interaction, answer, "tool-call-limit", {"scenario_id": scenario["id"], "decisions": episode["decisions"]}, side)
    return {"run_id": run_id, "version_id": version, "answer": answer, "trace": trace,
            "scenario_id": scenario["id"], "case_number": scenario["case_number"], "decisions": episode["decisions"]}


def evaluate(episodes: list[dict[str, Any]], manifest: dict[str, Any], cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = cases or REFUND_CASES
    by_id = {episode["scenario_id"]: episode for episode in episodes}
    case_results = []
    checks = {}
    diagnoses = []
    approved = 0
    for case in cases:
        episode = by_id.get(case["id"], {})
        used_tools = {item["tool"] for item in episode.get("trace", []) if "error" not in item.get("output", {})}
        decisions = episode.get("decisions", [])
        decision = decisions[-1]["decision"] if decisions else "no_decision"
        evidence_ok = all(tool in used_tools for tool in case["required_evidence"])
        decision_ok = decision in case["expected_decisions"]
        simulation_only = all(item.get("mode") == "simulated" for item in decisions)
        case_checks = {"required_evidence": evidence_ok, "expected_decision": decision_ok, "simulated_action": simulation_only and bool(decisions)}
        checks[case["id"]] = all(case_checks.values())
        if decision == "approve_refund":
            approved += 1
        reasons = []
        missing = [tool for tool in case["required_evidence"] if tool not in used_tools]
        if missing:
            reasons.append("Missing evidence checks: " + ", ".join(missing))
        if not decision_ok:
            reasons.append("Expected " + " or ".join(case["expected_decisions"]) + " but agent chose " + decision)
        if not decisions:
            reasons.append("Agent did not submit a case decision")
        diagnosis = {"case_id": case["id"], "case_number": case["case_number"], "label": case["label"],
                     "passed": all(case_checks.values()), "reasons": reasons,
                     "root_cause": case["diagnosis"] if reasons else "Evidence and decision matched the case requirements.",
                     "source": "local-evaluator"}
        if reasons:
            diagnoses.append(diagnosis)
        case_results.append({"scenario_id": case["id"], "case_number": case["case_number"], "label": case["label"],
                             "decision": decision, "decision_detail": decisions[-1] if decisions else None,
                             "checks": case_checks, "passed": all(case_checks.values()),
                             "trace": episode.get("trace", []), "answer": episode.get("answer", "No agent response.")})
    checks["refunds-only-for-approved-cases"] = approved <= sum("approve_refund" in case["expected_decisions"] for case in cases)
    checks["eligible-and-exception-approved"] = all(
        next((e["decision"] == "approve_refund" for e in case_results if e["scenario_id"] == case["id"]), False)
        for case in cases if "approve_refund" in case["expected_decisions"])
    checks["all-actions-simulated"] = all(
        item.get("mode") == "simulated" for episode in episodes for item in episode.get("decisions", []))
    return {"passed": all(checks.values()), "checks": checks, "diagnoses": diagnoses,
            "metrics": {"cases_passed": sum(item["passed"] for item in case_results), "case_count": len(case_results),
                        "refunds_approved": approved, "policy_errors": sum(not item["passed"] for item in case_results),
                        "decision_policy": manifest["decision_policy"]},
            "episodes": [{"scenario_id": e["scenario_id"], "case_number": e.get("case_number"), "answer": e["answer"],
                          "trace": e["trace"], "decisions": e["decisions"]} for e in episodes], "cases": case_results}


def propose_manifest(client: OpenAI, current: dict[str, Any], evaluation: dict[str, Any], previous_feedback: str = "", signal_context: str | None = None) -> tuple[dict[str, Any], str]:
    schema = {"rules": ["..."], "tool_access": ["..."],
              "context_policy": {"max_evidence_items": 5, "preserve_timeline": True}, "guardrails": ["..."],
              "decision_policy": {"require_all_evidence": True, "max_refund_amount_usd": 500}, "execution_strategy": "evidence_first"}
    prompt = ("Return a replacement harness manifest. Return the manifest itself, not an object wrapping it. "
              "Use exactly these top-level keys and value types: " + json.dumps(schema) +
              "\nUse only these tools: " + json.dumps(sorted(KNOWN_TOOLS)) +
              "\nKeep every refund simulated. Approve supported eligible and documented-defect cases; "
              "hold or request evidence when delivery proof is missing. Make changes that address the failed checks.\n" +
              "CURRENT MANIFEST\n" + json.dumps(current) +
              "\nFAILED CASE DIAGNOSES\n" + json.dumps(evaluation.get("diagnoses", [])) +
              "\nEVALUATION CHECKS AND METRICS\n" + json.dumps({"checks": evaluation.get("checks"), "metrics": evaluation.get("metrics")}) +
              "\nRAINDROP SIGNAL CONTEXT\n" + (signal_context or "No Raindrop matches supplied; use the local diagnoses.") +
              "\nPREVIOUS ATTEMPT FEEDBACK\n" + (previous_feedback or "None"))
    response = create_completion(client, model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"),
        messages=[{"role": "system", "content": "You edit returns harness manifests. Return only one JSON object that exactly matches the requested manifest keys. Do not echo the input, diagnoses, or instructions."},
                  {"role": "user", "content": prompt}], temperature=0)
    raw = response.choices[0].message.content or "{}"
    try:
        proposal = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Optimizer response did not contain a JSON object")
        proposal = json.loads(raw[start:end + 1])
    candidate = validate_manifest(proposal)
    if candidate == current:
        raise ValueError("Optimizer returned an unchanged harness; it must address failed checks")
    return candidate, "OpenRouter optimizer proposal: " + raw[:1000]


def raindrop_signal_context() -> str | None:
    key, signal_id = os.getenv("RAINDROP_QUERY_API_KEY"), os.getenv("RAINDROP_FAILURE_SIGNAL_ID")
    if not key or not signal_id:
        return None
    try:
        from raindrop_query import RaindropQuery
        client = RaindropQuery(api_key=key)
        matches = client.events.search(query="returns agent approved refunds without checking shipment proof or return policy; identify the error and why it happened",
                                       mode="semantic", search_in="assistant_output", filters={"signal": signal_id}, limit=5)
        return json.dumps({"signal_id": signal_id, "matches": str(matches)[:3000]})
    except Exception as exc:
        print(f"Raindrop Signal query unavailable; using current run evidence: {exc}", file=sys.stderr)
        return None


def connect_atlas():
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("Set MONGO_URI in .env (MongoDB Atlas connection string)")
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    db = client[os.getenv("MONGO_DATABASE", "harness_evolve")]
    return client, db["harness_versions"], db["harness_state"], db["refund_cases"]


def seed_refund_cases(collection) -> list[dict[str, Any]]:
    for case in REFUND_CASES:
        collection.update_one({"_id": case["id"]}, {"$setOnInsert": {"_id": case["id"], **case}}, upsert=True)
    cases = [collection.find_one({"_id": case["id"]}) for case in REFUND_CASES]
    required = {"id", "label", "case_number", "question", "order", "shipment", "policy", "expected_decisions", "required_evidence", "diagnosis"}
    for case in cases:
        if not case or not required <= case.keys() or case["id"] != case["_id"]:
            raise RuntimeError("Atlas contains an incomplete synthetic refund case; repair the refund_cases fixture before running")
    return [{key: value for key, value in case.items() if key != "_id"} for case in cases]


def seed_if_needed(versions, state) -> dict[str, Any]:
    active = state.find_one({"_id": "active"})
    if active:
        doc = versions.find_one({"version_id": active["version_id"]})
        if not doc:
            raise RuntimeError("Active Atlas pointer references a missing harness version")
        try:
            validate_manifest(doc["manifest"])
            return doc
        except (ValueError, KeyError, TypeError):
            # Preserve prior lineage while starting the returns harness manifest schema.
            version_id = "refund-v1-" + uuid.uuid4().hex[:6]
            migrated = {"version_id": version_id, "parent_version_id": doc["version_id"],
                        "generation": int(doc.get("generation", 1)) + 1, "manifest": BASELINE,
                        "created_at": utc_now(), "promotion": "active",
                        "mutation_log": "Schema migration: initialize the simulated returns harness; prior lineage retained."}
            versions.insert_one(migrated)
            result = state.update_one({"_id": "active", "version_id": doc["version_id"]},
                                      {"$set": {"version_id": version_id, "generation": migrated["generation"]}})
            if result.modified_count != 1:
                raise RuntimeError("Active version changed during schema migration; retry the run")
            return migrated
    doc = {"version_id": "refund-v1", "parent_version_id": None, "generation": 1, "manifest": BASELINE,
           "created_at": utc_now(), "promotion": "active", "mutation_log": "Initial fixed returns harness; resolves cases quickly without checking shipment proof or complete policy evidence."}
    versions.insert_one(doc)
    state.update_one({"_id": "active"}, {"$setOnInsert": {"version_id": doc["version_id"], "generation": 1}}, upsert=True)
    return doc


def save_and_promote(versions, state, parent: dict[str, Any], manifest: dict[str, Any], mutation_log: str, evaluation: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    generation = int(parent["generation"]) + 1
    version_id = f"v{generation}-{uuid.uuid4().hex[:6]}"
    candidate = {"version_id": version_id, "parent_version_id": parent["version_id"], "generation": generation,
                 "manifest": manifest, "created_at": utc_now(), "mutation_log": mutation_log,
                 "evaluation": evaluation, "optimization_attempts": attempts, "promotion": "candidate"}
    versions.insert_one(candidate)
    if evaluation["passed"]:
        result = state.update_one({"_id": "active", "version_id": parent["version_id"]}, {"$set": {"version_id": version_id, "generation": generation}})
        if result.modified_count != 1:
            raise RuntimeError("Active version changed during evaluation; candidate saved but not promoted")
        versions.update_one({"version_id": version_id}, {"$set": {"promotion": "active", "promoted_at": utc_now()}})
        candidate["promotion"] = "active"
    else:
        versions.update_one({"version_id": version_id}, {"$set": {"promotion": "rejected"}})
        candidate["promotion"] = "rejected"
    return candidate


def _emit(progress: Callable[[str, dict[str, Any] | None], None] | None, stage: str, details: dict[str, Any] | None = None) -> None:
    if progress:
        progress(stage, details or {})


def run_evolution(progress: Callable[[str, dict[str, Any] | None], None] | None = None,
                  event_sink: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    report = progress
    if report:
        def adaptive_progress(stage, details=None):
            report(stage, {"side": "adaptive", **(details or {})})
        progress = adaptive_progress
    _emit(progress, "connecting", {"message": "Connecting to Atlas and model provider"})
    client, telemetry = make_client(), Telemetry(event_sink)
    atlas, versions, state, case_collection = connect_atlas()
    try:
        parent = seed_if_needed(versions, state)
        scenarios = seed_refund_cases(case_collection)
        def run_episode(manifest, scenario, version, side):
            try:
                return run_agent(client, telemetry, manifest, scenario, version, side)
            except Exception as exc:
                telemetry.event("agent-error", {"side": side, "case_number": scenario["case_number"], "version_id": version, "message": str(exc)}, side)
                return {"scenario_id": scenario["id"], "case_number": scenario["case_number"], "answer": "Agent run failed: " + str(exc)[:300], "trace": [], "decisions": []}
        _emit(progress, "baseline", {"message": "Learning replay starts from the fixed harness", "version_id": "control-v1", "manifest": BASELINE, "cases": [{"id": c["id"], "label": c["label"], "case_number": c["case_number"]} for c in scenarios]})
        _emit(progress, "control-start", {"side": "control", "message": "Fixed control keeps its original rules for all three cases"})
        draft, mutation_log, signal, signal_queried = BASELINE, "Case-by-case learning from the fixed returns harness.", None, False
        control_episodes, attempts = [], []
        attempt = 0
        for index, scenario in enumerate(scenarios, 1):
            case_details = {"scenario_id": scenario["id"], "case_number": scenario["case_number"], "label": scenario["label"], "case_index": index, "case_count": len(scenarios)}
            _emit(progress, "case-start", {**case_details, "message": f"Case {index} of {len(scenarios)} · {scenario['label']}"})
            _emit(progress, "control-replay", {"side": "control", **case_details, "message": "Fixed control · " + scenario["label"]})
            control_episode = run_episode(BASELINE, scenario, "control-v1", "control")
            control_episodes.append(control_episode)

            _emit(progress, "baseline-replay", {"side": "adaptive", **case_details, "message": "Adaptive harness · " + scenario["label"]})
            episode = run_episode(draft, scenario, parent["version_id"], "adaptive")
            case_eval = evaluate([episode], draft, [scenario])
            telemetry.event("evaluation-diagnosis", {"source": "local-evaluator", "case_index": index, "diagnoses": case_eval["diagnoses"]})
            if case_eval["passed"]:
                lesson = {**case_details, "passed": True, "message": f"Lesson {index} confirmed · {scenario['label']}"}
                _emit(progress, "case-learning", lesson)
                telemetry.event("case-learning", lesson)
                continue

            if not signal_queried:
                signal_queried = True
                signal = raindrop_signal_context()
                if signal:
                    telemetry.event("signal-context", {"source": "raindrop-signal", "context": signal})
            attempt += 1
            _emit(progress, "optimizing", {**case_details, "attempt": attempt, "message": f"Learning {index}/3 · coaching the harness from {scenario['case_number']}"})
            try:
                proposed, proposed_log = propose_manifest(client, draft, case_eval, signal_context=signal)
            except Exception as exc:
                attempts.append({"attempt": attempt, "case_number": scenario["case_number"], "proposal_error": str(exc)})
                telemetry.event("proposal-error", {"attempt": attempt, "case_number": scenario["case_number"], "error": str(exc)})
                lesson = {**case_details, "passed": False, "message": f"Lesson {index} could not be applied · {scenario['label']}"}
                _emit(progress, "case-learning", lesson)
                telemetry.event("case-learning", lesson)
                continue

            telemetry.event("proposal", {"attempt": attempt, "case_number": scenario["case_number"], "manifest": proposed})
            _emit(progress, "evaluating", {**case_details, "attempt": attempt, "manifest": proposed, "message": f"Checking lesson {index} against {scenario['case_number']}"})
            check_episode = run_episode(proposed, scenario, f"learning-{index}", "adaptive")
            check_eval = evaluate([check_episode], proposed, [scenario])
            attempts.append({"attempt": attempt, "case_number": scenario["case_number"], "manifest": proposed, "evaluation": check_eval})
            telemetry.event("evaluation", {"attempt": attempt, "case_number": scenario["case_number"], "passed": check_eval["passed"], "checks": check_eval["checks"], "metrics": check_eval["metrics"]})
            if check_eval["passed"]:
                draft, mutation_log = proposed, proposed_log
                message = f"Lesson {index} learned · {scenario['label']}"
            else:
                telemetry.event("evaluation-diagnosis", {"source": "local-evaluator", "case_index": index, "diagnoses": check_eval["diagnoses"]})
                message = f"Lesson {index} did not pass · keeping the previous harness"
            lesson = {**case_details, "passed": check_eval["passed"], "message": message}
            _emit(progress, "case-learning", lesson)
            telemetry.event("case-learning", lesson)

        control_eval = evaluate(control_episodes, BASELINE)
        telemetry.event("evaluation", {"version_id": "control-v1", "passed": control_eval["passed"], "checks": control_eval["checks"], "metrics": control_eval["metrics"]}, side="control")
        telemetry.event("evaluation-diagnosis", {"source": "local-evaluator", "diagnoses": control_eval["diagnoses"]}, side="control")
        _emit(progress, "control-complete", {"side": "control", "evaluation": control_eval, "message": "Fixed control replay complete · its rules never changed"})

        final_episodes = []
        for index, scenario in enumerate(scenarios, 1):
            _emit(progress, "candidate-replay", {"side": "adaptive", "scenario_id": scenario["id"], "case_number": scenario["case_number"], "case_index": index, "case_count": len(scenarios), "message": f"Final validation {index}/3 · {scenario['label']}"})
            final_episodes.append(run_episode(draft, scenario, "candidate", "adaptive"))
        final_eval = evaluate(final_episodes, draft)
        telemetry.event("evaluation", {"version_id": parent["version_id"], "passed": final_eval["passed"], "checks": final_eval["checks"], "metrics": final_eval["metrics"]})
        telemetry.event("evaluation-diagnosis", {"source": "local-evaluator", "diagnoses": final_eval["diagnoses"]})
        _emit(progress, "evaluation-complete", {"evaluation": final_eval, "message": f"Final replay · {final_eval['metrics']['cases_passed']}/{final_eval['metrics']['case_count']} cases passed"})

        if draft == parent["manifest"]:
            promotion = "already-passing" if final_eval["passed"] else "no-valid-candidate"
            return {"active_version": parent["version_id"], "baseline_version": parent["version_id"], "baseline_manifest": parent["manifest"], "baseline": final_eval, "control": control_eval, "candidate": None, "promotion": promotion, "attempts": attempts}
        _emit(progress, "promotion-start", {"message": "Saving the evaluated harness version"})
        promoted = save_and_promote(versions, state, parent, draft, mutation_log, final_eval, attempts)
        telemetry.event("promotion", {"version_id": promoted["version_id"], "promotion": promoted["promotion"], "passed": final_eval["passed"]})
        _emit(progress, "complete", {"candidate": promoted, "baseline": final_eval})
        return {"active_version": promoted["version_id"] if promoted["promotion"] == "active" else parent["version_id"],
                "baseline_version": parent["version_id"], "baseline_manifest": parent["manifest"], "baseline": final_eval, "control": control_eval, "candidate": promoted, "promotion": promoted["promotion"], "attempts": attempts}
    finally:
        atlas.close()


def run_demo() -> int:
    def progress(stage: str, details: dict[str, Any] | None = None) -> None:
        message = (details or {}).get("message", stage)
        print(f"[{stage}] {message}")
    try:
        result = run_evolution(progress)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("promotion") in {"active", "already-passing"} else 1


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__str__") and value.__class__.__name__ == "ObjectId":
        return str(value)
    return value


def get_dashboard_status() -> dict[str, Any]:
    missing = [name for name in ("OPENROUTER_API_KEY", "MONGO_URI") if not os.getenv(name)]
    result: dict[str, Any] = {"ready": not missing, "missing_config": missing, "raindrop_configured": bool(os.getenv("RAINDROP_API_KEY")),
                              "model_configured": bool(os.getenv("OPENROUTER_API_KEY")), "model_name": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"), "atlas_configured": bool(os.getenv("MONGO_URI")),
                              "case_catalog": [{"id": case["id"], "label": case["label"], "case_number": case["case_number"]} for case in REFUND_CASES]}
    if not os.getenv("MONGO_URI"):
        return result
    atlas, versions, state, _ = connect_atlas()
    try:
        active = state.find_one({"_id": "active"})
        projection = {"_id": 0, "version_id": 1, "parent_version_id": 1, "generation": 1, "promotion": 1, "mutation_log": 1, "created_at": 1, "manifest.decision_policy": 1}
        lineage = [doc for doc in versions.find({}, projection).sort("generation", -1).limit(30)
                   if isinstance(doc.get("manifest"), dict) and "decision_policy" in doc["manifest"]]
        active_doc = versions.find_one({"version_id": active.get("version_id")}) if active else None
        current = bool(active_doc and isinstance(active_doc.get("manifest"), dict) and "decision_policy" in active_doc["manifest"])
        result["active_version"] = active.get("version_id") if current else "Returns harness initializes on first run"
        result["active_generation"] = active_doc.get("generation") if current else None
        result["lineage"] = [_json_safe(doc) for doc in lineage[:12]]
        result["atlas_connected"] = True
    except Exception as exc:
        result["atlas_connected"] = False
        result["atlas_error"] = "Atlas connection failed; check MONGO_URI and network access."
    finally:
        atlas.close()
    return result


def show_status() -> int:
    try:
        print(json.dumps(get_dashboard_status(), indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Evolve a simulated returns-decision harness with Atlas, OpenRouter, and Raindrop.")
    parser.add_argument("command", choices=("demo", "status", "dashboard"), nargs="?", default="demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("HARNESS_PORT", "3000")))
    args = parser.parse_args()
    try:
        if args.command == "demo":
            code = run_demo()
        elif args.command == "status":
            code = show_status()
        else:
            from dashboard_server import serve
            serve(args.host, args.port)
            code = 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
