// UI-only preview selections never enter the inference payload.
export class LayerSelection {
  constructor(available = [0, 4, 11, 21, 22]) {
    this.available = new Set(available);
    this.focused = 11;
    this.selected = new Set([11]);
    this.values = Array(24).fill(0.5);
  }
  strengths() {
    return Object.fromEntries(
      [...this.selected]
        .sort((a, b) => a - b)
        .filter((i) => this.available.has(i))
        .map((i) => [i, this.values[i]]),
    );
  }
  reset() {
    this.focused = 11;
    this.selected = new Set([11]);
    this.values.fill(0.5);
  }
}
export function mountLayers(onChange) {
  const state = new LayerSelection(
    [...document.querySelectorAll(".layer.available")].map((b) =>
      Number(b.dataset.layer),
    ),
  );
  const $ = (id) => document.getElementById(id);
  const buttons = [...document.querySelectorAll("[data-layer]")];
  const signed = (n) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
  function render() {
    buttons.forEach((b, i) => {
      b.classList.toggle("selected", state.selected.has(i));
      b.classList.toggle("focused", i === state.focused);
      b.setAttribute("aria-pressed", String(state.selected.has(i)));
    });
    const i = state.focused,
      available = state.available.has(i);
    $("layer-name").textContent = `Layer ${String(i).padStart(2, "0")}`;
    $("layer-kind").textContent = available
      ? `${buttons[i].dataset.concept} vector`
      : "Preview only · no vector";
    $("alpha").value = state.values[i];
    $("alpha-value").value = signed(state.values[i]);
    $("alpha").setAttribute(
      "aria-label",
      `Layer ${i} strength${available ? "" : " (preview only)"}`,
    );
    $("alpha").setAttribute("aria-valuetext", signed(state.values[i]));
    $("layer-enabled").checked = state.selected.has(i);

  }
  function change(action) {
    const before = JSON.stringify(state.strengths());
    action();
    render();
    if (before !== JSON.stringify(state.strengths())) onChange();
  }
  buttons.forEach((b, i) => {
    b.addEventListener("click", () => {
      state.focused = i;
      render();
    });
    b.addEventListener("keydown", (e) => {
      let next;
      if (e.key === "ArrowRight") next = (i + 1) % 24;
      if (e.key === "ArrowLeft") next = (i + 23) % 24;
      if (e.key === "Home") next = 0;
      if (e.key === "End") next = 23;
      if (next !== undefined) {
        e.preventDefault();
        state.focused = next;
        render();
        buttons[next].focus();
      }
    });
  });
  $("layer-enabled").addEventListener("change", () =>
    change(() => {
      if ($("layer-enabled").checked) state.selected.add(state.focused);
      else state.selected.delete(state.focused);
    }),
  );
  $("alpha").addEventListener("input", () =>
    change(() => {
      state.values[state.focused] = Number($("alpha").value);
    }),
  );
  $("reset-layers").addEventListener("click", () =>
    change(() => state.reset()),
  );
  render();
  return state;
}
