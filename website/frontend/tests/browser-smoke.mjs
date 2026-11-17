// Optional local browser QA. Uses installed Chrome + Node 22+, no npm packages.
// Start `make website`, then run `node website/frontend/tests/browser-smoke.mjs`.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.WEBSITE_URL || "http://127.0.0.1:8001";
const chromePath =
  process.env.CHROME_PATH ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const directory = await mkdtemp(join(tmpdir(), "secondthought-browser-"));
const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--remote-debugging-port=0",
    `--user-data-dir=${directory}`,
    "about:blank",
  ],
  { stdio: ["ignore", "ignore", "pipe"] },
);
let socket;
try {
  const devtools = await new Promise((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(
      () => reject(new Error("Chrome did not start")),
      15000,
    );
    chrome.once("error", reject);
    chrome.stderr.on("data", (chunk) => {
      output += chunk;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timeout);
        resolve(match[1]);
      }
    });
  });
  const origin = devtools.replace(/^ws:/, "http:").split("/devtools")[0];
  const targets = await (await fetch(`${origin}/json/list`)).json();
  const target = targets.find((t) => t.type === "page");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let id = 0;
  const pending = new Map();
  const exceptions = [];
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id);
      pending.delete(message.id);
      if (message.error)
        promise.reject(new Error(JSON.stringify(message.error)));
      else promise.resolve(message.result);
    }
    if (message.method === "Runtime.exceptionThrown")
      exceptions.push(message.params.exceptionDetails);
  };
  const cdp = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const requestId = ++id;
      pending.set(requestId, { resolve, reject });
      socket.send(JSON.stringify({ id: requestId, method, params }));
    });
  const evaluate = async (expression) => {
    const result = await cdp("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails)
      throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const until = async (expression, seconds = 35) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const geometry = await evaluate(`({
      url:location.href,width:innerWidth,height:innerHeight,scrollY,
      focus:document.activeElement?.id,
      workspace:document.querySelector('#experimental')?.getBoundingClientRect().toJSON(),
      header:document.querySelector('.site-header')?.getBoundingClientRect().toJSON(),
      slider:document.querySelector('#slider-panel')?.className,
      small:matchMedia('(max-width:650px)').matches,focused:document.hasFocus(),
      duplicatePanels:document.querySelectorAll('#slider-panel').length,
      duplicateWorkspaces:document.querySelectorAll('#experimental').length
    })`);
    throw new Error(
      `Timed out waiting for ${expression}; page state: ${JSON.stringify(geometry)}; exceptions: ${JSON.stringify(exceptions)}`,
    );
  };
  await cdp("Runtime.enable");
  await cdp("Page.enable");
  // Full-page navigation can leave a headless target unfocused. Emulate the
  // foreground tab so focus/blur and viewport events behave like a user session.
  await cdp("Emulation.setFocusEmulationEnabled", { enabled: true });
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 1100,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp("Page.navigate", { url: base + "/explore" });
  await until(
    `document.getElementById('model-status')?.parentElement.hidden`,
    90,
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('[data-layer]').length`),
    24,
  );
  assert.equal(await evaluate(`document.querySelectorAll('nav a').length`), 3);
  assert.equal(
    await evaluate(`document.documentElement.scrollWidth <= innerWidth`),
    true,
  );
  await evaluate(`document.querySelector('[data-sample]').click()`);
  await until(
    `!document.querySelector('#copy').disabled && document.querySelector('#output-card').getAttribute('aria-busy') === 'false'`,
  );
  const checkHighlights = async () => {
    const diff = await evaluate(
      `(async()=>{const {wordChanges}=await import('/assets/lifecycle.js');return {expected:wordChanges(document.querySelector('#draft').value.trim(),document.querySelector('#output').textContent).filter(x=>x.added).map(x=>x.text),actual:[...document.querySelectorAll('.word-new')].map(x=>x.textContent)}})()`,
    );
    assert.deepEqual(diff.actual, diff.expected);
  };
  await checkHighlights();
  const baseline = await evaluate(
    `document.querySelector('#output').textContent`,
  );
  await evaluate(
    `document.querySelector('[data-layer="3"]').click();document.querySelector('#layer-enabled').click();document.querySelector('#alpha').value='1.2';document.querySelector('#alpha').dispatchEvent(new Event('input'))`,
  );
  assert.equal(
    await evaluate(`document.querySelector('#output').textContent`),
    baseline,
  );
  assert.ok(
    await evaluate(
      `document.querySelector('#layer-kind').textContent.includes('Preview only')`,
    ),
  );
  await evaluate(
    `window.requests=[];const originalFetch=window.fetch;window.fetch=(url,options)=>{if(url.endsWith('/stream'))window.requests.push(JSON.parse(options.body));return originalFetch(url,options)};document.querySelector('[data-layer="4"]').click();document.querySelector('#layer-enabled').click()`,
  );
  await until(
    `!document.querySelector('#copy').disabled && document.querySelector('#output-card').getAttribute('aria-busy') === 'false'`,
  );
  const request = await evaluate(`window.requests.at(-1)`);
  assert.deepEqual(request.layer_strengths, { 4: 0.5, 11: 0.5 });
  await checkHighlights();
  await evaluate(
    `document.querySelector('#alpha').value='0.7';document.querySelector('#alpha').dispatchEvent(new Event('input'))`,
  );
  await until(
    `!document.querySelector('#copy').disabled && document.querySelector('#output-card').getAttribute('aria-busy') === 'false'`,
  );
  assert.deepEqual(await evaluate(`window.requests.at(-1).layer_strengths`), {
    4: 0.7,
    11: 0.5,
  });
  await evaluate(`document.querySelector('#changes-toggle').click()`);
  assert.equal(
    await evaluate(`document.querySelectorAll('.word-new').length`),
    0,
  );
  await evaluate(
    `document.querySelector('#changes-toggle').click()`,
  );
  await checkHighlights();
  await evaluate(`document.querySelector('[popovertarget="layer-guide"]').click()`);
  assert.equal(await evaluate(`document.querySelector('#layer-guide').matches(':popover-open')`), true);
  await cdp('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
  await cdp('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
  assert.equal(await evaluate(`document.querySelector('#layer-guide').matches(':popover-open')`), false);
  assert.equal(await evaluate(`document.querySelector('#motion-toggle')`), null);
  await cdp("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });
  assert.equal(
    await evaluate(
      `getComputedStyle(document.querySelector('.flow-pulse')).animationName`,
    ),
    "none",
  );
  await cdp("Emulation.setEmulatedMedia", { features: [] });
  await new Promise((resolve) => setTimeout(resolve, 800));
  await writeFile(
    join(directory, "explore.png"),
    Buffer.from(
      (
        await cdp("Page.captureScreenshot", {
          format: "png",
          captureBeyondViewport: true,
        })
      ).data,
      "base64",
    ),
  );
  await evaluate(`document.querySelector('#reset-layers').click()`);
  await until(
    `document.querySelector('#run-source').textContent === 'Tab cache'`,
  );
  await evaluate(
    `document.querySelector('#draft').value='A new request';document.querySelector('#draft').dispatchEvent(new Event('input'));document.querySelector('#clear').click()`,
  );
  assert.equal(
    await evaluate(`document.querySelector('#copy').disabled`),
    true,
  );
  assert.equal(
    await evaluate(`document.querySelector('#output').textContent`),
    "Your next wording starts here.",
  );
  for (const path of ["/community", "/evaluation"]) {
    await cdp("Page.navigate", { url: base + path });
    await until(
      `document.querySelector('nav [aria-current="page"]')?.getAttribute('href')===${JSON.stringify(path)}`,
    );
    assert.equal(
      await evaluate(`document.documentElement.scrollWidth <= innerWidth`),
      true,
    );
    if (path === "/community")
      assert.equal(
        await evaluate(`document.querySelector('.download-button').getAttribute('href').endsWith('.zip')`),
        true,
      );
    if (path === "/evaluation") {
      await until(
        `document.querySelectorAll('[data-eval-tiles] .eval-tile').length===4`,
      );
      assert.equal(
        await evaluate(
          `document.querySelectorAll('[data-eval-chart] .row').length`,
        ),
        35,
      );
      assert.equal(
        await evaluate(`document.querySelectorAll('[data-eval-units] .unit').length`),
        35,
      );
      assert.equal(
        await evaluate(`document.querySelectorAll('[data-eval-strip] .dot').length`),
        35,
      );
    }
    await writeFile(
      join(directory, path.slice(1) + ".png"),
      Buffer.from(
        (await cdp("Page.captureScreenshot", { format: "png" })).data,
        "base64",
      ),
    );
  }
  assert.deepEqual(exceptions, []);
  console.log(
    "Browser QA passed: real generation, multilayer payload, preview exclusion, independent strengths, word highlights, reset/cache, clear, motion and three pages.",
  );
  console.log("Screenshots:", directory);
} finally {
  if (socket) socket.close();
  chrome.kill("SIGTERM");
}
