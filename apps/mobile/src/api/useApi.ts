import Constants from 'expo-constants';
import { Platform } from 'react-native';

/** The port `make api` serves on. The dev server's host is discovered; its port is not. */
const API_PORT = 8000;

/**
 * The host Expo is serving this bundle from, e.g. `192.168.1.23`.
 *
 * `hostUri` is the current field; `debuggerHost` is what older Expo Go builds set; on the
 * web neither exists and the page's own address says the same thing. All three are absent
 * or irrelevant in a released native build, which is the point — a shipped app must never
 * derive its backend from whatever machine handed it the JavaScript.
 */
function devServerHost(): string | undefined {
  const raw =
    Constants.expoConfig?.hostUri ??
    (Constants.expoGoConfig as { debuggerHost?: string } | undefined)?.debuggerHost ??
    // A browser gets no manifest, so neither field is set — checked, not assumed, by
    // reading them from a page the dev server had just served. The address bar carries the
    // same information: the machine that served this page is the machine running the API.
    // It matters when the browser is on a phone; on the developer's own machine it says
    // localhost and nothing changes. Expo's static render runs this on the server, where
    // there is no address bar, so the first paint falls back to localhost and hydration
    // corrects it — visible in the dev banner, and over before any request is made.
    (Platform.OS === 'web' ? globalThis.location?.host : undefined);
  if (typeof raw !== 'string' || raw.length === 0) return undefined;

  // `exp://192.168.1.23:8081/--/path` → `192.168.1.23:8081` → `192.168.1.23`.
  const withoutScheme = raw.replace(/^[a-z+]+:\/\//i, '');
  const authority = withoutScheme.split('/')[0] ?? '';
  // An IPv6 literal keeps its brackets; the colons inside it are not a port separator.
  if (authority.startsWith('[')) {
    const close = authority.indexOf(']');
    return close > 0 ? authority.slice(0, close + 1) : undefined;
  }
  const host = authority.split(':')[0] ?? '';
  return host.length > 0 ? host : undefined;
}

/**
 * Where the app talks to its API.
 *
 * `expo.extra.apiBaseUrl` wins when it is set — that is how a build points at staging or
 * production. With nothing configured we follow the Expo dev server's host, because in
 * development the API is on the same machine that is serving the bundle. That matters on a
 * real phone: a hardcoded `localhost` there means the phone itself, so the app waits on a
 * server that is on the developer's desk, and the failure looks like an empty feed rather
 * than a wrong address. Deriving the host removes the edit that every developer had to make
 * by hand, and undo before committing.
 *
 * The fallback stays `localhost` for the cases with no host to ask: a native build with no
 * dev server behind it, and the unit tests.
 *
 * One case this cannot rescue: `expo start --tunnel` reports a public hostname that proxies
 * only Metro's port, so port 8000 there belongs to no one. Tunnel users still set
 * `extra.apiBaseUrl` (or tunnel the API too). The dev banner on the entry screen prints the
 * address the app settled on, so a wrong guess is visible instead of silent.
 */
export function apiBaseUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiBaseUrl;
  if (typeof configured === 'string' && configured.length > 0) return configured;

  const host = devServerHost();
  return host !== undefined ? `http://${host}:${API_PORT}` : `http://localhost:${API_PORT}`;
}

// `useApiClient` and `setAuthToken` used to live here — Phase 0's in-memory token, kept
// "so the accessor shape would not change" when D-007 moved auth into the session. Nothing
// ever called `setAuthToken` again, so the hook handed out a client that could only make
// unauthenticated requests, and the one component still using it showed its failure state
// on every open. A dead path that looks like a live one is worse than no path: deleted.
