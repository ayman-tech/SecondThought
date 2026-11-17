// Evaluation page: headline tiles and before/after (dumbbell) chart from eval-results.json.
(() => {
  const SVG = "http://www.w3.org/2000/svg";
  const METRICS = {
    toxicity: { better: "lower", verb: "less toxic" },
    formality: { better: "higher", verb: "more formal" },
  };
  const state = { metric: "toxicity", touch: "spread" };
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
  const status = (m) => REASONS.find(([, fails]) => fails(m))?.[0] ?? "Ready to send";
  const pct = (v, digits = 1) => `${(v * 100).toFixed(digits)}%`;
  const quantile = (sorted, q) => { // linear interpolation, like numpy's default
    const i = (sorted.length - 1) * q, lo = Math.floor(i);
    return sorted[lo] + (sorted[Math.ceil(i)] - sorted[lo]) * (i - lo);
  };

  // One hover card per figure: original, rewrite and a score line, placed above or below the mark.
  function hoverCard(figure) {
    const card = figure.querySelector(".eval-tooltip");
    const hide = () => { card.hidden = true; };
    const show = (target, m, score) => {
      card.replaceChildren(el("p", {}), el("p", {}), el("p", { class: "tip-score" }, score));
      card.children[0].append(el("span", { class: "tip-label" }, "ORIGINAL"), m.original);
      card.children[1].append(el("span", { class: "tip-label" }, "REWRITE"), m.rewritten);
      card.hidden = false;
      const box = target.getBoundingClientRect(), host = figure.getBoundingClientRect();
      const left = Math.min(Math.max(box.left - host.left + box.width / 2 - 170, 0), host.width - card.offsetWidth);
      const below = box.bottom - host.top + 6;
      card.style.left = `${left}px`;
      card.style.top = `${below + card.offsetHeight > host.height ? box.top - host.top - card.offsetHeight - 6 : below}px`;
    };
    const attach = (node, m, score) => {
      node.addEventListener("pointerenter", () => show(node, m, score));
      node.addEventListener("focus", () => show(node, m, score));
      node.addEventListener("pointerleave", hide);
      node.addEventListener("blur", hide);
    };
    return { attach, hide };
  }

  function ready() {
    const messages = data.systems[0].messages;
    const groups = new Map([["Ready to send", []], ...REASONS.map(([name]) => [name, []])]);
    for (const m of messages) groups.get(status(m)).push(m);
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

  // Light touch: how much text changed, as a swarm ("spread") or against the toxicity drop ("scatter").
  function strip() {
    const figure = $("[data-eval-strip]");
    const card = hoverCard(figure);
    const messages = [...data.systems[0].messages].sort((a, b) => a.edit_ratio - b.edit_ratio);
    const values = messages.map((m) => m.edit_ratio);
    const [q1, median, q3, p90] = [0.25, 0.5, 0.75, 0.9].map((q) => quantile(values, q));
    const drop = (m) => m.toxicity[0] - m.toxicity[1];
    const big = messages.filter((m) => drop(m) >= 0.5);
    const bigSmall = big.filter((m) => m.edit_ratio < 0.1);
    $("[data-eval-touch-kpi]").textContent = `Median ${pct(median)} of the text changed · at most ${pct(values.at(-1), 0)}`;
    $("[data-eval-touch-insight]").textContent = state.touch === "spread"
      ? `Half of all rewrites changed between ${pct(q1)} and ${pct(q3)} of the text; 9 in 10 changed ${pct(p90)} or less.`
      : `${bigSmall.length} of the ${big.length} rewrites that cut toxicity by 0.5 or more changed under 10% of the text.`;

    const scatter = state.touch === "scatter";
    const width = Math.max(figure.clientWidth - 32, 300);
    const m = scatter ? { top: 20, right: 18, bottom: 48, left: 54 } : { top: 40, right: 18, bottom: 48, left: 10 };
    const height = scatter ? 420 : 320;
    const plotW = width - m.left - m.right, plotH = height - m.top - m.bottom;
    const xMax = 0.25, x = (v) => m.left + (Math.min(v, xMax) / xMax) * plotW;
    const drops = messages.map(drop);
    const yMin = Math.min(-0.1, Math.floor(Math.min(...drops) * 4) / 4), yMax = 1;
    const y = (v) => m.top + ((yMax - v) / (yMax - yMin)) * plotH;
    const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": scatter
      ? "Scatter of share of text changed against toxicity drop, one dot per message."
      : `Swarm of share of text changed per message. Median ${pct(median)}, middle half ${pct(q1)} to ${pct(q3)}.` });

    // Grid and x axis (shared)
    const grid = el("svg:g", { class: "grid" }), axis = el("svg:g", { class: "axis" });
    for (let t = 0; t <= xMax + 1e-9; t += 0.025) {
      const major = Math.round(t * 1000) % 50 === 0;
      grid.append(el("svg:line", { class: major ? "major" : "minor", x1: x(t), x2: x(t), y1: m.top, y2: m.top + plotH }));
      if (major) axis.append(el("svg:text", { x: x(t), y: m.top + plotH + 18, "text-anchor": "middle" }, pct(t, 0)));
    }
    axis.append(el("svg:text", { class: "axis-title", x: m.left + plotW / 2, y: height - 6, "text-anchor": "middle" },
      "Share of the message's text changed (characters)"));
    svg.append(grid, axis);

    let positions;
    if (scatter) {
      for (let t = Math.ceil(yMin * 4) / 4; t <= yMax + 1e-9; t += 0.25) {
        grid.append(el("svg:line", { class: t === 0 ? "zero" : "major", x1: m.left, x2: m.left + plotW, y1: y(t), y2: y(t) }));
        axis.append(el("svg:text", { x: m.left - 8, y: y(t) + 3, "text-anchor": "end" }, t.toFixed(2)));
      }
      axis.append(el("svg:text", { class: "axis-title", x: 14, y: m.top + plotH / 2, "text-anchor": "middle",
        transform: `rotate(-90 14 ${m.top + plotH / 2})` }, "Toxicity drop (before − after)"));
      const zone = el("svg:g", { class: "zone" }); // the "light touch, big effect" corner
      zone.append(el("svg:rect", { x: x(0), y: y(yMax), width: x(0.1) - x(0), height: y(0.5) - y(yMax), rx: 6 }),
        el("svg:text", { x: x(0) + 8, y: y(0.5) + 16 }, "↑ under 10% changed, toxicity down 0.5 or more"));
      grid.after(zone);
      svg.append(el("svg:text", { class: "zero-label", x: m.left + plotW - 4, y: y(0) - 6, "text-anchor": "end" }, "no change in toxicity"));
      positions = messages.map((msg) => [x(msg.edit_ratio), y(drop(msg))]);
    } else {
      const mid = m.top + plotH / 2, r = 7, gap = 2 * r + 2, placed = [];
      positions = messages.map((msg) => { // centred swarm: nearest free slot to the midline, exact x
        const cx = x(msg.edit_ratio);
        for (let k = 0; ; k++) {
          const cy = mid + (k % 2 ? -1 : 1) * Math.ceil(k / 2) * gap * 0.9;
          if (placed.every(([px, py]) => Math.hypot(px - cx, py - cy) >= gap)) { placed.push([cx, cy]); return [cx, cy]; }
        }
      });
      const band = el("svg:g", { class: "band" });
      band.append(el("svg:rect", { x: x(q1), y: m.top, width: x(q3) - x(q1), height: plotH, rx: 6 }),
        el("svg:text", { x: (x(q1) + x(q3)) / 2, y: m.top - 8, "text-anchor": "middle" }, `middle half ${pct(q1)}–${pct(q3)}`));
      grid.after(band);
      for (const [cls, v, label] of [["median", median, `median ${pct(median)}`], ["p90", p90, `90% ≤ ${pct(p90)}`]]) {
        const g = el("svg:g", { class: cls });
        g.append(el("svg:line", { x1: x(v), x2: x(v), y1: m.top, y2: m.top + plotH }),
          el("svg:text", { x: x(v) + 6, y: m.top + plotH - 8 }, label));
        svg.append(g);
      }
    }

    messages.forEach((msg, i) => {
      const [cx, cy] = positions[i], s = status(msg);
      const dot = el("svg:circle", { class: `dot ${s === "Ready to send" ? "ready" : "not-ready"}`, cx, cy, r: 7, tabindex: "0",
        "aria-label": `${pct(msg.edit_ratio)} changed, toxicity drop ${drop(msg).toFixed(2)}, ${s}: ${msg.original}` });
      card.attach(dot, msg,
        `${pct(msg.edit_ratio)} changed · toxicity ${msg.toxicity[0].toFixed(2)} → ${msg.toxicity[1].toFixed(2)} · ${s}`);
      svg.append(dot);
    });
    figure.querySelector("svg")?.remove();
    figure.prepend(svg);
    card.hide();
  }

  function controls() {
    document.querySelectorAll("[data-metric]").forEach((button) =>
      button.addEventListener("click", () => { state.metric = button.dataset.metric; update(); }));
    document.querySelectorAll("[data-touch]").forEach((button) =>
      button.addEventListener("click", () => {
        state.touch = button.dataset.touch;
        document.querySelectorAll("[data-touch]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
        strip();
      }));
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

    const card = hoverCard(figure);

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
      card.attach(row, m, `${state.metric}: ${before.toFixed(2)} → ${after.toFixed(2)}`);
      svg.append(row);
    });
    figure.querySelector("svg")?.remove();
    figure.prepend(svg);
    card.hide();
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
