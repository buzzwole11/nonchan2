/**
 * Colours for research fields, and how to mix them (spec section 13).
 *
 * Section 13 asks for a tile whose colour is a 研究分野の重み付き混合 and says outright
 * **RGB単純平均を避ける**. That instruction is not aesthetic fussiness, and the reason is
 * specific: sRGB values are gamma-encoded, so averaging the channels averages *encodings*
 * rather than light, and the result comes out **darker than the midpoint of its parents**.
 * Measured on this palette, the naive average of `cs` and `cond-mat` has a perceived
 * lightness of 0.51 where both parents and the true midpoint sit around 0.59.
 *
 * That matters here for a reason beyond taste. Section 13 also uses **brightness to mean
 * recent activity**. A blend that comes out too dark is not merely ugly — it is a tile
 * quietly reporting the wrong value for a different variable, and no reader could tell.
 *
 * So mixing happens in **Oklab**, where the straight line between two colours passes
 * through what a person would call intermediate, and the blend's lightness is the average
 * of its parents' to three decimal places.
 *
 * (Mixing opposite hues — a blue field with a yellow one — correctly tends toward neutral
 * rather than green. Green is what *paint* does; this is light.)
 *
 * **Colour is never the only carrier** (section 20). A tile's field is also its position
 * on the plane — the island it sits in — and its label at close zoom. This module supplies
 * the colour; it does not make colour load-bearing.
 */
import { parseHex } from './contrast.ts';

/**
 * One base colour per top-level field.
 *
 * Chosen to stay distinguishable under the common colour-vision deficiencies: the set
 * varies in lightness as well as hue, so two fields never differ by red-versus-green
 * alone. A field with no entry falls back to a neutral rather than borrowing a
 * neighbour's colour — an unknown field must not look like a known one.
 */
export const FIELD_BASE_COLORS: Record<string, string> = {
  math: '#4c6ef5',
  physics: '#e8590c',
  cs: '#0ca678',
  'q-bio': '#ae3ec9',
  'q-fin': '#1098ad',
  stat: '#f59f00',
  'astro-ph': '#5f3dc4',
  'cond-mat': '#c2255c',
  'hep-th': '#7048e8',
  'hep-ph': '#9c36b5',
  'gr-qc': '#3b5bdb',
  'nucl-th': '#d9480f',
  econ: '#087f5b',
};

/** Used when a field has no colour of its own. Deliberately colourless. */
export const UNKNOWN_FIELD_COLOR = '#868e96';

export interface Oklab {
  L: number;
  a: number;
  b: number;
}

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(channel: number): number {
  const c = channel <= 0.0031308 ? channel * 12.92 : 1.055 * Math.pow(channel, 1 / 2.4) - 0.055;
  return Math.round(Math.max(0, Math.min(1, c)) * 255);
}

/** sRGB hex to Oklab (Björn Ottosson's transform). */
export function hexToOklab(hex: string): Oklab {
  const { r, g, b } = parseHex(hex);
  const lr = srgbToLinear(r);
  const lg = srgbToLinear(g);
  const lb = srgbToLinear(b);

  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);

  return {
    L: 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  };
}

export function oklabToHex({ L, a, b }: Oklab): string {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;

  const red = linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s);
  const green = linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s);
  const blue = linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s);

  return `#${[red, green, blue].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * The base colour for a field id, matching on the most specific prefix available.
 *
 * `math.PR` uses `math`'s colour so a reader sees one mathematics island rather than
 * nine unrelated ones, while a field that earns its own entry (`hep-th`) keeps it.
 */
export function fieldColor(fieldId: string | null | undefined): string {
  if (!fieldId) return UNKNOWN_FIELD_COLOR;
  if (FIELD_BASE_COLORS[fieldId]) return FIELD_BASE_COLORS[fieldId];
  const root = fieldId.split('.')[0];
  return (root && FIELD_BASE_COLORS[root]) || UNKNOWN_FIELD_COLOR;
}

/**
 * A weighted blend of field colours, mixed perceptually.
 *
 * Weights need not sum to 1 and are normalised here; a non-positive weight is dropped
 * rather than allowed to pull the mix backwards through the colour space. An empty or
 * all-zero set returns the neutral, because "no fields" and "a field we have no colour
 * for" are the same thing to look at.
 */
export function blendFieldColors(weights: Record<string, number>): string {
  const entries = Object.entries(weights).filter(([, weight]) => weight > 0);
  if (entries.length === 0) return UNKNOWN_FIELD_COLOR;
  if (entries.length === 1) return fieldColor(entries[0]?.[0]);

  const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
  const mixed = entries.reduce<Oklab>(
    (accumulator, [fieldId, weight]) => {
      const share = weight / total;
      const lab = hexToOklab(fieldColor(fieldId));
      return {
        L: accumulator.L + lab.L * share,
        a: accumulator.a + lab.a * share,
        b: accumulator.b + lab.b * share,
      };
    },
    { L: 0, a: 0, b: 0 },
  );

  return oklabToHex(mixed);
}
