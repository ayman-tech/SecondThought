import { mountLayers } from "./layers.js";
import "./experiment-ui.js";
import { mountLayerEvidence } from "./layer-evidence.js";
import { mountPromptControls } from "./prompts.js";
import {
  Revisions,
  ResultCache,
  experimentCacheKey,
  consumeNDJSON,
  wordChanges,
} from "./lifecycle.js";

const $ = (id) => document.getElementById(id);
const elements = Object.fromEntries(
  [
    "draft",
    "output",
    "output-card",
    "output-context",
    "change-note",
    "latency",
    "status",
    "clear",
    "error-box",
    "error-message",
    "retry",
    "character-count",
    "model-dot",
    "model-status",
    "reconnect",
  ].map((id) => [id, $(id)]),
);
const revisions = new Revisions();
const cache = new ResultCache();
const session = crypto.randomUUID(); // A tab-local routing key, not an account.
let config = null,
  ready = false,
  active = null,
  completed = null;
let trailingTimer = null,
  maxWaitTimer = null,
  readinessTimer = null;
let composing = false;

const signed = (n) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
const layers = mountLayers(
  () => inputChanged("slider"),
  () => {
    // Flush only work still scheduled. A pause/max-wait may already have
    // dispatched this revision; releasing must not cancel and restart it.
    if (trailingTimer !== null || maxWaitTimer !== null) void dispatch();
  },
);
mountLayerEvidence(layers.vectorChoices);
const prompts = mountPromptControls(() => inputChanged('text'));
const describe = (interventions) => (interventions || []).map(entry => {
  const vector = layers.vectors.find(v=>v.id===entry.vector_id);
  return `${vector?.feature_label || entry.vector_id} L${vector?.layer_index ?? '?'} ${signed(entry.strength)}`;
}).join(' · ') || 'Prompt only · no steering';
const desired = () => ({
  message: elements.draft.value.trim(),
  interventions: layers.interventions(),
  ...prompts.settings(),
});
const currentKey = () =>
  experimentCacheKey(
    desired().message,
    config?.catalog_model_id,
    config?.steering_version,
    desired().interventions,
    prompts.settings(),
  );

function setStatus(message, busy = false) {
  elements.status.textContent = message;
  elements.status.parentElement.hidden = !message;
  elements["output-card"].setAttribute("aria-busy", String(busy));
}
function showError(message) {
  elements["error-box"].hidden = false;
  elements["error-message"].textContent = message;
  setStatus("Could not finish this response. Your input is still here.");
}
function clearError() {
  elements["error-box"].hidden = true;
}
function clearSchedule() {
  clearTimeout(trailingTimer);
  clearTimeout(maxWaitTimer);
  trailingTimer = maxWaitTimer = null;
}
function cancelActive() {
  if (!active) return;
  const previous = active;
  active = null;
  previous.controller.abort();
  // Explicit cancellation also covers a request still queued on the server.
  void fetch("/api/v2/lab/runs/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify({ session_id: session, revision: previous.revision }),
  }).catch(() => {});
}
function renderText(text, before = null) {
  const fragment = document.createDocumentFragment();
  const segments =
    before !== null
      ? wordChanges(before, text)
      : [{ text, added: false }];
  for (const segment of segments) {
    if (segment.added) {
      const span = document.createElement("span");
      span.className = "word-new";
      span.textContent = segment.text;
      fragment.append(span);
    } else fragment.append(document.createTextNode(segment.text));
  }
  elements.output.replaceChildren(fragment);
  elements.output.classList.remove("placeholder");
}
function keepPrevious() {
  const label = completed
    ? "Previous result · updating for your latest input"
    : "Preparing your response";
  // Already showing it: don't rebuild the response on every keystroke.
  if (elements["output-context"].textContent === label) return;
  if (completed) {
    // Keep the changed-word highlights, so the response doesn't flash plain while you type.
    renderText(completed.text, completed.task === "rewrite" ? completed.source : null);
  } else {
    elements.output.textContent = "Generating a response…";
    elements.output.classList.add("placeholder");
  }
  elements["output-context"].textContent = label;
}
function refreshControls() {
  elements["character-count"].textContent =
    `${elements.draft.value.length.toLocaleString()} / ${elements.draft.maxLength.toLocaleString()}`;
}
function inputChanged(kind = "text") {
  revisions.next();
  clearError();
  refreshControls();
  const { message } = desired();
  if (!message) {
    clearSchedule();
    cancelActive();
    completed = null;
    cache.clear();
    elements.output.replaceChildren(
      document.createTextNode("Your response starts here."),
    );
    elements.output.classList.add("placeholder");
    elements["output-context"].textContent = "Enter input to begin";
    elements["change-note"].textContent =
      "";
    elements.latency.textContent = "";
    clearInspection();
    setStatus("");
    return;
  }
  // Invalidate display immediately. Network cancellation happens at dispatch,
  // except text edits, where old-context generation is no longer useful.
  if (kind === "text") cancelActive();
  keepPrevious();
  markScoresStale();
  setStatus(
    ready
      ? "Waiting for a short pause in your input…"
      : "Your input is ready. Waiting for the model.",
    true,
  );
  clearTimeout(trailingTimer);
  trailingTimer = setTimeout(dispatch, kind === "slider" ? 250 : 450);
  if (kind === "slider" && maxWaitTimer === null)
    maxWaitTimer = setTimeout(dispatch, 1000);
}
function finish(event, snapshot, fromCache = false) {
  completed = {
    text: event.rewritten_text,
    source: snapshot.message,
    interventions: snapshot.interventions,
    task: snapshot.task,
  };
  renderText(completed.text, snapshot.task === 'rewrite' ? completed.source : null);
  elements["output-context"].textContent =
    event.finish_reason === "length"
      ? "Output limit reached · review this partial rewrite"
      : "Response";
  elements["change-note"].textContent =
    event.finish_reason === "length"
      ? `This response reached the ${snapshot.max_new_tokens}-token output limit. Increase it in Instructions & limits for a longer response.`
      : "";
  elements.latency.textContent = fromCache
    ? `Cached · originally ${(event.latency_ms / 1000).toFixed(2)}s`
    : `${(event.latency_ms / 1000).toFixed(2)}s generation`;
  updateInspection(event, snapshot, fromCache);
  void scoreResponse(event, snapshot, revisions.value);
  setStatus("");
}

// Response inspector scores. Fired for every completed response (typing and
// slider changes both start a new run); a newer revision discards older scores.
const SIMILARITY_CUTOFF = 0.9, TOXIC_CUTOFF = 0.5; // same cut-offs as the Evaluation page
const scoreIds = ["formality", "toxicity", "similarity", "values"];
const pair = (score) => `${score.input.toFixed(2)} → ${score.response.toFixed(2)}`;
function setScores(values, state, note = null) {
  for (const id of scoreIds) {
    const [value, detail, title] = values[id] ?? [];
    if (value !== undefined) $(`score-${id}`).textContent = value;
    if (detail !== undefined) $(`score-${id}-detail`).textContent = detail;
    if (value !== undefined) $(`score-${id}`).title = title ?? "";
  }
  $("quality-metrics").dataset.state = state;
  if (note !== null) $("score-status").textContent = note;
}
function resetScores(note = "Waiting for a response") {
  setScores({
    formality: ["—", "Input → response, higher is more formal"],
    toxicity: ["—", "Input → response, lower is better"],
    similarity: ["—", "Meaning kept, rewrite task only"],
    values: ["—", "Numbers, dates, amounts, links, IDs"],
  }, "empty", note);
}
function markScoresStale() {
  if ($("quality-metrics").dataset.state === "scored") setScores({}, "stale", "Updating with your input…");
}
function showScores(scores, snapshot, finishReason) {
  const f = scores.formality, t = scores.toxicity, v = scores.values;
  const lowest = f.lowest < f.response - 0.05 ? `Least formal sentence ${f.lowest.toFixed(2)}` : "Higher is more formal";
  const similarity = scores.similarity === null
    ? ["n/a", `Rewrite task only (this is ${snapshot.task})`]
    : [scores.similarity.toFixed(2), scores.similarity >= SIMILARITY_CUTOFF ? "Same meaning (0.90 or more)" : "Meaning may have drifted (below 0.90)"];
  let values = ["n/a", `Rewrite task only (this is ${snapshot.task})`];
  if (v) {
    const changes = [v.missing.length && `Lost: ${v.missing.join(", ")}`, v.added.length && `Added: ${v.added.join(", ")}`].filter(Boolean);
    values = v.count === 0 && !v.added.length
      ? ["None", "No numbers, dates or IDs in the input"]
      : [`${v.kept} of ${v.count} kept`, changes.join(" · ") || "Every value kept exactly"];
  }
  setScores({
    formality: [pair(f), lowest, f.lowest_sentence],
    toxicity: [pair(t), t.response >= TOXIC_CUTOFF ? `Still toxic (${TOXIC_CUTOFF} or more)` : "Lower is better"],
    similarity,
    values,
  }, "scored", finishReason === "length" ? "Scored · partial response" : "Scored");
}
// Curves tab: formality and toxicity of each scored response over time, newest on the right.
const SVG_NS = "http://www.w3.org/2000/svg";
const TREND_LIMIT = 60; // ponytail: keeps the last 60 responses in memory; no persistence across reloads
const trend = [];
let trendStart = null;
const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
const svg = (tag, attrs = {}, text) => {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
};
function recordTrend(scores, snapshot, text) {
  const last = trend.at(-1);
  if (last && last.text === text && last.input === snapshot.message) return; // same response re-shown
  const now = Date.now();
  trendStart ??= now;
  trend.push({ t: (now - trendStart) / 1000, formality: scores.formality, toxicity: scores.toxicity,
    similarity: scores.similarity ?? null, text, input: snapshot.message });
  if (trend.length > TREND_LIMIT) trend.shift();
  drawTrend();
}
function drawTrend() {
  const figure = $("trend-chart");
  $("trend-status").textContent = trend.length
    ? `${trend.length} response${trend.length === 1 ? "" : "s"} · latest at ${clock(trend.at(-1).t)}`
    : "No responses yet";
  if ($("inspect-panel-curves").hidden) return; // drawn when the tab opens; hidden panels have no width
  if (!trend.length) {
    cancelAnimationFrame(trendFrame);
    chartView = null;
    figure.replaceChildren(Object.assign(document.createElement("p"), {
      className: "trend-empty", textContent: "Type in the input. Each completed response adds a point here.",
    }));
    return;
  }
  const width = Math.max(figure.clientWidth, 320);
  if (!chartView || chartView.width !== width || chartView.mode !== trendMode || !figure.contains(chartView.chart)) {
    chartView = buildTrendFrame(figure, width, chartView);
  }
  // The time axis grows in round steps, so older points don't slide sideways on every new one.
  const span = trend.at(-1).t - trend[0].t;
  const t0 = trend[0].t, target = [t0, t0 + ([10, 30, 60, 120, 300, 600, 1200].find((step) => span <= step * 0.9) ?? Math.ceil(span / 600) * 600)];
  // Animate from what is on screen now: known points glide, a new point grows out of the previous line end.
  const view = chartView, fromDomain = view.domain ?? target, from = view.shown;
  const targets = trend.map((p) => ({ t: p.t, ...Object.fromEntries(TREND_SERIES.map((name) => [name, plotted(p, name)])) }));
  const seeds = trend.map((p, i) => from.get(p) ?? from.get(trend[i - 1]) ?? targets[i]);
  const duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 450;
  const started = performance.now();
  cancelAnimationFrame(trendFrame);
  const step = (now) => {
    const k = duration ? Math.min(1, (now - started) / duration) : 1, e = 1 - (1 - k) ** 3;
    const mix = (a, b) => b == null ? null : a == null ? b : a + (b - a) * e; // similarity can be missing
    view.domain = [mix(fromDomain[0], target[0]), mix(fromDomain[1], target[1])];
    view.shown = new Map(trend.map((p, i) => [p, {
      t: mix(seeds[i].t, p.t), ...Object.fromEntries(TREND_SERIES.map((name) => [name, mix(seeds[i][name], targets[i][name])])),
    }]));
    paintTrend(view);
    if (k < 1) trendFrame = requestAnimationFrame(step);
  };
  trendFrame = requestAnimationFrame(step);
}
let chartView = null, trendFrame = 0;
// "change" plots what the rewrite did, oriented so up is better for both: formality gained (response minus
// input) and toxicity removed (input minus response). "score" plots the response's own scores.
// Similarity is already a response-vs-input measure (meaning kept, 0 to 1), so it is the same in both modes.
let trendMode = "change";
const TREND_SERIES = ["formality", "toxicity", "similarity"];
const TREND_MODES = {
  change: { range: [-1, 1], grid: [-1, -0.5, 0, 0.5, 1], baseline: 0, baselineLabel: "No change",
    names: { formality: "Formality change", toxicity: "Toxicity reduction", similarity: "Similarity" },
    label: "Formality change, toxicity reduction and similarity of each completed response over time",
    note: "Above zero is better for both changes: formality change is response minus input, toxicity reduction is input minus response. Similarity is how much of the input's meaning the response keeps (0 to 1, Rewrite task only). Hover a point for its text." },
  score: { range: [0, 1], grid: [0, 0.25, 0.5, 0.75, 1], baseline: 0.5, baselineLabel: "Toxic at 0.5 or more",
    names: { formality: "Formality", toxicity: "Toxicity", similarity: "Similarity" },
    label: "Formality, toxicity and similarity of each completed response over time",
    note: "Each point is one completed response, scored by the same models as the Metrics tab. Similarity is for the Rewrite task only. Hover a point for its text." },
};
const plotted = (p, name) => {
  if (name === "similarity") return p.similarity;
  if (trendMode === "score") return p[name].response;
  return name === "toxicity" ? p.toxicity.input - p.toxicity.response : p.formality.response - p.formality.input;
};
const signedChange = (v) => { const r = Number(v.toFixed(2)); return r === 0 ? "0.00" : `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}`; };
const axisValue = (v) => trendMode === "change" ? signedChange(v) : v.toFixed(2);
const seriesValue = (name, v) => name === "similarity" || trendMode === "score" ? v.toFixed(2) : signedChange(v);
const TREND_H = 240, TREND_M = { top: 14, right: 168, bottom: 36, left: 38 };
const trendY = (v) => {
  const [lo, hi] = TREND_MODES[trendMode].range;
  return TREND_M.top + ((hi - v) / (hi - lo)) * (TREND_H - TREND_M.top - TREND_M.bottom);
};
// Static parts (grid, baseline, axis titles) are drawn once per mode and width; paintTrend only moves the
// existing nodes. Carrying the previous view's positions over lets a mode switch glide instead of jump.
function buildTrendFrame(figure, width, previous) {
  const m = TREND_M, mode = TREND_MODES[trendMode], chart = svg("svg", { viewBox: `0 0 ${width} ${TREND_H}`, width, height: TREND_H });
  for (const v of mode.grid) {
    chart.append(svg("line", { class: "trend-grid", x1: m.left, x2: width - m.right, y1: trendY(v), y2: trendY(v) }),
      svg("text", { class: "trend-axis", x: m.left - 8, y: trendY(v) + 3, "text-anchor": "end" }, axisValue(v)));
  }
  chart.append(svg("line", { class: "trend-threshold", x1: m.left, x2: width - m.right, y1: trendY(mode.baseline), y2: trendY(mode.baseline) }));
  const ticks = [0, 1, 2, 3, 4].map((i) => svg("text", {
    class: "trend-axis", x: m.left + ((width - m.left - m.right) * i) / 4, y: TREND_H - m.bottom + 16,
    "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" }));
  chart.append(...ticks, svg("text", { class: "trend-axis-title", x: m.left + (width - m.left - m.right) / 2, y: TREND_H - 4, "text-anchor": "middle" },
    "Time since the first response (min:sec)"));
  const series = {};
  for (const name of TREND_SERIES) {
    series[name] = { line: svg("path", { class: `trend-line ${name}` }), dots: svg("g"), label: svg("text", { class: `trend-label ${name}` }) };
    chart.append(series[name].line, series[name].dots);
  }
  chart.append(...TREND_SERIES.map((name) => series[name].label));
  figure.replaceChildren(chart);
  return { width, mode: trendMode, chart, ticks, series, domain: previous?.domain ?? null, shown: previous?.shown ?? new Map() };
}
function paintTrend(view) {
  const m = TREND_M, [t0, t1] = view.domain;
  const x = (t) => m.left + ((t - t0) / (t1 - t0 || 1)) * (view.width - m.left - m.right);
  view.ticks.forEach((tick, i) => { tick.textContent = clock(t0 + ((t1 - t0) * i) / 4); });
  const shown = trend.map((p) => [p, view.shown.get(p)]);
  for (const [name, { line, dots }] of Object.entries(view.series)) {
    // A missing value (similarity outside Rewrite) breaks the line instead of bridging it.
    let d = "", pen = "M";
    for (const [, s] of shown) {
      if (s[name] == null) { pen = "M"; continue; }
      d += `${pen}${x(s.t).toFixed(1)},${trendY(s[name]).toFixed(1)}`;
      pen = "L";
    }
    line.setAttribute("d", d);
    while (dots.children.length > shown.length) dots.lastChild.remove();
    while (dots.children.length < shown.length) dots.append(svg("circle", { class: `trend-dot ${name}` }));
    shown.forEach(([p, s], i) => {
      const dot = dots.children[i];
      if (!dot.firstChild) dot.append(svg("title"));
      dot.setAttribute("visibility", s[name] == null ? "hidden" : "visible");
      if (s[name] == null) return;
      dot.setAttribute("cx", x(s.t).toFixed(1));
      dot.setAttribute("cy", trendY(s[name]).toFixed(1));
      dot.setAttribute("r", i === shown.length - 1 ? 5.5 : 4);
      const f = p.formality, t = p.toxicity;
      dot.firstChild.textContent = `${clock(p.t)} · formality ${f.input.toFixed(2)} → ${f.response.toFixed(2)} (${signedChange(f.response - f.input)})`
        + ` · toxicity ${t.input.toFixed(2)} → ${t.response.toFixed(2)} (reduced ${signedChange(t.input - t.response)})`
        + ` · similarity ${p.similarity == null ? "n/a (Rewrite only)" : p.similarity.toFixed(2)}\n${p.text}`;
    });
  }
  // Direct labels ride the line ends, pushed apart top to bottom so they never overlap.
  const end = shown.at(-1)[1], latest = trend.at(-1), names = TREND_MODES[trendMode].names;
  const placed = TREND_SERIES.filter((name) => end[name] != null)
    .map((name) => ({ name, y: trendY(end[name]) + 4 })).sort((a, b) => a.y - b.y);
  placed.forEach((item, i) => { if (i && item.y - placed[i - 1].y < 14) item.y = placed[i - 1].y + 14; });
  for (const name of TREND_SERIES) {
    const label = view.series[name].label, spot = placed.find((item) => item.name === name);
    label.setAttribute("visibility", spot ? "visible" : "hidden");
    if (!spot) continue;
    label.setAttribute("x", (x(end.t) + 10).toFixed(1));
    label.setAttribute("y", spot.y.toFixed(1));
    label.textContent = `${names[name]} ${seriesValue(name, plotted(latest, name))}`;
  }
}
document.querySelectorAll("[data-trend-mode]").forEach((button) => button.addEventListener("click", () => {
  trendMode = button.dataset.trendMode;
  const mode = TREND_MODES[trendMode];
  document.querySelectorAll("[data-trend-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
  $("trend-threshold-label").textContent = mode.baselineLabel;
  for (const name of TREND_SERIES) $(`trend-key-${name}`).textContent = mode.names[name];
  $("trend-note").textContent = mode.note;
  $("trend-chart").setAttribute("aria-label", mode.label);
  drawTrend();
}));
new MutationObserver(drawTrend).observe($("inspect-panel-curves"), { attributes: true, attributeFilter: ["hidden"] });
window.addEventListener("resize", drawTrend);
$("trend-clear").addEventListener("click", () => { trend.length = 0; trendStart = null; drawTrend(); });

async function scoreResponse(event, snapshot, revision) {
  if (event.scores) {
    showScores(event.scores, snapshot, event.finish_reason);
    return recordTrend(event.scores, snapshot, event.rewritten_text);
  }
  if (!event.rewritten_text?.trim()) return resetScores("Nothing to score");
  setScores({}, $("quality-metrics").dataset.state === "empty" ? "empty" : "stale", "Scoring…");
  for (let attempt = 0; attempt < 30; attempt++) {
    let response, body;
    try {
      response = await fetch("/api/v2/lab/score", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: snapshot.message, response: event.rewritten_text, task: snapshot.task }),
      });
      body = await response.json().catch(() => ({}));
    } catch {
      if (revisions.accepts(revision)) resetScores("Couldn't reach the scorer");
      return;
    }
    if (!revisions.accepts(revision)) return; // a newer response is on its way
    if (response.ok) {
      event.scores = body; // cached responses keep their scores
      showScores(body, snapshot, event.finish_reason);
      return recordTrend(body, snapshot, event.rewritten_text);
    }
    if (response.status === 503 && body.detail === "Scoring is loading") {
      setScores({}, "stale", "Loading scoring models…");
      await new Promise((resolve) => setTimeout(resolve, 2000));
      if (!revisions.accepts(revision)) return;
      continue;
    }
    return resetScores(response.status === 503 ? "Scoring unavailable" : "Couldn't score this response");
  }
  if (revisions.accepts(revision)) resetScores("Scoring models still loading");
}

function clearInspection() {
  for (const id of [
    "run-alpha",
    "run-time",
    "run-tokens",
    "run-finish",
    "run-source",
    "run-task", "run-prompt", "run-budgets", "run-runtime",
    "change-source-count",
    "change-output-count",
    "change-added-count",
  ])
    $(id).textContent = "—";
  $("change-summary").textContent =
    "Complete a rewrite to inspect its wording.";
  resetScores();
}

function updateInspection(event, snapshot, fromCache) {
  $("run-runtime").textContent = event.runtime ? `${event.runtime.device ?? 'unknown device'} · ${event.runtime.dtype ?? 'unknown dtype'}` : '—';
  $("run-task").textContent = snapshot.task;
  $("run-prompt").textContent = snapshot.system_prompt ?? 'No system message';
  const format=event.applied?.prompt_format;
  if(format?.mode==='assistant_prefill')
    $("run-prompt").textContent+=`\n\nUser instruction: ${format.user_instruction}\nThe input passage prefills the assistant response; output contains only new text.`;
  if(format?.mode==='rewrite_then_continue')
    $("run-prompt").textContent+=`\n\nContinuation instruction: ${format.continuation_system_prompt}\nUser instruction: ${format.user_instruction}\nBoth stages use the selected vectors and share the output budget.`;
  $("run-budgets").textContent = `${snapshot.max_input_tokens} / ${snapshot.max_new_tokens}`;
  $("change-added-row").hidden = snapshot.task !== 'rewrite';
  $("run-alpha").textContent = describe(snapshot.interventions);
  $("run-alpha").title = snapshot.interventions.map(i=>i.vector_id).join(', ');
  $("run-time").textContent = `${(event.latency_ms / 1000).toFixed(2)}s`;
  $("run-tokens").textContent = event.generated_tokens ?? "—";
  $("run-finish").textContent =
    event.finish_reason === "length" ? "Token limit reached" : "Complete";
  $("run-source").textContent = fromCache ? "Tab cache" : "Model generation";
  const countWords = (text) => (text.match(/\S+/gu) || []).length;
  $("change-source-count").textContent = countWords(snapshot.message);
  $("change-output-count").textContent = countWords(event.rewritten_text);
  $("change-added-count").textContent = wordChanges(
    snapshot.message,
    event.rewritten_text,
  ).filter((segment) => segment.added).length;
  $("change-summary").textContent =
    snapshot.task === 'rewrite'
      ? `Last completed rewrite with ${describe(snapshot.interventions)}, compared with its input.`
      : `Input and response lengths for the completed ${snapshot.task} run. Word differences do not measure steering effects.`;
}
async function dispatch() {
  clearSchedule();
  const snapshot = desired();
  if (!snapshot.message || composing || !ready) return;
  const revision = revisions.next();
  const key = currentKey();
  cancelActive();
  clearError();
  const cached = cache.get(key);
  if (cached) {
    finish(cached, snapshot, true);
    return;
  }
  const controller = new AbortController();
  const run = { controller, revision };
  active = run;
  let text = "",
    terminal = false,
    timedOut = false,
    firstText = true;
  const timeout = setTimeout(() => {
    if (active === run) {
      timedOut = true;
      cancelActive();
    }
  }, config?.request_timeout_ms || 110000);
  setStatus("Requesting a response…", true);
  try {
    const response = await fetch("/api/v2/lab/runs/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        session_id: session,
        revision,
        model_id: config.catalog_model_id,
        catalog_version: config.catalog_version,
        input: snapshot.message,
        task: snapshot.task, system_prompt: snapshot.system_prompt,
        interventions: snapshot.interventions,
        generation: {max_input_tokens:snapshot.max_input_tokens,max_new_tokens:snapshot.max_new_tokens},
      }),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      const detail =
        typeof problem.detail === "string"
          ? problem.detail
          : "Please check the input, instructions and settings.";
      throw new Error(
        response.status === 429
          ? "The model is busy. Wait a moment, then retry."
          : detail,
      );
    }
    if (!response.body)
      throw new Error("Streaming is unavailable in this browser.");
    await consumeNDJSON(response.body.getReader(), (event) => {
      if (!revisions.accepts(revision) || active !== run) return;
      if (event.revision !== revision)
        throw new Error("The server returned a mismatched input revision.");
      if (event.event === "queued")
        setStatus("Waiting for the model’s current request to finish…", true);
      if (event.event === "started") setStatus("Generating…", true);
      if (event.event === "delta") {
        if (firstText) {
          elements.output.replaceChildren();
          elements.output.classList.remove("placeholder");
          elements["output-context"].textContent = "Generating · partial text";
          elements["change-note"].textContent =
            "New wording is arriving. This response is provisional until complete.";
          elements.latency.textContent = "";
          firstText = false;
        }
        text += event.text;
        const span = document.createElement("span");
        span.className = "stream-word";
        span.textContent = event.text;
        elements.output.append(span);
      }
      if (event.event === "completed") {
        event.rewritten_text = event.text;
        terminal = true;
        cache.put(key, event);
        finish(event, snapshot);
      }
      if (event.event === "error") {
        terminal = true;
        throw new Error(event.detail);
      }
      if (event.event === "cancelled") {
        terminal = true;
        throw new Error("This response was cancelled. Retry your latest input.");
      }
    });
    if (revisions.accepts(revision) && active === run && !terminal)
      throw new Error("The response ended early. Please retry.");
  } catch (error) {
    if (revisions.accepts(revision) && (active === run || timedOut)) {
      if (error.name !== "AbortError" || timedOut) {
        keepPrevious();
        showError(
          timedOut
            ? "The request timed out. Reduce the input or output budget and retry."
            : error.message,
        );
      }
    }
  } finally {
    clearTimeout(timeout);
    if (active === run) active = null;
  }
}

async function checkReadiness() {
  clearTimeout(readinessTimer);
  try {
    const response = await fetch("/api/v1/steering/config", {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Connection failed");
    config = await response.json();
    ready = config.status === "ready";
    elements["model-status"].parentElement.hidden = ready;
    elements["model-status"].textContent = ready
      ? ""
      : config.status === "loading"
        ? "Loading model…"
        : "Model unavailable";
    elements["model-dot"].className =
      `status-dot ${ready ? "" : config.status === "loading" ? "loading" : "offline"}`;
    elements.reconnect.hidden = ready || config.status === "loading";
    if (ready && desired().message) {
      revisions.next();
      await dispatch();
    }
    if (!ready && config.status === "loading")
      readinessTimer = setTimeout(checkReadiness, 2000);
  } catch {
    ready = false;
    elements["model-status"].parentElement.hidden = false;
    elements["model-status"].textContent = "Server unavailable";
    elements["model-dot"].className = "status-dot offline";
    elements.reconnect.hidden = false;
    setStatus(
      "Start the website’s Python server, then reconnect. Your input is kept in this tab.",
    );
  }
}

elements.draft.addEventListener("compositionstart", () => {
  composing = true;
  clearSchedule();
});
elements.draft.addEventListener("compositionend", () => {
  composing = false;
  inputChanged();
});
elements.draft.addEventListener("input", () => {
  if (!composing) inputChanged();
});
elements.clear.addEventListener("click", () => {
  elements.draft.value = "";
  inputChanged();
  elements.draft.focus();
});
elements.retry.addEventListener("click", () => {
  revisions.next();
  void dispatch();
});
elements.reconnect.addEventListener("click", () => {
  void checkReadiness();
});
window.addEventListener("pagehide", () => {
  clearSchedule();
  clearTimeout(readinessTimer);
  cancelActive();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    // A Back/Forward cache restore resumes this module rather than reloading it.
    // Restart readiness polling and invalidate any pre-navigation request.
    revisions.next();
    ready = false;
    clearSchedule();
    void checkReadiness();
  }
});

refreshControls();
void checkReadiness();
