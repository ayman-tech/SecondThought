import test from 'node:test';
import assert from 'node:assert/strict';
import { LayerSelection, resolveVectorSet } from '../assets/layers.js';

test('single layer replaces selection; multi-layer accumulation is explicit and reversible', () => {
  const state = new LayerSelection([3,4,11]);
  assert.equal(state.mode,'single');
  state.focus(3); state.focus(4);
  assert.deepEqual(state.strengths(),{4:.5});
  state.setMode('multi'); state.focus(3);
  assert.deepEqual(state.strengths(),{4:.5},'Inspecting does not enable a layer in multi mode');
  state.setEnabled(true); state.values[3] = .9;
  assert.deepEqual(state.strengths(),{3:.9,4:.5});
  state.setMode('single');
  assert.deepEqual(state.strengths(),{3:.9},'Keep focused enabled layer when leaving multi mode');
  state.setMode('multi'); state.focus(4); state.setEnabled(true);
  state.focus(11); state.setMode('single');
  assert.equal(state.focused,3);
  assert.deepEqual(state.strengths(),{3:.9},'Otherwise keep the first enabled layer');
  state.setEnabled(false); assert.deepEqual(state.strengths(),{});
  state.setMode('multi'); state.setMode('single');
  assert.deepEqual(state.strengths(),{},'Mode changes preserve prompt-only baseline');
  state.focus(23); assert.deepEqual(state.strengths(),{},'Unavailable layers never steer');
  state.reset(); assert.equal(state.mode,'single');
  assert.deepEqual(state.strengths(),{11:.5});
});

test('feature × pooling resolves one exact vector per layer and preserves strengths', () => {
  const vectors = ['formality','detoxification'].flatMap(feature_id =>
    ['mean','final_token'].flatMap(pooling => Array.from({length:24},(_,layer_index)=>({
      id:`${feature_id}-${pooling}-${layer_index}`, feature_id, pooling, layer_index,
      selectable:true, available:true,
    }))));
  // A legacy vector with identical layer/feature/pooling must never win lookup.
  vectors.unshift({...vectors[0], id:'legacy', selectable:false});
  const state = new LayerSelection([],vectors);
  state.selected.add(4); state.selected.add(21); state.values[4] = -.7;
  for (const feature of ['formality','detoxification']) {
    for (const pooling of ['mean','final_token']) {
      state.useVectorSet(feature,pooling);
      assert.equal(Object.keys(state.vectorChoices).length,24);
      assert.deepEqual(state.strengths(),{4:-.7,11:.5,21:.5});
      for (let i=0;i<24;i++)
        assert.equal(state.vectorChoices[i].id,`${feature}-${pooling}-${i}`);
      for (const [i,id] of Object.entries(state.vectorIds()))
        assert.equal(id,state.vectorChoices[i].id);
    }
  }
  state.reset();
  assert.equal(state.feature,'formality'); assert.equal(state.pooling,'mean');
  assert.deepEqual(state.vectorIds(),{11:'formality-mean-11'});
  assert.throws(()=>resolveVectorSet([...vectors,vectors[1]],'formality','mean'),/Ambiguous/);
  vectors.find(v=>v.id==='detoxification-mean-11').available = false;
  state.useVectorSet('detoxification','mean');
  assert.deepEqual(state.strengths(),{});
  assert.deepEqual(state.vectorIds(),{});
});

test('available layers are supplied by the model; previews never enter strengths', () => {
  const state = new LayerSelection([4,11]);
  state.selected.add(3);
  state.selected.add(4);
  state.values[3] = 2;
  assert.deepEqual(state.strengths(), {4:0.5,11:0.5});
  const full = new LayerSelection(Array.from({length:24},(_,i)=>i));
  full.selected.add(23);
  assert.deepEqual(full.strengths(), {11:0.5,23:0.5});
  full.vectorChoices[23] = {id:'detox-23'};
  full.vectorChoices[3] = {id:'detox-3'};
  assert.deepEqual(full.vectorIds(), {23:'detox-23'});
  full.reset();
  assert.deepEqual(full.vectorIds(), {});
});

