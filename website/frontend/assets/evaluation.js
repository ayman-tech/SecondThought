// Evaluation page: model scorecard and before/after (dumbbell) chart from eval-results.json.
(() => {
  const SVG = "http://www.w3.org/2000/svg";
  const METRICS = {
    toxicity: { better: "lower", verb: "less toxic" },
    formality: { better: "higher", verb: "more formal" },
  };
  const COLUMNS = [ // scorecard: summary key, format, which direction wins
    ["critical_value_exact_rate", (v) => `${Math.round(v * 100)}%`, "higher"],
    ["average_toxicity_rewritten", (v) => v.toFixed(3), "lower"],
    ["average_semantic_similarity", (v) => v.toFixed(3), "higher"],
    ["average_formality_rewritten", (v) => v.toFixed(2), "higher"],
  ];
  const state = { system: 0, metric: "toxicity" };
  let data;

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, text) => {
    const node = tag.startsWith("svg:") ? document.createElementNS(SVG, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function scorecard() {
    const best = COLUMNS.map(([key, , dir]) => {
      const values = data.systems.map((s) => s.summary[key]);
      return dir === "higher" ? Math.max(...values) : Math.min(...values);
    });
    const body = $("[data-eval-scorecard] tbody");
    body.replaceChildren(...data.systems.map((system) => {
      const row = el("tr");
      const name = el("th", { scope: "row" }, system.label);
      name.append(el("small", {}, system.description));
      row.append(name);
      COLUMNS.forEach(([key, format], i) => {
        const value = system.summary[key];
        const cell = el("td");
        const score = el("span", { class: "score" }, format(value));
        if (value === best[i]) score.append(el("span", { class: "score-best" }, "BEST"));
        const bar = el("span", { class: "score-bar", "aria-hidden": "true" });
        bar.style.width = `${Math.max(value * 100, 2)}%`;
        cell.append(score, bar);
        row.append(cell);
      });
      return row;
    }));
    $("[data-eval-note]").textContent = `${data.dataset}. ${data.note}`;
  }

  function controls() {
    const group = $("[data-eval-systems]");
    group.replaceChildren(...data.systems.map((system, i) => {
      const button = el("button", { type: "button", "aria-pressed": String(i === state.system) }, system.label);
      button.addEventListener("click", () => { state.system = i; update(); });
      return button;
    }));
    document.querySelectorAll("[data-metric]").forEach((button) =>
      button.addEventListener("click", () => { state.metric = button.dataset.metric; update(); }));
  }

  function rows() {
    const sign = METRICS[state.metric].better === "lower" ? 1 : -1;
    return [...data.systems[state.system].messages]
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
    document.querySelectorAll("[data-eval-systems] button").forEach((b, i) => b.setAttribute("aria-pressed", String(i === state.system)));
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
    scorecard();
    controls();
    update();
    let pending, lastWidth = $("[data-eval-chart]").clientWidth;
    new ResizeObserver(([entry]) => { // redraw on width change only; height changes come from our own redraw
      const width = Math.round(entry.contentRect.width);
      if (width === lastWidth) return;
      lastWidth = width;
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => chart(rows()));
    }).observe($("[data-eval-chart]"));
  }

  document.addEventListener("DOMContentLoaded", init);
})();
