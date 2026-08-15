/**
 * Wires the deck reducer to the API, the offline cache and the impression log.
 *
 * The reducer holds the rules; this holds the effects. Keeping them apart is what lets
 * `deck.test.ts` cover the awkward cases (undo before the server confirms, a failed page
 * with cards still in hand) without a network.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

import type { FeedItem, MathCardTeaser, SaveReason } from '@papermatch/shared-types';

import { NetworkError } from '../api/client';
import { useSession } from '../api/session';
import { cacheFeed, readCachedFeed } from '../offline/cache';
import {
  type DeckState,
  type SwipeDirection,
  currentCard,
  deckReducer,
  initialDeckState,
  nextCard,
  shouldPrefetch,
} from './deck';
import { type FeedbackControl, feedbackRequest, needsReload } from './feedback';

const PAGE_SIZE = 20;

export interface DeckController {
  state: DeckState;
  current: FeedItem | null;
  next: FeedItem | null;
  /** Left or right; returns once the action has been sent (or has failed offline). */
  act: (direction: SwipeDirection, reasons?: SaveReason[]) => Promise<void>;
  /** Replace the tags on an already-saved paper (spec section 9: 任意タグ). */
  setSaveReasons: (paperId: string, reasons: SaveReason[]) => Promise<boolean>;
  undo: () => Promise<void>;
  dismissUndo: () => void;
  /** Called when a card becomes visible, and again with dwell when it leaves. */
  noteImpression: (paperId: string, position: number, dwellMs?: number) => void;
  reload: () => void;
  /**
   * Send one of section 16's five feed controls. Resolves to the action id so the caller
   * can offer Undo, or to null when the request could not be sent.
   */
  sendFeedback: (control: FeedbackControl) => Promise<string | null>;
  /**
   * A maths card offered with the first page, or null — null most of the time by design
   * (spec section 10: 低頻度). Rendered beside the deck, never as a card in it.
   */
  mathCardTeaser: MathCardTeaser | null;
  dismissMathCardTeaser: () => void;
}

export function useDeck(): DeckController {
  const { api } = useSession();
  const [state, dispatch] = useReducer(deckReducer, initialDeckState);
  // The async callbacks below (the impression flush timer, `act`, `undo`) all run after
  // a commit and need the *latest* deck state, not the state captured when the callback
  // was created. The ref is updated in an effect rather than during render: a render can
  // be thrown away, and a ref written by a discarded render would leave these callbacks
  // acting on a deck the user never saw.
  //
  // Declared before the effects that read it, so it is already current when they run.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const loadPage = useCallback(
    async (cursor: string | null, { allowCache }: { allowCache: boolean }) => {
      dispatch({ type: 'load_started' });
      try {
        const page = await api.feed({ limit: PAGE_SIZE, cursor: cursor ?? undefined });
        dispatch({
          type: 'page_loaded',
          items: page.items,
          cursor: page.nextCursor,
          degraded: page.degraded,
          // The server has already recorded the offer, so it is shown rather than saved
          // for later — held back it would just expire inside the cooldown. Later pages
          // pass undefined and leave the current offer alone.
          mathCard: cursor === null ? page.mathCard : undefined,
        });
        // Only the first page is worth caching: it is what a cold offline start shows.
        if (cursor === null) void cacheFeed(page.items, page.nextCursor);
      } catch (error) {
        if (error instanceof NetworkError && allowCache) {
          const cached = await readCachedFeed();
          if (cached && cached.items.length > 0) {
            dispatch({
              type: 'page_loaded',
              items: cached.items,
              cursor: cached.cursor,
              // Cached content is degraded by definition; the UI says so.
              degraded: true,
            });
            return;
          }
        }
        dispatch({
          type: 'load_failed',
          reason: error instanceof NetworkError ? 'offline' : 'failed',
        });
      }
    },
    [api],
  );

  useEffect(() => {
    void loadPage(null, { allowCache: true });
  }, [loadPage]);

  // Top up before the deck runs dry rather than when it does.
  useEffect(() => {
    if (shouldPrefetch(state)) {
      void loadPage(state.cursor, { allowCache: false });
    }
  }, [state, loadPage]);

  // Impressions are batched: one request per card would be a request per swipe.
  useEffect(() => {
    if (state.unsentImpressions.length === 0) return undefined;
    const timer = setTimeout(() => {
      const batch = stateRef.current.unsentImpressions;
      if (batch.length === 0) return;
      void api
        .recordImpressions({
          impressions: batch.map((i) => ({
            paperId: i.paperId,
            position: i.position,
            dwellMs: i.dwellMs,
          })),
        })
        .then(() => {
          dispatch({ type: 'impressions_flushed', paperIds: batch.map((i) => i.paperId) });
        })
        .catch(() => {
          // Left in the queue. An impression that never arrives means a card the user
          // already saw comes back, so it is retried rather than dropped.
        });
    }, 1200);
    return () => clearTimeout(timer);
  }, [state.unsentImpressions, api]);

  const act = useCallback(
    async (direction: SwipeDirection, reasons?: SaveReason[]) => {
      const card = currentCard(stateRef.current);
      if (card === null) return;

      dispatch({ type: 'card_acted', direction });
      if (direction !== 'left' && direction !== 'right') return;

      try {
        const response = await api.recordAction({
          type: direction === 'right' ? 'save' : 'skip',
          paperId: card.paper.id,
          payload: reasons && reasons.length > 0 ? { reasons } : {},
        });
        dispatch({ type: 'action_confirmed', actionId: response.action.id });
      } catch {
        // The card stays off the deck and the Undo control stays disabled, because there
        // is no server-side action to reverse. Reloading brings the card back.
      }
    },
    [api],
  );

  const setSaveReasons = useCallback(
    async (paperId: string, reasons: SaveReason[]) => {
      try {
        await api.updateSaved(paperId, { reasons });
        return true;
      } catch {
        // The paper stays saved with whatever it had; only the tag failed to stick. The
        // caller says so rather than leaving a chip looking selected when it is not.
        return false;
      }
    },
    [api],
  );

  const undo = useCallback(async () => {
    const pending = stateRef.current.pendingUndo;
    if (pending === null || pending.actionId === null) return;
    try {
      await api.undoAction(pending.actionId);
      dispatch({ type: 'undo_applied' });
    } catch {
      // Leave the toast up so the user can try again rather than silently losing the card.
    }
  }, [api]);

  const dismissUndo = useCallback(() => dispatch({ type: 'undo_dismissed' }), []);

  const noteImpression = useCallback((paperId: string, position: number, dwellMs?: number) => {
    dispatch({ type: 'impression_recorded', paperId, position, dwellMs: dwellMs ?? null });
  }, []);

  const reload = useCallback(() => {
    dispatch({ type: 'reset' });
    void loadPage(null, { allowCache: true });
  }, [loadPage]);

  const sendFeedback = useCallback(
    async (control: FeedbackControl): Promise<string | null> => {
      const request = feedbackRequest(control, currentCard(stateRef.current));
      if (request === null) return null;
      try {
        const response = await api.recordAction(request);
        if (needsReload(control.kind)) {
          // `hide_topic` and `hide_author` remove candidates, so the deck in hand is now
          // partly made of exactly what the reader asked to see less of. Rebuilding it is
          // the only way the request takes effect on cards already fetched.
          dispatch({ type: 'reset' });
          void loadPage(null, { allowCache: false });
        }
        return response.action.id;
      } catch {
        // Reported by the caller rather than swallowed: a control that silently fails is
        // one the reader keeps pressing.
        return null;
      }
    },
    [api, loadPage],
  );

  // Memoised, because a screen that lists this object in an effect's dependencies would
  // otherwise re-run that effect on every render — and the effect on the Discover screen
  // records an impression, so it dispatched, re-rendered, and dispatched again.
  return useMemo(
    () => ({
      state,
      current: currentCard(state),
      next: nextCard(state),
      mathCardTeaser: state.mathCardTeaser,
      dismissMathCardTeaser: () => dispatch({ type: 'math_teaser_dismissed' }),
      act,
      setSaveReasons,
      undo,
      dismissUndo,
      noteImpression,
      reload,
      sendFeedback,
    }),
    [state, act, setSaveReasons, undo, dismissUndo, noteImpression, reload, sendFeedback],
  );
}
