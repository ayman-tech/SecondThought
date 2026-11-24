// Optional local browser QA. Uses installed Chrome + Node 22+, no npm packages.
// Start `make website`, then run `node website/frontend/tests/browser-smoke.mjs`.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkSliderRelease } from "./slider-release-checks.mjs";
import { checkEveryVectorRoute } from './vector-routing-checks.mjs';

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

  await cdp('Runtime.enable');await cdp('Page.enable');
  await cdp('Emulation.setFocusEmulationEnabled',{enabled:true});
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:base+'/explore'});
  await until(`document.getElementById('model-status')?.parentElement.hidden`,90);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('[data-mix-toggle]')].map(n=>n.dataset.mixToggle)`),
    ['formality','fluency','empathy','politeness']);
  assert.equal(await evaluate(`document.querySelector('.experiment-settings,#layer-enabled,#layer-mode-single,#layer-mode-multi,#focused-feature')`),null);
  assert.equal(await evaluate(`document.querySelectorAll('[data-layer]').length`),24);
  assert.equal(await evaluate(`document.querySelector('[data-mix-toggle="empathy"]').closest('.mix-feature-axis').getAttribute('opacity')`),'0.5');
  await evaluate(`
    window.__chooseFamily=(feature,pooling)=>{
      const ids=[...document.querySelectorAll('[data-mix-toggle]')].map(n=>n.dataset.mixToggle);
      for(const id of ids){const button=document.querySelector('[data-mix-toggle="'+id+'"]');
        if((button.getAttribute('aria-pressed')==='true')!==(id===feature))
          button.dispatchEvent(new MouseEvent('click',{bubbles:true}));
      }
      const select=document.querySelector('#focused-pooling');select.value=pooling;
      select.dispatchEvent(new Event('change'));
    };
    document.querySelector('#clear-layers').click();
    document.querySelector('[data-layer="7"]').click();document.querySelector('[data-layer="9"]').click();
  `);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.layer.selected')].map(n=>Number(n.dataset.layer))`),[7,9]);
  await evaluate(`document.querySelector('[data-layer="7"]').click()`);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.layer.selected')].map(n=>Number(n.dataset.layer))`),[9]);
  await evaluate(`document.querySelector('[data-mix-toggle="empathy"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.equal(await evaluate(`document.querySelector('[data-mix-toggle="empathy"]').closest('.mix-feature-axis').getAttribute('opacity')`),'1');
  await evaluate(`document.querySelector('[data-layer="4"]').click();window.__chooseFamily('formality','mean')`);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.layer.selected')].map(n=>Number(n.dataset.layer))`),[9]);
  // Selection paint follows all enabled feature banks, including shared layers.
  assert.equal(await evaluate(`document.querySelector('.layer-score,.heat-scale')`),null);
  assert.equal(await evaluate(`document.querySelector('[data-layer="0"]').style.getPropertyValue('--layer-fill')`),'#edf0f5');
  await evaluate(`document.querySelector('[data-mix-toggle="empathy"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));document.querySelector('[data-layer="9"]').click()`);
  assert.equal(await evaluate(`document.querySelector('[data-layer="9"]').dataset.selectedFeatures`),'formality,empathy');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('[data-layer="9"] .layer-fin')).backgroundImage.startsWith('linear-gradient')`),true);
  assert.equal(await evaluate(`document.querySelector('[data-layer="4"]').dataset.selectedFeatures`),'empathy');
  await evaluate(`document.querySelector('[data-mix-toggle="empathy"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.equal(await evaluate(`document.querySelector('[data-layer="9"]').dataset.selectedFeatures`),'formality');
  assert.equal(await evaluate(`document.querySelector('[data-layer="4"]').style.getPropertyValue('--layer-fill')`),'#edf0f5');
  // The Task menu contains the existing, live prompt controls.
  await evaluate(`document.querySelector('[popovertarget="task-controls"]').click();
    document.querySelector('#experiment-prompt').value='summarize';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'))`);
  assert.equal(await evaluate(`document.querySelector('#task-label').textContent`),'Summarize');
  await evaluate(`document.querySelector('#experiment-prompt').value='rewrite';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'));document.querySelector('#task-controls').hidePopover();document.querySelector('#reset-layers').click()`);
  await evaluate(`document.querySelector('#draft').value='Please send the report today.';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`document.querySelector('#output-card').getAttribute('aria-busy')==='false'&&!document.querySelector('#output').classList.contains('placeholder')`,90);
  await evaluate(`document.querySelector('#clear').click()`);
  await checkSliderRelease({evaluate,cdp,until});
  const report=await checkEveryVectorRoute({evaluate,until});
  assert.equal(report.length,192);
  await writeFile(join(directory,'vector-routing.json'),JSON.stringify(report,null,2));
  // Keep inspector coverage alongside the compact layer controls.
  await evaluate(`document.querySelector('#inspect-curves').click();document.querySelector('#inspect-curves').focus()`);
  assert.equal(await evaluate(`document.querySelector('#inspect-panel-curves').hidden`),false);
  assert.equal(await evaluate(`document.querySelector('#trend-chart')!==null`),true);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Home',code:'Home'});
  await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Home',code:'Home'});
  assert.equal(await evaluate(`document.querySelector('#inspect-metrics').getAttribute('aria-selected')`),'true');
  assert.equal(await evaluate(`document.querySelectorAll('.quality-metrics dd.metric-value').length`),4);
  // Multiple features retain separate layer banks without exposing a mode switch.
  await evaluate(`
    document.querySelector('#clear-layers').click();document.querySelector('[data-layer="4"]').click();document.querySelector('[data-layer="7"]').click();
    document.querySelector('[data-mix-toggle="empathy"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
    document.querySelector('[data-layer="12"]').click();
  `);
  assert.equal(await evaluate(`document.querySelectorAll('#active-layer-list button').length`),4);
  await evaluate(`document.querySelector('#clear-layers').click();document.querySelector('#reset-layers').click()`);
  for(const [width,height] of [[1920,1080],[1440,1100],[390,844]]){
    await cdp('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<600});
    await evaluate(`new Promise(resolve=>setTimeout(resolve,150))`);
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth`),true,`overflow at ${width}`);
    if(width>=1280){
      const geometry=await evaluate(`(()=>{const model=document.querySelector('.model-section').getBoundingClientRect(),writing=document.querySelector('.writing-section').getBoundingClientRect();return {model:model.left,writing:writing.left,width:model.width}})()`);
      assert.ok(Math.abs(geometry.model-geometry.writing)<2);
      assert.ok(geometry.width>width*.8);
    }
    await writeFile(join(directory,`compact-${width}.png`),Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  }
  assert.deepEqual(exceptions,[]);
  console.log('Compact lab browser QA passed: direct layer toggles, four feature toggles, task controls, release behaviour and all 192 vector routes.');
  console.log('Screenshots:',directory);
} finally {
  if(socket)socket.close();chrome.kill('SIGTERM');
}
