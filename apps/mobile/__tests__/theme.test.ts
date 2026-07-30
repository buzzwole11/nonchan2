/**
 * Theme resolution, including the three accessibility inputs from spec section 20.
 */
import { tokens } from '@papermatch/design-tokens';

import { buildTheme, resolveColorScheme } from '../src/theme/theme';

describe('colour scheme resolution', () => {
  it('follows the device when the preference is "system"', () => {
    expect(resolveColorScheme('system', 'dark')).toBe('dark');
    expect(resolveColorScheme('system', 'light')).toBe('light');
  });

  it('falls back to light when the device does not report a scheme', () => {
    expect(resolveColorScheme('system', null)).toBe('light');
    expect(resolveColorScheme('system', undefined)).toBe('light');
  });

  it('lets an explicit preference override the device', () => {
    expect(resolveColorScheme('light', 'dark')).toBe('light');
    expect(resolveColorScheme('dark', 'light')).toBe('dark');
  });
});

describe('theme', () => {
  const base = { preference: 'system', systemScheme: 'light', reduceMotion: false, fontScale: 1 } as const;

  it('exposes the token palette for the resolved scheme', () => {
    expect(buildTheme(base).color.background).toBe(tokens.color.light.background);
    expect(buildTheme({ ...base, preference: 'dark' }).color.background).toBe(
      tokens.color.dark.background,
    );
  });

  it('shortens every animation when Reduce Motion is on', () => {
    const normal = buildTheme(base);
    const reduced = buildTheme({ ...base, reduceMotion: true });
    for (const speed of ['fast', 'base', 'slow'] as const) {
      expect(reduced.duration(speed)).toBeLessThanOrEqual(normal.duration(speed));
    }
    expect(reduced.duration('slow')).toBeLessThan(normal.duration('slow'));
  });

  it('scales type with Dynamic Type', () => {
    const normal = buildTheme(base);
    const large = buildTheme({ ...base, fontScale: 1.8 });
    expect(large.type('abstract').fontSize).toBeGreaterThan(normal.type('abstract').fontSize);
    expect(large.type('abstract').lineHeight).toBeGreaterThan(large.type('abstract').fontSize);
  });

  it('never lets a touch target fall below the accessibility floor', () => {
    for (const fontScale of [0.5, 1, 1.5, 2]) {
      const theme = buildTheme({ ...base, fontScale });
      expect(theme.touchTarget).toBeGreaterThanOrEqual(tokens.a11y.minTouchTarget);
    }
  });

  it('grows touch targets alongside larger text', () => {
    expect(buildTheme({ ...base, fontScale: 2 }).touchTarget).toBeGreaterThan(
      buildTheme(base).touchTarget,
    );
  });
});
