import test from 'node:test';
import assert from 'node:assert/strict';
import { FeatureExperiment } from '../assets/feature-state.js';
import { experimentCacheKey } from '../assets/lifecycle.js';

const vectors=['formality','detoxification','empathy'].flatMap(feature_id=>
  ['mean','final_token'].flatMap(pooling=>Array.from({length:24},(_,layer_index)=>({
    id:`${feature_id}-${layer_index}-${pooling}`,feature_id,feature_label:feature_id,pooling,layer_index,
    available:true,selectable:true,
  }))));

test('features retain independent layers, mode, pooling, and strengths',()=>{
  const state=new FeatureExperiment(vectors);
  state.bank.focus(7);state.bank.values[7]=.4;
  state.enableFeature('detoxification',true);
  state.bank.focus(4);state.bank.values[4]=.8;
  state.bank.useVectorSet('detoxification','final_token');
  assert.deepEqual(state.interventions(),[
    {vector_id:'detoxification-4-final_token',strength:.8},
    {vector_id:'formality-7-mean',strength:.4},
  ]);
  state.bank.setMode('multi');state.bank.focus(11);state.bank.setEnabled(true);state.bank.values[11]=-.3;
  state.selectFeature('formality');
  assert.equal(state.bank.mode,'single');assert.equal(state.bank.focused,7);
  state.bank.focus(21);
  assert.equal(state.interventions().length,3);
  assert.ok(state.interventions().some(i=>i.vector_id==='detoxification-4-final_token'));
  state.enableFeature('detoxification',false);
  assert.deepEqual(state.interventions(),[{vector_id:'formality-21-mean',strength:.5}]);
  state.enableFeature('detoxification',true);
  assert.equal(state.bank.mode,'multi');assert.equal(state.bank.pooling,'final_token');
  assert.equal(state.interventions().length,3);
  state.clear();assert.deepEqual(state.interventions(),[]);
  state.reset();assert.deepEqual(state.interventions(),[{vector_id:'formality-11-mean',strength:.5}]);
});

test('new catalog features and mixed same-layer directions need no hardcoded feature routing',()=>{
  const state=new FeatureExperiment(vectors);
  state.enableFeature('detoxification',true);state.enableFeature('empathy',true);
  assert.equal(state.interventions().length,3);
  assert.equal(state.entries().every(i=>i.layer===11),true);
  const settings={task:'rewrite',system_prompt:'Rewrite.',max_input_tokens:2048,max_new_tokens:128};
  const key=entries=>experimentCacheKey('Source','model','version',entries,settings);
  assert.equal(key(state.interventions()),key([...state.interventions()].reverse()));
  const before=key(state.interventions());
  state.bank.values[11]=-.8;assert.notEqual(before,key(state.interventions()));
  state.enableFeature('empathy',false);state.selectFeature('empathy');state.bank.focus(7);
  assert.equal(state.interventions().length,2,'Inspecting a disabled feature never activates it');
});
