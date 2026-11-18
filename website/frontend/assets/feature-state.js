import { LayerSelection } from './layer-state.js';

// A separate layer bank per feature prevents editing one direction from
// silently moving or rescaling another direction's interventions.
export class FeatureExperiment {
  constructor(vectors) {
    this.vectors = vectors;
    this.features = [...new Map(vectors.filter(v=>v.selectable)
      .map(v=>[v.feature_id,{id:v.feature_id,label:v.feature_label}])).values()];
    this.reset();
  }
  reset() {
    this.banks = new Map(this.features.map(feature=>{
      const bank = new LayerSelection([],this.vectors);
      bank.useVectorSet(feature.id,'mean');
      return [feature.id,bank];
    }));
    this.editing = this.features.find(f=>f.id==='formality')?.id || this.features[0]?.id;
    this.enabled = new Set(this.editing ? [this.editing] : []);
  }
  get bank() { return this.banks.get(this.editing); }
  get vectorChoices() { return this.bank?.vectorChoices || {}; }
  selectFeature(id) {
    if (!this.banks.has(id)) throw new Error('Unknown feature');
    this.editing=id;
  }
  enableFeature(id,enabled) {
    if (!this.banks.has(id)) throw new Error('Unknown feature');
    if (enabled) { this.enabled.add(id); this.editing=id; }
    else {
      this.enabled.delete(id);
      if (this.editing===id && this.enabled.size) this.editing=[...this.enabled][0];
    }
  }
  interventions() {
    return [...this.enabled].flatMap(id=>{
      const bank=this.banks.get(id);
      return Object.entries(bank.strengths()).map(([index,strength])=>({
        vector_id:bank.vectorChoices[index].id,strength,
      }));
    }).sort((a,b)=>a.vector_id.localeCompare(b.vector_id));
  }
  entries() {
    return [...this.enabled].flatMap(id=>{
      const bank=this.banks.get(id);
      return Object.entries(bank.strengths()).map(([index,strength])=>({
        feature:id,label:this.features.find(f=>f.id===id).label,layer:Number(index),strength,
        vector_id:bank.vectorChoices[index].id,
      }));
    });
  }
  clear() { for (const bank of this.banks.values()) bank.selected.clear(); }
}
