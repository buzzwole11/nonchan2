import Constants from 'expo-constants';

/** Base URL from `app.json` → `expo.extra.apiBaseUrl`, overridable per environment. */
export function apiBaseUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiBaseUrl;
  return typeof configured === 'string' && configured.length > 0
    ? configured
    : 'http://localhost:8000';
}

// `useApiClient` and `setAuthToken` used to live here — Phase 0's in-memory token, kept
// "so the accessor shape would not change" when D-007 moved auth into the session. Nothing
// ever called `setAuthToken` again, so the hook handed out a client that could only make
// unauthenticated requests, and the one component still using it showed its failure state
// on every open. A dead path that looks like a live one is worse than no path: deleted.
