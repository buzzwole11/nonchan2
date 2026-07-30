/**
 * Theme resolution.
 *
 * All values come from `@papermatch/design-tokens`; nothing here invents a colour or a
 * duration. The three accessibility inputs from spec section 20 — colour scheme, Reduce
 * Motion and Dynamic Type — are resolved in one place so a screen never has to remember
 * to check them.
 */
import {
  type ColorScheme,
  type MotionSpeed,
  type Theme,
  duration,
  getTheme,
  scaledType,
  type tokens,
} from '@papermatch/design-tokens';

export type ColorSchemePreference = 'system' | 'light' | 'dark';

export interface AppTheme extends Theme {
  /** True when the OS asked for reduced motion, or the user turned it on in settings. */
  reduceMotion: boolean;
  /** Clamped OS font scale (spec section 20: Dynamic Type). */
  fontScale: number;
  /** Duration in ms for an animation, already reduced when Reduce Motion is on. */
  duration: (speed: MotionSpeed) => number;
  /** Font size, line height and family for a role, already scaled. */
  type: (role: keyof typeof tokens.typography.scale) => ReturnType<typeof scaledType>;
  /** Minimum hit target, never smaller than the accessibility floor. */
  touchTarget: number;
}

/**
 * `systemScheme` is typed loosely because React Native's `ColorSchemeName` can also be
 * `'unspecified'` on some platforms; anything that is not an explicit dark preference
 * resolves to light.
 */
export function resolveColorScheme(
  preference: ColorSchemePreference,
  systemScheme: string | null | undefined,
): ColorScheme {
  if (preference === 'light' || preference === 'dark') return preference;
  return systemScheme === 'dark' ? 'dark' : 'light';
}

export function buildTheme(options: {
  preference: ColorSchemePreference;
  systemScheme: string | null | undefined;
  reduceMotion: boolean;
  fontScale: number;
}): AppTheme {
  const scheme = resolveColorScheme(options.preference, options.systemScheme);
  const base = getTheme(scheme);
  const { reduceMotion } = options;

  return {
    ...base,
    reduceMotion,
    fontScale: options.fontScale,
    duration: (speed) => duration(speed, reduceMotion),
    type: (role) => scaledType(role, options.fontScale),
    // Targets grow with the text so a large-type layout stays usable.
    touchTarget: Math.max(base.a11y.minTouchTarget, base.a11y.minTouchTarget * options.fontScale),
  };
}
