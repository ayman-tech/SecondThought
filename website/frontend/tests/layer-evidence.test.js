import test from 'node:test';
import assert from 'node:assert/strict';
import { FEATURE_COLOURS, layerAppearance } from '../assets/layer-colours.js';

test('unselected layers use one neutral appearance', () => {
  assert.deepEqual(layerAppearance([]), layerAppearance(['unknown']));
  assert.equal(layerAppearance([]).fill, '#edf0f5');
});

test('each feature uses its own pale fill and matching border', () => {
  const fills = Object.keys(FEATURE_COLOURS).map(feature => {
    const appearance = layerAppearance([feature]);
    assert.equal(appearance.border, FEATURE_COLOURS[feature]);
    assert.match(appearance.fill, /, 0\.24\)$/);
    return appearance.fill;
  });
  assert.equal(new Set(fills).size, 4);
});

test('shared layers show stable stripes for all selected features', () => {
  const mixed = layerAppearance(['empathy', 'formality', 'empathy']);
  assert.deepEqual(mixed.features, ['formality', 'empathy']);
  assert.match(mixed.fill, /^linear-gradient/);
  assert.ok(mixed.fill.includes(layerAppearance(['formality']).fill));
  assert.ok(mixed.fill.includes(layerAppearance(['empathy']).fill));
  assert.deepEqual(mixed, layerAppearance(['formality', 'empathy']));
});
