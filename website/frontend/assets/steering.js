import { mountLayers } from "./layers.js";
import {
  Revisions,
  ResultCache,
  cacheKey,
  consumeNDJSON,
  wordChanges,
} from "./lifecycle.js";

const $ = (id) => document.getElementById(id);
const elements = Object.fromEntries(
  [
    "draft",
    "alpha",
    "alpha-value",
    "output",
    "output-card",
    "output-context",
    "change-note",
    "latency",
    "status",
    "copy",
    "changes-toggle",
    "changes-check",
    "clear",
    "error-box",
    "error-message",
    "retry",
    "character-count",
    "model-dot",
    "model-status",
    "reconnect",
    "live-indicator",
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
let highlightChanges = true,
  composing = false;

const signed = (n) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
const layers = mountLayers(() => inputChanged("slider"));
const describe = (strengths) =>
  Object.entries(strengths || {})
    .map(([i, a]) => `L${i} ${signed(a)}`)
    .join(" · ") || "Prompt only · no steering";
const desired = () => ({
  message: elements.draft.value.trim(),
  alpha: layers.strengths()[11] ?? 0,
  layer_strengths: layers.strengths(),
});
const currentKey = () =>
  cacheKey(
    desired().message,
    desired().alpha,
    config?.steering_version,
    desired().layer_strengths,
  );

function setStatus(message, busy = false) {
  elements.status.textContent = message;
  elements.status.parentElement.hidden = !message;
  elements["output-card"].setAttribute("aria-busy", String(busy));
  elements["live-indicator"].className =
    `live-indicator ${busy ? "busy" : completed ? "complete" : ""}`;
}
function showError(message) {
  elements["error-box"].hidden = false;
  elements["error-message"].textContent = message;
  setStatus("Could not finish this rewrite. Your draft is still here.");
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
  void fetch("/api/v1/steering/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify({ session_id: session, revision: previous.revision }),
  }).catch(() => {});
}
function renderText(text, before = null) {
  const fragment = document.createDocumentFragment();
  const segments =
    before !== null && highlightChanges
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
    elements.output.textContent = "Finding another way to say it…";
    elements.output.classList.add("placeholder");
    elements["output-context"].textContent = "Preparing your rewrite";
  }
  elements.copy.disabled = true;
}
function refreshControls() {
  elements["character-count"].textContent =
    `${elements.draft.value.length.toLocaleString()} / 2,000`;
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
      document.createTextNode("Your next wording starts here."),
    );
    elements.output.classList.add("placeholder");
    elements["output-context"].textContent = "Write a draft to begin";
    elements["change-note"].textContent =
      "";
    elements.latency.textContent = "";
    elements.copy.disabled = true;
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
      : "Your draft is ready. Waiting for the model.",
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
    alpha: snapshot.alpha,
    layer_strengths: snapshot.layer_strengths,
  };
  renderText(completed.text, completed.source);
  elements["output-context"].textContent =
    event.finish_reason === "length"
      ? "Output limit reached · review this partial rewrite"
      : "Your rewrite";
  elements["change-note"].textContent =
    event.finish_reason === "length"
      ? "This result reached the 64-token limit. Shorten your draft for a complete rewrite."
      : "";
  elements.latency.textContent = fromCache
    ? `Cached · originally ${(event.latency_ms / 1000).toFixed(2)}s`
    : `${(event.latency_ms / 1000).toFixed(2)}s generation`;
  elements.copy.disabled = false;
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
    "change-source-count",
    "change-output-count",
    "change-added-count",
  ])
    $(id).textContent = "—";
  $("change-summary").textContent =
    "Complete a rewrite to inspect its wording.";
}

function updateInspection(event, snapshot, fromCache) {
  $("run-alpha").textContent = describe(snapshot.layer_strengths);
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
    `Last completed rewrite with ${describe(snapshot.layer_strengths)}, compared with the original draft submitted for that run. New input may still be generating.`;
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
  }, 35000);
  setStatus("Requesting a rewrite…", true);
  try {
    const response = await fetch("/api/v1/steering/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        session_id: session,
        revision,
        ...snapshot,
        beta: 0,
      }),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      const detail =
        typeof problem.detail === "string"
          ? problem.detail
          : "Please check the draft length and slider value.";
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
      if (event.event === "started") setStatus("Rewriting your draft…", true);
      if (event.event === "delta") {
        if (firstText) {
          elements.output.replaceChildren();
          elements.output.classList.remove("placeholder");
          elements["output-context"].textContent = "Rewriting · partial text";
          elements["change-note"].textContent =
            "New wording is arriving. Copy becomes available when it is complete.";
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
        throw new Error("This rewrite was cancelled. Retry your latest input.");
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
            ? "The request timed out. Shorten the draft and retry."
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
    elements.alpha.min = config.alpha.min;
    elements.alpha.max = config.alpha.max;
    elements.alpha.step = config.alpha.step;
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
      "Start the website’s Python server, then reconnect. Your draft is kept in this tab.",
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
document.querySelectorAll("[data-sample]").forEach((button) =>
  button.addEventListener("click", () => {
    elements.draft.value = button.dataset.sample;
    inputChanged();
    void dispatch();
  }),
);
elements.retry.addEventListener("click", () => {
  revisions.next();
  void dispatch();
});
elements.reconnect.addEventListener("click", () => {
  void checkReadiness();
});
elements["changes-toggle"].addEventListener("click", () => {
  highlightChanges = !highlightChanges;
  elements["changes-toggle"].setAttribute(
    "aria-pressed",
    String(highlightChanges),
  );
  elements["changes-check"].textContent = highlightChanges ? "✓" : "";
  if (completed && !elements.copy.disabled)
    renderText(completed.text, completed.source);
});
elements.copy.addEventListener("click", async () => {
  if (!completed || elements.copy.disabled) return;
  try {
    await navigator.clipboard.writeText(completed.text);
    setStatus("Copied your completed rewrite.");
  } catch {
    setStatus("Clipboard access was unavailable. Select the text to copy it.");
  }
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
