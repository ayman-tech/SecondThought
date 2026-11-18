// Optional local browser QA. Uses installed Chrome + Node 22+, no npm packages.
// Start `make website`, then run `node website/frontend/tests/browser-smoke.mjs`.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkSliderRelease } from "./slider-release-checks.mjs";

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
  await evaluate(`
    window.__captureRun=body=>{
      const vectors=JSON.parse(document.querySelector('#layer-vector-data').textContent);
      return {...body,message:body.input,max_input_tokens:body.generation.max_input_tokens,max_new_tokens:body.generation.max_new_tokens,
        layer_strengths:Object.fromEntries(body.interventions.map(i=>[vectors.find(v=>v.id===i.vector_id).layer_index,i.strength])),
        layer_vector_ids:Object.fromEntries(body.interventions.map(i=>[vectors.find(v=>v.id===i.vector_id).layer_index,i.vector_id]))};
    };
    window.__chooseFamily=(feature,pooling)=>{
      for(const checkbox of document.querySelectorAll('#feature-selection input')) {
        const enabled=checkbox.dataset.feature===feature;
        if(checkbox.checked!==enabled) checkbox.click();
      }
      document.querySelector('#focused-feature').value=feature;
      document.querySelector('#focused-feature').dispatchEvent(new Event('change'));
      document.querySelector('#focused-pooling').value=pooling;
      document.querySelector('#focused-pooling').dispatchEvent(new Event('change'));
    };
  `);
  assert.equal(
    await evaluate(`document.querySelectorAll('[data-layer]').length`),
    24,
  );
  assert.equal(await evaluate(`document.querySelectorAll('nav a').length`), 3);
  assert.equal(
    await evaluate(`document.documentElement.scrollWidth <= innerWidth`),
    true,
  );
  assert.equal(await evaluate(`document.querySelector('#layer-colour-profile')`), null);
  for (const id of ['focused-feature','focused-pooling'])
    assert.deepEqual(await evaluate(`[...document.querySelector('#${id}').options].map(o=>o.disabled)`),[false,false]);
  // Exhaustively verify all 96 colour/vector mappings against the shipped catalog.
  for (const feature of ['formality','detoxification']) {
    for (const pooling of ['mean','final_token']) {
      await evaluate(`window.__chooseFamily('${feature}','${pooling}')`);
      const mapping = await evaluate(`(() => {
        const vectors=JSON.parse(document.querySelector('#layer-vector-data').textContent);
        const evidence=JSON.parse(document.querySelector('#layer-evidence-data').textContent).flatMap(p=>p.layers);
        return [...document.querySelectorAll('[data-layer]')].map(b=>{
          const matches=vectors.filter(v=>v.selectable && v.feature_id==='${feature}' && v.pooling==='${pooling}' && v.layer_index===Number(b.dataset.layer));
          const vector=matches[0], score=evidence.find(e=>e.vector_id===vector?.id);
          return {count:matches.length,id:b.dataset.evidenceVectorId,expected:vector?.id,
            score:Number(b.dataset.evidenceValue),expectedScore:score?.value,state:b.dataset.evidenceState};
        });
      })()`);
      assert.equal(mapping.length,24);
      for (const row of mapping) {
        assert.equal(row.count,1);
        assert.equal(row.id,row.expected);
        assert.equal(row.score,row.expectedScore);
        assert.equal(row.state,'measured');
      }
    }
  }
  await evaluate(`document.querySelector('#reset-layers').click()`);
  assert.equal(await evaluate(`document.querySelector('[data-layer="11"]').getAttribute('aria-pressed')`),'true');
  assert.equal(await evaluate(`document.querySelector('#mix-formality').value`),'0.5');
  await until(`getComputedStyle(document.querySelector('[data-layer="11"] .layer-fin')).backgroundColor === document.querySelector('[data-layer="11"]').style.getPropertyValue('--evidence-fill')`);
  for (const id of ['focused-feature','focused-pooling'])
    assert.equal(await evaluate(`document.getElementById(${JSON.stringify(id)}).disabled`), false);
  for (const id of ['experiment-model'])
    assert.equal(await evaluate(`document.getElementById(${JSON.stringify(id)}).disabled`), true);
  assert.equal(await evaluate(`document.querySelector('#system-prompt').readOnly`), false);
  assert.equal(await evaluate(`document.querySelector('#system-prompt').value`),
    "Rewrite the user's sentence while preserving its meaning. Return only the rewritten sentence.");
  for (const [layer, feature, pooling] of [
    [0, 'formality', 'mean'], [22, 'formality', 'mean'],
    [4, 'formality', 'mean'], [3, 'formality', 'mean'], [11, 'formality', 'mean'],
  ]) {
    await evaluate(`document.querySelector('[data-layer="${layer}"]').click()`);
    assert.equal(await evaluate(`document.querySelector('#focused-feature').value`), feature);
    assert.equal(await evaluate(`document.querySelector('#focused-pooling').value`), pooling);
  }
  await evaluate(`document.querySelector('#inspect-curves').click();document.querySelector('#inspect-curves').focus()`);
  assert.equal(await evaluate(`document.querySelector('#inspect-panel-curves').hidden`), false);
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Home', code: 'Home' });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Home', code: 'Home' });
  assert.equal(await evaluate(`document.querySelector('#inspect-metrics').getAttribute('aria-selected')`), 'true');
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.quality-metrics dd')].map(x=>x.textContent)`), ['—', '—', '—', '—']);
  // Single mode replaces selection; multi mode requires an explicit enable.
  assert.equal(await evaluate(`document.querySelector('#layer-mode-single').checked`),true);
  await evaluate(`document.querySelector('[data-layer="4"]').click();document.querySelector('[data-layer="3"]').click()`);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.layer.selected')].map(b=>Number(b.dataset.layer))`),[3]);
  await evaluate(`document.querySelector('#layer-mode-multi').click();document.querySelector('[data-layer="4"]').click()`);
  assert.equal(await evaluate(`document.querySelector('#layer-enabled').checked`),false);
  await evaluate(`document.querySelector('#layer-enabled').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('.active-layer-chip').length`),2);
  assert.equal(await evaluate(`document.querySelector('#multi-layer-note').hidden`),false);
  await evaluate(`document.querySelector('#layer-mode-single').click()`);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.layer.selected')].map(b=>Number(b.dataset.layer))`),[4]);
  await evaluate(`document.querySelector('.active-layer-chip').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('.layer.selected').length`),0);
  assert.ok(await evaluate(`document.querySelector('#active-layer-summary').textContent.includes('Prompt only')`));
  await evaluate(`document.querySelector('[data-layer="4"]').click();document.querySelector('#clear-layers').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('.active-layer-chip').length`),0);
  await evaluate(`document.querySelector('#reset-layers').click()`);
  await checkSliderRelease({ evaluate, cdp, until });
  await evaluate(`document.querySelector('#draft').value='hey can u send the report by 3 PM?';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(
    `!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,
  );
  const checkHighlights = async () => {
    const diff = await evaluate(
      `(async()=>{const {wordChanges}=await import('/assets/lifecycle.js');return {expected:wordChanges(document.querySelector('#draft').value.trim(),document.querySelector('#output').textContent).filter(x=>x.added).map(x=>x.text),actual:[...document.querySelectorAll('.word-new')].map(x=>x.textContent)}})()`,
    );
    assert.deepEqual(diff.actual, diff.expected);
  };
  await checkHighlights();
  await evaluate(`window.__singleRequests=[];window.__singleFetch=window.fetch;window.fetch=(url,options)=>{if(String(url).endsWith('/stream'))window.__singleRequests.push(window.__captureRun(JSON.parse(options.body)));return window.__singleFetch(url,options)};document.querySelector('[data-layer="4"]').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  assert.deepEqual(await evaluate(`window.__singleRequests.at(-1).layer_strengths`),{4:.5});
  await evaluate(`document.querySelector('#reset-layers').click();window.fetch=window.__singleFetch`);
  await until(`document.querySelector('#run-source').textContent === 'Tab cache'`);
  await evaluate(`document.querySelector('#layer-mode-multi').click()`);
  const baseline = await evaluate(
    `document.querySelector('#output').textContent`,
  );
  await evaluate(
    `document.querySelector('[data-layer="3"]').click()`,
  );
  assert.equal(
    await evaluate(`document.querySelector('#output').textContent`),
    baseline,
  );
  assert.ok(
    await evaluate(
      `document.querySelector('#layer-kind').textContent.includes('Formality')`,
    ),
  );
  // Layer 3 was previously unavailable. Verify the new catalog direction goes
  // through the actual browser/API/model path, then restore the default run.
  await evaluate(`
    window.__catalogRequests=[];window.__catalogFetch=window.fetch;
    window.fetch=(url,options)=>{if(String(url).endsWith('/stream'))window.__catalogRequests.push(window.__captureRun(JSON.parse(options.body)));return window.__catalogFetch(url,options)};
    document.querySelector('#layer-enabled').click();
  `);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  assert.deepEqual(await evaluate(`window.__catalogRequests.at(-1).layer_strengths`), {3:0.5,11:0.5});
  assert.ok(await evaluate(`document.querySelector('#run-alpha').textContent.includes('L3')`));
  // Exercise generation for all four families with both selected layers.
  for (const feature of ['detoxification','formality']) {
    for (const pooling of ['final_token','mean']) {
      await evaluate(`window.__chooseFamily('${feature}','${pooling}');document.querySelector('#layer-mode-multi').click();for(const index of [3,11]){document.querySelector('[data-layer=\"'+index+'\"]').click();if(!document.querySelector('#layer-enabled').checked)document.querySelector('#layer-enabled').click()}`);
      await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
      // The last formality/mean run can be served from the earlier tab cache.
      const expected = await evaluate(`Object.fromEntries(JSON.parse(document.querySelector('#layer-vector-data').textContent).filter(v=>v.selectable && v.feature_id==='${feature}' && v.pooling==='${pooling}' && [3,11].includes(v.layer_index)).map(v=>[v.layer_index,v.id]))`);
      if (await evaluate(`document.querySelector('#run-source').textContent !== 'Tab cache'`)) {
        const request = await evaluate(`window.__catalogRequests.at(-1)`);
        assert.deepEqual(request.layer_strengths,{3:.5,11:.5});
        assert.deepEqual(request.layer_vector_ids,expected);
      }
      for (const id of Object.values(expected))
        assert.ok(await evaluate(`document.querySelector('#run-alpha').title.includes(${JSON.stringify(id)})`));
    }
  }
  await evaluate(`document.querySelector('#reset-layers').click()`);
  await until(`document.querySelector('#run-source').textContent === 'Tab cache'`);
  await evaluate(`window.fetch=window.__catalogFetch`);
  await evaluate(
    `document.querySelector('#layer-mode-multi').click();window.requests=[];const originalFetch=window.fetch;window.fetch=(url,options)=>{if(url.endsWith('/stream'))window.requests.push(window.__captureRun(JSON.parse(options.body)));return originalFetch(url,options)};document.querySelector('[data-layer="4"]').click();document.querySelector('#layer-enabled').click()`,
  );
  await until(
    `!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,
  );
  const request = await evaluate(`window.requests.at(-1)`);
  assert.deepEqual(request.layer_strengths, { 4: 0.5, 11: 0.5 });
  await checkHighlights();
  await evaluate(
    `document.querySelector('#mix-formality').value='0.7';document.querySelector('#mix-formality').dispatchEvent(new Event('input'))`,
  );
  await until(
    `!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,
  );
  assert.deepEqual(await evaluate(`window.requests.at(-1).layer_strengths`), {
    4: 0.7,
    11: 0.5,
  });
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
  const requestsBeforeTabs = await evaluate(`window.requests.length`);
  for (const [width, height] of [[1280, 800], [1366, 768], [1440, 900], [1920, 1080]]) {
    await cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await evaluate(`window.scrollTo({top:0,behavior:'instant'})`);
    const bounds = await evaluate(`Object.fromEntries(['#draft','#output','#mix-formality','#layer-grid','.draft-card','.output-card'].map(selector=>[selector,document.querySelector(selector).getBoundingClientRect().toJSON()]))`);
    for (const [selector, box] of Object.entries(bounds))
      assert.ok(box.top>=0 && box.bottom<=height+1 && box.left>=0 && box.right<=width+1,
        `${selector} fits ${width}×${height}: ${JSON.stringify(box)}`);
    const alignment=await evaluate(`Object.fromEntries(['.experiment-settings','.draft-card','.output-card','.feature-mixer','.model-map'].map(s=>[s,document.querySelector(s).getBoundingClientRect().toJSON()]))`);
    assert.ok(Math.abs(alignment['.experiment-settings'].bottom-alignment['.output-card'].bottom)<2,'Setup panel aligns with writing card bottoms');
    assert.ok(Math.abs(alignment['.draft-card'].bottom-alignment['.output-card'].bottom)<2,'Input/output card bottoms align');
    assert.ok(alignment['.feature-mixer'].right<=alignment['.model-map'].left,'Mixer sits left of model');
    assert.equal(await evaluate(`document.querySelector('#alpha')`),null,'Duplicate long strength slider is removed');
    const beforeOpen=await evaluate(`Object.fromEntries(['.model-section','.draft-card','.output-card','.experiment-settings'].map(s=>[s,document.querySelector(s).getBoundingClientRect().toJSON()]))`);
    await evaluate(`document.querySelector('.advanced-settings').open=true`);
    const afterOpen=await evaluate(`Object.fromEntries(['.model-section','.draft-card','.output-card','.experiment-settings'].map(s=>[s,document.querySelector(s).getBoundingClientRect().toJSON()]))`);
    for(const selector of Object.keys(beforeOpen)) {
      assert.ok(Math.abs(beforeOpen[selector].top-afterOpen[selector].top)<1,`${selector} never moves when instructions expand`);
      assert.ok(Math.abs(beforeOpen[selector].height-afterOpen[selector].height)<1,`${selector} never stretches when instructions expand`);
    }
    assert.ok(await evaluate(`document.querySelector('#slider-panel').getBoundingClientRect().height<=50`),'Layer controls occupy one compact line');
    if(height<=800)
      assert.ok(await evaluate(`document.querySelector('.setup-panel-body').scrollHeight>document.querySelector('.setup-panel-body').clientHeight`),'Instructions scroll at the panel limit');
    if(width===1366) {
      const expanded=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      await writeFile(join(directory,'instructions-expanded.png'),Buffer.from(expanded.data,'base64'));
    }
    await evaluate(`document.querySelector('.advanced-settings').open=false`);
    if (width === 1366 || width === 1920) {
      const screenshot = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      await writeFile(join(directory, `experiment-${width}.png`), Buffer.from(screenshot.data, 'base64'));
    }
  }
  await evaluate(`document.querySelector('#inspect-run').click();document.querySelector('.advanced-settings').open=true`);
  assert.ok(await evaluate(`Math.abs(document.querySelector('.experiment-settings').getBoundingClientRect().bottom-document.querySelector('.output-card').getBoundingClientRect().bottom)<2`),'Expanded prompt settings scroll within the aligned setup panel');
  assert.equal(await evaluate(`document.querySelector('#inspect-panel-run').hidden`), false);
  assert.ok(await evaluate(`document.querySelector('#run-alpha').textContent.includes('L11')`));
  assert.equal(await evaluate(`window.requests.length`), requestsBeforeTabs, 'Inspector and prompt display must not trigger generation');
  for (const width of [320, 390, 768, 1280]) {
    await cdp('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, `No horizontal overflow at ${width}px`);
    if (width === 390) {
      const screenshot = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      await writeFile(join(directory, 'experiment-mobile.png'), Buffer.from(screenshot.data, 'base64'));
    }
  }
  const mobile = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(join(directory, 'setup-responsive.png'), Buffer.from(mobile.data, 'base64'));
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await evaluate(
    `document.querySelector('#draft').value='A new request';document.querySelector('#draft').dispatchEvent(new Event('input'));document.querySelector('#clear').click()`,
  );
  assert.equal(
    await evaluate(`document.querySelector('#output').classList.contains('placeholder')`),
    true,
  );
  assert.equal(
    await evaluate(`document.querySelector('#output').textContent`),
    "Your response starts here.",
  );
  // Both checkboxes route independent feature banks through the v2 API.
  await evaluate(`document.querySelector('#reset-layers').click();document.querySelector('#draft').value='Please send the report before noon.';document.querySelector('#draft').dispatchEvent(new Event('input'));document.querySelector('#feature-detoxification').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  let combined=await evaluate(`window.requests.at(-1).interventions`);
  assert.deepEqual(combined.map(i=>i.vector_id).sort(),['qwen-detoxification-l11-mean-v1','qwen-formality-l11-mean-v1']);
  assert.equal(await evaluate(`document.querySelectorAll('.active-layer-chip').length`),2);
  await evaluate(`document.querySelector('#mix-detoxification').value='0.8';document.querySelector('#mix-detoxification').dispatchEvent(new Event('input'));document.querySelector('#mix-detoxification').dispatchEvent(new Event('change'))`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  combined=await evaluate(`window.requests.at(-1).interventions`);
  assert.equal(combined.find(i=>i.vector_id.startsWith('qwen-formality')).strength,.5);
  assert.equal(combined.find(i=>i.vector_id.startsWith('qwen-detoxification')).strength,.8);
  await evaluate(`document.querySelector('#focused-feature').value='formality';document.querySelector('#focused-feature').dispatchEvent(new Event('change'));document.querySelector('[data-layer="7"]').click();document.querySelector('#focused-pooling').value='final_token';document.querySelector('#focused-pooling').dispatchEvent(new Event('change'));document.querySelector('#mix-formality').value='0.4';document.querySelector('#mix-formality').dispatchEvent(new Event('input'));document.querySelector('#mix-formality').dispatchEvent(new Event('change'))`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  combined=await evaluate(`window.requests.at(-1).interventions`);
  assert.deepEqual(combined,[{vector_id:'qwen-detoxification-l11-mean-v1',strength:.8},{vector_id:'qwen-formality-l7-final_token-v1',strength:.4}]);
  assert.ok(await evaluate(`document.querySelector('#run-alpha').textContent.includes('Detoxification L11') && document.querySelector('#run-alpha').textContent.includes('Formality L7')`));
  await evaluate(`document.querySelector('#focused-feature').value='detoxification';document.querySelector('#focused-feature').dispatchEvent(new Event('change'))`);
  assert.equal(await evaluate(`document.querySelector('#focused-pooling').value`),'mean');
  assert.equal(await evaluate(`document.querySelector('#layer-name').textContent`),'Layer 11');
  assert.equal(await evaluate(`document.querySelector('#mix-formality').value`),'0.4');
  // Drag a wheel feature point; the other feature must retain its strength.
  await evaluate(`document.querySelector('.feature-mixer').scrollIntoView({block:'center',behavior:'instant'})`);
  const wheelGeometry=await evaluate(`({point:document.querySelector('[data-mix-feature="formality"]').getBoundingClientRect().toJSON(),wheel:document.querySelector('#mix-wheel').getBoundingClientRect().toJSON()})`);
  await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:wheelGeometry.point.left+wheelGeometry.point.width/2,y:wheelGeometry.point.top+wheelGeometry.point.height/2,button:'left',clickCount:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:wheelGeometry.wheel.left+wheelGeometry.wheel.width/2,y:wheelGeometry.wheel.top+wheelGeometry.wheel.height*(100-68*.6/2)/200,button:'left',buttons:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:wheelGeometry.wheel.left+wheelGeometry.wheel.width/2,y:wheelGeometry.wheel.top+wheelGeometry.wheel.height*(100-68*.6/2)/200,button:'left',clickCount:1});
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  combined=await evaluate(`window.requests.at(-1).interventions`);
  assert.equal(combined.find(i=>i.vector_id.startsWith('qwen-formality')).strength,.6);
  assert.equal(combined.find(i=>i.vector_id.startsWith('qwen-detoxification')).strength,.8);
  const mixerBox=await evaluate(`document.querySelector('.feature-mixer').getBoundingClientRect().toJSON()`);
  assert.ok(Math.abs(mixerBox.width-mixerBox.height)<2,'Mixer is square');
  const bothShot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile(join(directory,'both-features.png'),Buffer.from(bothShot.data,'base64'));
  await evaluate(`document.querySelector('#feature-detoxification').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  assert.equal(await evaluate(`window.requests.at(-1).interventions.length`),1);
  await evaluate(`document.querySelector('#feature-detoxification').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  assert.equal(await evaluate(`document.querySelector('#run-source').textContent`),'Tab cache','Re-enabling restores exact combined settings from cache');
  // Task presets and Apply-only prompt/limit edits use the real API/model path.
  await evaluate(`document.querySelector('#clear-layers').click();document.querySelector('#experiment-prompt').value='summarize';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'));document.querySelector('#draft').value='The town library opens at nine each morning. It closes at six each evening. Membership is free for residents. '.repeat(50);document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,100);
  const summaryRequest = await evaluate(`window.requests.at(-1)`);
  assert.equal(summaryRequest.task,'summarize');
  assert.ok(summaryRequest.system_prompt.startsWith('Summarize'));
  assert.equal(summaryRequest.max_input_tokens,2048);
  assert.equal(summaryRequest.max_new_tokens,256);
  assert.ok(summaryRequest.message.length>2000);
  assert.equal(await evaluate(`document.querySelector('#changes-toggle')`),null);
  assert.equal(await evaluate(`document.querySelectorAll('#output .word-new').length`),0);
  assert.equal(await evaluate(`document.querySelector('#run-task').textContent`),'summarize');
  const beforePromptEdit = await evaluate(`window.requests.length`);
  await evaluate(`document.querySelector('#system-prompt').value='Respond with one short sentence.';document.querySelector('#system-prompt').dispatchEvent(new Event('input'));document.querySelector('#input-budget').value=4096;document.querySelector('#output-budget').value=64;document.querySelector('#output-budget').dispatchEvent(new Event('input'))`);
  assert.equal(await evaluate(`window.requests.length`),beforePromptEdit,'Unapplied edits never generate');
  assert.equal(await evaluate(`document.querySelector('#run-task').textContent`),'summarize');
  await evaluate(`document.querySelector('#apply-prompt').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,100);
  const customRequest = await evaluate(`window.requests.at(-1)`);
  assert.equal(customRequest.task,'custom');
  assert.equal(customRequest.system_prompt,'Respond with one short sentence.');
  assert.equal(customRequest.max_input_tokens,4096); assert.equal(customRequest.max_new_tokens,64);
  assert.equal(await evaluate(`document.querySelector('#run-prompt').textContent`),customRequest.system_prompt);
  await evaluate(`document.querySelector('#clear').click();document.querySelector('#experiment-prompt').value='none';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'));document.querySelector('#draft').value='What is two plus two?';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,100);
  assert.equal(await evaluate(`window.requests.at(-1).system_prompt`),null);
  assert.equal(await evaluate(`document.querySelector('#run-prompt').textContent`),'No system message');
  await evaluate(`document.querySelector('#clear').click();document.querySelector('#experiment-prompt').value='rewrite';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'))`);
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
