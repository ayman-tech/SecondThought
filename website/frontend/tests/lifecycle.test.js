import test from 'node:test';
import assert from 'node:assert/strict';
import { Revisions, ResultCache, cacheKey, consumeNDJSON, wordChanges } from '../assets/lifecycle.js';

test('only the latest revision may change the visible output, including after clear', () => {
  const revisions = new Revisions();
  const first = revisions.next(); const second = revisions.next();
  assert.equal(revisions.accepts(first), false);
  assert.equal(revisions.accepts(second), true);
  revisions.next(); // Clear draft, even without sending a new request.
  assert.equal(revisions.accepts(second), false);
});

test('cache keys distinguish settings, model versions, and meaningful source whitespace', () => {
  assert.equal(cacheKey(' x ', 0.5, 'v1'), cacheKey('x', 0.5, 'v1'));
  assert.notEqual(cacheKey('x', 0.5, 'v1'), cacheKey('x', 0.6, 'v1'));
  assert.notEqual(cacheKey('x', 0.5, 'v1'), cacheKey('x', 0.5, 'v2'));
  assert.notEqual(cacheKey('x  y', 0.5, 'v1'), cacheKey('x y', 0.5, 'v1'));
});

test('bounded LRU cache excludes partial or failed generations', () => {
  const cache = new ResultCache(2);
  const complete = { finish_reason: 'stop', rewritten_text: 'real text' };
  cache.put('a', complete); cache.put('b', complete); cache.get('a'); cache.put('c', complete);
  assert.equal(cache.get('b'), undefined); assert.ok(cache.get('a'));
  cache.put('partial', { finish_reason: 'length' });
  assert.equal(cache.get('partial'), undefined);
  cache.clear(); assert.equal(cache.get('a'), undefined);
});

test('stream parser handles fragmented JSON, multiple events, and split Unicode bytes', async () => {
  const text = '{"event":"delta","text":"café α"}\n{"event":"completed"}\n';
  const bytes = new TextEncoder().encode(text); const received = [];
  const stream = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  }});
  await consumeNDJSON(stream.getReader(), e => received.push(e));
  assert.deepEqual(received, [{ event: 'delta', text: 'café α' }, { event: 'completed' }]);
});

test('diff preserves exact output text and highlights only additions', () => {
  const output = 'Please send the report by 3 PM.';
  const changes = wordChanges('send the report by 3 PM.', output);
  assert.equal(changes.map(x => x.text).join(''), output);
  assert.deepEqual(changes.filter(x => x.added).map(x => x.text), ['Please']);
  assert.ok(wordChanges(output, output).every(x => !x.added));
  const html = '<img src=x onerror=alert(1)> 👋';
  assert.equal(wordChanges('', html).map(x => x.text).join(''), html);
});
