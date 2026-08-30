/**
 * The continuous transformation between the Canvas tile and the Library row (spec
 * section 14: 選択中のタイルがLibraryの該当行へ連続変形).
 *
 * **Why an animation is load-bearing here rather than decoration.** Section 14 asks for the
 * two views to be the same library, and section 1 for the switch between them to be smooth.
 * The thing the reader has to believe is that *the square on the plane and the row in the
 * list are one paper*. A cut between two layouts leaves them to work that out; a shape that
 * travels from one to the other says it without words. That is also why the morph runs on
 * the **selected** tile only — it is an answer to "where did my paper go", and there is no
 * such question when nothing was selected.
 *
 * **This module is only the geometry**, so the part that decides what is drawn can be
 * tested without a renderer. The measuring and the animating live next door in
 * `MorphLayer`; what is here is pure and total.
 *
 * **A morph that cannot be honest is refused.** `canMorph` rejects a pair of rectangles
 * where either end is empty or off-screen. A tile scrolled out of view has no on-screen
 * position, and animating from a guessed one would draw a shape flying in from a place the
 * reader's paper never was — worse than no animation, because it asserts something false
 * about where they had been looking. The caller falls back to a fade.
 */
import { hexToOklab, oklabToHex } from '@papermatch/design-tokens';

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Below this, a measured rectangle is treated as "not really on screen". */
const MIN_VISIBLE = 4;

/**
 * Whether a morph between these two rectangles would be truthful.
 *
 * Both ends must have real extent, and both must overlap the viewport — a rectangle at
 * `y: -800` is a row that exists in the list but is scrolled far above it, and starting or
 * ending the animation there would be a claim about the reader's position that is not true.
 */
export function canMorph(
  from: Rect | null,
  to: Rect | null,
  viewport: { width: number; height: number },
): boolean {
  if (from === null || to === null) return false;
  for (const rect of [from, to]) {
    if (rect.width < MIN_VISIBLE || rect.height < MIN_VISIBLE) return false;
    if (rect.x + rect.width <= 0 || rect.x >= viewport.width) return false;
    if (rect.y + rect.height <= 0 || rect.y >= viewport.height) return false;
  }
  return true;
}

/** Linear interpolation, clamped: `t` outside 0..1 is a caller bug, not a longer animation. */
function mix(from: number, to: number, t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  return from + (to - from) * clamped;
}

export function interpolateRect(from: Rect, to: Rect, t: number): Rect {
  return {
    x: mix(from.x, to.x, t),
    y: mix(from.y, to.y, t),
    width: mix(from.width, to.width, t),
    height: mix(from.height, to.height, t),
  };
}

/**
 * Interpolate the tile's field colour towards the row's card colour **in Oklab**, for the
 * same reason the field blend uses it (D-048): sRGB channel averaging averages the encoding
 * rather than the light, so the midpoint of the trip would be darker than either end. Here
 * that would read as the tile briefly dimming on its way to the list, which looks like the
 * paper being deselected at exactly the moment the reader is following it.
 */
export function interpolateColor(from: string, to: string, t: number): string {
  const a = hexToOklab(from);
  const b = hexToOklab(to);
  return oklabToHex({
    L: mix(a.L, b.L, t),
    a: mix(a.a, b.a, t),
    b: mix(a.b, b.b, t),
  });
}

export interface MorphFrame extends Rect {
  borderRadius: number;
  backgroundColor: string;
}

export interface MorphEnds {
  from: Rect;
  to: Rect;
  fromRadius: number;
  toRadius: number;
  fromColor: string;
  toColor: string;
}

/** The drawn state at progress `t`. */
export function morphFrame(ends: MorphEnds, t: number): MorphFrame {
  return {
    ...interpolateRect(ends.from, ends.to, t),
    borderRadius: mix(ends.fromRadius, ends.toRadius, t),
    backgroundColor: interpolateColor(ends.fromColor, ends.toColor, t),
  };
}
