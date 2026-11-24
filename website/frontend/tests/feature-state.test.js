import test from 'node:test';
import assert from 'node:assert/strict';
import { FeatureExperiment } from '../assets/feature-state.js';
import { experimentCacheKey } from '../assets/lifecycle.js';

const vectors=['formality','detoxification','fluency','simplification','conciseness','empathy','politeness'].flatMap(feature_id=>
  ['mean','final_token'].flatMap(pooling=>Array.from({length:24},(_,layer_index)=>({
    id:`${feature_id}-${layer_index}-${pooling}`,feature_id,feature_label:feature_id,pooling,layer_index,
    available:true,selectable:true,
  }))));

test('direct layer clicks toggle independent feature selections without an enable step',()=>{
  const state=new FeatureExperiment(vectors);
  state.clear();state.bank.toggle(4);state.bank.values[4]=.7;state.bank.toggle(12);
  assert.deepEqual([...state.bank.selected],[4,12]);
  state.enableFeature('empathy',true);state.bank.toggle(7);state.bank.values[7]=-.3;
  state.selectFeature('formality');
  assert.equal(state.bank.values[4],.7);
  state.bank.toggle(4);
  assert.deepEqual([...state.bank.selected],[12]);
  assert.ok(state.interventions().some(v=>v.vector_id==='empathy-7-mean'&&v.strength===-.3));
  state.bank.toggle(100);
  assert.deepEqual([...state.bank.selected],[12],'Unavailable layers cannot enter the request');
});

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
  state.enableFeature('detoxification',true);state.enableFeature('fluency',true);
  assert.equal(state.interventions().length,3);
  assert.equal(state.entries().every(i=>i.layer===11),true);
  const settings={task:'rewrite',system_prompt:'Rewrite.',max_input_tokens:2048,max_new_tokens:128};
  const key=entries=>experimentCacheKey('Source','model','version',entries,settings);
  assert.equal(key(state.interventions()),key([...state.interventions()].reverse()));
  const before=key(state.interventions());
  state.bank.values[11]=-.8;assert.notEqual(before,key(state.interventions()));
  state.enableFeature('fluency',false);state.selectFeature('fluency');state.bank.focus(7);
  assert.equal(state.interventions().length,2,'Inspecting a disabled feature never activates it');
});

test('disabled edited layer cannot hide other active layers or their peak strength',()=>{
  const state=new FeatureExperiment(vectors);
  state.bank.setMode('multi');state.bank.values[11]=1.7;
  state.bank.focus(12);state.bank.setEnabled(true);state.bank.values[12]=-1.7;
  state.bank.focus(13);state.bank.setEnabled(true);state.bank.values[13]=.5;
  let summary=state.featureSummary('formality');
  assert.equal(summary.peak,1.7);assert.equal(summary.active.length,3);
  state.bank.focus(10);
  summary=state.featureSummary('formality');
  assert.equal(summary.editingSelected,false);assert.equal(summary.active.length,3);
  assert.equal(summary.peak,1.7);
  state.enableFeature('formality',false);
  summary=state.featureSummary('formality');
  assert.equal(summary.active.length,0);assert.equal(summary.saved.length,3);
});

test('seven catalog features retain independent pooling, layers and strengths',()=>{
  const state=new FeatureExperiment(vectors);
  state.features.forEach((feature,index)=>{
    state.enableFeature(feature.id,true);
    state.bank.focus(index);
    state.bank.values[index]=index/10;
    state.bank.useVectorSet(feature.id,index%2?'final_token':'mean');
  });
  assert.equal(state.interventions().length,7);
  state.features.forEach((feature,index)=>{
    const entry=state.interventions().find(i=>i.vector_id.startsWith(feature.id+'-'));
    assert.equal(entry.strength,index/10);
    assert.equal(entry.vector_id,`${feature.id}-${index}-${index%2?'final_token':'mean'}`);
  });
});
