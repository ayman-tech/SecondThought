// Evaluation page: headline tiles and before/after (dumbbell) chart from eval-results.json.
(() => {
  const SVG = "http://www.w3.org/2000/svg";
  const METRICS = {
    toxicity: { better: "lower", verb: "less toxic" },
    formality: { better: "higher", verb: "more formal" },
  };
  const state = { metric: "toxicity" };
  let data;

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, text) => {
    const node = tag.startsWith("svg:") ? document.createElementNS(SVG, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function tiles() {
    const { summary: s, description } = data.systems[0];
    const kept = Math.round(s.critical_value_exact_rate * s.examples);
    const items = [
      ["Toxicity", `${s.average_toxicity_original.toFixed(2)} → ${s.average_toxicity_rewritten.toFixed(2)}`, "Average, lower is better"],
      ["Formality", `${s.average_formality_original.toFixed(2)} → ${s.average_formality_rewritten.toFixed(2)}`, "Average, higher is more formal"],
      ["Meaning kept", s.average_semantic_similarity.toFixed(3), "Average similarity, 1 is identical meaning"],
      ["Facts kept", `${kept} of ${s.examples}`, "Messages with every number, date and ID intact"],
    ];
    $("[data-eval-tiles]").replaceChildren(...items.map(([label, value, note]) => {
      const tile = el("div", { class: "eval-tile" });
      tile.append(el("dt", {}, label), el("dd", { class: "tile-value" }, value), el("dd", {}, note));
      return tile;
    }));
    $("[data-eval-note]").textContent = `${description}. ${data.note}`;
  }

  // "Ready to send": not toxic, every fact kept, same meaning, and actually changed.
  // ponytail: one fixed cut-off per check; revisit once the team agrees on thresholds.
  const READY = { toxicity: 0.5, similarity: 0.9 };
  const REASONS = [ // checked in this order; the first failing check names the group
    ["No suggestion", (m) => m.original.trim() === m.rewritten.trim()],
    ["Still toxic", (m) => m.toxicity[1] >= READY.toxicity],
    ["Fact lost or added", (m) => !m.facts_kept],
    ["Meaning drifted", (m) => m.similarity < READY.similarity],
  ];
  const tip = (m) => `${m.original}\n→ ${m.rewritten}`;

  function ready() {
    const messages = data.systems[0].messages;
    const groups = new Map([["Ready to send", []], ...REASONS.map(([name]) => [name, []])]);
    for (const m of messages) groups.get(REASONS.find(([, fails]) => fails(m))?.[0] ?? "Ready to send").push(m);
    const ok = groups.get("Ready to send").length;
    $("[data-eval-ready-kpi]").textContent =
      `${ok} of ${messages.length} rewrites ready to send (${Math.round((ok / messages.length) * 100)}%)`;
    $("[data-eval-ready-rule]").textContent =
      `Ready means toxicity below ${READY.toxicity}, every fact kept, meaning similarity ${READY.similarity.toFixed(2)} or higher, ` +
      "and the message actually changed. The other groups show the first check each rewrite failed.";
    const ordered = [...groups].sort(([a, x], [b, y]) => (a === "Ready to send" ? -1 : b === "Ready to send" ? 1 : y.length - x.length));
    $("[data-eval-units]").replaceChildren(...ordered.filter(([, list]) => list.length).map(([name, list]) => {
      const group = el("div", { class: `unit-group${name === "Ready to send" ? " is-ready" : ""}` });
      const label = el("p", { class: "unit-label" });
      label.append(el("strong", {}, String(list.length)), ` ${name}`);
      const units = el("div", { class: "units", role: "list", "aria-label": `${name}: ${list.length} messages` });
      units.append(...list.map((m) => el("span", { class: "unit", role: "listitem", title: tip(m), "aria-label": tip(m) })));
      group.append(label, units);
      return group;
    }));
  }

  function strip() {
    const figure = $("[data-eval-strip]");
    const messages = [...data.systems[0].messages].sort((a, b) => a.edit_ratio - b.edit_ratio);
    const values = messages.map((m) => m.edit_ratio);
    const median = (values[(values.length - 1) >> 1] + values[values.length >> 1]) / 2;
    $("[data-eval-touch-kpi]").textContent =
      `Median ${(median * 100).toFixed(1)}% of the text changed · at most ${Math.round(values.at(-1) * 100)}%`;
    const width = Math.max(figure.clientWidth - 32, 260), max = 0.25, r = 5, left = 4, right = 10;
    const x = (v) => left + (Math.min(v, max) / max) * (width - left - right);
    const lastX = []; // per level, the x of its right-most dot: each dot takes the lowest level it fits on
    const dots = messages.map((m) => {
      const cx = x(m.edit_ratio);
      let level = lastX.findIndex((px) => cx - px >= r * 2 + 1);
      if (level === -1) level = lastX.length;
      lastX[level] = cx;
      return { m, level };
    });
    const levels = lastX.length;
    const base = 18 + levels * (r * 2 + 2);
    const svg = el("svg:svg", { viewBox: `0 0 ${width} ${base + 26}`, role: "img",
      "aria-label": `Share of text changed per message. Median ${(median * 100).toFixed(1)} percent.` });
    const axis = el("svg:g", { class: "axis" });
    [0, 0.05, 0.1, 0.15, 0.2, 0.25].forEach((t) => {
      axis.append(el("svg:line", { class: "tick", x1: x(t), x2: x(t), y1: base + 2, y2: base + 6 }),
        el("svg:text", { x: x(t), y: base + 20, "text-anchor": t === 0 ? "start" : t === max ? "end" : "middle" }, `${Math.round(t * 100)}%`));
    });
    axis.append(el("svg:line", { class: "baseline", x1: x(0), x2: x(max), y1: base + 2, y2: base + 2 }));
    const mid = el("svg:g", { class: "median" });
    mid.append(el("svg:line", { x1: x(median), x2: x(median), y1: 4, y2: base + 2 }),
      el("svg:text", { x: x(median) + 6, y: 12 }, `median ${(median * 100).toFixed(1)}%`));
    svg.append(axis, mid);
    for (const { m, level } of dots) {
      const dot = el("svg:circle", { class: "dot", cx: x(m.edit_ratio), cy: base - r - level * (r * 2 + 2), r });
      dot.append(el("svg:title", {}, `${(m.edit_ratio * 100).toFixed(1)}% changed\n${tip(m)}`));
      svg.append(dot);
    }
    figure.replaceChildren(svg);
  }

  function controls() {
    document.querySelectorAll("[data-metric]").forEach((button) =>
      button.addEventListener("click", () => { state.metric = button.dataset.metric; update(); }));
  }

  function rows() {
    const sign = METRICS[state.metric].better === "lower" ? 1 : -1;
    return [...data.systems[0].messages]
      .sort((a, b) => sign * ((b[state.metric][0] - b[state.metric][1]) - (a[state.metric][0] - a[state.metric][1])));
  }

  function headline(messages) {
    const { better, verb } = METRICS[state.metric];
    const improved = messages.filter(({ [state.metric]: [before, after] }) => better === "lower" ? after < before : after > before);
    const mean = (i) => messages.reduce((sum, m) => sum + m[state.metric][i], 0) / messages.length;
    $("[data-eval-headline]").textContent =
      `${improved.length} of ${messages.length} rewrites ${verb} · average ${mean(0).toFixed(2)} → ${mean(1).toFixed(2)}`;
  }

  function chart(messages) {
    const figure = $("[data-eval-chart]");
    const tooltip = figure.querySelector(".eval-tooltip");
    const width = Math.max(figure.clientWidth - 32, 260);
    const rowH = 16, top = 22, left = 4, right = 10;
    const height = top + messages.length * rowH + 4;
    const x = (v) => left + v * (width - left - right);
    const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `${state.metric} before and after rewriting, one row per message. Use the table below for exact values.` });

    const grid = el("svg:g", { class: "grid" });
    const axis = el("svg:g", { class: "axis" });
    [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
      grid.append(el("svg:line", { x1: x(t), x2: x(t), y1: top - 4, y2: height }));
      axis.append(el("svg:text", { x: x(t), y: 12, "text-anchor": t === 0 ? "start" : t === 1 ? "end" : "middle" }, t.toFixed(2)));
    });
    svg.append(grid, axis);

    const show = (m, target) => {
      const [before, after] = m[state.metric];
      tooltip.replaceChildren(
        el("p", {}, ""), el("p", {}, ""), el("p", { class: "tip-score" }, `${state.metric}: ${before.toFixed(2)} → ${after.toFixed(2)}`));
      tooltip.children[0].append(el("span", { class: "tip-label" }, "ORIGINAL"), m.original);
      tooltip.children[1].append(el("span", { class: "tip-label" }, "REWRITE"), m.rewritten);
      tooltip.hidden = false;
      const box = target.getBoundingClientRect(), host = figure.getBoundingClientRect();
      const tipLeft = Math.min(Math.max(box.left - host.left + box.width / 2 - 170, 0), host.width - tooltip.offsetWidth);
      const below = box.bottom - host.top + 6;
      tooltip.style.left = `${tipLeft}px`;
      tooltip.style.top = `${below + tooltip.offsetHeight > host.height ? box.top - host.top - tooltip.offsetHeight - 6 : below}px`;
    };
    const hide = () => { tooltip.hidden = true; };

    messages.forEach((m, i) => {
      const [before, after] = m[state.metric];
      const y = top + i * rowH + rowH / 2;
      const row = el("svg:g", { class: "row", tabindex: "0",
        "aria-label": `${m.original} — ${state.metric} ${before.toFixed(2)} to ${after.toFixed(2)}` });
      row.append(
        el("svg:rect", { class: "hit", x: 0, y: y - rowH / 2, width, height: rowH, rx: 3 }),
        el("svg:line", { x1: x(before), x2: x(after), y1: y, y2: y }),
        el("svg:circle", { class: "before", cx: x(before), cy: y, r: 4.5 }),
        el("svg:circle", { class: "after", cx: x(after), cy: y, r: 5 }));
      row.addEventListener("pointerenter", () => show(m, row));
      row.addEventListener("focus", () => show(m, row));
      row.addEventListener("pointerleave", hide);
      row.addEventListener("blur", hide);
      svg.append(row);
    });
    figure.querySelector("svg")?.remove();
    figure.prepend(svg);
    hide();
  }

  function table(messages) {
    $("[data-eval-messages] tbody").replaceChildren(...messages.map((m) => {
      const row = el("tr");
      row.append(el("td", {}, m.original), el("td", {}, m.rewritten),
        el("td", {}, m[state.metric][0].toFixed(2)), el("td", {}, m[state.metric][1].toFixed(2)));
      return row;
    }));
  }

  function update() {
    document.querySelectorAll("[data-metric]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.metric === state.metric)));
    const messages = rows();
    headline(messages);
    chart(messages);
    table(messages);
  }

  async function init() {
    try {
      const response = await fetch("/assets/eval-results.json");
      if (!response.ok) throw new Error(response.status);
      data = await response.json();
    } catch {
      $("[data-eval-note]").textContent = "Evaluation results could not be loaded.";
      return;
    }
    tiles();
    ready();
    strip();
    controls();
    update();
    let pending, lastWidth = $("[data-eval-chart]").clientWidth;
    new ResizeObserver(([entry]) => { // redraw on width change only; height changes come from our own redraw
      const width = Math.round(entry.contentRect.width);
      if (width === lastWidth) return;
      lastWidth = width;
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => { chart(rows()); strip(); });
    }).observe($("[data-eval-chart]"));
  }

  document.addEventListener("DOMContentLoaded", init);
})();
