/**
 * Finding the same paper on both sides of the view switch (spec section 14).
 *
 * The morph needs two rectangles in screen coordinates: where the paper is now, and where
 * it will be after the switch. Only the views themselves know that — the tile is inside two
 * nested ScrollViews on a plane, the row is inside a FlatList — so each view registers the
 * node it drew for a paper, and the screen asks for it by id.
 *
 * **The second measurement cannot be taken until the other view has rendered**, which is
 * why `awaitTarget` waits for the id to appear rather than measuring immediately. Measuring
 * too early returns the rectangle of a node that has not been laid out yet: zeros, or the
 * position it briefly held at mount. Both would send the shape somewhere the paper is not.
 * It gives up after a deadline instead of waiting forever — a row that never appears (the
 * list is filtered, the plane is zoomed elsewhere) is a normal outcome, and the caller
 * falls back to a plain swap.
 */
import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef } from 'react';
import type { View } from 'react-native';

import type { Rect } from './morph';

interface Measurable {
  measureInWindow(callback: (x: number, y: number, width: number, height: number) => void): void;
}

/**
 * How the view draws this paper.
 *
 * Registered rather than inferred from the rectangle. A tile is a rounded square, an island
 * is a circle and a row is a card, and the only thing that knows which is the view that drew
 * it — deriving "probably a circle, it is small and square" would be a guess that goes wrong
 * exactly when a field has one saved paper.
 */
export interface MorphShape {
  radius: number;
  color: string;
}

export interface MorphPlacement extends MorphShape {
  rect: Rect;
}

export interface MorphTargets {
  measure(id: string): Promise<MorphPlacement | null>;
  /** Resolve once `id` has registered and can be measured, or null at the deadline. */
  awaitTarget(id: string, timeoutMs?: number): Promise<MorphPlacement | null>;
  register(id: string, node: Measurable, shape: MorphShape): () => void;
  /**
   * Drop what is currently registered for `id`.
   *
   * Called between measuring the outgoing view and rendering the incoming one. Without it
   * the view being left is still registered when the destination is asked for, and
   * `awaitTarget` answers with the rectangle the paper is *leaving* — the shape then
   * "travels" from the row to the row and the reader sees a coloured box appear over the
   * new view for a quarter of a second. Found by watching it happen.
   */
  forget(id: string): void;
}

const MorphContext = createContext<MorphTargets | null>(null);

/** `measureInWindow` takes a callback and has no failure path; treat silence as "gone". */
function measureNode(node: Measurable, timeoutMs = 200): Promise<Rect | null> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (rect: Rect | null) => {
      if (settled) return;
      settled = true;
      resolve(rect);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);
    node.measureInWindow((x, y, width, height) => {
      clearTimeout(timer);
      const usable = [x, y, width, height].every((value) => Number.isFinite(value));
      finish(usable ? { x, y, width, height } : null);
    });
  });
}

const DEFAULT_TIMEOUT_MS = 600;
const POLL_MS = 16;

export function MorphTargetsProvider({ children }: { children: ReactNode }) {
  // A ref, not state: registering a node must not re-render anything. The map is read only
  // when the reader switches views.
  const nodes = useRef(new Map<string, { node: Measurable; shape: MorphShape }>());

  const value = useMemo<MorphTargets>(() => {
    const map = nodes.current;
    return {
      register(id, node, shape) {
        const entry = { node, shape };
        map.set(id, entry);
        // Identity-guarded, so the outgoing view's unmount cleanup — which can run after the
        // incoming view has already registered — cannot delete the new node.
        return () => {
          if (map.get(id) === entry) map.delete(id);
        };
      },
      forget(id) {
        map.delete(id);
      },
      async measure(id) {
        const entry = map.get(id);
        if (entry === undefined) return null;
        const rect = await measureNode(entry.node);
        return rect === null ? null : { rect, ...entry.shape };
      },
      async awaitTarget(id, timeoutMs = DEFAULT_TIMEOUT_MS) {
        const deadline = Date.now() + timeoutMs;
        for (;;) {
          const entry = map.get(id);
          if (entry !== undefined) {
            const rect = await measureNode(entry.node);
            // A registered-but-unlaid-out node measures as an empty box; keep waiting for
            // it to have a size rather than reporting a rectangle of zero extent.
            if (rect !== null && rect.width > 0 && rect.height > 0) {
              return { rect, ...entry.shape };
            }
          }
          if (Date.now() >= deadline) return null;
          await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        }
      },
    };
  }, []);

  return <MorphContext.Provider value={value}>{children}</MorphContext.Provider>;
}

/** Null outside a provider, so a view can be rendered on its own (tests, the gallery). */
export function useMorphTargets(): MorphTargets | null {
  return useContext(MorphContext);
}

/**
 * A ref callback that registers this node as the paper's position in the current view.
 *
 * Returns the unregister function from the ref callback (React 19), so a tile that scrolls
 * out of the tree stops being offered as a morph endpoint.
 */
export function useMorphTarget(
  id: string | null,
  shape: MorphShape,
): (node: View | null) => (() => void) | void {
  const targets = useMorphTargets();
  const { radius, color } = shape;
  return useCallback(
    (node: View | null) => {
      if (targets === null || id === null || node === null) return;
      return targets.register(id, node, { radius, color });
    },
    // Destructured rather than depending on the object, which is rebuilt every render and
    // would re-register the node on each one.
    [targets, id, radius, color],
  );
}
