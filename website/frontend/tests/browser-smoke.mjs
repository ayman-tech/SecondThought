// Optional local browser QA. Uses installed Chrome + Node 22+, no npm packages.
// Start `make website`, then run `node website/frontend/tests/browser-smoke.mjs`.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const base = process.env.WEBSITE_URL || 'http://127.0.0.1:8001';
const chromePath = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const directory = await mkdtemp(join(tmpdir(), 'secondthought-browser-'));
const chrome = spawn(chromePath, [
  '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--remote-debugging-port=0', `--user-data-dir=${directory}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
try {
  const devtools = await new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('Chrome did not start')), 15000);
    chrome.once('error', reject);
    chrome.stderr.on('data', chunk => {
      output += chunk;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timeout); resolve(match[1]); }
    });
  });
  const origin = devtools.replace(/^ws:/, 'http:').split('/devtools')[0];
  const targets = await (await fetch(`${origin}/json/list`)).json();
  const target = targets.find(t => t.type === 'page');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0; const pending = new Map(); const exceptions = [];
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const promise = pending.get(message.id); pending.delete(message.id);
      if (message.error) promise.reject(new Error(JSON.stringify(message.error)));
      else promise.resolve(message.result);
    }
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
  };
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id; pending.set(requestId, { resolve, reject });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
  const evaluate = async expression => {
    const result = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const until = async (expression, seconds = 35) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
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
    throw new Error(`Timed out waiting for ${expression}; page state: ${JSON.stringify(geometry)}; exceptions: ${JSON.stringify(exceptions)}`);
  };
  await cdp('Runtime.enable'); await cdp('Page.enable');
  // Full-page navigation can leave a headless target unfocused. Emulate the
  // foreground tab so focus/blur and viewport events behave like a user session.
  await cdp('Emulation.setFocusEmulationEnabled', { enabled: true });
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: base });
  await until(`document.querySelector('.page-home') !== null`);
  assert.equal(await evaluate(`document.querySelector('#experimental')`), null);
  assert.equal(await evaluate(`document.querySelector('script[src="/assets/steering.js"]')`), null);
  await evaluate(`document.querySelector('a[href="/steering"]').click()`);
  await until(`document.getElementById('model-status')?.textContent.includes('ready')`, 60);
  assert.equal(await evaluate(`Boolean(document.querySelector('button[type=submit]'))`), false);
  assert.equal(await evaluate(`document.querySelector('#alpha').min`), '-2');
  assert.equal(await evaluate(`document.querySelector('#alpha').max`), '2');
  await evaluate(`document.querySelector('#draft').value='its really hard when u want to know what happened'; document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);
  const first = await evaluate(`document.querySelector('#output').textContent`);
  assert.ok(first.length > 3);
  await evaluate(`document.querySelector('#alpha').value='1'; document.querySelector('#alpha').dispatchEvent(new Event('input')); document.querySelector('#alpha').dispatchEvent(new Event('change'))`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.') && document.querySelector('#output-parameters').textContent.includes('+1.0')`);
  const second = await evaluate(`document.querySelector('#output').textContent`);
  assert.notEqual(first, second, 'Chosen notebook example should respond to alpha');
  async function assertSourceHighlights() {
    const comparison = await evaluate(`(async()=>{
      const {wordChanges}=await import('/assets/lifecycle.js');
      return {
        expected:wordChanges(document.querySelector('#draft').value.trim(),document.querySelector('#output').textContent).filter(x=>x.added).map(x=>x.text),
        actual:[...document.querySelectorAll('#output .word-new')].map(x=>x.textContent)
      };
    })()`);
    assert.deepEqual(comparison.actual, comparison.expected, 'Highlights must always compare with the original input');
  }
  await assertSourceHighlights();
  console.log('Real model + browser:', { alpha05: first, alpha1: second });

  // Keep source, rewrite, strength, and the complete layer stack visible at
  // normal desktop viewport sizes. Long results scroll inside their own panel.
  for (const [width, height] of [[1280, 800], [1366, 768], [1440, 900], [1920, 1080]]) {
    await cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await evaluate(`window.scrollTo({top:0,behavior:'instant'});window.dispatchEvent(new Event('resize'))`);
    const bounds = await evaluate(`Object.fromEntries(['#output-card','#draft','#alpha','.layer-stack','.inspector-tabs'].map(selector=>[selector,document.querySelector(selector).getBoundingClientRect().toJSON()]))`);
    for (const [selector, box] of Object.entries(bounds)) {
      assert.ok(box.top >= 0 && box.bottom <= height + 1 && box.left >= 0 && box.right <= width + 1,
        `${selector} must fit ${width}×${height}: ${JSON.stringify(box)}`);
    }
    assert.ok(await evaluate(`document.documentElement.scrollWidth <= innerWidth`));
    const screenshot = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    await writeFile(join(directory, `workspace-${width}.png`), Buffer.from(screenshot.data, 'base64'));
  }
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await evaluate(`document.querySelector('#tab-run').click()`);
  assert.equal(await evaluate(`document.querySelector('#panel-run').hidden`), false);
  assert.equal(await evaluate(`document.querySelector('#run-alpha').textContent`), '+1.0');
  assert.ok(await evaluate(`Number(document.querySelector('#run-tokens').textContent)>0`));
  await evaluate(`document.querySelector('#tab-changes').click();document.querySelector('#tab-changes').focus()`);
  assert.equal(await evaluate(`document.querySelector('#change-source-count').textContent`), '10');
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Home', code: 'Home' });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Home', code: 'Home' });
  assert.equal(await evaluate(`document.querySelector('#tab-evaluation').getAttribute('aria-selected')`), 'true');

  // Immediate feedback, final-value scheduling, stale-response rejection.
  await evaluate(`
    window.__testRequests=[];
    window.__originalFetch=window.fetch;
    window.fetch=async function(url,options) {
      if(String(url).endsWith('/steering/cancel')) return new Response('{}');
      if(!String(url).endsWith('/steering/stream')) return window.__originalFetch(url,options);
      const body=JSON.parse(options.body); window.__testRequests.push(body);
      const delay=body.message.includes('slow')?800:40;
      return new Response(new ReadableStream({start(controller){setTimeout(()=>{
        const encoder=new TextEncoder();
        const text=body.message==='stable result source'?'A rewritten sentence.':'Browser test: '+body.message+' @ '+body.alpha;
        for(const event of [
          {event:'delta',text},
          {event:'completed',rewritten_text:text,finish_reason:'stop',latency_ms:40},
        ]) controller.enqueue(encoder.encode(JSON.stringify({...event,revision:body.revision,alpha:body.alpha})+'\\n'));
        controller.close();
      },delay)}}),{headers:{'Content-Type':'application/x-ndjson'}});
    };
    document.querySelector('#draft').value='slow obsolete input';
    document.querySelector('#draft').dispatchEvent(new Event('input'));
  `);
  await until(`window.__testRequests.length === 1`);
  await evaluate(`
    document.querySelector('#draft').value='latest <img src=x onerror=alert(1)>';
    document.querySelector('#draft').dispatchEvent(new Event('input'));
    for(const value of ['-1','0','0.6','1.4']) {
      document.querySelector('#alpha').value=value;
      document.querySelector('#alpha').dispatchEvent(new Event('input'));
    }
    document.querySelector('#alpha').dispatchEvent(new Event('change'));
  `);
  assert.equal(await evaluate(`document.querySelector('#alpha-value').value`), '+1.4');
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.') && document.querySelector('#output').textContent.includes('@ 1.4')`);
  await new Promise(resolve => setTimeout(resolve, 1000));
  assert.ok(await evaluate(`document.querySelector('#output').textContent.includes('latest')`));
  assert.equal(await evaluate(`document.querySelectorAll('#output img').length`), 0);
  assert.equal(await evaluate(`window.__testRequests.length`), 2);
  assert.equal(await evaluate(`document.querySelector('#run-alpha').textContent`), '+1.4');
  // Back to the exact cached setting: no new model request.
  await evaluate(`document.querySelector('[data-alpha="0"]').click()`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);
  await evaluate(`document.querySelector('#alpha').value='1.4'; document.querySelector('#alpha').dispatchEvent(new Event('input')); document.querySelector('#alpha').dispatchEvent(new Event('change'))`);
  await until(`document.querySelector('#status').textContent.includes('Restored')`);
  assert.equal(await evaluate(`window.__testRequests.length`), 3);
  assert.equal(await evaluate(`document.querySelector('#run-source').textContent`), 'Tab cache');
  await assertSourceHighlights();

  // A response after Clear must not repopulate the output.
  await evaluate(`document.querySelector('#draft').value='slow cleared input';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`window.__testRequests.length === 4`);
  await evaluate(`document.querySelector('#clear').click()`);
  await new Promise(resolve => setTimeout(resolve, 1000));
  assert.equal(await evaluate(`document.querySelector('#output').textContent`), 'Your next wording starts here.');
  assert.equal(await evaluate(`document.querySelector('#copy').disabled`), true);
  assert.equal(await evaluate(`document.querySelector('#run-alpha').textContent`), '—');
  assert.equal(await evaluate(`document.querySelector('#change-source-count').textContent`), '—');

  // Identical consecutive rewrites must retain differences from the source.
  await evaluate(`document.querySelector('#draft').value='stable result source';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);
  await assertSourceHighlights();
  await evaluate(`document.querySelector('#alpha').value='0.8';document.querySelector('#alpha').dispatchEvent(new Event('input'));document.querySelector('#alpha').dispatchEvent(new Event('change'))`);
  await until(`document.querySelector('#change-note').textContent.startsWith('Same wording')`);
  await assertSourceHighlights();
  assert.ok(await evaluate(`document.querySelectorAll('#output .word-new').length > 0`));
  await evaluate(`document.querySelector('#changes-toggle').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('#output .word-new').length`), 0);
  await evaluate(`document.querySelector('#changes-toggle').click()`);
  await assertSourceHighlights();

  // A network error preserves the draft and offers a working retry.
  await evaluate(`window.fetch=async()=>{throw new TypeError('Network disconnected')};document.querySelector('#draft').value='retry source';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`!document.querySelector('#error-box').hidden`);
  assert.equal(await evaluate(`document.querySelector('#draft').value`), 'retry source');
  await evaluate(`window.fetch=window.__originalFetch;document.querySelector('#retry').click()`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);

  await evaluate(`document.querySelector('#experimental').scrollIntoView({behavior:'instant',block:'start'})`);
  const desktop = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'desktop.png'), Buffer.from(desktop.data, 'base64'));
  await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate(`document.querySelector('#draft').blur();document.querySelector('#experimental').scrollIntoView({behavior:'instant',block:'start'});window.dispatchEvent(new Event('resize'))`);
  await until(`document.querySelector('#slider-panel').classList.contains('is-docked')`, 5);
  assert.ok(await evaluate(`document.querySelector('#alpha').getBoundingClientRect().bottom < window.innerHeight`));
  assert.equal(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`), true, 'No mobile horizontal overflow');
  const mobile = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'mobile.png'), Buffer.from(mobile.data, 'base64'));
  await evaluate(`document.querySelector('#draft').focus()`);
  await until(`!document.querySelector('#slider-panel').classList.contains('is-docked')`);
  await cdp('Page.navigate', { url: base });
  await until(`document.querySelector('.page-home') !== null`);
  assert.equal(await evaluate(`document.querySelector('#experimental')`), null);
  await evaluate(`window.scrollTo({top:0,behavior:'instant'})`);
  const overview = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'overview.png'), Buffer.from(overview.data, 'base64'));
  const history = await cdp('Page.getNavigationHistory');
  const labEntry = history.entries.slice(0, history.currentIndex).findLast(entry => entry.url === base + '/steering');
  assert.ok(labEntry);
  await cdp('Page.navigateToHistoryEntry', { entryId: labEntry.id });
  await until(`document.querySelector('#model-status')?.textContent.includes('ready')`);
  await evaluate(`document.querySelector('#draft').value='A fresh draft after going back.';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);
  await assertSourceHighlights();
  for (const path of ['/extension', '/evaluation', '/about']) {
    await cdp('Page.navigate', { url: base + path });
    await until(`document.querySelector('nav [aria-current="page"]')?.getAttribute('href') === ${JSON.stringify(path)}`);
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`), true);
  }
  assert.deepEqual(exceptions, []);
  console.log('Browser QA passed: separate pages, original-input highlights, latest revision, clear, cache, HTML-safe rendering, retry, mobile layout.');
  console.log('Screenshots:', directory);
} finally {
  if (socket) socket.close();
  chrome.kill('SIGTERM');
}
