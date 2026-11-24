// Layer identity and selection details; held-out scores never determine tile appearance.
export function mountLayerEvidence(initialChoices = {}) {
  const $ = id => document.getElementById(id);
  const buttons = [...document.querySelectorAll('[data-layer]')];
  let choices = initialChoices;
  function render() {
    const first = Object.values(choices)[0];
    $('layer-family-label').textContent = first
      ? `${first.feature_label} · ${first.pooling === 'mean' ? 'mean' : 'last token'}` : 'Unavailable';
    $('layer-profile-note').textContent = 'Neutral tiles are unselected. Coloured tiles show selected features; stripes indicate shared layers.';
    for (const button of buttons) {
      const index = Number(button.dataset.layer), vector = choices[index];
      button.dataset.vectorId = vector?.id || '';
      const selected = button.dataset.appliedFeatures || 'none';
      const note = vector?.available ? `Click to toggle ${vector.feature_label} at this layer.` : 'Vector unavailable.';
      button.title = `Layer ${index}\nSelected here: ${selected}\n${note}\n${vector?.id || ''}`;
      button.setAttribute('aria-label', `Layer ${index}. Selected here: ${selected}. ${note}`);
      if (button.classList.contains('focused')) $('layer-evidence-summary').textContent = `Selected here: ${selected}`;
    }
  }
  document.addEventListener('layer-settings-changed', event => { choices = event.detail; render(); });
  render();
}
