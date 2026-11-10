// Settings page. Everything is stored through settings.js, so the popup and
// the in-page nudge pick up changes straight away.
const API_BASE = "http://127.0.0.1:8000";

const nudgeToggle = document.getElementById("nudge-enabled");
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

function kindRow(kind, checked, triggerKinds) {
  const row = document.createElement("label");
  row.className = "row";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = checked;
  box.addEventListener("change", () => save({ triggerKinds: { ...triggerKinds, [kind.key]: box.checked } }));
  const text = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = kind.label;
  const examples = document.createElement("small");
  examples.textContent = kind.examples;
  text.append(name, examples);
  row.append(box, text);
  return row;
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
  const { nudgeEnabled, triggerKinds, disabledSites } = await SecondThoughtSettings.load();
  nudgeToggle.checked = nudgeEnabled;
  kindsSection.classList.toggle("off", !nudgeEnabled);
  kindsEl.replaceChildren(
    ...SecondThoughtSettings.KINDS.map((kind) => kindRow(kind, triggerKinds[kind.key], triggerKinds)),
  );
  sitesEl.replaceChildren(...[...disabledSites].sort().map(siteRow));
  noSitesEl.hidden = disabledSites.length > 0;
}

async function checkServer() {
  const dot = document.getElementById("server-dot");
  const text = document.getElementById("server-text");
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 3000);
    const body = await (await fetch(`${API_BASE}/health`, { signal: controller.signal })).json();
    dot.className = body.status === "ok" ? "status-dot ok" : "status-dot down";
    text.textContent = body.status === "ok" ? `Running · ${body.model}` : `Running, but not ready: ${body.detail}`;
  } catch {
    dot.className = "status-dot down";
    text.textContent = "Not running";
  }
}

nudgeToggle.addEventListener("change", () => save({ nudgeEnabled: nudgeToggle.checked }));
// Stay in sync when the popup changes something while this page is open.
chrome.storage.onChanged.addListener(render);

render();
checkServer();
