// Feature/pooling select one vector family; layer selection controls injection.
export function resolveVectorSet(vectors, feature, pooling) {
  const choices = {};
  for (const vector of vectors.filter(v => v.selectable &&
    v.feature_id === feature && v.pooling === pooling)) {
    if (choices[vector.layer_index]) throw new Error('Ambiguous catalog vector family');
    choices[vector.layer_index] = vector;
  }
  return choices;
}
export class LayerSelection {
  constructor(available = [0, 4, 11, 21, 22], vectors = null) {
    this.vectors = vectors;
    this.available = new Set(available);
    this.focused = 11;
    this.selected = new Set([11]);
    this.mode = 'single';
    this.values = Array(24).fill(0.5);
    this.vectorChoices = {};
    if (vectors) this.useVectorSet("formality", "mean");
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
    this.mode = 'single';
    this.values.fill(0.5);
    this.vectorChoices = {};
    if (this.vectors) this.useVectorSet("formality", "mean");
  }
  useVectorSet(feature, pooling) {
    this.feature = feature;
    this.pooling = pooling;
    this.vectorChoices = resolveVectorSet(this.vectors, feature, pooling);
    this.available = new Set(Object.values(this.vectorChoices)
      .filter(v => v.available).map(v => v.layer_index));
  }
  focus(index) {
    this.focused = index;
    if (this.mode === 'single')
      this.selected = new Set(this.available.has(index) ? [index] : []);
  }
  setMode(mode) {
    if (!['single','multi'].includes(mode)) throw new Error('Unknown layer mode');
    this.mode = mode;
    if (mode === 'single') {
      const keep = this.selected.has(this.focused) ? this.focused :
        [...this.selected].sort((a,b)=>a-b).find(i=>this.available.has(i));
      this.selected = new Set(keep === undefined ? [] : [keep]);
      if (keep !== undefined) this.focused = keep;
    }
  }
  setEnabled(enabled) {
    if (!enabled) this.selected.delete(this.focused);
    else if (this.available.has(this.focused)) {
      if (this.mode === 'single') this.selected.clear();
      this.selected.add(this.focused);
    }
  }
  vectorIds() {
    return Object.fromEntries(Object.keys(this.strengths())
      .filter(i => this.vectorChoices[i]).map(i => [i, this.vectorChoices[i].id]));
  }
}
