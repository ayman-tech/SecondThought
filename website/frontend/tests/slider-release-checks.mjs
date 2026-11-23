import assert from "node:assert/strict";

// Hold scheduling timers and model responses independently. Release must submit
// synchronously, without waiting for a 250ms timer or for an older model job.
export async function checkSliderRelease({ evaluate, cdp, until }) {
  await evaluate(`
    window.__releaseQA = {
      fetch: window.fetch, setTimeout: window.setTimeout, clearTimeout: window.clearTimeout,
      timers: new Map(), nextTimer: -1, requests: []
    };
    window.setTimeout = function(callback, delay, ...args) {
      const qa = window.__releaseQA;
      if ([250, 450, 1000].includes(delay)) {
        const id = qa.nextTimer--;
        qa.timers.set(id, { delay, callback: () => callback(...args) });
        return id;
      }
      return qa.setTimeout.call(window, callback, delay, ...args);
    };
    window.clearTimeout = function(id) {
      if (!window.__releaseQA.timers.delete(id))
        window.__releaseQA.clearTimeout.call(window, id);
    };
    window.fetch = async function(url, options) {
      const qa = window.__releaseQA;
      if (String(url).endsWith('/cancel')) return new Response('{}');
      if (!String(url).endsWith('/stream')) return qa.fetch.call(window, url, options);
      const request = { body: JSON.parse(options.body), signal: options.signal };
      qa.requests.push(request);
      return new Response(new ReadableStream({ start(controller) { request.controller = controller; } }),
        { headers: { 'Content-Type': 'application/x-ndjson' } });
    };
    window.__releaseEdit = function(value, commit = true) {
      const slider = document.querySelector('#mix-formality');
      slider.value = value;
      slider.dispatchEvent(new Event('input'));
      if (commit) slider.dispatchEvent(new Event('change'));
    };
    window.__releaseTimer = function(delay) {
      const entry = [...window.__releaseQA.timers].find(([, timer]) => timer.delay === delay);
      if (!entry) throw new Error('Expected a pending ' + delay + 'ms timer');
      window.__releaseQA.timers.delete(entry[0]);
      entry[1].callback();
    };
    window.__releaseFinish = function(index, text) {
      const request = window.__releaseQA.requests[index];
      if (request.finished) return;
      request.finished = true;
      const encoder = new TextEncoder();
      for (const event of [
        { event: 'delta', text },
        { event: 'completed', text, generated_tokens: 3,
          finish_reason: 'stop', latency_ms: 20 }
      ]) request.controller.enqueue(encoder.encode(JSON.stringify({
        ...event, revision: request.body.revision
      }) + '\\n'));
      request.controller.close();
    };
    document.querySelector('#draft').value = 'Phase zero original draft';
    document.querySelector('#draft').dispatchEvent(new Event('input'));
  `);
  const requestCount = () => evaluate(`window.__releaseQA.requests.length`);
  const release = () => evaluate(`document.querySelector('#mix-formality').dispatchEvent(new Event('change'))`);
  try {
    await evaluate(`window.__releaseTimer(450)`);
    assert.equal(await requestCount(), 1);
    await evaluate(`window.__releaseEdit('1.1', false)`);
    assert.equal(await requestCount(), 1, "Dragging still debounces");
    await release();
    assert.equal(await requestCount(), 2, "Release submits before the scheduling timer runs");
    assert.equal(await evaluate(`window.__releaseQA.requests[0].signal.aborted`), true);
    assert.deepEqual(await evaluate(`Object.fromEntries(window.__releaseQA.requests[1].body.interventions.map(i=>[Number(i.vector_id.match(/-l(\\d+)-/)[1]),i.strength]))`), { 11: 1.1 });
    assert.equal(await evaluate(`window.__releaseQA.timers.size`), 0);
    await release();
    assert.equal(await requestCount(), 2, "Repeated commit must not restart in-flight work");

    await evaluate(`window.__releaseFinish(0, 'Obsolete response')`);
    await evaluate(`new Promise(resolve => window.__releaseQA.setTimeout.call(window, resolve, 0))`);
    assert.equal(await evaluate(`document.querySelector('#output').textContent.includes('Obsolete')`), false);

    await evaluate(`window.__releaseEdit('1.2', false); window.__releaseTimer(250)`);
    assert.equal(await requestCount(), 3, "Pause during a drag still dispatches");
    await release();
    assert.equal(await requestCount(), 3, "Release after debounce must not duplicate the job");
    await evaluate(`window.__releaseEdit('1.3', false); window.__releaseTimer(1000)`);
    assert.equal(await requestCount(), 4, "Maximum-wait dispatch remains active");
    await release();
    assert.equal(await requestCount(), 4, "Release after maximum wait must not duplicate the job");
    await evaluate(`window.__releaseFinish(3, 'Current response')`);
    await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
    await release();
    assert.equal(await requestCount(), 4, "Commit after completion must not regenerate");

    await evaluate(`window.__releaseEdit('1.4'); window.__releaseFinish(4, 'Another response')`);
    await until(`!document.querySelector('#output').classList.contains('placeholder') && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`);
    await evaluate(`window.__releaseEdit('1.3')`);
    assert.equal(await requestCount(), 5, "Release restores the completed cached setting");
    assert.equal(await evaluate(`document.querySelector('#run-source').textContent`), "Tab cache");
    await release();
    assert.equal(await requestCount(), 5);

    await evaluate(`
      document.querySelector('#layer-mode-multi').click();
      const preview=document.querySelector('.layer.preview');
      if(preview) { preview.click(); document.querySelector('#layer-enabled').click(); window.__releaseEdit('1.8'); }
      document.querySelector('[data-layer="4"]').click(); window.__releaseEdit('0.7');`);
    assert.equal(await requestCount(), 5, "Preview and unselected layers never submit on release");
    await evaluate(`document.querySelector('#draft').value = 'Pending typing';
      document.querySelector('#draft').dispatchEvent(new Event('input'));`);
    await release();
    assert.equal(await requestCount(), 5, "Unselected-layer release cannot flush pending typing");
    await evaluate(`document.querySelector('[data-mix-feature="formality"]').dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true}))`);
    assert.equal(await requestCount(),5,'Disabled spider-axis release cannot flush pending typing');
    assert.equal(await evaluate(`[...window.__releaseQA.timers.values()].some(t => t.delay === 450)`), true);
    await evaluate(`document.querySelector('#clear').click();
      document.querySelector('[data-layer="11"]').click(); window.__releaseEdit('0.6');`);
    assert.equal(await requestCount(), 5, "Empty/cleared drafts never generate");
    assert.equal(await evaluate(`window.__releaseQA.timers.size`), 0);

    // Exercise actual native input/change events as well as synthetic commits.
    await evaluate(`document.querySelector('#mix-precise-controls').showPopover()`);
    await evaluate(`document.querySelector('#draft').value = 'Keyboard and pointer source';
      document.querySelector('#draft').dispatchEvent(new Event('input'));
      window.__releaseTimer(450); document.querySelector('#mix-formality').focus();`);
    assert.equal(await requestCount(), 6);
    await cdp("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight" });
    await cdp("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight" });
    assert.equal(await requestCount(), 7, "Native keyboard commit dispatches immediately");
    await evaluate(`document.querySelector('#mix-formality').scrollIntoView({behavior:'instant',block:'center'})`);
    const bounds = await evaluate(`document.querySelector('#mix-formality').getBoundingClientRect().toJSON()`);
    const x = bounds.left + bounds.width * 0.8, y = bounds.top + bounds.height / 2;
    await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    assert.equal(await requestCount(), 7, "Pointer drag waits while scheduling timers are held");
    await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
    assert.equal(await requestCount(), 8, "Native pointer release dispatches immediately");
    assert.equal(await evaluate(`window.__releaseQA.requests.at(-1).body.interventions.find(i=>i.vector_id.includes('-l11-')).strength`),
      await evaluate(`Number(document.querySelector('#mix-formality').value)`));
    await evaluate(`document.querySelector('#mix-precise-controls').hidePopover();
      document.querySelector('[data-mix-feature="formality"]').focus()`);
    await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Home',code:'Home'});
    await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Home',code:'Home'});
    assert.equal(await requestCount(),9,'Spider-web keyboard release dispatches immediately');
    assert.equal(await evaluate(`window.__releaseQA.requests.at(-1).body.interventions[0].strength`),-2);
  } finally {
    // Finish obsolete test streams after invalidating them and leave the real
    // browser smoke test with a clean draft, default layers, and normal timers.
    await evaluate(`
      document.querySelector('#clear').click(); document.querySelector('#reset-layers').click();
      if(document.querySelector('#mix-precise-controls').matches(':popover-open'))document.querySelector('#mix-precise-controls').hidePopover();
      window.__releaseQA.requests.forEach((_, index) => window.__releaseFinish(index, 'Late fixture response'));
      window.fetch = window.__releaseQA.fetch;
      window.setTimeout = window.__releaseQA.setTimeout;
      window.clearTimeout = window.__releaseQA.clearTimeout;
    `);
  }
  console.log("Phase 0: immediate release, debounce/max-wait, no duplicates, stale rejection, cache, preview exclusion, clear, keyboard and pointer passed.");
}
