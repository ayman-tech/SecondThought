// Service worker. The in-page nudge runs inside sites like Gmail, and their
// security rules stop it from calling the local server directly, so it asks
// here and the request goes out with the extension's own permissions.
const API_BASE = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 30000;

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request?.type !== "secondthought:rewrite") return false;
  rewrite(request.message).then(sendResponse);
  return true; // reply asynchronously
});

function errorDetail(body, status) {
  const detail = body && body.detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  if (typeof detail === "string") return detail;
  return `Server returned HTTP ${status}.`;
}

async function rewrite(message) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) return { ok: false, error: errorDetail(body, response.status) };
    return { ok: true, result: body };
  } catch (err) {
    if (err.name === "AbortError") {
      return { ok: false, error: `The rewrite took longer than ${REQUEST_TIMEOUT_MS / 1000}s. Try again.` };
    }
    return { ok: false, error: "Can't reach the SecondThought server. Start it with python -m api.server." };
  } finally {
    clearTimeout(timer);
  }
}
