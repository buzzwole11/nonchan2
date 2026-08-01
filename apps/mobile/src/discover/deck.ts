/**
 * Deck state, as a pure reducer.
 *
 * The swipe deck has to hold several things at once — the queue, the card being acted on,
 * what Undo would restore, and whether more pages exist — and get them right while the
 * network is slow or absent. Keeping the logic pure means all of that is unit-testable
 * without rendering anything or mocking a server.
 *
 * Two behaviours are load-bearing:
 *
 * * **The acted-on card is remembered, not discarded.** Undo has to put the exact card
 *   back at the front (spec section 6), and refetching it would be both slow and wrong —
 *   the server has already excluded it by then.
 * * **The queue is topped up before it empties.** Spec section 25 asks for the next card
 *   to be there without a wait; a deck that fetches when it hits zero always shows a
 *   spinner between cards.
 */
import type { FeedItem } from '@papermatch/shared-types';

/** Fetch more when this many cards remain (spec section 25: 次カードを事前取得). */
export const PREFETCH_THRESHOLD = 5;

export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

export interface PendingUndo {
  /** The card to restore. */
  item: FeedItem;
  /** Set once the server has confirmed the action; Undo is disabled until then. */
  actionId: string | null;
  actionType: 'skip' | 'save';
}

export interface DeckState {
  queue: FeedItem[];
  cursor: string | null;
  /** True when the API said this page came from cache (spec section 25). */
  degraded: boolean;
  /** True while a page request is in flight, so the reducer does not launch a second. */
  loading: boolean;
  /** No cursor and nothing left: the deck is genuinely finished, not merely empty. */
  exhausted: boolean;
  pendingUndo: PendingUndo | null;
  /** Impressions recorded but not yet accepted by the server. */
  unsentImpressions: { paperId: string; position: number; dwellMs: number | null }[];
  error: 'offline' | 'failed' | null;
}

export type DeckEvent =
  | { type: 'load_started' }
  | { type: 'page_loaded'; items: FeedItem[]; cursor: string | null; degraded: boolean }
  | { type: 'load_failed'; reason: 'offline' | 'failed' }
  | { type: 'card_acted'; direction: SwipeDirection }
  | { type: 'action_confirmed'; actionId: string }
  | { type: 'undo_applied' }
  | { type: 'undo_dismissed' }
  | { type: 'impression_recorded'; paperId: string; position: number; dwellMs: number | null }
  | { type: 'impressions_flushed'; paperIds: string[] }
  | { type: 'reset' };

export const initialDeckState: DeckState = {
  queue: [],
  cursor: null,
  degraded: false,
  loading: false,
  exhausted: false,
  pendingUndo: null,
  unsentImpressions: [],
  error: null,
};

/** Only left and right remove a card; up opens the source and down shows prerequisites. */
export function isDismissing(direction: SwipeDirection): boolean {
  return direction === 'left' || direction === 'right';
}

export function deckReducer(state: DeckState, event: DeckEvent): DeckState {
  switch (event.type) {
    case 'load_started':
      return { ...state, loading: true, error: null };

    case 'page_loaded': {
      // De-duplicate against what is already queued: a retry or a cursor reset can hand
      // back a card the deck is still holding, and showing it twice is exactly what spec
      // section 16 forbids.
      const present = new Set(state.queue.map((item) => item.paper.canonicalId));
      const fresh = event.items.filter((item) => !present.has(item.paper.canonicalId));
      const queue = [...state.queue, ...fresh];
      return {
        ...state,
        queue,
        cursor: event.cursor,
        degraded: event.degraded,
        loading: false,
        error: null,
        exhausted: event.cursor === null && queue.length === 0,
      };
    }

    case 'load_failed':
      return {
        ...state,
        loading: false,
        // Cards already in hand stay usable; the error only describes the fetch.
        error: event.reason,
      };

    case 'card_acted': {
      const [current, ...rest] = state.queue;
      if (current === undefined) return state;
      if (!isDismissing(event.direction)) return state;
      return {
        ...state,
        queue: rest,
        pendingUndo: {
          item: current,
          actionId: null,
          actionType: event.direction === 'right' ? 'save' : 'skip',
        },
        exhausted: rest.length === 0 && state.cursor === null,
      };
    }

    case 'action_confirmed':
      if (state.pendingUndo === null) return state;
      return { ...state, pendingUndo: { ...state.pendingUndo, actionId: event.actionId } };

    case 'undo_applied': {
      if (state.pendingUndo === null) return state;
      return {
        ...state,
        queue: [state.pendingUndo.item, ...state.queue],
        pendingUndo: null,
        exhausted: false,
      };
    }

    case 'undo_dismissed':
      return { ...state, pendingUndo: null };

    case 'impression_recorded': {
      const existing = state.unsentImpressions.find((i) => i.paperId === event.paperId);
      if (existing !== undefined) {
        // Re-recording the same card can only ever raise its dwell time. When it does not,
        // return the state that came in rather than an equal copy of it: a reducer that
        // hands back a new object for an action that changed nothing turns any effect
        // watching the state into a render loop, which is exactly what happened here.
        const dwell = Math.max(existing.dwellMs ?? 0, event.dwellMs ?? 0);
        if (dwell === (existing.dwellMs ?? 0)) return state;
        return {
          ...state,
          unsentImpressions: state.unsentImpressions.map((i) =>
            i.paperId === event.paperId ? { ...i, dwellMs: dwell } : i,
          ),
        };
      }
      return {
        ...state,
        unsentImpressions: [
          ...state.unsentImpressions,
          { paperId: event.paperId, position: event.position, dwellMs: event.dwellMs },
        ],
      };
    }

    case 'impressions_flushed': {
      const sent = new Set(event.paperIds);
      return {
        ...state,
        unsentImpressions: state.unsentImpressions.filter((i) => !sent.has(i.paperId)),
      };
    }

    case 'reset':
      return initialDeckState;

    default:
      return state;
  }
}

export function currentCard(state: DeckState): FeedItem | null {
  return state.queue[0] ?? null;
}

/** The card rendered behind the current one, so the deck looks like a stack. */
export function nextCard(state: DeckState): FeedItem | null {
  return state.queue[1] ?? null;
}

export function shouldPrefetch(state: DeckState): boolean {
  return (
    !state.loading &&
    state.cursor !== null &&
    state.queue.length <= PREFETCH_THRESHOLD &&
    state.error === null
  );
}
