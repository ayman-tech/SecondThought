// "Get SecondThought" on the Community page: OS tabs for the installer command,
// copy buttons, and a live check of whether the local service is running.
(() => {
  const section = document.getElementById("install");
  if (!section) return;

  // OS tabs, starting on the visitor's own system.
  const tabs = [...section.querySelectorAll('[role="tab"]')];
  const panels = [...section.querySelectorAll('[role="tabpanel"]')];
  function select(os, focus = false) {
    for (const tab of tabs) {
      const active = tab.dataset.os === os;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus) tab.focus();
    }
    for (const panel of panels) panel.hidden = panel.dataset.os !== os;
  }
  const platform = (navigator.userAgentData?.platform || navigator.platform || navigator.userAgent).toLowerCase();
  select(platform.includes("mac") ? "mac" : platform.includes("linux") ? "linux" : "windows");
  for (const tab of tabs) {
    tab.addEventListener("click", () => select(tab.dataset.os));
    tab.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!step) return;
      const next = tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length];
      select(next.dataset.os, true);
    });
  }

  for (const button of section.querySelectorAll(".copy")) {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Select and copy";
      }
      setTimeout(() => { button.textContent = "Copy"; }, 1500);
    });
  }

  const status = section.querySelector(".service-status");
  const label = status.querySelector(".label");
  const api = section.dataset.api;

  async function check() {
    try {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), 2000);
      const body = await (await fetch(`${api}/health`, { cache: "no-store", signal: controller.signal })).json();
      const ok = body.status === "ok";
      status.className = `service-status ${ok ? "running" : "stopped"}`;
      label.textContent = ok ? "SecondThought is running. You're all set." : "It's starting, but not ready yet.";
    } catch {
      status.className = "service-status stopped";
      label.textContent = "Not running yet. This turns green once it starts.";
    }
  }

  check();
  // Keep the status honest while this tab is open, without polling in the background.
  let timer = setInterval(check, 4000);
  document.addEventListener("visibilitychange", () => {
    clearInterval(timer);
    if (!document.hidden) {
      check();
      timer = setInterval(check, 4000);
    }
  });
})();
