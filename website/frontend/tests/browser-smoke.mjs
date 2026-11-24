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
  // An unselected edited layer must not imply the feature is disabled.
  await evaluate(`document.querySelector('#layer-mode-multi').click();document.querySelector('[data-layer="9"]').click();document.querySelector('#layer-enabled').click();document.querySelector('[data-layer="10"]').click()`);
  assert.equal(await evaluate(`document.querySelector('#mix-detoxification').disabled`),true);
  assert.ok(await evaluate(`document.querySelector('#mix-status-detoxification').textContent.includes('2 other layers still active')`));
  assert.ok(await evaluate(`document.querySelector('#mix-detoxification').previousElementSibling.textContent.includes('other layers')`));
  await evaluate(`document.querySelector('#mix-precise-controls').showPopover();document.querySelector('#mix-status-detoxification').click()`);
  assert.equal(await evaluate(`document.querySelector('#mix-layers-detoxification').matches(':popover-open')`),true);
  assert.ok(await evaluate(`document.querySelector('#mix-layers-detoxification').textContent.includes('L9') && document.querySelector('#mix-layers-detoxification').textContent.includes('L11')`));
  await evaluate(`document.querySelector('#mix-layers-detoxification').hidePopover();document.querySelector('#mix-precise-controls').hidePopover();document.querySelector('[aria-label="Disable Detoxification layer 9"]').click();document.querySelector('[data-layer="11"]').click()`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
  assert.ok(await evaluate(`document.querySelector('#run-runtime').textContent.includes('torch.float')`),'Actual generation dtype is visible');
  // Drag a wheel feature point; the other feature must retain its strength.
  await evaluate(`document.querySelector('.feature-mixer').scrollIntoView({block:'center',behavior:'instant'})`);
  const wheelGeometry=await evaluate(`(() => {const wheel=document.querySelector('#mix-wheel'),p=wheel.createSVGPoint();
    p.x=250;p.y=240-130*(.6+2)/4;const target=p.matrixTransform(wheel.getScreenCTM());
    return {point:document.querySelector('[data-mix-feature="formality"]').getBoundingClientRect().toJSON(),target:{x:target.x,y:target.y}};})()`);
  await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:wheelGeometry.point.left+wheelGeometry.point.width/2,y:wheelGeometry.point.top+wheelGeometry.point.height/2,button:'left',clickCount:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:wheelGeometry.target.x,y:wheelGeometry.target.y,button:'left',buttons:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:wheelGeometry.target.x,y:wheelGeometry.target.y,button:'left',clickCount:1});
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
  await evaluate(`document.querySelector('#clear').click();document.querySelector('#experiment-prompt').value='rewrite_continue';document.querySelector('#experiment-prompt').dispatchEvent(new Event('change'));
    document.querySelector('#draft').value="hell i'm not gonna do this work unless I get a reward. you can always choose to fire me but these are my conditions at the moment.";document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,100);
  assert.equal(await evaluate(`window.requests.at(-1).task`),'rewrite_continue');
  assert.equal(await evaluate(`document.querySelector('#run-task').textContent`),'rewrite_continue');
  assert.ok(await evaluate(`document.querySelector('#output').textContent.includes('\\n\\n')`),'Combined output contains rewrite and continuation');
  assert.ok(await evaluate(`document.querySelector('#run-prompt').textContent.includes('Both stages')`),'Run details disclose both phases');
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
        await evaluate(`document.querySelector('.community-hero .landing-outline').getAttribute('href') === '#install' && document.querySelector('.zip-link').getAttribute('href').endsWith('.zip') && /Setup-(Windows|macOS)/.test(document.querySelector('.setup-button').getAttribute('href'))`),
        true,
      );
    if (path === "/community")
      assert.equal(
        await evaluate(`(() => { document.querySelector('#tab-mac').click(); return !document.querySelector('#panel-mac').hidden && document.querySelector('#panel-windows').hidden; })()`),
        true,
        "the developer OS tabs switch the command",
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
  if(socket)socket.close();chrome.kill('SIGTERM');
}
