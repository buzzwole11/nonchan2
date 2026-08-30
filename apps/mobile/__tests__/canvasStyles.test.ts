/**
 * The other Canvas styles and the timeline (spec section 13).
 *
 * The rendering is checked in the browser; what is held down here is the arithmetic that
 * decides what a reader is being told — which years appear as bands, and what the history
 * slider replays.
 */
import type { CanvasTile } from '@papermatch/shared-types';

import { yearBands } from '../src/canvas/CanvasStyles';
import { fieldBreadth, timelineSteps, visibleAt } from '../src/canvas/timeline';

function tile(id: string, year: number, savedAt: string, field = 'math.PR'): CanvasTile {
  return {
    entityType: 'paper',
    entityId: id,
    x: 0,
    y: 0,
    clusterId: field,
    weight: 0.5,
    userOverride: false,
    savedAt,
    paper: { id, year, fieldWeights: { [field]: 1 } },
  } as unknown as CanvasTile;
}

describe('Spectrum bands', () => {
  it('draws a band for a year with nothing in it', () => {
    // A library that jumps 2014 → 2023 must not put those bands side by side: that says the
    // reader has been reading steadily when they have a nine-year hole. The gap is the
    // information.
    const bands = yearBands([
      tile('a', 2014, '2026-01-01T00:00:00Z'),
      tile('b', 2017, '2026-01-01T00:00:00Z'),
    ]);

    expect(bands.map((band) => band.year)).toEqual([2014, 2015, 2016, 2017]);
    expect(bands.filter((band) => band.empty).map((band) => band.year)).toEqual([2015, 2016]);
  });

  it('counts the papers in each year', () => {
    const bands = yearBands([
      tile('a', 2020, '2026-01-01T00:00:00Z'),
      tile('b', 2020, '2026-01-01T00:00:00Z'),
    ]);

    expect(bands).toHaveLength(1);
    expect(bands[0]?.count).toBe(2);
  });

  it('has nothing to draw for an empty library', () => {
    expect(yearBands([])).toEqual([]);
  });
});

describe('the history slider', () => {
  it('steps one month at a time from the first save to the last', () => {
    const steps = timelineSteps([
      tile('a', 2024, '2025-11-04T10:00:00Z'),
      tile('b', 2024, '2026-02-20T10:00:00Z'),
    ]);

    expect(steps.map((step) => `${step.year}-${step.month}`)).toEqual([
      '2025-11',
      '2025-12',
      '2026-1',
      '2026-2',
    ]);
  });

  it('ends at the month of the last save, so nothing recent is hidden', () => {
    // Stopping at the last *completed* month would drop this week's saves and the reader
    // would think they had lost them.
    const steps = timelineSteps([tile('a', 2024, '2026-02-20T10:00:00Z')]);

    expect(steps[steps.length - 1]).toMatchObject({ year: 2026, month: 2 });
  });

  it('offers no slider at all for an empty library', () => {
    expect(timelineSteps([])).toEqual([]);
  });

  it('replays by hiding what had not been saved yet', () => {
    const tiles = [
      tile('old', 2020, '2025-11-04T10:00:00Z'),
      tile('new', 2024, '2026-02-20T10:00:00Z'),
    ];
    const steps = timelineSteps(tiles);
    const first = steps[0];

    expect(first).toBeDefined();
    expect(visibleAt(tiles, first?.cutoff ?? 0).map((t) => t.entityId)).toEqual(['old']);
  });

  it('shows everything when no cutoff is set', () => {
    const tiles = [tile('a', 2020, '2025-11-04T10:00:00Z')];

    expect(visibleAt(tiles, null)).toHaveLength(1);
  });

  it('never hides a tile whose timestamp cannot be read', () => {
    // A tile with a broken date disappearing from the plane looks like a lost paper. Being
    // visible at every step is the failure mode that does not alarm anyone.
    const tiles = [tile('broken', 2020, 'not a date')];
    const steps = timelineSteps([tile('a', 2020, '2025-11-04T10:00:00Z')]);

    expect(visibleAt(tiles, steps[0]?.cutoff ?? 0)).toHaveLength(1);
  });

  it('measures widening interest by distinct fields, not by paper count', () => {
    // Section 13: 関心領域の拡大を客観的に表示. The number of papers grows even when someone
    // reads the same corner forever; the number of fields is what actually widens.
    const tiles = [
      tile('a', 2020, '2025-11-04T10:00:00Z', 'math.PR'),
      tile('b', 2020, '2025-11-06T10:00:00Z', 'math.PR'),
      tile('c', 2020, '2025-12-06T10:00:00Z', 'hep-th'),
    ];
    const steps = timelineSteps(tiles);

    expect(fieldBreadth(tiles, steps)).toEqual([1, 2]);
  });
});
