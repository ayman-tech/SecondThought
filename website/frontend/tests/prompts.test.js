import test from 'node:test';
import assert from 'node:assert/strict';
import { mountPromptControls } from '../assets/prompts.js';

test('custom instructions and budgets apply atomically; no-system does not leak into custom edits', () => {
  class Element extends EventTarget {
    value=''; disabled=false; readOnly=false; textContent=''; validity='';
    setCustomValidity(value) { this.validity=value; }
    reportValidity() { return !this.validity; }
    focus() {}
  }
  const ids=Object.fromEntries(['task-presets','prompt-limits','experiment-prompt','system-prompt',
    'input-budget','output-budget','apply-prompt','prompt-state','changes-toggle','draft',
    'prompt-settings'].map(id=>[id,new Element()]));
  ids['task-presets'].textContent=JSON.stringify({
    rewrite:{system_prompt:'Rewrite.',output_tokens:128},
    summarize:{system_prompt:'Summarize.',output_tokens:256},
    custom:{system_prompt:'Rewrite.',output_tokens:256},
    none:{system_prompt:null,output_tokens:256},
  });
  ids['prompt-limits'].textContent=JSON.stringify({input:{default:2048},output:{default:128}});
  const previous=globalThis.document;
  globalThis.document={getElementById:id=>ids[id]};
  const emit=(id,type)=>ids[id].dispatchEvent(new Event(type));
  const choose=task=>{ids['experiment-prompt'].value=task;emit('experiment-prompt','change');};
  try {
    let changes=0;
    const controls=mountPromptControls(()=>changes++);
    choose('none');
    assert.equal(controls.settings().system_prompt,null);
    assert.equal(ids['system-prompt'].readOnly,true);
    choose('custom');
    assert.equal(changes,1,'Selecting Custom opens the editor without generating');
    assert.equal(controls.settings().task,'none');
    assert.equal(ids['system-prompt'].readOnly,false);
    emit('apply-prompt','click');
    assert.equal(changes,1,'Empty custom instruction cannot replace the applied settings');
    ids['system-prompt'].value='Answer briefly.';emit('system-prompt','input');
    ids['input-budget'].value='4096';
    assert.equal(changes,1,'Draft edits stay local');
    emit('apply-prompt','click');
    assert.deepEqual(controls.settings(),{task:'custom',system_prompt:'Answer briefly.',
      max_input_tokens:4096,max_new_tokens:256});
    assert.equal(changes,2);
    choose('summarize');
    assert.equal(controls.settings().system_prompt,'Summarize.');
    assert.equal(controls.settings().max_input_tokens,4096);
    assert.equal(ids['changes-toggle'].hidden,true);
    choose('rewrite');
    assert.equal(ids['changes-toggle'].hidden,false);
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document=previous;
  }
});
