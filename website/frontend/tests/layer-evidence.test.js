import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceColour } from '../assets/layer-evidence.js';

test('colour scale uses an absolute 50–100% reference and never invents missing scores',()=>{
  for(const value of [null,undefined,NaN,Infinity,'0.9',-0.1,1.1])
    assert.equal(evidenceColour(value),null);
  assert.deepEqual(evidenceColour(0.499),evidenceColour(0.5));
  assert.notDeepEqual(evidenceColour(0.5),evidenceColour(0.75));
  assert.notDeepEqual(evidenceColour(0.75),evidenceColour(1));
  assert.deepEqual(evidenceColour(0.9),evidenceColour(0.9));
});
