// In-page nudge. When triggers.js spots heated or overly casual wording in the
// text box you're typing in, a small "SecondThought?" pill appears next to it.
// Your text only leaves the page, to the local SecondThought server, when you
// click the pill.
(() => {
  const CHECK_DELAY_MS = 600;
  const MAX_CHARS = 4000;
  const SITE = location.hostname;

  let enabled = true;
  let field = null; // the text box the nudge is attached to
  let reasons = [];
  let checkTimer = null;
  let ui = null; // built on first use, so most pages are never touched
  let pending = null; // the text the open card is working on
  const wavedOff = new WeakMap(); // field -> sentences the user already decided about

  chrome.storage.local.get({ disabledSites: [] }).then(({ disabledSites }) => {
    enabled = !disabledSites.includes(SITE);
  });
  chrome.storage.onChanged.addListener((changes) => {
    if (!changes.disabledSites) return;
    enabled = !(changes.disabledSites.newValue || []).includes(SITE);
    if (!enabled) closeAll();
  });

  // --- Finding the text box ---------------------------------------------

  function editableRoot(node) {
    if (!(node instanceof Element)) return null;
    if (node instanceof HTMLTextAreaElement) return node.readOnly || node.disabled ? null : node;
    if (node instanceof HTMLInputElement) return node.type === "text" && !node.readOnly ? node : null;
    if (!node.isContentEditable) return null;
    let root = node;
    while (root.parentElement && root.parentElement.isContentEditable) root = root.parentElement;
    return root;
  }

  const isPlainField = (el) => el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement;
  const fieldText = (el) => (isPlainField(el) ? el.value : el.innerText);
  const cardOpen = () => ui && !ui.card.hidden;

  // Signatures and quoted replies aren't the user's message, so they're neither
  // checked nor rewritten.
  const NOT_THEIR_TEXT = ".gmail_signature, .gmail_quote, blockquote, #Signature, #divRplyFwdMsg, [data-smartmail]";
  const BLOCK_TAGS = new Set(["DIV", "P", "LI", "UL", "OL", "SECTION", "ARTICLE", "PRE", "TABLE", "TR", "H1", "H2", "H3", "H4", "H5", "H6"]);
  const isSignatureMark = (text) => /^--\s*$/.test(text);

  function plainLines(el) {
    const lines = [];
    let offset = 0;
    for (const text of el.value.split("\n")) {
      if (isSignatureMark(text)) break;
      lines.push({ text, start: offset, end: offset + text.length });
      offset += text.length + 1;
    }
    return lines;
  }

  function richLines(el) {
    const lines = [];
    let current = null;
    const flush = () => {
      if (current) lines.push(current);
      current = null;
    };
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        current ??= { text: "", first: node };
        current.text += node.nodeValue;
        current.last = node;
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.matches(NOT_THEIR_TEXT)) return flush();
        if (node.tagName === "BR") {
          if (current) flush();
          else lines.push({ text: "" });
          return;
        }
        const block = BLOCK_TAGS.has(node.tagName);
        if (block) flush();
        node.childNodes.forEach(walk);
        if (block) flush();
      }
    };
    el.childNodes.forEach(walk);
    flush();
    const mark = lines.findIndex((line) => isSignatureMark(line.text));
    return mark === -1 ? lines : lines.slice(0, mark);
  }

  function ownLines(el) {
    const lines = isPlainField(el) ? plainLines(el) : richLines(el);
    return lines.filter((line) => !line.text.trimStart().startsWith(">"));
  }

  const ownText = (el) => ownLines(el).map((line) => line.text).join("\n");

  const flaggedSentences = (text) =>
    text
      .split(/\n|(?<=[.!?])\s+/)
      .map((sentence) => sentence.trim())
      .filter((sentence) => sentence && SecondThoughtTriggers.check(sentence).length);

  // Still typing the same sentence stays quiet; a new sentence or a new trigger
  // word in this one doesn't.
  const isNewSentence = (sentence, seen) =>
    !seen.some((old) => sentence.startsWith(old) && !SecondThoughtTriggers.check(sentence.slice(old.length)).length);

  function waveOff() {
    wavedOff.set(field, [...(wavedOff.get(field) || []), ...flaggedSentences(ownText(field))]);
  }

  document.addEventListener(
    "input",
    (event) => {
      if (!enabled) return;
      const el = editableRoot(event.target);
      if (!el) return;
      clearTimeout(checkTimer);
      checkTimer = setTimeout(() => runCheck(el), CHECK_DELAY_MS);
    },
    true,
  );

  // Moving to another text box retires the old pill at once, so it can never
  // act on the wrong box's text.
  document.addEventListener(
    "focusin",
    (event) => {
      const el = editableRoot(event.target);
      if (!el || cardOpen()) return;
      if (el !== field) hidePill();
      // Coming back to a box brings its pill back too.
      if (enabled) {
        clearTimeout(checkTimer);
        checkTimer = setTimeout(() => runCheck(el), CHECK_DELAY_MS);
      }
    },
    true,
  );

  document.addEventListener(
    "focusout",
    () => {
      // Our buttons keep focus in the text box, so a real blur means the user moved on.
      setTimeout(() => {
        if (!cardOpen() && field && document.activeElement !== field && !field.contains(document.activeElement)) {
          hidePill();
        }
      }, 150);
    },
    true,
  );

  function runCheck(el) {
    if (cardOpen() && el === field) return; // don't disturb an open suggestion
    const text = ownText(el);
    if (!text.trim() || text.length > MAX_CHARS) {
      if (el === field) hidePill();
      return;
    }
    const found = SecondThoughtTriggers.check(text);
    const seen = wavedOff.get(el) || [];
    const fresh = flaggedSentences(text).filter((sentence) => isNewSentence(sentence, seen));
    if (!found.length || (seen.length && !fresh.length)) {
      if (el === field) hidePill();
      return;
    }
    field = el;
    reasons = seen.length ? SecondThoughtTriggers.check(fresh.join(" ")) : found;
    showPill();
  }

  // --- UI ------------------------------------------------------------------

  const STYLES = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .pill, .card { --bg: #ffffff; --text: #1c2330; --muted: #5f6b7a; --border: #d9dde3; --surface: #f6f7f9;
      --accent: #3b5bdb; --accent-hover: #2f4ac0; --del: #c92a2a; --del-bg: #fff0f0; --ins: #2b8a3e; --ins-bg: #ebfbee; }
    @media (prefers-color-scheme: dark) {
      .pill, .card { --bg: #1f2227; --text: #e6e8eb; --muted: #9aa3ae; --border: #3a3f47; --surface: #272b31;
        --accent: #6b86f0; --accent-hover: #859bf3; --del: #ff8787; --del-bg: #3a1f22; --ins: #69db7c; --ins-bg: #1d3324; }
    }
    [hidden] { display: none !important; }
    .pill { position: fixed; display: flex; align-items: center; gap: 6px; padding: 5px 11px;
      border: 1px solid var(--border); border-radius: 999px; background: var(--bg); color: var(--text);
      font-size: 12px; font-weight: 600; cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,.15);
      animation: pop .15s ease-out; }
    .pill:hover { border-color: var(--accent); color: var(--accent); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
    .card { position: fixed; width: min(380px, calc(100vw - 16px)); padding: 12px 14px 10px;
      border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text);
      font-size: 13px; line-height: 1.45; box-shadow: 0 8px 28px rgba(0,0,0,.22); animation: pop .15s ease-out; }
    @keyframes pop { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
    .head strong { font-size: 13px; }
    .close { border: none; background: none; color: var(--muted); font-size: 18px; line-height: 1; cursor: pointer; padding: 0 2px; }
    .reasons { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
    .chip { padding: 1px 7px; border-radius: 999px; background: var(--surface); color: var(--muted); font-size: 11px; }
    .chip b { color: var(--text); font-weight: 600; }
    .body { padding: 8px 10px; border-radius: 6px; background: var(--surface); white-space: pre-wrap; word-wrap: break-word; max-height: 220px; overflow: auto; }
    .body.muted { color: var(--muted); }
    del { color: var(--del); background: var(--del-bg); text-decoration: line-through; border-radius: 3px; padding: 0 2px; }
    ins { color: var(--ins); background: var(--ins-bg); text-decoration: none; border-radius: 3px; padding: 0 2px; }
    .actions { display: flex; gap: 6px; margin-top: 10px; }
    .actions button { padding: 5px 12px; border: 1px solid var(--border); border-radius: 6px; background: transparent;
      color: var(--text); font-size: 12px; cursor: pointer; }
    .actions button:hover { background: var(--surface); }
    .actions .primary { border-color: var(--accent); background: var(--accent); color: #fff; font-weight: 600; }
    .actions .primary:hover { background: var(--accent-hover); }
    .actions button:disabled { opacity: .5; cursor: default; }
    .mute { margin-top: 8px; border: none; background: none; color: var(--muted); font-size: 11px; cursor: pointer; padding: 0; text-decoration: underline; }
  `;

  function buildUi() {
    const host = document.createElement("secondthought-nudge");
    host.style.cssText = "all: initial; position: fixed; top: 0; left: 0; z-index: 2147483647;";
    const shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>${STYLES}</style>
      <button class="pill" type="button" hidden><span class="dot"></span>SecondThought?</button>
      <div class="card" role="dialog" aria-label="SecondThought suggestion" hidden>
        <div class="head"><strong>SecondThought</strong><button class="close" type="button" aria-label="Close">×</button></div>
        <div class="reasons"></div>
        <div class="body"></div>
        <div class="actions"></div>
        <button class="mute" type="button"></button>
      </div>`;
    document.documentElement.appendChild(host);
    const $ = (selector) => shadow.querySelector(selector);
    ui = { host, pill: $(".pill"), card: $(".card"), reasons: $(".reasons"), body: $(".body"), actions: $(".actions"), mute: $(".mute") };
    ui.mute.textContent = `Don't suggest on ${SITE}`;

    // Keep focus and the selection in the text box while our buttons are used.
    shadow.addEventListener("mousedown", (event) => {
      if (event.target.closest("button")) event.preventDefault();
    });
    ui.pill.addEventListener("click", openCard);
    $(".close").addEventListener("click", dismiss);
    ui.mute.addEventListener("click", muteSite);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape" && cardOpen()) {
          event.stopPropagation();
          dismiss();
        }
      },
      true,
    );
  }

  function place() {
    if (!ui || ui.pill.hidden && ui.card.hidden) return;
    if (!field || !field.isConnected) return closeAll();
    const rect = field.getBoundingClientRect();
    const bottom = Math.min(rect.bottom, innerHeight) - 8;
    const right = Math.min(rect.right, innerWidth) - 8;
    const visible = rect.width > 0 && rect.bottom > 0 && rect.top < innerHeight;

    if (!ui.pill.hidden) {
      ui.pill.style.visibility = visible ? "visible" : "hidden";
      ui.pill.style.left = `${Math.max(8, right - ui.pill.offsetWidth)}px`;
      ui.pill.style.top = `${Math.max(8, bottom - ui.pill.offsetHeight)}px`;
    }
    if (!ui.card.hidden) {
      const width = ui.card.offsetWidth;
      const height = ui.card.offsetHeight;
      const above = bottom - height;
      ui.card.style.left = `${Math.min(Math.max(8, right - width), innerWidth - width - 8)}px`;
      ui.card.style.top = `${above >= 8 ? above : Math.min(rect.bottom + 8, innerHeight - height - 8)}px`;
    }
  }

  function showPill() {
    if (!ui) buildUi();
    ui.card.hidden = true;
    ui.pill.hidden = false;
    ui.pill.title = `Spotted: ${reasons.map((r) => r.word).join(", ")}`;
    place();
  }

  function hidePill() {
    if (ui) ui.pill.hidden = true;
  }

  function closeAll() {
    if (!ui) return;
    ui.pill.hidden = true;
    ui.card.hidden = true;
    pending = null;
  }

  function dismiss() {
    if (field) waveOff();
    closeAll();
  }

  async function muteSite() {
    const { disabledSites } = await chrome.storage.local.get({ disabledSites: [] });
    if (!disabledSites.includes(SITE)) disabledSites.push(SITE);
    await chrome.storage.local.set({ disabledSites });
    closeAll();
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Words and punctuation are compared separately, so adding a full stop doesn't
  // make "lazy" look like it was replaced by "lazy.".
  function diffTokens(text) {
    return [...text.matchAll(/(\s*)([\w'\u2019-]+|\S)/g)].map(([, space, token]) => ({ token, space: space ? " " : "" }));
  }

  // Word-level diff: struck-out words were removed, highlighted ones added.
  function diffHtml(before, after) {
    const a = diffTokens(before);
    const b = diffTokens(after);
    const lcs = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i--) {
      for (let j = b.length - 1; j >= 0; j--) {
        lcs[i][j] = a[i].token === b[j].token ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
    const kept = ({ token, space }) => space + escapeHtml(token);
    const removed = ({ token, space }) => `${space}<del>${escapeHtml(token)}</del>`;
    const added = ({ token, space }) => `${space}<ins>${escapeHtml(token)}</ins>`;
    const out = [];
    let i = 0;
    let j = 0;
    while (i < a.length && j < b.length) {
      if (a[i].token === b[j].token) {
        out.push(kept(b[j]));
        i++;
        j++;
      } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
        out.push(removed(a[i++]));
      } else {
        out.push(added(b[j++]));
      }
    }
    while (i < a.length) out.push(removed(a[i++]));
    while (j < b.length) out.push(added(b[j++]));
    return out.join("").trim();
  }

  function setActions(buttons) {
    ui.actions.replaceChildren(
      ...buttons.map(({ label, onClick, primary = false }) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        if (primary) button.className = "primary";
        button.addEventListener("click", onClick);
        return button;
      }),
    );
  }

  function setBody(content, { html = false, muted = false } = {}) {
    if (html) ui.body.innerHTML = content;
    else ui.body.textContent = content;
    ui.body.classList.toggle("muted", muted);
  }

  // --- Rewriting -------------------------------------------------------------

  // What to rewrite: the selection if there is one, otherwise only the lines that
  // set off a trigger. Every other line, its formatting included, stays as it is.
  function captureTarget() {
    if (isPlainField(field)) {
      const { selectionStart: start, selectionEnd: end, value } = field;
      if (start !== end) return { pieces: [{ text: value.slice(start, end), start, end }] };
    } else {
      const selection = getSelection();
      if (selection.rangeCount && !selection.isCollapsed) {
        const range = selection.getRangeAt(0);
        if (field.contains(range.commonAncestorContainer)) {
          return { pieces: [{ text: selection.toString(), range: range.cloneRange() }] };
        }
      }
    }
    const lines = ownLines(field);
    const written = lines.filter((line) => line.text.trim());
    const flagged = written.filter((line) => SecondThoughtTriggers.check(line.text).length);
    const pieces = flagged.length ? flagged : written;
    if (!isPlainField(field)) {
      for (const piece of pieces) {
        piece.range = document.createRange();
        piece.range.setStart(piece.first, 0);
        piece.range.setEnd(piece.last, piece.last.length);
      }
    }
    return { pieces, lines };
  }

  async function requestRewrite(message) {
    try {
      return await chrome.runtime.sendMessage({ type: "secondthought:rewrite", message });
    } catch {
      return { ok: false, error: "SecondThought was updated. Reload this page to keep using it." };
    }
  }

  async function openCard() {
    const target = captureTarget();
    if (!target.pieces.length) return;
    pending = target;
    ui.pill.hidden = true;
    ui.card.hidden = false;
    ui.reasons.innerHTML = reasons
      .slice(0, 4)
      .map((r) => `<span class="chip"><b>${escapeHtml(r.word)}</b> · ${r.label}</span>`)
      .join("");
    setBody("Rethinking…", { muted: true });
    setActions([{ label: "Cancel", onClick: dismiss }]);
    place();

    let failure = null;
    for (const piece of target.pieces) {
      const reply = await requestRewrite(piece.text.trim());
      if (pending !== target) return; // closed while waiting
      if (!reply?.ok) {
        failure = reply?.error || "Something went wrong.";
        break;
      }
      piece.rewrite = reply.result.rewritten_text;
    }

    const changed = target.pieces.filter((piece) => piece.rewrite && piece.rewrite.trim() !== piece.text.trim());
    if (failure) {
      setBody(failure, { muted: true });
      setActions([
        { label: "Try again", onClick: openCard, primary: true },
        { label: "Dismiss", onClick: dismiss },
      ]);
    } else if (!changed.length) {
      setBody("This already reads fine. No changes suggested.", { muted: true });
      setActions([{ label: "Close", onClick: dismiss }]);
    } else {
      setBody(changed.map((piece) => diffHtml(piece.text, piece.rewrite)).join("\n"), { html: true });
      setActions([
        { label: "Replace", onClick: () => replace(target, changed), primary: true },
        { label: "Copy", onClick: () => copy(copyText(target)) },
        { label: "Dismiss", onClick: dismiss },
      ]);
    }
    place();
  }

  function copyText(target) {
    const all = target.lines || target.pieces;
    return all.map((line) => line.rewrite ?? line.text).join("\n").trim();
  }

  const isStale = (piece) =>
    isPlainField(field)
      ? field.value.slice(piece.start, piece.end) !== piece.text
      : piece.range.toString() !== piece.text;

  function selectPiece(piece) {
    if (isPlainField(field)) {
      field.setSelectionRange(piece.start, piece.end);
      return;
    }
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(piece.range);
  }

  function replace(target, changed) {
    field.focus();
    if (changed.some(isStale)) {
      setBody("Your text changed while this card was open. Try again to get a fresh suggestion.", { muted: true });
      setActions([
        { label: "Try again", onClick: openCard, primary: true },
        { label: "Dismiss", onClick: dismiss },
      ]);
      return place();
    }
    target.before = fieldText(field);
    // Last line first, so earlier positions in a plain text box stay valid.
    for (const piece of [...changed].reverse()) {
      selectPiece(piece);
      // insertText goes through the browser's editing pipeline, so the site's own
      // editor (Gmail, Slack) sees a normal edit and Ctrl+Z still works.
      if (!document.execCommand("insertText", false, piece.rewrite)) {
        if (isPlainField(field)) {
          field.setRangeText(piece.rewrite, piece.start, piece.end, "end");
        } else {
          const range = getSelection().getRangeAt(0);
          range.deleteContents();
          range.insertNode(document.createTextNode(piece.rewrite));
        }
        field.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
    // Don't nag about whatever the rewrite still contains.
    waveOff();
    setBody("Replaced. Press Undo to bring your original back.", { muted: true });
    setActions([
      { label: "Undo", onClick: () => undo(target, changed.length), primary: true },
      { label: "Close", onClick: closeAll },
    ]);
    place();
  }

  // Each replaced line is its own step in the browser's undo history.
  function undo(target, steps) {
    field.focus();
    for (let step = 0; step < steps && fieldText(field) !== target.before; step++) {
      document.execCommand("undo");
    }
    closeAll();
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      setBody("Copied. Paste it wherever you like.", { muted: true });
      setActions([{ label: "Close", onClick: closeAll }]);
    } catch {
      setBody("Couldn't copy on this page. Use Replace instead.", { muted: true });
    }
    place();
  }
})();
