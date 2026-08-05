/**
 * The tile → row morph (spec section 14: 選択中のタイルがLibraryの該当行へ連続変形).
 *
 * The animation itself is not what these tests hold down. What matters is that the shape
 * only ever travels between two places the reader's paper actually was, and that it does
 * not dip darker on the way — the same claim the field-colour blend makes, for the same
 * reason (D-048).
 */
import { hexToOklab } from '@papermatch/design-tokens';

import {
  type Rect,
  canMorph,
  interpolateColor,
  interpolateRect,
  morphFrame,
} from '../src/canvas/morph';

const VIEWPORT = { width: 390, height: 844 };

const TILE: Rect = { x: 120, y: 300, width: 44, height: 44 };
const ROW: Rect = { x: 16, y: 210, width: 358, height: 132 };

describe('deciding whether to morph at all', () => {
  it('morphs between two rectangles the reader can see', () => {
    expect(canMorph(TILE, ROW, VIEWPORT)).toBe(true);
  });

  it('refuses when one end is off the top of the screen', () => {
    // A row scrolled far above the list is somewhere the paper is not. Flying the shape in
    // from there would assert something false about where the reader had been looking.
    expect(canMorph(TILE, { ...ROW, y: -400 }, VIEWPORT)).toBe(false);
  });

  it('refuses when one end is off to the side', () => {
    expect(canMorph({ ...TILE, x: 520 }, ROW, VIEWPORT)).toBe(false);
  });

  it('refuses a rectangle with no extent', () => {
    // What an unlaid-out node measures as.
    expect(canMorph({ x: 0, y: 0, width: 0, height: 0 }, ROW, VIEWPORT)).toBe(false);
  });

  it('refuses when a measurement is missing entirely', () => {
    expect(canMorph(null, ROW, VIEWPORT)).toBe(false);
    expect(canMorph(TILE, null, VIEWPORT)).toBe(false);
  });
});

describe('the path', () => {
  it('starts exactly on the tile and ends exactly on the row', () => {
    // If either end is approximate, the shape visibly jumps at the moment it takes off or
    // the moment it is removed.
    expect(interpolateRect(TILE, ROW, 0)).toEqual(TILE);
    expect(interpolateRect(TILE, ROW, 1)).toEqual(ROW);
  });

  it('is halfway across at halfway through', () => {
    expect(interpolateRect(TILE, ROW, 0.5)).toEqual({ x: 68, y: 255, width: 201, height: 88 });
  });

  it('clamps rather than overshooting', () => {
    // A progress value outside 0..1 is a caller bug; extrapolating would throw the shape off
    // the screen instead of making the bug visible where it is.
    expect(interpolateRect(TILE, ROW, 1.4)).toEqual(ROW);
    expect(interpolateRect(TILE, ROW, -2)).toEqual(TILE);
  });

  it('carries the corner radius from the tile’s quarter-side to the row’s', () => {
    const ends = {
      from: TILE,
      to: ROW,
      fromRadius: 11,
      toRadius: 16,
      fromColor: '#4c6ef5',
      toColor: '#ffffff',
    };

    expect(morphFrame(ends, 0).borderRadius).toBe(11);
    expect(morphFrame(ends, 1).borderRadius).toBe(16);
    expect(morphFrame(ends, 0.5).borderRadius).toBeCloseTo(13.5, 5);
  });
});

describe('the colour on the way', () => {
  it('lands on both ends', () => {
    expect(interpolateColor('#4c6ef5', '#ffffff', 0).toLowerCase()).toBe('#4c6ef5');
    expect(interpolateColor('#4c6ef5', '#ffffff', 1).toLowerCase()).toBe('#ffffff');
  });

  it('never dips darker than both ends', () => {
    // The sRGB channel average of a saturated tile colour and white is darker than the true
    // midpoint (D-048). Mid-flight that reads as the tile dimming, which looks like the
    // paper being deselected exactly while the reader is following it.
    const from = '#4c6ef5';
    const to = '#ffffff';
    const ends = [hexToOklab(from).L, hexToOklab(to).L];
    const floor = Math.min(...ends);

    for (const t of [0.1, 0.25, 0.5, 0.75, 0.9]) {
      expect(hexToOklab(interpolateColor(from, to, t)).L).toBeGreaterThanOrEqual(floor - 1e-6);
    }
  });

  it('moves in a straight line through perceptual lightness', () => {
    const midpoint = hexToOklab(interpolateColor('#4c6ef5', '#ffffff', 0.5)).L;
    const expected = (hexToOklab('#4c6ef5').L + hexToOklab('#ffffff').L) / 2;

    expect(midpoint).toBeCloseTo(expected, 3);
  });
});
