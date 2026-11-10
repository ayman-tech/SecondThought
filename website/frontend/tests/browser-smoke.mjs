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
    throw new Error(`Timed out waiting for ${expression}`);
  };
  await cdp('Runtime.enable'); await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: base });
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
  console.log('Real model + browser:', { alpha05: first, alpha1: second });

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
        const text='Browser test: '+body.message+' @ '+body.alpha;
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
  // Back to the exact cached setting: no new model request.
  await evaluate(`document.querySelector('[data-alpha="0"]').click()`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);
  await evaluate(`document.querySelector('#alpha').value='1.4'; document.querySelector('#alpha').dispatchEvent(new Event('input')); document.querySelector('#alpha').dispatchEvent(new Event('change'))`);
  await until(`document.querySelector('#status').textContent.includes('Restored')`);
  assert.equal(await evaluate(`window.__testRequests.length`), 3);

  // A response after Clear must not repopulate the output.
  await evaluate(`document.querySelector('#draft').value='slow cleared input';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`window.__testRequests.length === 4`);
  await evaluate(`document.querySelector('#clear').click()`);
  await new Promise(resolve => setTimeout(resolve, 1000));
  assert.equal(await evaluate(`document.querySelector('#output').textContent`), 'Your next wording starts here.');
  assert.equal(await evaluate(`document.querySelector('#copy').disabled`), true);

  // A network error preserves the draft and offers a working retry.
  await evaluate(`window.fetch=async()=>{throw new TypeError('Network disconnected')};document.querySelector('#draft').value='retry source';document.querySelector('#draft').dispatchEvent(new Event('input'))`);
  await until(`!document.querySelector('#error-box').hidden`);
  assert.equal(await evaluate(`document.querySelector('#draft').value`), 'retry source');
  await evaluate(`window.fetch=window.__originalFetch;document.querySelector('#retry').click()`);
  await until(`document.querySelector('#status').textContent.startsWith('Up to date.')`);

  await evaluate(`document.querySelector('#experimental').scrollIntoView({behavior:'instant',block:'start'})`);
  const desktop = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'desktop.png'), Buffer.from(desktop.data, 'base64'));
  await evaluate(`window.scrollTo({top:0,behavior:'instant'})`);
  const overview = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'overview.png'), Buffer.from(overview.data, 'base64'));
  await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate(`document.querySelector('#draft').blur();document.querySelector('#experimental').scrollIntoView({behavior:'instant',block:'start'})`);
  await until(`document.querySelector('#slider-panel').classList.contains('is-docked')`);
  assert.ok(await evaluate(`document.querySelector('#alpha').getBoundingClientRect().bottom < window.innerHeight`));
  assert.equal(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`), true, 'No mobile horizontal overflow');
  const mobile = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(directory, 'mobile.png'), Buffer.from(mobile.data, 'base64'));
  await evaluate(`document.querySelector('#draft').focus()`);
  await until(`!document.querySelector('#slider-panel').classList.contains('is-docked')`);
  assert.deepEqual(exceptions, []);
  console.log('Browser QA passed: latest revision, clear, cache, HTML-safe rendering, retry, mobile layout.');
  console.log('Screenshots:', directory);
} finally {
  if (socket) socket.close();
  chrome.kill('SIGTERM');
}
