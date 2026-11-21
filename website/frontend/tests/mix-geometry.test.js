import test from 'node:test';
import assert from 'node:assert/strict';
import { MIX,featurePoint,pointStrength,strengthRadius } from '../assets/mix-geometry.js';

test('signed spider-web axes round-trip strengths for all three features',()=>{
  for(let axis=0;axis<3;axis++) for(const strength of [-2,-1.4,-.2,0,.5,2]) {
    const point=featurePoint(axis,3,strength);
    assert.equal(pointStrength(point.x,point.y,axis,3),strength);
  }
  assert.equal(strengthRadius(-2),0);
  assert.equal(strengthRadius(0),MIX.radius/2);
  assert.equal(strengthRadius(2),MIX.radius);
});

test('drag projection clamps to bounds and ignores perpendicular motion',()=>{
  assert.equal(pointStrength(MIX.x,MIX.y-1000,0,3),2);
  assert.equal(pointStrength(MIX.x,MIX.y+1000,0,3),-2);
  const point=featurePoint(0,3,.8);
  assert.equal(pointStrength(point.x+60,point.y,0,3),.8);
});
