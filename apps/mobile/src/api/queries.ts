/**
 * Data fetching for the screens that read rather than swipe (spec sections 25, 26).
 *
 * These screens used to fetch in an effect and write the result into three pieces of state
 * — the rows, a loading flag, and an offline flag. React Compiler flags that pattern
 * (`react-hooks/set-state-in-effect`) and it was suppressed a line at a time; this is the
 * actual fix rather than the suppression.
 *
 * **The offline fallback is inside the query function, not around it.** Section 25 requires
 * 外部API失敗時もキャッシュ済みフィードを表示 and section 26 wants saved content readable with
 * no network at all. React Query's cache is in memory, so it is empty the moment the app is
 * killed — which is exactly when someone opens the app on a train. The AsyncStorage cache is
 * what survives that, and it stays where it was.
 *
 * **Offline is part of the data, not a second state.** Returning `{ rows, offline }` from one
 * function means the flag and the rows always came from the same attempt. Kept apart, they
 * can disagree for a render — showing fresh rows under an "offline" banner, or the reverse —
 * and that disagreement is invisible until someone reports it.
 *
 * **A 4xx is not an outage.** `NetworkError` means the request never landed and cached
 * content is the honest answer. Any other failure means the server replied and said no;
 * serving a cache for that would hide a real error behind stale rows.
 */
import { QueryClient } from '@tanstack/react-query';

import type { SavedEntry } from '@papermatch/shared-types';

import { NetworkError } from './client';
import type { ApiClient } from './client';
import { cacheSaved, readCachedSaved } from '../offline/cache';

/** Rows plus how they were obtained, so the two can never disagree. */
export interface Offlineable<T> {
  rows: T;
  offline: boolean;
}

export const queryKeys = {
  saved: (sort: string) => ['saved', sort] as const,
  search: (query: string) => ['search', query] as const,
  canvas: () => ['canvas'] as const,
  expressions: () => ['expressions'] as const,
  review: () => ['review'] as const,
  mathCards: () => ['math-cards'] as const,
  mathCard: (id: string) => ['math-card', id] as const,
};

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A screen that refetches on every focus makes the abstract list flicker for no new
        // information; these lists change when the reader changes them, not on their own.
        refetchOnWindowFocus: false,
        // Retrying a network failure fights the offline fallback: the query function has
        // already substituted cached rows, so a retry would replace them with the same
        // cached rows a second later, having spent the time.
        retry: false,
        staleTime: 30_000,
      },
    },
  });
}

export function savedQuery(api: ApiClient, sort: string) {
  return {
    queryKey: queryKeys.saved(sort),
    queryFn: async (): Promise<Offlineable<{ saved: SavedEntry[]; total: number }>> => {
      try {
        const response = await api.saved({ sort: sort as never, limit: 50 });
        void cacheSaved(response.saved, response.total);
        return { rows: { saved: response.saved, total: response.total }, offline: false };
      } catch (error) {
        if (!(error instanceof NetworkError)) throw error;
        const cached = await readCachedSaved();
        return {
          rows: { saved: cached?.saved ?? [], total: cached?.total ?? 0 },
          offline: true,
        };
      }
    },
  };
}

/**
 * Search the saved library (spec section 24, D-041).
 *
 * There is deliberately **no offline fallback here**, unlike `savedQuery`. Substring
 * matching over the AsyncStorage cache would be easy and would quietly answer a different
 * question: the cache holds one page of one sort order, so an offline search would report
 * "nothing matches" for a paper the reader definitely saved. Saying "search needs a
 * connection" is the honest answer; the cached library is still listed underneath.
 *
 * `enabled` keeps a blank box from making a request. The server also treats blank as "not
 * asked yet" — the check exists in both places because the client one saves a round trip
 * and the server one is the definition.
 */
export function searchQuery(api: ApiClient, query: string) {
  const trimmed = query.trim();
  return {
    queryKey: queryKeys.search(trimmed),
    queryFn: () => api.searchSaved(trimmed),
    enabled: trimmed.length > 0,
  };
}

/**
 * The Canvas plane (spec section 13).
 *
 * No offline fallback: the plane's coordinates are created on the server the first time a
 * paper is placed, so there is nothing meaningful to serve from a cache that has never
 * seen them. Saved is the surface that works without a connection.
 */
export function canvasQuery(api: ApiClient) {
  return {
    queryKey: queryKeys.canvas(),
    queryFn: () => api.canvas(),
  };
}

/** The Learn tab's two lists, fetched together because the screen shows them together. */
export function learnQuery(api: ApiClient) {
  return {
    queryKey: queryKeys.review(),
    queryFn: async () => {
      const [queue, list] = await Promise.all([
        api.reviewQueue(5),
        api.expressions({ limit: 100 }),
      ]);
      return {
        due: queue.due,
        totalDue: queue.totalDue,
        expressions: list.expressions,
        total: list.total,
      };
    },
  };
}

export function mathCardsQuery(api: ApiClient) {
  return {
    queryKey: queryKeys.mathCards(),
    queryFn: async () => (await api.mathCards({ limit: 20 })).cards,
  };
}

export function mathCardQuery(api: ApiClient, id: string) {
  return {
    queryKey: queryKeys.mathCard(id),
    queryFn: () => api.mathCard(id),
    enabled: id !== '',
  };
}
