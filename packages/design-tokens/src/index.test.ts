import assert from 'node:assert/strict';
import { test } from 'node:test';

import { contrastRatio } from './contrast.ts';
import {
  PROVENANCE_KINDS,
  clampFontScale,
  duration,
  getTheme,
  provenanceBadge,
  scaledType,
  tokens,
} from './index.ts';

const SCHEMES = ['light', 'dark'] as const;

test('light and dark palettes expose the same colour roles', () => {
  const lightRoles = Object.keys(tokens.color.light).sort();
  const darkRoles = Object.keys(tokens.color.dark).sort();
  assert.deepEqual(lightRoles, darkRoles);
});

test('every palette colour is a parseable hex or rgba value', () => {
  for (const scheme of SCHEMES) {
    for (const [role, value] of Object.entries(tokens.color[scheme])) {
      assert.match(
        value,
        /^(#[0-9A-Fa-f]{6}|rgba\(.+\))$/,
        `${scheme}.${role} is not a hex or rgba colour: ${value}`,
      );
    }
  }
});

test('body text meets the WCAG contrast floor on card and background surfaces', () => {
  const floor = tokens.a11y.minContrastBodyText;
  for (const scheme of SCHEMES) {
    const palette = tokens.color[scheme];
    for (const surface of ['background', 'card', 'formulaSurface', 'translationSurface'] as const) {
      const ratio = contrastRatio(palette.textPrimary, palette[surface]);
      assert.ok(
        ratio >= floor,
        `${scheme}: textPrimary on ${surface} is ${ratio.toFixed(2)}:1, below ${floor}:1`,
      );
    }
  }
});

test('secondary text meets the large-text contrast floor on the card surface', () => {
  const floor = tokens.a11y.minContrastLargeText;
  for (const scheme of SCHEMES) {
    const palette = tokens.color[scheme];
    const ratio = contrastRatio(palette.textSecondary, palette.card);
    assert.ok(ratio >= floor, `${scheme}: textSecondary on card is ${ratio.toFixed(2)}:1`);
  }
});

test('provenance kinds all carry an icon and a text label, not colour alone', () => {
  for (const kind of PROVENANCE_KINDS) {
    for (const scheme of SCHEMES) {
      const badge = provenanceBadge(kind, scheme);
      assert.ok(badge.icon.length > 0, `${kind} has no icon`);
      assert.ok(badge.labelKey.startsWith('provenance.'), `${kind} has no label key`);
      assert.match(badge.color, /^#[0-9A-Fa-f]{6}$/);
    }
  }
});

test('reduce motion shortens or removes every duration', () => {
  for (const speed of ['instant', 'fast', 'base', 'slow'] as const) {
    const normal = duration(speed, false);
    const reduced = duration(speed, true);
    assert.ok(reduced <= normal, `${speed}: reduced ${reduced}ms exceeds normal ${normal}ms`);
  }
});

test('font scale is clamped into the designed Dynamic Type range', () => {
  const { minScale, maxScale } = tokens.typography.dynamicType;
  assert.equal(clampFontScale(0.2), minScale);
  assert.equal(clampFontScale(5), maxScale);
  assert.equal(clampFontScale(1.35), 1.35);
  assert.equal(clampFontScale(Number.NaN), minScale);
});

test('scaled type keeps line height above font size at maximum Dynamic Type', () => {
  for (const role of Object.keys(
    tokens.typography.scale,
  ) as (keyof typeof tokens.typography.scale)[]) {
    const scaled = scaledType(role, tokens.typography.dynamicType.maxScale);
    assert.ok(
      scaled.lineHeight > scaled.fontSize,
      `${role}: lineHeight ${scaled.lineHeight} <= fontSize ${scaled.fontSize}`,
    );
    assert.ok(scaled.fontFamily.length > 0);
  }
});

test('touch targets and reading measures match the spec section 19 values', () => {
  const theme = getTheme('light');
  assert.equal(theme.spacing.screenHorizontal, 20);
  assert.equal(theme.spacing.cardPadding, 24);
  assert.equal(theme.spacing.paragraphGap, 16);
  assert.equal(theme.typography.scale.abstract.fontSize, 17);
  assert.ok(theme.a11y.minTouchTarget >= 44);
});
