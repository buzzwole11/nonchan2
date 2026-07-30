import type { FeedItem } from '@papermatch/shared-types';

import {
  type DeckState,
  currentCard,
  deckReducer,
  initialDeckState,
  isDismissing,
  nextCard,
  shouldPrefetch,
} from '../src/discover/deck';

function card(id: string): FeedItem {
  return {
    paper: { id, canonicalId: `doi:10.1/${id}`, title: `Paper ${id}` },
    reasons: ['matches_field'],
    reasonText: '選んだ分野に一致します。',
    position: 0,
    pool: 'matched',
    scoreBreakdown: {},
  } as unknown as FeedItem;
}

function loaded(ids: string[], cursor: string | null = '1:20'): DeckState {
  return deckReducer(initialDeckState, {
    type: 'page_loaded',
    items: ids.map(card),
    cursor,
    degraded: false,
  });
}

describe('loading', () => {
  it('appends a page and keeps the cursor', () => {
    const state = loaded(['a', 'b']);
    expect(state.queue).toHaveLength(2);
    expect(state.cursor).toBe('1:20');
    expect(state.loading).toBe(false);
    expect(state.exhausted).toBe(false);
  });

  it('never queues the same paper twice', () => {
    const first = loaded(['a', 'b']);
    const second = deckReducer(first, {
      type: 'page_loaded',
      items: [card('b'), card('c')],
      cursor: null,
      degraded: false,
    });
    expect(second.queue.map((i) => i.paper.id)).toEqual(['a', 'b', 'c']);
  });

  it('is exhausted only when there is no cursor and no cards', () => {
    expect(loaded([], null).exhausted).toBe(true);
    expect(loaded([], '1:20').exhausted).toBe(false);
    expect(loaded(['a'], null).exhausted).toBe(false);
  });

  it('keeps the cards in hand when a page fails', () => {
    const state = deckReducer(loaded(['a', 'b']), { type: 'load_failed', reason: 'offline' });
    expect(state.queue).toHaveLength(2);
    expect(state.error).toBe('offline');
    expect(state.loading).toBe(false);
  });

  it('prefetches before the deck runs dry, and not while a request is in flight', () => {
    expect(shouldPrefetch(loaded(['a', 'b']))).toBe(true);
    expect(shouldPrefetch(loaded(['a', 'b', 'c', 'd', 'e', 'f', 'g']))).toBe(false);
    expect(shouldPrefetch(loaded(['a'], null))).toBe(false);
    expect(shouldPrefetch({ ...loaded(['a']), loading: true })).toBe(false);
    expect(shouldPrefetch({ ...loaded(['a']), error: 'offline' })).toBe(false);
  });
});

describe('acting on a card', () => {
  it('removes the current card and remembers it for undo', () => {
    const state = deckReducer(loaded(['a', 'b']), { type: 'card_acted', direction: 'right' });
    expect(state.queue.map((i) => i.paper.id)).toEqual(['b']);
    expect(state.pendingUndo?.item.paper.id).toBe('a');
    expect(state.pendingUndo?.actionType).toBe('save');
    expect(state.pendingUndo?.actionId).toBeNull();
  });

  it('treats a left swipe as a skip', () => {
    const state = deckReducer(loaded(['a']), { type: 'card_acted', direction: 'left' });
    expect(state.pendingUndo?.actionType).toBe('skip');
  });

  it('leaves the deck alone for up and down', () => {
    expect(isDismissing('up')).toBe(false);
    expect(isDismissing('down')).toBe(false);
    const state = deckReducer(loaded(['a', 'b']), { type: 'card_acted', direction: 'up' });
    expect(state.queue).toHaveLength(2);
    expect(state.pendingUndo).toBeNull();
  });

  it('does nothing when the deck is empty', () => {
    const empty = loaded([], null);
    expect(deckReducer(empty, { type: 'card_acted', direction: 'left' })).toBe(empty);
  });
});

describe('undo', () => {
  it('is not offered until the server confirms the action', () => {
    const acted = deckReducer(loaded(['a', 'b']), { type: 'card_acted', direction: 'left' });
    expect(acted.pendingUndo?.actionId).toBeNull();

    const confirmed = deckReducer(acted, { type: 'action_confirmed', actionId: 'act-1' });
    expect(confirmed.pendingUndo?.actionId).toBe('act-1');
  });

  it('puts the exact card back at the front of the deck', () => {
    let state = loaded(['a', 'b', 'c']);
    state = deckReducer(state, { type: 'card_acted', direction: 'left' });
    state = deckReducer(state, { type: 'action_confirmed', actionId: 'act-1' });
    state = deckReducer(state, { type: 'undo_applied' });

    expect(state.queue.map((i) => i.paper.id)).toEqual(['a', 'b', 'c']);
    expect(state.pendingUndo).toBeNull();
  });

  it('un-exhausts a deck that emptied on the last card', () => {
    let state = loaded(['a'], null);
    state = deckReducer(state, { type: 'card_acted', direction: 'right' });
    expect(state.exhausted).toBe(true);

    state = deckReducer(state, { type: 'undo_applied' });
    expect(state.exhausted).toBe(false);
    expect(currentCard(state)?.paper.id).toBe('a');
  });

  it('dismissing drops the offer without restoring the card', () => {
    let state = deckReducer(loaded(['a', 'b']), { type: 'card_acted', direction: 'left' });
    state = deckReducer(state, { type: 'undo_dismissed' });
    expect(state.pendingUndo).toBeNull();
    expect(state.queue.map((i) => i.paper.id)).toEqual(['b']);
  });
});

describe('impressions', () => {
  it('queues one entry per paper', () => {
    let state = loaded(['a', 'b']);
    state = deckReducer(state, {
      type: 'impression_recorded',
      paperId: 'a',
      position: 0,
      dwellMs: null,
    });
    state = deckReducer(state, {
      type: 'impression_recorded',
      paperId: 'b',
      position: 1,
      dwellMs: 900,
    });
    expect(state.unsentImpressions).toHaveLength(2);
  });

  it('keeps the longest dwell rather than adding a second entry', () => {
    let state = loaded(['a']);
    state = deckReducer(state, {
      type: 'impression_recorded',
      paperId: 'a',
      position: 0,
      dwellMs: 500,
    });
    state = deckReducer(state, {
      type: 'impression_recorded',
      paperId: 'a',
      position: 0,
      dwellMs: 9000,
    });
    expect(state.unsentImpressions).toHaveLength(1);
    expect(state.unsentImpressions[0]?.dwellMs).toBe(9000);
  });

  it('retains impressions that were not flushed, so a shown card cannot return', () => {
    let state = loaded(['a', 'b']);
    for (const paperId of ['a', 'b']) {
      state = deckReducer(state, {
        type: 'impression_recorded',
        paperId,
        position: 0,
        dwellMs: null,
      });
    }
    state = deckReducer(state, { type: 'impressions_flushed', paperIds: ['a'] });
    expect(state.unsentImpressions.map((i) => i.paperId)).toEqual(['b']);
  });
});

describe('accessors', () => {
  it('expose the top two cards for the stacked look', () => {
    const state = loaded(['a', 'b', 'c']);
    expect(currentCard(state)?.paper.id).toBe('a');
    expect(nextCard(state)?.paper.id).toBe('b');
    expect(currentCard(initialDeckState)).toBeNull();
    expect(nextCard(initialDeckState)).toBeNull();
  });
});
