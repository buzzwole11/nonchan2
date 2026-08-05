/**
 * Finding the same paper on both sides of the view switch (spec section 14).
 *
 * The registry is where the morph went wrong in practice, so these are regression tests
 * before they are anything else. The failure was not subtle once seen — a coloured box
 * appearing over the new view and shrinking in place — but nothing in the types prevented
 * it, because both ends were perfectly valid rectangles. They were just the same one.
 */
import { act, render } from '@testing-library/react-native';
import { useEffect } from 'react';

import {
  MorphTargetsProvider,
  type MorphTargets,
  useMorphTargets,
} from '../src/canvas/MorphTargets';

/** Stands in for a laid-out native view. */
function node(x: number, y: number, width = 40, height = 40) {
  return {
    measureInWindow(callback: (x: number, y: number, w: number, h: number) => void) {
      callback(x, y, width, height);
    },
  };
}

/** A node whose measurement callback never fires — what an unmounted view behaves like. */
const SILENT = { measureInWindow() {} };

function withTargets(): Promise<MorphTargets> {
  return new Promise((resolve) => {
    function Probe() {
      const targets = useMorphTargets();
      useEffect(() => {
        if (targets !== null) resolve(targets);
      }, [targets]);
      return null;
    }
    render(
      <MorphTargetsProvider>
        <Probe />
      </MorphTargetsProvider>,
    );
  });
}

describe('registering where a paper is', () => {
  it('measures the node the view registered, with the shape it drew', async () => {
    const targets = await withTargets();
    targets.register('p1', node(16, 210, 358, 132), { radius: 16, color: '#ffffff' });

    const placement = await targets.measure('p1');

    expect(placement).toEqual({
      rect: { x: 16, y: 210, width: 358, height: 132 },
      radius: 16,
      color: '#ffffff',
    });
  });

  it('carries the drawn shape rather than guessing it from the rectangle', async () => {
    // A single-paper island is a small circle; a small tile is a small rounded square. The
    // rectangle cannot tell them apart, so the view that drew it says which.
    const targets = await withTargets();
    targets.register('p1', node(100, 100, 44, 44), { radius: 22, color: '#7048e8' });

    expect((await targets.measure('p1'))?.radius).toBe(22);
  });

  it('knows nothing about a paper no view drew', async () => {
    const targets = await withTargets();

    expect(await targets.measure('missing')).toBeNull();
  });
});

describe('handing over between the two views', () => {
  it('stops answering for the view being left', async () => {
    // The regression. Without `forget`, the outgoing row is still registered when the
    // destination is asked for, so the shape "travels" from the row to the row: a coloured
    // box that appears over the new view and shrinks in place.
    const targets = await withTargets();
    targets.register('p1', node(16, 210, 358, 132), { radius: 16, color: '#ffffff' });

    targets.forget('p1');

    expect(await targets.measure('p1')).toBeNull();
  });

  it('lets the arriving view’s node win even if the old cleanup runs late', async () => {
    // React can run the outgoing ref's cleanup after the incoming one has registered. An
    // unguarded cleanup would delete the new node and the morph would silently stop.
    const targets = await withTargets();
    const releaseOld = targets.register('p1', node(16, 210), { radius: 16, color: '#ffffff' });
    targets.register('p1', node(120, 300), { radius: 22, color: '#7048e8' });

    releaseOld();

    expect((await targets.measure('p1'))?.rect.x).toBe(120);
  });

  it('waits for the arriving view to render, then answers', async () => {
    const targets = await withTargets();
    const arrived = targets.awaitTarget('p1', 2000);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
      targets.register('p1', node(120, 300), { radius: 11, color: '#7048e8' });
    });

    expect((await arrived)?.rect).toEqual({ x: 120, y: 300, width: 40, height: 40 });
  });

  it('gives up rather than waiting forever for a paper that never appears', async () => {
    // Normal: the plane is filtered to another field, or the row is not in the search
    // results. The caller falls back to a plain swap.
    const targets = await withTargets();

    expect(await targets.awaitTarget('p1', 80)).toBeNull();
  });

  it('keeps waiting while the node is registered but has no size yet', async () => {
    // What a node measures as between registering and being laid out. Reporting that zero
    // box would send the shape to the top-left corner of the screen.
    const targets = await withTargets();
    targets.register('p1', node(0, 0, 0, 0), { radius: 0, color: '#ffffff' });

    expect(await targets.awaitTarget('p1', 80)).toBeNull();
  });

  it('treats a node that never answers as gone instead of hanging', async () => {
    const targets = await withTargets();
    targets.register('p1', SILENT, { radius: 16, color: '#ffffff' });

    expect(await targets.measure('p1')).toBeNull();
  });
});
