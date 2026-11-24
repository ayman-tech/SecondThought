// Settings page. Everything is stored through settings.js, so the popup and
// the in-page nudge pick up changes straight away.
const API_BASE = "http://127.0.0.1:8000";
const CHECK_EVERY_MS = 4000;

const nudgeToggle = document.getElementById("nudge-enabled");
const idleToggle = document.getElementById("idle-check");
const kindsSection = document.getElementById("kinds-section");
const kindsEl = document.getElementById("kinds");
const sitesEl = document.getElementById("sites");
const noSitesEl = document.getElementById("no-sites");
const savedEl = document.getElementById("saved");

let savedTimer = null;
function showSaved() {
  savedEl.hidden = false;
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { savedEl.hidden = true; }, 1200);
}

async function save(changes) {
  await SecondThoughtSettings.save(changes);
  showSaved();
}

function kindTile(kind, checked, triggerKinds) {
  const tile = document.createElement("label");
  tile.className = "kind";
  const head = document.createElement("span");
  head.className = "kind-head";
  const name = document.createElement("span");
  name.textContent = kind.label;
  const box = document.createElement("input");
  box.type = "checkbox";
  box.setAttribute("role", "switch");
  box.checked = checked;
  box.addEventListener("change", () => save({ triggerKinds: { ...triggerKinds, [kind.key]: box.checked } }));
  head.append(name, box);
  const examples = document.createElement("span");
  examples.className = "examples";
  examples.append(...kind.examples.map((text) => {
    const chip = document.createElement("span");
    chip.textContent = text;
    return chip;
  }));
  tile.append(head, examples);
  return tile;
}

function siteRow(site) {
  const item = document.createElement("li");
  const name = document.createElement("span");
  name.textContent = site;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Turn back on";
  button.addEventListener("click", async () => {
    await SecondThoughtSettings.setSiteEnabled(site, true);
    showSaved();
  });
  item.append(name, button);
  return item;
}

async function render() {
  const { nudgeEnabled, idleCheck, triggerKinds, disabledSites } = await SecondThoughtSettings.load();
  nudgeToggle.checked = nudgeEnabled;
  idleToggle.checked = idleCheck;
  kindsSection.classList.toggle("off", !nudgeEnabled);
  document.getElementById("idle-row").classList.toggle("off", !nudgeEnabled);
  kindsEl.replaceChildren(
    ...SecondThoughtSettings.KINDS.map((kind) => kindTile(kind, triggerKinds[kind.key], triggerKinds)),
  );
  sitesEl.replaceChildren(...[...disabledSites].sort().map(siteRow));
  noSitesEl.hidden = disabledSites.length > 0;
}

// The service status, kept live while this tab is visible.
const statusCard = document.getElementById("server");
const statusDot = document.getElementById("server-dot");
const statusTitle = document.getElementById("server-title");
const statusDetail = document.getElementById("server-detail");

function showStatus(state, title, detail) {
  statusCard.className = `card status-card ${state}`;
  statusDot.className = `status-dot big ${state}`;
  statusTitle.textContent = title;
  statusDetail.textContent = detail;
}

async function checkServer() {
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 3000);
    const body = await (await fetch(`${API_BASE}/health`, { cache: "no-store", signal: controller.signal })).json();
    if (body.status !== "ok") {
      showStatus("down", "SecondThought is starting", body.detail || "Give it a moment.");
      return;
    }
    const tone = {
      ready: "tone check ready",
      loading: "tone check starting up",
      off: "tone check off",
      error: "tone check failed to start",
    }[body.tone_check];
    showStatus("ok", "SecondThought is running", [body.model?.replace("->", "→"), tone].filter(Boolean).join(" · "));
  } catch {
    showStatus("down", "SecondThought isn't running",
      "Double-click Start SecondThought on your Desktop. This updates by itself.");
  }
}

let timer = null;
function watchServer() {
  clearInterval(timer);
  if (document.hidden) return;
  checkServer();
  timer = setInterval(checkServer, CHECK_EVERY_MS);
}
document.addEventListener("visibilitychange", watchServer);
document.getElementById("server-recheck").addEventListener("click", () => {
  statusTitle.textContent = "Checking…";
  watchServer();
});

nudgeToggle.addEventListener("change", () => save({ nudgeEnabled: nudgeToggle.checked }));
idleToggle.addEventListener("change", () => save({ idleCheck: idleToggle.checked }));
// Stay in sync when the popup changes something while this page is open.
chrome.storage.onChanged.addListener(render);

document.getElementById("version").textContent = `Version ${chrome.runtime.getManifest().version}`;
document.getElementById("advanced-link").href = SecondThoughtSettings.siteLink("/explore");
document.getElementById("guide-link").href = SecondThoughtSettings.siteLink("/community#install");

render();
watchServer();
