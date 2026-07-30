import Constants from 'expo-constants';
import { useMemo } from 'react';

import { ApiClient } from './client';

/** Base URL from `app.json` → `expo.extra.apiBaseUrl`, overridable per environment. */
export function apiBaseUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiBaseUrl;
  return typeof configured === 'string' && configured.length > 0
    ? configured
    : 'http://localhost:8000';
}

let inMemoryToken: string | null = null;

/**
 * Phase 0 keeps the guest token in memory only. Phase 1 moves it into
 * `expo-secure-store`; the accessor shape does not change (spec section 25: keys and
 * tokens are never written somewhere the client cannot protect).
 */
export function setAuthToken(token: string | null): void {
  inMemoryToken = token;
}

export function useApiClient(): ApiClient {
  return useMemo(() => new ApiClient({ baseUrl: apiBaseUrl(), getToken: () => inMemoryToken }), []);
}
