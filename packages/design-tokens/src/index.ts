/**
 * PaperMatch design tokens.
 *
 * `tokens/tokens.json` is the single source of truth (spec section 19). This module
 * only adds types and small resolution helpers on top of it, so the mobile app and
 * any future surface read identical values.
 */
import tokensJson from '../tokens/tokens.json' with { type: 'json' };

export const tokens = tokensJson;

export type ColorScheme = 'light' | 'dark';

export type ColorRole = keyof (typeof tokensJson)['color']['light'];
export type TypographyRole = keyof (typeof tokensJson)['typography']['scale'];
export type SpacingRole = keyof (typeof tokensJson)['spacing'];
export type MotionSpeed = keyof (typeof tokensJson)['motion']['durations'];

/** Provenance labels from spec section 11 — colour is always paired with icon + label key. */
export const PROVENANCE_KINDS = [
  'original',
  'verified_step',
  'ai_explanation',
  'assumption',
  'human_reviewed',
] as const;

export type ProvenanceKind = (typeof PROVENANCE_KINDS)[number];

export interface ProvenanceBadge {
  kind: ProvenanceKind;
  /** Icon name — meaning must survive with colour removed. */
  icon: string;
  /** i18n key for the visible text label. */
  labelKey: string;
  color: string;
}

export interface Theme {
  scheme: ColorScheme;
  color: Record<ColorRole, string>;
  spacing: Record<SpacingRole, number>;
  radius: (typeof tokensJson)['radius'];
  typography: (typeof tokensJson)['typography'];
  elevation: (typeof tokensJson)['elevation'];
  a11y: (typeof tokensJson)['a11y'];
}

/** Resolve the full palette for a colour scheme. */
export function getTheme(scheme: ColorScheme): Theme {
  return {
    scheme,
    color: tokensJson.color[scheme],
    spacing: tokensJson.spacing,
    radius: tokensJson.radius,
    typography: tokensJson.typography,
    elevation: tokensJson.elevation,
    a11y: tokensJson.a11y,
  };
}

/**
 * Duration for an animation, honouring the user's Reduce Motion preference
 * (spec section 20: continuous morphs collapse to a short fade, never to a jump
 * that loses the user's sense of place).
 */
export function duration(speed: MotionSpeed, reduceMotion: boolean): number {
  return reduceMotion
    ? tokensJson.motion.reducedDurations[speed]
    : tokensJson.motion.durations[speed];
}

/** Badge descriptor for a provenance kind — never returns colour alone. */
export function provenanceBadge(kind: ProvenanceKind, scheme: ColorScheme): ProvenanceBadge {
  const entry = tokensJson.provenance[kind];
  return {
    kind,
    icon: entry.icon,
    labelKey: entry.labelKey,
    color: entry[scheme],
  };
}

/**
 * Clamp the OS font scale into the range the layouts are designed for
 * (spec section 20: Dynamic Type support).
 */
export function clampFontScale(osFontScale: number): number {
  const { minScale, maxScale } = tokensJson.typography.dynamicType;
  if (!Number.isFinite(osFontScale)) return minScale;
  return Math.min(maxScale, Math.max(minScale, osFontScale));
}

/** Scaled font size + line height for a typography role. */
export function scaledType(
  role: TypographyRole,
  osFontScale = 1,
): { fontSize: number; lineHeight: number; fontFamily: string; fontWeight: string } {
  const spec = tokensJson.typography.scale[role];
  const scale = clampFontScale(osFontScale);
  const family = tokensJson.typography.families[spec.family as keyof typeof tokensJson.typography.families];
  return {
    fontSize: Math.round(spec.fontSize * scale),
    lineHeight: Math.round(spec.lineHeight * scale),
    fontFamily: family,
    fontWeight: spec.weight,
  };
}
