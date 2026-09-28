// SecondThought popup. Talks only to the local API; no keys live here.
const API_BASE = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 30000;
const START_HINT = "Start the local server: <code>python -m api.server</code> from the repo root.";

const messageEl = document.getElementById("message");
const rewriteBtn = document.getElementById("rewrite");
const resultEl = document.getElementById("result");
const rewrittenEl = document.getElementById("rewritten");
const metaEl = document.getElementById("meta");
const copyBtn = document.getElementById("copy");
const bannerEl = document.getElementById("banner");
const statusDot = document.getElementById("server-status");

function showBanner(html, kind = "error") {
  bannerEl.innerHTML = html;
  bannerEl.className = kind === "info" ? "banner info" : "banner";
  bannerEl.hidden = false;
}

function hideBanner() {
  bannerEl.hidden = true;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function errorDetail(body, status) {
  const detail = body && body.detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  if (typeof detail === "string") return detail;
  return `Server returned HTTP ${status}.`;
}

async function checkServer() {
  try {
    const response = await fetchWithTimeout(`${API_BASE}/health`, {}, 3000);
    const body = await response.json();
    if (body.status === "ok") {
      statusDot.className = "status-dot ok";
      statusDot.title = `Server OK · ${body.model}`;
    } else {
      statusDot.className = "status-dot down";
      statusDot.title = "Server is running but not configured";
      showBanner(`Server is running but not configured: ${escapeHtml(body.detail || "unknown error")}`);
    }
  } catch {
    statusDot.className = "status-dot down";
    statusDot.title = "Server unreachable";
    showBanner(`Can't reach the SecondThought server at ${API_BASE}. ${START_HINT}`);
  }
}

// Prefill with whatever the user had selected on the page (text, textarea, or editor).
async function prefillFromSelection() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || tab.id === undefined) return;
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const el = document.activeElement;
        if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT") &&
            typeof el.selectionStart === "number") {
          return el.value.substring(el.selectionStart, el.selectionEnd);
        }
        return window.getSelection().toString();
      },
    });
    const selected = (injection && injection.result || "").trim();
    if (selected && !messageEl.value) messageEl.value = selected;
  } catch {
    // Restricted pages (chrome://, Web Store) can't be scripted; typing still works.
  }
}

function setLoading(loading) {
  rewriteBtn.disabled = loading;
  rewriteBtn.textContent = loading ? "Rethinking…" : "Second thought?";
}

async function rewrite() {
  const message = messageEl.value.trim();
  if (!message) {
    showBanner("Type or paste a message first.", "info");
    messageEl.focus();
    return;
  }

  hideBanner();
  resultEl.hidden = true; // never leave an older rewrite next to a new message
  setLoading(true);
  try {
    const response = await fetchWithTimeout(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      showBanner(escapeHtml(errorDetail(body, response.status)));
      return;
    }

    rewrittenEl.textContent = body.rewritten_text;
    const unchanged = body.rewritten_text.trim() === message;
    metaEl.textContent = (unchanged ? "Already professional, so no changes. · " : "") +
      `${body.model_info} · ${(body.latency_ms / 1000).toFixed(1)}s`;
    resultEl.hidden = false;
    copyBtn.textContent = "Copy";
    statusDot.className = "status-dot ok";
  } catch (err) {
    if (err.name === "AbortError") {
      showBanner(`The rewrite took longer than ${REQUEST_TIMEOUT_MS / 1000}s. Try again.`);
    } else {
      statusDot.className = "status-dot down";
      showBanner(`Can't reach the SecondThought server at ${API_BASE}. ${START_HINT}`);
    }
  } finally {
    setLoading(false);
  }
}

async function copyResult() {
  const text = rewrittenEl.textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const scratch = document.createElement("textarea");
    scratch.value = text;
    document.body.appendChild(scratch);
    scratch.select();
    document.execCommand("copy");
    scratch.remove();
  }
  copyBtn.textContent = "Copied ✓";
  setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
}

rewriteBtn.addEventListener("click", rewrite);
copyBtn.addEventListener("click", copyResult);
messageEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) rewrite();
});

messageEl.focus();
prefillFromSelection();
checkServer();
