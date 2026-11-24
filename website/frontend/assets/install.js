// The Community page: download buttons for the visitor's system, the rewrite
// demo, OS tabs and copy buttons for developers, and a live check of whether
// the local service is running.
(() => {
  const page = document.querySelector(".community-page");
  const section = document.getElementById("install");
  if (!page || !section) return;

  // Tab lists (the demo and the developer commands) with arrow-key support.
  function tablist(tabs, show) {
    function select(tab, focus = false) {
      for (const other of tabs) {
        const active = other === tab;
        other.setAttribute("aria-selected", String(active));
        other.tabIndex = active ? 0 : -1;
      }
      if (focus) tab.focus();
      show(tab);
    }
    for (const tab of tabs) {
      tab.addEventListener("click", () => select(tab));
      tab.addEventListener("keydown", (event) => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (step) select(tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length], true);
      });
    }
    return select;
  }

  const platform = (navigator.userAgentData?.platform || navigator.platform || navigator.userAgent).toLowerCase();
  const os = platform.includes("mac") ? "mac" : platform.includes("linux") ? "linux" : "windows";

  // Developer commands, starting on the visitor's own system.
  const osTabs = [...section.querySelectorAll(".os-tabs [role=tab]")];
  const osPanels = [...section.querySelectorAll(".os-panel")];
  const selectOs = tablist(osTabs, (tab) => {
    for (const panel of osPanels) panel.hidden = panel.dataset.os !== tab.dataset.os;
  });
  selectOs(osTabs.find((tab) => tab.dataset.os === os) || osTabs[0]);

  // Rewrite demo.
  const demoTabs = [...page.querySelectorAll(".demo-tabs [role=tab]")];
  if (demoTabs.length) {
    tablist(demoTabs, (tab) => {
      for (const panel of page.querySelectorAll(".demo-panel")) {
        panel.hidden = panel.id !== tab.getAttribute("aria-controls");
      }
    });
  }

  // Every download button follows the chosen system, with a link to the other one.
  const setups = [...page.querySelectorAll(".setup-button")];
  const switcher = page.querySelector("[data-switch-os]");
  const names = { windows: "Windows", mac: "Mac" };
  function showSetup(target) {
    for (const setup of setups) {
      setup.href = setup.dataset[target];
      setup.querySelector(".setup-label").textContent = `Download for ${names[target]}`;
    }
    const other = target === "mac" ? "windows" : "mac";
    switcher.textContent = `Get the ${names[other]} version`;
    switcher.parentElement.firstChild.textContent = `Not on ${names[target]}? `;
    switcher.onclick = () => showSetup(other);
    for (const help of section.querySelectorAll(".os-help")) help.hidden = help.dataset.os !== target;
  }
  showSetup(os === "mac" ? "mac" : "windows");

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
      label.textContent = ok ? "SecondThought is running. You're all set." : "SecondThought is starting. Give it a moment.";
    } catch {
      status.className = "service-status stopped";
      label.textContent = "SecondThought isn't running yet. This turns green once you start it.";
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
