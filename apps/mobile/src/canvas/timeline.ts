/**
 * Replaying the reader's saving history (spec section 13).
 *
 * 「年月スライダーで保存履歴を再生 / 関心領域の拡大を客観的に表示」. The slider moves a cutoff
 * through time and the plane shows what the reader had saved by then.
 *
 * **Months, not an arbitrary number of steps.** A slider with fifty positions over a
 * three-month history moves in increments that mean nothing; one step per month is a unit
 * the reader already has. A library saved entirely in one month gets one step, which is
 * honest — there is nothing to replay.
 *
 * **The last position is always "now".** A replay that stopped at the last completed month
 * would hide the papers saved this week, and the reader would think they had lost them.
 *
 * **This filters; it never re-places.** Section 13's plane is a place, and a tile must not
 * move because the reader dragged a time slider. `visibleAt` returns a subset in the same
 * coordinates.
 */
import type { CanvasTile } from '@papermatch/shared-types';

export interface TimelineStep {
  /** Inclusive cutoff: tiles saved at or before this instant are visible. */
  cutoff: number;
  year: number;
  /** 1-12. */
  month: number;
}

function startOfMonth(time: number): Date {
  const date = new Date(time);
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
}

function endOfMonth(date: Date): number {
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1) - 1;
}

/**
 * One step per month from the first save to the last, oldest first.
 *
 * Empty for an empty library — there is no history to replay, and a one-step slider that
 * does nothing is a control that lies about being useful.
 */
export function timelineSteps(tiles: CanvasTile[]): TimelineStep[] {
  const times = tiles
    .map((tile) => Date.parse(tile.savedAt))
    .filter((time) => Number.isFinite(time))
    .sort((a, b) => a - b);
  const first = times[0];
  const last = times[times.length - 1];
  if (first === undefined || last === undefined) return [];

  const steps: TimelineStep[] = [];
  let cursor = startOfMonth(first);
  const limit = startOfMonth(last);
  // Bounded: a corrupt far-future timestamp must not spin here.
  for (let guard = 0; guard < 1200; guard += 1) {
    steps.push({
      cutoff: endOfMonth(cursor),
      year: cursor.getUTCFullYear(),
      month: cursor.getUTCMonth() + 1,
    });
    if (cursor.getTime() >= limit.getTime()) break;
    cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
  }
  return steps;
}

/** The tiles saved at or before `cutoff`, in their own coordinates. */
export function visibleAt(tiles: CanvasTile[], cutoff: number | null): CanvasTile[] {
  if (cutoff === null) return tiles;
  return tiles.filter((tile) => {
    const time = Date.parse(tile.savedAt);
    return !Number.isFinite(time) || time <= cutoff;
  });
}

/**
 * How many fields the reader had touched by each step.
 *
 * Section 13 asks for 関心領域の拡大を客観的に表示 — objectively, meaning a count rather than
 * an impression. This is the count of distinct fields, which is the thing that actually
 * widens; the number of papers grows even when someone reads the same corner forever.
 */
export function fieldBreadth(tiles: CanvasTile[], steps: TimelineStep[]): number[] {
  return steps.map(
    (step) => new Set(visibleAt(tiles, step.cutoff).map((tile) => tile.clusterId ?? '')).size,
  );
}
