const $ = selector => document.querySelector(selector);
const runButton = $("#run-button");
let polling = null;
let lastEvents = "";
let lastTrace = "";
let activeRunId = "";
let raindropKeySet = false;
let resetReady = false;
let selectedCaseId = "";
let currentRun = null;
let caseCatalog = [];
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const timeOf = value => { try { return new Date(value).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"}); } catch { return ""; } };

function setReady(status) {
  caseCatalog = status.case_catalog || caseCatalog;
  raindropKeySet = Boolean(status.raindrop_configured);
  $("#connection-label").textContent = status.atlas_connected && status.model_configured ? "SYSTEMS CONNECTED" : status.ready ? "READY" : "CONFIG REQUIRED";
  $("#model-name").textContent = status.model_name || "OpenRouter";
  $("#model-state").textContent = status.model_configured ? "CONNECTED" : "MISSING KEY";
  $("#atlas-state").textContent = status.atlas_connected ? "CONNECTED" : status.atlas_configured ? "UNAVAILABLE" : "MISSING URI";
  $("#raindrop-state").textContent = status.raindrop_configured ? "KEY SET · VERIFY ON RUN" : "DEGRADED · NOT CONFIGURED";
  $("#raindrop-state").classList.toggle("degraded", !status.raindrop_configured);
  const ready = status.model_configured && status.atlas_connected;
  $("#active-status").classList.toggle("ready", ready);
  $("#active-status").innerHTML = "<i></i> " + (ready ? "READY" : "CHECK SETUP");
  $("#active-generation").textContent = status.active_generation ?? status.lineage?.find(item => item.promotion === "active")?.generation ?? "—";
  $("#active-version").textContent = status.active_version || "No active version";
  const note = $("#config-note");
  if (!resetReady || status.error || status.missing_config?.length || !status.atlas_connected) {
    note.hidden = false;
    note.textContent = !resetReady ? "Restart the dashboard server once to enable refresh reset." : status.error || (status.missing_config?.length ? "Missing configuration: " + status.missing_config.join(", ") : "Atlas connection unavailable. Check MONGO_URI and network access.");
  } else note.hidden = true;
  runButton.disabled = !ready || !resetReady;
  renderLineage(status.lineage || []);
  if (!currentRun || currentRun.status === "idle") {
    renderCaseSelector(caseCatalog, null, null, []);
    renderCases("control", null, [], caseCatalog);
    renderCases("adaptive", null, [], caseCatalog);
  }
}

function renderLineage(items) {
  $("#lineage").innerHTML = items.length ? items.map(item => {
    const state = item.promotion || "candidate";
    return '<div class="lineage-item"><span class="lineage-generation">GEN ' + esc(item.generation) + '</span><span class="lineage-copy"><strong>' + esc(item.version_id) + '</strong><span>' + esc(item.mutation_log || "Harness version") + '</span></span><span class="lineage-badge ' + esc(state) + '">' + esc(state.toUpperCase()) + '</span></div>';
  }).join("") : '<div class="empty-state">Atlas has no harness versions yet.</div>';
}

function summarizeEvent(event) {
  const d = event.details || {}, out = d.output || {}, kind = event.type || "event";
  if (kind === "tool-call") {
    const names = {get_order_record:"Order record read", get_shipment_evidence:"Shipment evidence read", get_return_policy:"Return policy read", submit_case_decision:"Simulated decision submitted"};
    if (out.error) return "Lookup/action failed: " + out.error;
    if (out.decision) return out.decision.replaceAll("_", " ") + (out.amount_usd ? " · " + money(out.amount_usd) + " simulated" : " · no payment issued");
    return (names[d.tool] || d.tool || "Atlas tool") + (out.case_number ? " · " + out.case_number : "");
  }
  if (kind === "episode-start") return (d.case_number || d.scenario || "Case") + " · " + (d.label || "review started");
  if (kind === "episode-finish") return (d.case_number || d.scenario_id || "Case") + " · review complete";
  if (kind === "evaluation-diagnosis") {
    const failures = (d.diagnoses || []).length;
    return failures ? failures + " case diagnosis" + (failures === 1 ? "" : "s") + " · coaching evidence recorded" : "No case failures · clean evaluation recorded";
  }
  if (kind === "case-learning") return d.message || ((d.passed ? "Lesson confirmed" : "Lesson not applied") + " · " + (d.case_number || d.label || "case"));
  if (kind === "agent-error") return (d.case_number || "Case") + " · " + d.message;
  if (kind === "signal-context") return "Raindrop Signal returned failure examples for optimizer guidance";
  if (kind === "proposal") return "Harness proposal · " + (d.manifest?.tool_access || []).length + " tools · " + (d.manifest?.execution_strategy || "updated rules");
  if (kind === "evaluation") return "Replay evaluation · " + (d.metrics?.cases_passed ?? 0) + "/" + (d.metrics?.case_count ?? 0) + " cases passed · " + (d.passed ? "eligible" : "needs improvement");
  if (kind === "promotion") return "Atlas " + (d.promotion || "candidate") + " · " + (d.version_id || "");
  if (kind === "telemetry-confirmed") return "Raindrop accepted the first event";
  return d.message || d.error || kind.replaceAll("-", " ");
}

function renderEvents(events) {
  const key = JSON.stringify(events);
  window.latestEvents = events;
  const failure = events.some(item => item.type === "telemetry-error");
  const confirmed = events.some(item => item.type === "telemetry-confirmed");
  const status = $("#trace-status");
  status.textContent = failure ? "DEGRADED" : confirmed ? "STREAMING" : raindropKeySet ? "KEY SET" : "LOCAL ONLY";
  status.classList.toggle("trace-degraded", failure);
  $("#trace-count").textContent = String(events.length).padStart(2, "0");
  $("#trace-provider").textContent = failure ? "RAINDROP DELIVERY ISSUE · LOCAL EVIDENCE ACTIVE" : confirmed ? "RAINDROP CONNECTED · DIAGNOSES AND TRACES" : raindropKeySet ? "RAINDROP KEY SET · DELIVERY UNVERIFIED" : "LOCAL FINDINGS · RAINDROP NOT CONFIGURED";
  if (key === lastEvents) return;
  lastEvents = key;
  $("#event-feed").innerHTML = events.length ? events.slice().reverse().map((event, index) => {
    const kind = event.type || "event", problem = kind.includes("error") || kind === "evaluation-diagnosis";
    return '<div class="event-item ' + (index === 0 ? "event-new " : "") + (problem ? "event-error" : "") + '"><span class="event-time">' + timeOf(event.at) + '</span><div class="event-copy"><strong><i class="event-marker"></i>' + esc(kind.replaceAll("-", " ").toUpperCase()) + '</strong><span>' + esc(summarizeEvent(event)) + '</span></div></div>';
  }).join("") : '<div class="empty-state">Agent decisions, Atlas lookups, diagnoses, and promotion events will appear here.</div>';
  renderSideTraces(events);
  renderDiagnosis(events);
}

function money(value) { return "$" + Number(value || 0).toFixed(2); }
function renderSideTraces(events) {
  const key = JSON.stringify(events);
  if (key === lastTrace) return;
  lastTrace = key;
  for (const [side, id] of [["control", "control-trace"], ["adaptive", "adaptive-trace"]]) {
    const rows = events.filter(event => event.details?.side === side).slice(-7).reverse();
    $("#" + id).innerHTML = rows.length ? rows.map(event => '<div class="side-trace-row"><i class="trace-tick ' + (event.type === "tool-call" ? "trace-tick-tool" : event.type.includes("error") ? "trace-tick-error" : "") + '"></i><span><b>' + esc((event.type || "event").replaceAll("-", " ").toUpperCase()) + '</b><small>' + esc(summarizeEvent(event)) + '</small></span><time>' + timeOf(event.at) + '</time></div>').join("") : '<span class="trace-placeholder">Waiting for the ' + side + ' run…</span>';
  }
}

function renderDiagnosis(events, evaluation) {
  const signal = events.slice().reverse().find(event => event.type === "signal-context");
  const diagnosisEvents = events.filter(event => event.type === "evaluation-diagnosis" && event.details?.side === "adaptive");
  const learned = events.filter(event => event.type === "case-learning" && event.details?.side === "adaptive");
  const latestDiagnoses = new Map();
  for (const event of diagnosisEvents) for (const item of event.details?.diagnoses || []) latestDiagnoses.set(item.case_id, item);
  for (const item of evaluation?.diagnoses || []) latestDiagnoses.set(item.case_id, item);
  const lessons = new Map(learned.map(event => [event.details?.scenario_id, event.details]));
  const items = [...latestDiagnoses.values()];
  const content = [];
  for (const item of items) {
    const lesson = lessons.get(item.case_id);
    content.push('<div class="diagnosis-item"><b>' + esc(item.case_number || item.case_id) + ' · ' + esc(item.label || "Case review") + (lesson ? ' · ' + esc(lesson.passed ? 'LEARNED' : 'GAP') : '') + '</b><span>' + esc(item.root_cause || item.reasons?.join("; ") || "Evidence check failed") + '</span>' + (item.reasons?.length ? '<small>' + esc(item.reasons.join(" · ")) + '</small>' : '') + '</div>');
  }
  for (const [caseId, lesson] of lessons) if (!latestDiagnoses.has(caseId)) content.push('<div class="diagnosis-item"><b>' + esc(lesson.case_number || caseId) + ' · ' + esc(lesson.label || "Case review") + ' · LEARNED</b><span>' + esc(lesson.message) + '</span></div>');
  if (signal) content.push('<div class="signal-context"><b>Retrieved from Raindrop Signal</b><span>' + esc(String(signal.details?.context || "Failure examples added to optimizer context").slice(0, 650)) + '</span></div>');
  $("#adaptive-diagnosis").innerHTML = content.length ? content.join("") : "Raindrop will surface the missing evidence and decision rule behind each failed case.";
  const delivered = events.some(event => event.type === "telemetry-confirmed");
  const failed = events.some(event => event.type === "telemetry-error");
  $("#diagnosis-source").textContent = signal ? "SIGNAL + EVALUATOR" : delivered && !failed ? "RAINDROP TRACE + EVAL" : raindropKeySet && !failed ? "DELIVERY UNVERIFIED · EVAL" : diagnosisEvents ? "LOCAL EVALUATOR ONLY" : "AWAITING RUN";
}

function decisionLabel(value) {
  return ({approve_refund:"Refund approved", hold:"Held for review", request_evidence:"Evidence requested", deny:"Refund denied", no_decision:"No decision", waiting:"Waiting for replay", in_review:"Review in progress"})[value] || "In review";
}
function caseStatus(id, side, evaluation, events) {
  const result = evaluation?.cases?.find(item => item.scenario_id === id);
  if (result) return result.passed ? "PASSED" : "GAP";
  const activity = events.filter(event => event.details?.side === side && event.details?.scenario === id);
  if (activity.some(event => event.type === "tool-call" && event.details?.output?.decision)) return "DECIDED";
  return activity.length ? "LIVE" : "QUEUED";
}
function renderCaseSelector(catalog, controlEval, adaptiveEval, events) {
  const host = $("#case-selector");
  const cases = catalog?.length ? catalog : (controlEval?.cases || adaptiveEval?.cases || []).map(item => ({id:item.scenario_id,label:item.label,case_number:item.case_number}));
  if (!cases.length) {
    selectedCaseId = "";
    $("#case-count").textContent = "READY";
    $("#selected-case-label").textContent = "Select a case to compare both agents";
    host.innerHTML = '<div class="empty-state">Cases load when the demo starts.</div>';
    return;
  }
  if (!cases.some(item => item.id === selectedCaseId)) selectedCaseId = cases[0].id;
  $("#case-count").textContent = String(cases.length).padStart(2, "0") + " CASES";
  const selected = cases.find(item => item.id === selectedCaseId);
  $("#selected-case-label").textContent = selected.case_number + " · " + selected.label;
  host.innerHTML = cases.map((item, index) => {
    const control = caseStatus(item.id, "control", controlEval, events), adaptive = caseStatus(item.id, "adaptive", adaptiveEval, events);
    return '<button class="case-tab ' + (item.id === selectedCaseId ? "selected" : "") + '" type="button" role="tab" aria-selected="' + (item.id === selectedCaseId) + '" data-case-id="' + esc(item.id) + '"><span class="case-tab-index">0' + (index + 1) + '</span><span class="case-tab-copy"><b>' + esc(item.label) + '</b><small>' + esc(item.case_number) + '</small></span><span class="case-tab-results"><i class="fixed-state ' + control.toLowerCase() + '" title="Fixed: ' + control.toLowerCase() + '"></i><i class="adaptive-state ' + adaptive.toLowerCase() + '" title="Adaptive: ' + adaptive.toLowerCase() + '"></i></span><span class="case-tab-arrow" aria-hidden="true">↗</span></button>';
  }).join("");
}
function renderCases(side, evaluation, events, catalog) {
  const host = $("#" + side + "-cases");
  const eventByCase = new Map();
  for (const event of events) {
    const details = event.details || {};
    if (details.side !== side || !details.scenario) continue;
    const entry = eventByCase.get(details.scenario) || {tools: [], decision: null, started: false};
    if (event.type === "episode-start") entry.started = true;
    if (event.type === "tool-call") {
      entry.tools.push(details.tool);
      if (details.output?.decision) entry.decision = details.output.decision;
    }
    eventByCase.set(details.scenario, entry);
  }
  const cases = evaluation?.cases || [];
  const list = catalog?.length ? catalog : cases.map(item => ({id:item.scenario_id,label:item.label,case_number:item.case_number}));
  if (!list.length) { host.innerHTML = '<div class="empty-state">Start the demo to review the return cases.</div>'; return; }
  host.innerHTML = list.filter(item => item.id === selectedCaseId).map(item => {
    const result = cases.find(row => row.scenario_id === item.id), live = eventByCase.get(item.id) || {tools:[], started:false};
    const decision = result?.decision || live.decision?.decision || (live.started ? "in_review" : "waiting");
    const state = result ? (result.passed ? "pass" : "fail") : live.started ? "active" : "waiting";
    const tools = result?.trace?.filter(row => !row.output?.error).map(row => row.tool) || live.tools;
    const checkText = result ? Object.entries(result.checks || {}).map(([name, ok]) => '<span class="check-pill ' + (ok ? "ok" : "bad") + '">' + (ok ? "✓ " : "! ") + esc(name.replaceAll("_", " ")) + '</span>').join("") : tools.map(tool => '<span class="check-pill ok">✓ ' + esc(tool.replaceAll("_", " ")) + '</span>').join("");
    const detail = result?.decision_detail;
    const reason = detail?.reason || live.decision?.reason;
    return '<article class="case-card ' + state + '"><div class="case-top"><span class="case-index">' + esc(item.case_number || item.id) + '</span><span class="case-state">' + (state === "pass" ? "CHECKS PASS" : state === "fail" ? "GAP FOUND" : state === "active" ? "IN REVIEW" : "QUEUED") + '</span></div><h4>' + esc(item.label) + '</h4><div class="case-decision"><span>SIMULATED DECISION</span><b>' + esc(decisionLabel(decision)) + (detail?.amount_usd ? ' · ' + money(detail.amount_usd) : '') + '</b></div>' + (reason ? '<p class="case-reason">' + esc(reason) + '</p>' : '') + '<div class="case-checks">' + (checkText || '<span class="check-muted">Evidence checks appear during the run</span>') + '</div></article>';
  }).join("");
}

function renderMetrics(id, evaluation, adaptive = false, generation = "—") {
  const metrics = evaluation?.metrics || {};
  $("#" + id).innerHTML = '<div><span>CASES PASSED</span><b>' + (evaluation ? metrics.cases_passed + '/' + metrics.case_count : '—') + '</b></div><div><span>SIMULATED REFUNDS</span><b>' + (evaluation ? metrics.refunds_approved : '—') + '</b></div><div><span>' + (adaptive ? 'GENERATION' : 'POLICY ERRORS') + '</span><b>' + (adaptive ? esc(generation) : evaluation ? metrics.policy_errors : '—') + '</b></div>';
}

function setEvaluation(side, evaluation, generation) {
  if (!evaluation) return;
  const prefix = side === "control" ? "baseline" : "candidate";
  const score = $("#" + prefix + "-score");
  score.textContent = evaluation.passed ? "ALL CASES PASS" : "POLICY GAPS FOUND";
  score.classList.toggle("pass", evaluation.passed);
  score.classList.remove("neutral");
  $("#" + prefix + "-heading").textContent = side === "control" ? "Fixed control · no learning" : "Adaptive · " + (generation || "active harness");
  renderMetrics(prefix + "-metrics", evaluation, side === "adaptive", generation);
}

function renderDiff(before, candidate) {
  const host = $("#manifest-diff");
  if (!candidate?.manifest) { $("#diff-count").textContent = "NO PATCH YET"; host.innerHTML = '<div class="empty-state">No candidate change was needed, or the optimizer could not produce a valid proposal.</div>'; return; }
  const old = before?.manifest || {}, next = candidate.manifest;
  const fields = [["RULES","rules"],["AVAILABLE TOOLS","tool_access"],["EVIDENCE CONTEXT","context_policy"],["DECISION POLICY","decision_policy"],["GUARDRAILS","guardrails"],["EXECUTION STRATEGY","execution_strategy"]];
  let count = 0;
  const html = fields.map(([label, key]) => {
    if (JSON.stringify(old[key] ?? null) === JSON.stringify(next[key] ?? null)) return "";
    count++;
    const show = value => typeof value === "string" ? value : JSON.stringify(value);
    return '<div class="diff-group"><h4>' + label + '</h4><div class="diff-value removed">' + esc(show(old[key])) + '</div><div class="diff-value">' + esc(show(next[key])) + '</div></div>';
  }).join("");
  $("#diff-count").textContent = count ? count + " FIELDS UPDATED" : "NO HARNESS CHANGE";
  host.innerHTML = html || '<div class="empty-state">Candidate kept the existing manifest.</div>';
}

const stages = ["queued","connecting","baseline","case-start","control-replay","baseline-replay","optimizing","evaluating","case-learning","control-complete","candidate-replay","evaluation-complete","promotion-start","complete"];
function renderRun(run) {
  currentRun = run;
  if (run.run_id && run.run_id !== activeRunId) {
    activeRunId = run.run_id;
    selectedCaseId = "";
    lastEvents = ""; lastTrace = "";
    $("#baseline-score").textContent = "WAITING"; $("#candidate-score").textContent = "WAITING";
    $("#baseline-score").classList.add("neutral"); $("#candidate-score").classList.add("neutral");
    $("#control-cases").innerHTML = '<div class="empty-state">Loading Atlas case records…</div>';
    $("#adaptive-cases").innerHTML = '<div class="empty-state">Loading Atlas case records…</div>';
    $("#adaptive-diagnosis").textContent = "Collecting first-run evidence…";
    $("#manifest-diff").innerHTML = '<div class="empty-state">Waiting for Raindrop feedback and optimizer proposal.</div>';
  }
  const busy = run.status === "running" || run.status === "queued";
  $("#run-state").textContent = busy ? (run.stage || "running").replaceAll("-", " ").toUpperCase() : run.status === "error" ? "DEMO ERROR" : run.status === "complete" ? "DEMO COMPLETE" : "AWAITING RUN";
  $("#run-state").dataset.running = String(busy);
  runButton.disabled = busy || !resetReady || !$("#model-state").textContent.includes("CONNECTED") || !$("#atlas-state").textContent.includes("CONNECTED");
  $("#run-label").textContent = busy ? "RUNNING BOTH AGENTS" : "START DEMO";
  const stageIndex = Math.max(0, stages.indexOf(run.stage));
  $("#progress-bar").style.width = (busy ? Math.min(92, 8 + stageIndex * 7) : run.status === "complete" ? 100 : 0) + "%";
  const last = run.progress?.at(-1);
  $("#progress-copy").textContent = last?.message || last?.stage || "Atlas cases → Raindrop diagnosis → improve → replay";
  const events = run.events || [], progress = run.progress || [];
  renderEvents(events);
  const catalog = progress.find(item => item.stage === "baseline")?.cases || caseCatalog;
  if (busy) {
    const activeCase = progress.slice().reverse().find(item => ["case-start", "control-replay", "baseline-replay", "optimizing", "evaluating", "case-learning", "candidate-replay"].includes(item.stage) && item.scenario_id);
    if (activeCase) selectedCaseId = activeCase.scenario_id;
  }
  const controlProgress = progress.slice().reverse().find(item => item.stage === "control-complete");
  const activeProgress = progress.slice().reverse().find(item => item.stage === "baseline-complete");
  const candidateProgress = progress.slice().reverse().find(item => item.stage === "evaluation-complete");
  const controlEval = controlProgress?.evaluation;
  let adaptiveEval = candidateProgress?.evaluation || activeProgress?.evaluation;
  if (controlEval) setEvaluation("control", controlEval);
  if (adaptiveEval) setEvaluation("adaptive", adaptiveEval, candidateProgress ? "attempt " + candidateProgress.attempt : activeProgress?.version_id);
  renderCaseSelector(catalog, controlEval, adaptiveEval, events);
  renderCases("control", controlEval, events, catalog);
  renderCases("adaptive", adaptiveEval, events, catalog);
  renderDiagnosis(events, adaptiveEval);
  const proposal = progress.slice().reverse().find(item => item.stage === "evaluating" && item.manifest);
  if (proposal?.manifest) renderDiff({manifest:progress.find(item => item.stage === "baseline")?.manifest}, {manifest:proposal.manifest});
  if (run.error) { $("#adaptive-diagnosis").textContent = run.error; $("#adaptive-diagnosis").classList.add("error-copy"); }
  if (!run.result) return;
  const result = run.result, control = result.control, candidate = result.candidate;
  adaptiveEval = candidate?.evaluation || result.baseline;
  if (control) { setEvaluation("control", control); renderCases("control", control, events, catalog); }
  if (adaptiveEval) { setEvaluation("adaptive", adaptiveEval, candidate?.version_id || result.active_version); renderCases("adaptive", adaptiveEval, events, catalog); renderDiagnosis(events, adaptiveEval); }
  if (candidate?.evaluation) {
    const score = $("#candidate-score");
    score.textContent = candidate.promotion === "active" ? "PROMOTED" : "NOT PROMOTED";
    score.classList.toggle("pass", candidate.promotion === "active");
    score.classList.remove("neutral");
    $("#adaptive-attempt").textContent = candidate.promotion === "active" ? "PROMOTED TO ATLAS" : "ATLAS VERSION RETAINED";
    renderDiff({manifest:result.baseline_manifest}, candidate);
  } else {
    $("#candidate-score").textContent = result.promotion === "already-passing" ? "ACTIVE PASSED" : "ACTIVE UNCHANGED";
    $("#candidate-score").classList.toggle("pass", result.promotion === "already-passing");
    $("#candidate-score").classList.remove("neutral");
    $("#adaptive-attempt").textContent = result.promotion === "already-passing" ? "NO PATCH NEEDED" : "NO PROMOTION";
    $("#manifest-diff").innerHTML = '<div class="empty-state">No new harness version was promoted.</div>';
    $("#diff-count").textContent = "NO PATCH NEEDED";
  }
  refreshStatus();
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Local dashboard request failed");
  return data;
}
async function refreshStatus() {
  try { setReady(await api("/api/status")); }
  catch (error) { $("#connection-label").textContent = "LOCAL SERVER ERROR"; $("#config-note").hidden = false; $("#config-note").textContent = error.message; }
}
async function poll() {
  try {
    const run = await api("/api/run");
    renderRun(run);
    if (run.status === "running" || run.status === "queued") { if (!polling) polling = setInterval(poll, 1400); }
    else { clearInterval(polling); polling = null; }
  } catch (error) { $("#run-state").textContent = "CONNECTION LOST"; $("#adaptive-diagnosis").textContent = error.message; }
}
runButton.addEventListener("click", async () => {
  runButton.disabled = true; $("#run-label").textContent = "STARTING…";
  try { renderRun(await api("/api/run", {method:"POST"})); poll(); }
  catch (error) { $("#adaptive-diagnosis").textContent = error.message; runButton.disabled = false; $("#run-label").textContent = "START DEMO"; }
});
$("#case-selector").addEventListener("click", event => {
  const button = event.target.closest("[data-case-id]");
  if (!button) return;
  selectedCaseId = button.dataset.caseId;
  if (currentRun) renderRun(currentRun);
  else {
    renderCaseSelector(caseCatalog, null, null, []);
    renderCases("control", null, [], caseCatalog);
    renderCases("adaptive", null, [], caseCatalog);
  }
});
async function initialize() {
  try { await api("/api/reset", {method:"POST"}); resetReady = true; }
  catch { resetReady = false; $("#run-state").textContent = "SERVER RESTART REQUIRED"; }
  await refreshStatus();
  if (resetReady) await poll();
}
initialize();
setInterval(refreshStatus, 20000);
