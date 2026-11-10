// Small, browser-independent pieces of the request and output lifecycle.
export class Revisions {
  constructor() { this.value = 0; }
  next() { return ++this.value; }
  accepts(revision) { return revision === this.value; }
}

export function cacheKey(text, alpha, version) {
  return JSON.stringify([text.trim(), Number(alpha).toFixed(1), 0, version]);
}

export class ResultCache {
  constructor(limit = 24) { this.limit = limit; this.items = new Map(); }
  clear() { this.items.clear(); }
  get(key) {
    const value = this.items.get(key);
    if (value) { this.items.delete(key); this.items.set(key, value); }
    return value;
  }
  put(key, value) {
    if (value.finish_reason !== 'stop') return;
    this.items.delete(key); this.items.set(key, value);
    while (this.items.size > this.limit) this.items.delete(this.items.keys().next().value);
  }
}

export async function consumeNDJSON(reader, onEvent) {
  const decoder = new TextDecoder();
  let buffer = '';
  function consumeLines() {
    let boundary;
    while ((boundary = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > 100_000) throw new Error('The server response was too large.');
      consumeLines();
    }
    buffer += decoder.decode();
    consumeLines();
    if (buffer.trim()) onEvent(JSON.parse(buffer));
  } finally { reader.releaseLock(); }
}

// LCS preserves unchanged words; only real output text is ever returned.
export function wordChanges(before, after) {
  const oldWords = before.match(/\S+/gu) || [];
  const newWords = after.match(/\S+/gu) || [];
  const table = Array.from({ length: oldWords.length + 1 }, () => new Uint16Array(newWords.length + 1));
  for (let i = oldWords.length - 1; i >= 0; i--) {
    for (let j = newWords.length - 1; j >= 0; j--) {
      table[i][j] = oldWords[i] === newWords[j] ? 1 + table[i + 1][j + 1]
        : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const kept = new Set();
  let i = 0, j = 0;
  while (i < oldWords.length && j < newWords.length) {
    if (oldWords[i] === newWords[j]) { kept.add(j); i++; j++; }
    else if (table[i + 1][j] >= table[i][j + 1]) i++;
    else j++;
  }
  let word = 0;
  return (after.match(/\s+|\S+/gu) || []).map(text => ({
    text, added: /^\s+$/u.test(text) ? false : !kept.has(word++),
  }));
}
