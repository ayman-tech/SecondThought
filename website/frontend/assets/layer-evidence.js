// Absolute, fixed-scale held-out evidence. Presentation never changes inference.
export function evidenceColour(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) return null;
  const strength = Math.max(0, Math.min(1, (value - 0.5) / 0.5));
  const stops = [[183, 154, 117], [79, 158, 154], [8, 102, 95]];
  const part = strength <= 0.5 ? 0 : 1;
  const t = part === 0 ? strength * 2 : (strength - 0.5) * 2;
  const rgb = stops[part].map((a, i) => Math.round(a + (stops[part + 1][i] - a) * t));
  return { border: `rgb(${rgb.join(", ")})`, fill: `rgba(${rgb.join(", ")}, ${(0.23 + strength * 0.35).toFixed(3)})` };
}

export function mountLayerEvidence(initialChoices = {}) {
  const $ = id => document.getElementById(id);
  const profiles = JSON.parse($("layer-evidence-data").textContent);
  // Look up evidence by exact vector identity, never by a layer number alone.
  const evidenceById = new Map(profiles.flatMap(p => p.layers)
    .filter(row => row.vector_id).map(row => [row.vector_id, row]));
  const buttons = [...document.querySelectorAll("[data-layer]")];
  const percent = value => `${(value * 100).toFixed(1)}%`;
  let choices = initialChoices;

  function description(evidence) {
    if (!evidence?.measured) return evidence?.reason || "No recorded measurement for this exact vector.";
    return `${evidence.feature} / ${evidence.pooling.replace("_", " ")}: ${percent(evidence.value)} pair ordering; ` +
      `Wilson 95% interval ${percent(evidence.interval_low)}–${percent(evidence.interval_high)}; n=${evidence.pairs.toLocaleString()}.`;
  }
  function render() {
    const first = Object.values(choices)[0];
    $("layer-family-label").textContent = first
      ? `${first.feature_label} · ${first.pooling === 'mean' ? 'mean' : 'last token'}` : 'Unavailable';
    $("layer-profile-note").textContent =
      'Held-out pair ordering for the chosen vectors, not rewrite quality. Compare layers within this feature and pooling. Only selected layers enter generation.';
    for (const button of buttons) {
      const index = Number(button.dataset.layer);
      const vector = choices[index];
      const evidence = evidenceById.get(vector?.id);
      const colour = vector?.available && evidence?.measured ? evidenceColour(evidence.value) : null;
      button.dataset.evidenceVectorId = vector?.id || '';
      button.dataset.evidenceValue = colour ? String(evidence.value) : '';
      button.dataset.evidenceState = colour ? "measured" : "missing";
      button.style.setProperty("--evidence-fill", colour?.fill || "rgba(152, 158, 175, 0.12)");
      button.style.setProperty("--evidence-border", colour?.border || "#bac0cc");
      button.querySelector(".layer-score").textContent = colour ? (evidence.value * 100).toFixed(1) : "—";
      const note = !vector?.available ? 'Vector unavailable; no steering is applied at this layer.' : description(evidence);
      const applied = button.dataset.appliedFeatures || 'none';
      button.title = `${vector?.id || 'No vector'}\n${note}\nApplied here: ${applied}\nCohort: ${evidence?.cohort_id || "unmeasured"}.\nFeature separation is not rewrite effectiveness.`;
      button.setAttribute("aria-label", `Layer ${index}: ${vector?.feature_label || 'unavailable'}. Applied here: ${applied}. Colour evidence: ${note}`);
      if (button.classList.contains('focused'))
        $("layer-evidence-summary").textContent = `Vector evidence: ${note}`;
    }
  }
  document.addEventListener('layer-settings-changed', event => {
    choices = event.detail;
    render();
  });
  render();
}
