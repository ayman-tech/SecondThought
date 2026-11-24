// "Get SecondThought" on the Community page: the download button for the
// visitor's system, OS tabs and copy buttons for developers, and a live check
// of whether the local service is running.
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
  const os = platform.includes("mac") ? "mac" : platform.includes("linux") ? "linux" : "windows";
  select(os);

  // The big download button: the visitor's own system, with a link to the other one.
  const setup = section.querySelector(".setup-button");
  const switcher = section.querySelector("[data-switch-os]");
  const names = { windows: "Windows", mac: "Mac" };
  function showSetup(target) {
    setup.href = setup.dataset[target];
    setup.querySelector(".setup-label").textContent = `Download for ${names[target]}`;
    const other = target === "mac" ? "windows" : "mac";
    switcher.textContent = `Get the ${names[other]} version`;
    switcher.parentElement.firstChild.textContent = `Not on ${names[target]}? `;
    switcher.onclick = () => showSetup(other);
    for (const help of section.querySelectorAll(".os-help")) help.hidden = help.dataset.os !== target;
  }
  showSetup(os === "mac" ? "mac" : "windows");
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
