// Setup guide on the Community page: copy buttons, and a live check of whether
// the extension's local rewriting service is running.
(() => {
  const section = document.getElementById("install");
  if (!section) return;

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
      label.textContent = ok ? "Running. You're all set." : "Running, but not ready yet.";
    } catch {
      status.className = "service-status stopped";
      label.textContent = "Not running yet. Start it with the command above.";
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
