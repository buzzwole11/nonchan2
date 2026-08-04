import assert from 'node:assert/strict';
import { test } from 'node:test';

import { contrastRatio, parseHex } from './contrast.ts';
import {
  FIELD_BASE_COLORS,
  UNKNOWN_FIELD_COLOR,
  blendFieldColors,
  fieldColor,
  hexToOklab,
  oklabToHex,
  readableOn,
  TILE_INK_DARK,
  TILE_INK_LIGHT,
} from './fieldColor.ts';

test('a round trip through Oklab returns the colour it started with', () => {
  for (const hex of Object.values(FIELD_BASE_COLORS)) {
    const back = oklabToHex(hexToOklab(hex));
    const original = parseHex(hex);
    const returned = parseHex(back);
    // Within one 8-bit step per channel: the transform is lossy at the last bit only.
    assert.ok(Math.abs(original.r - returned.r) <= 1, `${hex} -> ${back} (r)`);
    assert.ok(Math.abs(original.g - returned.g) <= 1, `${hex} -> ${back} (g)`);
    assert.ok(Math.abs(original.b - returned.b) <= 1, `${hex} -> ${back} (b)`);
  }
});

test('a subfield inherits its parent field colour', () => {
  // One mathematics island rather than nine unrelated ones.
  assert.equal(fieldColor('math.PR'), FIELD_BASE_COLORS['math']);
  assert.equal(fieldColor('math.CO'), FIELD_BASE_COLORS['math']);
});

test('a field with its own entry keeps it', () => {
  assert.equal(fieldColor('hep-th'), FIELD_BASE_COLORS['hep-th']);
  assert.notEqual(fieldColor('hep-th'), fieldColor('hep-ph'));
});

test('an unknown field is neutral rather than borrowing a neighbour', () => {
  assert.equal(fieldColor('not-a-field'), UNKNOWN_FIELD_COLOR);
  assert.equal(fieldColor(null), UNKNOWN_FIELD_COLOR);
  assert.equal(fieldColor(undefined), UNKNOWN_FIELD_COLOR);
  assert.equal(fieldColor(''), UNKNOWN_FIELD_COLOR);
});

test('blending one field returns that field exactly', () => {
  assert.equal(blendFieldColors({ 'math.PR': 1 }), FIELD_BASE_COLORS['math']);
});

test('blending nothing returns the neutral', () => {
  assert.equal(blendFieldColors({}), UNKNOWN_FIELD_COLOR);
  assert.equal(blendFieldColors({ math: 0 }), UNKNOWN_FIELD_COLOR);
});

test('a non-positive weight is dropped rather than pulling the mix backwards', () => {
  assert.equal(blendFieldColors({ math: 1, physics: -5 }), fieldColor('math'));
});

test('weights need not sum to one', () => {
  assert.equal(blendFieldColors({ math: 3, cs: 3 }), blendFieldColors({ math: 1, cs: 1 }));
});

test('the blend is weighted, not just an even mix', () => {
  const even = blendFieldColors({ math: 1, physics: 1 });
  const mostlyMath = blendFieldColors({ math: 9, physics: 1 });
  assert.notEqual(even, mostlyMath);

  // The lopsided mix must be nearer the dominant parent.
  const target = hexToOklab(fieldColor('math'));
  const distance = (hex: string) => {
    const lab = hexToOklab(hex);
    return Math.hypot(lab.L - target.L, lab.a - target.a, lab.b - target.b);
  };
  assert.ok(distance(mostlyMath) < distance(even));
});

test('a blend keeps the lightness its parents had, where an RGB average loses it', () => {
  // Spec section 13: RGB単純平均を避ける. sRGB is gamma-encoded, so averaging channels
  // averages encodings and comes out darker than the true midpoint. Section 13 uses
  // brightness for *recent activity*, so a blend that darkens is a tile reporting the
  // wrong value for a different variable.
  const pairs: [string, string][] = [
    ['gr-qc', 'stat'],
    ['math', 'physics'],
    ['cs', 'cond-mat'],
  ];

  for (const [first, second] of pairs) {
    const a = fieldColor(first);
    const b = fieldColor(second);
    const midpoint = (hexToOklab(a).L + hexToOklab(b).L) / 2;

    const perceptual = hexToOklab(blendFieldColors({ [first]: 1, [second]: 1 })).L;
    const pa = parseHex(a);
    const pb = parseHex(b);
    const naiveHex = `#${[(pa.r + pb.r) / 2, (pa.g + pb.g) / 2, (pa.b + pb.b) / 2]
      .map((v) => Math.round(v).toString(16).padStart(2, '0'))
      .join('')}`;
    const naive = hexToOklab(naiveHex).L;

    assert.ok(
      Math.abs(perceptual - midpoint) < 0.005,
      `${first}+${second}: perceptual L ${perceptual} should match midpoint ${midpoint}`,
    );
    assert.ok(
      naive < midpoint - 0.01,
      `${first}+${second}: the naive average ${naive} should be darker than ${midpoint}`,
    );
  }
});

test('every base colour is a valid six-digit hex', () => {
  for (const [field, hex] of Object.entries(FIELD_BASE_COLORS)) {
    assert.match(hex, /^#[0-9a-f]{6}$/, `${field} = ${hex}`);
  }
  assert.match(UNKNOWN_FIELD_COLOR, /^#[0-9a-f]{6}$/);
});

test('no two fields share a base colour', () => {
  const values = Object.values(FIELD_BASE_COLORS);
  assert.equal(new Set(values).size, values.length);
  assert.ok(!values.includes(UNKNOWN_FIELD_COLOR));
});

test('a blend is always a valid colour', () => {
  const fields = Object.keys(FIELD_BASE_COLORS);
  for (const first of fields) {
    for (const second of fields) {
      assert.match(blendFieldColors({ [first]: 2, [second]: 1 }), /^#[0-9a-f]{6}$/);
    }
  }
});

test('a tile label is legible on every field colour', () => {
  // Spec section 20. Field colours span a wide lightness range on purpose — `stat` is a
  // bright amber — and fixing the label to white fails WCAG on the light end, putting the
  // one label that names the field out of reach of the readers most likely to need it.
  for (const hex of [...Object.values(FIELD_BASE_COLORS), UNKNOWN_FIELD_COLOR]) {
    const ink = readableOn(hex);
    assert.ok(
      contrastRatio(ink, hex) >= 3,
      `${hex}: ink ${ink} only reaches ${contrastRatio(ink, hex).toFixed(2)}:1`,
    );
  }
});

test('the ink flips rather than staying white on a light field', () => {
  assert.equal(readableOn(FIELD_BASE_COLORS['stat'] as string), TILE_INK_DARK);
  assert.equal(readableOn(FIELD_BASE_COLORS['hep-th'] as string), TILE_INK_LIGHT);
});
