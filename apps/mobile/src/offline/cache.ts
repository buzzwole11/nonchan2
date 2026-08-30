/**
 * Offline cache (spec sections 25, 26, 29).
 *
 * Section 26 asks for the next 20 cards and the saved abstracts to be available offline,
 * and section 29 makes "API障害時にキャッシュ済みカードを表示" a completion criterion. This
 * is deliberately a small, explicit store rather than a general query-cache persister: the
 * only things worth surviving a cold start are the deck and the library, and keeping the
 * list short means it is obvious what is written to disk (spec section 25, privacy).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { FeedItem, SavedEntry } from '@papermatch/shared-types';

const FEED_KEY = 'papermatch.cache.feed.v1';
const SAVED_KEY = 'papermatch.cache.saved.v1';

/** Matches the default of `UserSettings.offlinePrefetchCount` (spec section 26). */
export const DEFAULT_OFFLINE_COUNT = 20;

interface CachedFeed {
  items: FeedItem[];
  cursor: string | null;
  storedAt: string;
}

interface CachedSaved {
  saved: SavedEntry[];
  total: number;
  storedAt: string;
}

async function readJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    // A corrupt or unreadable cache is not an error the user should see; the app simply
    // has nothing cached.
    return null;
  }
}

async function writeJson(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Out of space or storage unavailable. Losing the cache degrades offline use; it must
    // never break the session that is working right now.
  }
}

export async function cacheFeed(
  items: FeedItem[],
  cursor: string | null,
  limit = DEFAULT_OFFLINE_COUNT,
): Promise<void> {
  await writeJson(FEED_KEY, {
    items: items.slice(0, limit),
    cursor,
    storedAt: new Date().toISOString(),
  } satisfies CachedFeed);
}

export async function readCachedFeed(): Promise<CachedFeed | null> {
  return readJson<CachedFeed>(FEED_KEY);
}

export async function cacheSaved(saved: SavedEntry[], total: number): Promise<void> {
  await writeJson(SAVED_KEY, {
    saved,
    total,
    storedAt: new Date().toISOString(),
  } satisfies CachedSaved);
}

export async function readCachedSaved(): Promise<CachedSaved | null> {
  return readJson<CachedSaved>(SAVED_KEY);
}

/** Spec section 25: the user can delete their data, and that includes what is on device. */
export async function clearCache(): Promise<void> {
  try {
    await AsyncStorage.multiRemove([FEED_KEY, SAVED_KEY]);
  } catch {
    // Nothing to do; the keys were already unreachable.
  }
}
