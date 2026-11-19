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
  if (completed) {
    renderText(completed.text);
    elements["output-context"].textContent =
      "Previous result · updating for your latest input";
  } else {
    elements.output.textContent = "Generating a response…";
    elements.output.classList.add("placeholder");
    elements["output-context"].textContent = "Preparing your response";
  }
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
  setStatus("");
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
}

function updateInspection(event, snapshot, fromCache) {
  $("run-runtime").textContent = event.runtime ? `${event.runtime.device ?? 'unknown device'} · ${event.runtime.dtype ?? 'unknown dtype'}` : '—';
  $("run-task").textContent = snapshot.task;
  $("run-prompt").textContent = snapshot.system_prompt ?? 'No system message';
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
