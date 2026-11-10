import { Revisions, ResultCache, cacheKey, consumeNDJSON, wordChanges } from './lifecycle.js';

const $ = id => document.getElementById(id);
const elements = Object.fromEntries([
  'draft', 'alpha', 'alpha-value', 'slider-help', 'output', 'output-card',
  'output-context', 'output-parameters', 'change-note', 'latency', 'status',
  'copy', 'changes-toggle', 'changes-check', 'clear', 'error-box', 'error-message',
  'retry', 'character-count', 'vector-line', 'vector-point', 'vector-description',
  'model-dot', 'model-status', 'reconnect', 'live-indicator',
].map(id => [id, $(id)]));
const revisions = new Revisions();
const cache = new ResultCache();
const session = crypto.randomUUID(); // A tab-local routing key, not an account.
let config = null, ready = false, active = null, completed = null;
let trailingTimer = null, maxWaitTimer = null, readinessTimer = null;
let highlightChanges = true, composing = false;

const signed = n => `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(1)}`;
const desired = () => ({ message: elements.draft.value.trim(), alpha: Number(elements.alpha.value) });
const currentKey = () => cacheKey(desired().message, desired().alpha, config?.steering_version);

function setStatus(message, busy = false) {
  elements.status.textContent = message;
  elements['output-card'].setAttribute('aria-busy', String(busy));
  elements['live-indicator'].className = `live-indicator ${busy ? 'busy' : completed ? 'complete' : ''}`;
}
function showError(message) {
  elements['error-box'].hidden = false;
  elements['error-message'].textContent = message;
  setStatus('Could not finish this rewrite. Your draft is still here.');
}
function clearError() { elements['error-box'].hidden = true; }
function clearSchedule() {
  clearTimeout(trailingTimer); clearTimeout(maxWaitTimer);
  trailingTimer = maxWaitTimer = null;
}
function cancelActive() {
  if (!active) return;
  const previous = active;
  active = null;
  previous.controller.abort();
  // Explicit cancellation also covers a request still queued on the server.
  void fetch('/api/v1/steering/cancel', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
    body: JSON.stringify({ session_id: session, revision: previous.revision }),
  }).catch(() => {});
}
function renderText(text, before = null) {
  const fragment = document.createDocumentFragment();
  const segments = before !== null && highlightChanges ? wordChanges(before, text) : [{ text, added: false }];
  for (const segment of segments) {
    if (segment.added) {
      const span = document.createElement('span');
      span.className = 'word-new'; span.textContent = segment.text; fragment.append(span);
    } else fragment.append(document.createTextNode(segment.text));
  }
  elements.output.replaceChildren(fragment);
  elements.output.classList.remove('placeholder');
}
function keepPrevious() {
  if (completed) {
    renderText(completed.text);
    elements['output-context'].textContent = 'Previous result · updating for your latest input';
    elements['output-parameters'].textContent = `Shown at α ${signed(completed.alpha)}`;
  } else {
    elements.output.textContent = 'Finding another way to say it…';
    elements.output.classList.add('placeholder');
    elements['output-context'].textContent = 'Preparing your rewrite';
    elements['output-parameters'].textContent = '';
  }
  elements.copy.disabled = true;
}
function refreshControls() {
  const { alpha } = desired();
  elements['alpha-value'].value = signed(alpha);
  elements.alpha.setAttribute('aria-valuetext', `${signed(alpha)} formality strength`);
  elements['character-count'].textContent = `${elements.draft.value.length.toLocaleString()} / 2,000`;
  const percent = 50 + alpha * 22.5;
  elements['vector-point'].style.left = `${percent}%`;
  elements['vector-line'].style.left = `${Math.min(percent, 50)}%`;
  elements['vector-line'].style.width = `${Math.abs(percent - 50)}%`;
  elements['vector-description'].textContent = alpha === 0 ? 'No formality vector'
    : alpha < 0 ? 'Against the learned direction' : 'Along the learned direction';
  elements['slider-help'].textContent = alpha === 0
    ? 'The neutral rewrite prompt is still active. Zero is a model baseline, not a copy of your draft.'
    : Math.abs(alpha) > 1 ? 'A stronger intervention. Watch for changed meaning, names, facts, or requested actions.'
      : 'Results vary by sentence. Nearby values can produce the same wording.';
}
function inputChanged(kind = 'text') {
  revisions.next(); clearError(); refreshControls();
  const { message } = desired();
  if (!message) {
    clearSchedule(); cancelActive(); completed = null; cache.clear();
    elements.output.replaceChildren(document.createTextNode('Your next wording starts here.'));
    elements.output.classList.add('placeholder');
    elements['output-context'].textContent = 'Write a draft below';
    elements['output-parameters'].textContent = '';
    elements['change-note'].textContent = 'Type a draft or choose a sample. No Generate button needed.';
    elements.latency.textContent = ''; elements.copy.disabled = true;
    setStatus('Waiting for a draft.'); return;
  }
  // Invalidate display immediately. Network cancellation happens at dispatch,
  // except text edits, where old-context generation is no longer useful.
  if (kind === 'text') cancelActive();
  keepPrevious();
  setStatus(ready ? 'Waiting for a short pause in your input…' : 'Your draft is ready. Waiting for the model.', true);
  clearTimeout(trailingTimer);
  trailingTimer = setTimeout(dispatch, kind === 'slider' ? 250 : 450);
  if (kind === 'slider' && maxWaitTimer === null) maxWaitTimer = setTimeout(dispatch, 1000);
}
function finish(event, snapshot, fromCache = false) {
  const previous = completed?.source === snapshot.message ? completed.text : snapshot.message;
  const unchanged = completed?.source === snapshot.message && completed.text === event.rewritten_text;
  completed = { text: event.rewritten_text, source: snapshot.message, alpha: snapshot.alpha, before: previous };
  renderText(completed.text, unchanged ? null : previous);
  elements['output-context'].textContent = event.finish_reason === 'length' ? 'Output limit reached · review this partial rewrite' : 'Your rewrite';
  elements['output-parameters'].textContent = `α ${signed(snapshot.alpha)} · β 0`;
  elements['change-note'].textContent = event.finish_reason === 'length'
    ? 'This result reached the 64-token limit. Shorten your draft for a complete rewrite.'
    : unchanged ? 'Same wording at this setting. Identical results are possible.'
      : 'Highlighted words changed from the previous result, or from your draft on the first run.';
  elements.latency.textContent = fromCache ? `Cached · originally ${(event.latency_ms / 1000).toFixed(2)}s`
    : `${(event.latency_ms / 1000).toFixed(2)}s generation`;
  elements.copy.disabled = false;
  setStatus(fromCache ? 'Restored a completed result from this tab’s memory.' : 'Up to date. Move the slider to explore another wording.');
}
async function dispatch() {
  clearSchedule();
  const snapshot = desired();
  if (!snapshot.message || composing || !ready) return;
  const revision = revisions.next();
  const key = currentKey();
  cancelActive(); clearError();
  const cached = cache.get(key);
  if (cached) { finish(cached, snapshot, true); return; }
  const controller = new AbortController();
  const run = { controller, revision };
  active = run;
  let text = '', terminal = false, timedOut = false, firstText = true;
  const timeout = setTimeout(() => {
    if (active === run) { timedOut = true; cancelActive(); }
  }, 35000);
  setStatus('Requesting a rewrite…', true);
  try {
    const response = await fetch('/api/v1/steering/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ session_id: session, revision, ...snapshot, beta: 0 }),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      const detail = typeof problem.detail === 'string' ? problem.detail : 'Please check the draft length and slider value.';
      throw new Error(response.status === 429 ? 'The model is busy. Wait a moment, then retry.' : detail);
    }
    if (!response.body) throw new Error('Streaming is unavailable in this browser.');
    await consumeNDJSON(response.body.getReader(), event => {
      if (!revisions.accepts(revision) || active !== run) return;
      if (event.revision !== revision) throw new Error('The server returned a mismatched input revision.');
      if (event.event === 'queued') setStatus('Waiting for the model’s current request to finish…', true);
      if (event.event === 'started') setStatus('Rewriting your draft…', true);
      if (event.event === 'delta') {
        if (firstText) {
          elements.output.replaceChildren(); elements.output.classList.remove('placeholder');
          elements['output-context'].textContent = 'Rewriting · partial text';
          elements['output-parameters'].textContent = `α ${signed(snapshot.alpha)} · β 0`;
          elements['change-note'].textContent = 'New wording is arriving. Copy becomes available when it is complete.';
          elements.latency.textContent = ''; firstText = false;
        }
        text += event.text;
        const span = document.createElement('span'); span.className = 'stream-word'; span.textContent = event.text;
        elements.output.append(span);
      }
      if (event.event === 'completed') { terminal = true; cache.put(key, event); finish(event, snapshot); }
      if (event.event === 'error') { terminal = true; throw new Error(event.detail); }
      if (event.event === 'cancelled') { terminal = true; throw new Error('This rewrite was cancelled. Retry your latest input.'); }
    });
    if (revisions.accepts(revision) && active === run && !terminal) throw new Error('The response ended early. Please retry.');
  } catch (error) {
    if (revisions.accepts(revision) && (active === run || timedOut)) {
      if (error.name !== 'AbortError' || timedOut) {
        keepPrevious(); showError(timedOut ? 'The request timed out. Shorten the draft and retry.' : error.message);
      }
    }
  } finally {
    clearTimeout(timeout);
    if (active === run) active = null;
  }
}

async function checkReadiness() {
  clearTimeout(readinessTimer);
  try {
    const response = await fetch('/api/v1/steering/config', { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('Connection failed');
    config = await response.json(); ready = config.status === 'ready';
    elements.alpha.min = config.alpha.min; elements.alpha.max = config.alpha.max; elements.alpha.step = config.alpha.step;
    elements['model-status'].textContent = ready ? 'Qwen 0.5B · ready' : config.status === 'loading' ? 'Loading Qwen 0.5B…' : 'Model unavailable';
    elements['model-dot'].className = `status-dot ${ready ? '' : config.status === 'loading' ? 'loading' : 'offline'}`;
    elements.reconnect.hidden = ready || config.status === 'loading';
    if (ready && desired().message) { revisions.next(); await dispatch(); }
    if (!ready && config.status === 'loading') readinessTimer = setTimeout(checkReadiness, 2000);
  } catch {
    ready = false; elements['model-status'].textContent = 'Server unavailable';
    elements['model-dot'].className = 'status-dot offline'; elements.reconnect.hidden = false;
    setStatus('Start the website’s Python server, then reconnect. Your draft is kept in this tab.');
  }
}

elements.alpha.addEventListener('input', () => inputChanged('slider'));
elements.alpha.addEventListener('change', () => { if (!active || active.revision !== revisions.value) void dispatch(); });
elements.draft.addEventListener('compositionstart', () => { composing = true; clearSchedule(); });
elements.draft.addEventListener('compositionend', () => { composing = false; inputChanged(); });
elements.draft.addEventListener('input', () => { if (!composing) inputChanged(); });
elements.clear.addEventListener('click', () => { elements.draft.value = ''; inputChanged(); elements.draft.focus(); });
document.querySelectorAll('[data-alpha]').forEach(button => button.addEventListener('click', () => {
  elements.alpha.value = button.dataset.alpha; inputChanged('slider'); void dispatch();
}));
document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', () => {
  elements.draft.value = button.dataset.sample; inputChanged(); void dispatch();
}));
elements.retry.addEventListener('click', () => { revisions.next(); void dispatch(); });
elements.reconnect.addEventListener('click', () => { void checkReadiness(); });
elements['changes-toggle'].addEventListener('click', () => {
  highlightChanges = !highlightChanges;
  elements['changes-toggle'].setAttribute('aria-pressed', String(highlightChanges));
  elements['changes-check'].textContent = highlightChanges ? '✓' : '';
  if (completed && !elements.copy.disabled) renderText(completed.text, highlightChanges ? completed.before : null);
});
elements.copy.addEventListener('click', async () => {
  if (!completed || elements.copy.disabled) return;
  try { await navigator.clipboard.writeText(completed.text); setStatus('Copied your completed rewrite.'); }
  catch { setStatus('Clipboard access was unavailable. Select the text to copy it.'); }
});
window.addEventListener('pagehide', () => { clearSchedule(); clearTimeout(readinessTimer); cancelActive(); });

// Keep the live control within reach while viewing the output on a small screen.
// Undock while editing so a virtual keyboard does not compete for input space.
let dockingFrame = null;
function updateDocking() {
  dockingFrame = null;
  const bounds = $('experimental').getBoundingClientRect();
  const headerBottom = document.querySelector('.site-header').getBoundingClientRect().bottom;
  $('slider-panel').classList.toggle('is-docked',
    matchMedia('(max-width: 650px)').matches && document.activeElement !== elements.draft
    && bounds.top <= headerBottom + 40 && bounds.bottom > window.innerHeight * 0.6);
}
function scheduleDocking() {
  if (dockingFrame === null) dockingFrame = requestAnimationFrame(updateDocking);
}
window.addEventListener('scroll', scheduleDocking, { passive: true });
window.addEventListener('resize', scheduleDocking);
elements.draft.addEventListener('focus', scheduleDocking);
elements.draft.addEventListener('blur', scheduleDocking);
scheduleDocking();
refreshControls(); void checkReadiness();
