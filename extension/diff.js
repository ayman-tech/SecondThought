// Word-level diff shared by the popup and the in-page card: struck-out words
// were removed, highlighted ones added.
const SecondThoughtDiff = (() => {
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Words and punctuation are compared separately, so adding a full stop doesn't
  // make "lazy" look like it was replaced by "lazy.".
  function tokens(text) {
    return [...text.matchAll(/(\s*)([\w'’-]+|\S)/g)].map(([, space, token]) => ({ token, space: space ? " " : "" }));
  }

  function html(before, after) {
    const a = tokens(before);
    const b = tokens(after);
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
        // A word swapped at the very start has no space of its own to show.
        const gap = !b[j].space && out.length && /\w/.test(b[j].token) ? " " : "";
        out.push(gap + added(b[j++]));
      }
    }
    while (i < a.length) out.push(removed(a[i++]));
    while (j < b.length) out.push(added(b[j++]));
    return out.join("").trim();
  }

  return { html };
})();
