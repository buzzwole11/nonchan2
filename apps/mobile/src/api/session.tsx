/**
 * Session bootstrap.
 *
 * Spec section 4 puts the first Abstract card before any sign-up, so the app creates a
 * guest account on first launch and keeps using it. The token lives in the platform
 * keystore via `expo-secure-store` (spec section 25: APIキーをクライアントへ置かない — the
 * same reasoning applies to the user's bearer token).
 */
import * as SecureStore from 'expo-secure-store';
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import type { User } from '@papermatch/shared-types';

import { ApiClient, NetworkError } from './client';
import { apiBaseUrl } from './useApi';

const TOKEN_KEY = 'papermatch.accessToken';

export type SessionStatus = 'loading' | 'ready' | 'offline';

interface SessionValue {
  status: SessionStatus;
  user: User | null;
  api: ApiClient;
  /** Re-read /me after a settings or interests change. */
  refreshUser: () => Promise<void>;
  /** Retry the bootstrap after an offline start. */
  retry: () => void;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

/** SecureStore is unavailable on web; fall back to memory so the app still runs there. */
const memoryStore = new Map<string, string>();

async function readToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return memoryStore.get(TOKEN_KEY) ?? null;
  }
}

async function writeToken(token: string | null): Promise<void> {
  try {
    if (token === null) await SecureStore.deleteItemAsync(TOKEN_KEY);
    else await SecureStore.setItemAsync(TOKEN_KEY, token);
  } catch {
    if (token === null) memoryStore.delete(TOKEN_KEY);
    else memoryStore.set(TOKEN_KEY, token);
  }
}

export interface SessionProviderProps {
  children: ReactNode;
  /** Test seam: inject a client instead of building one from config. */
  client?: ApiClient;
}

export function SessionProvider({ children, client }: SessionProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [attempt, setAttempt] = useState(0);

  // The client reads the token through a ref so a refreshed token takes effect without
  // rebuilding the client (and invalidating every react-query cache keyed on it).
  //
  // A ref, not a memoised object: this value is mutated, and mutating something React
  // memoised is how you get a value that silently reverts when React decides to discard
  // the memo.
  //
  // The ref is the only copy. It used to be mirrored into state as well, but nothing
  // rendered from that copy — the UI keys off `status` and `user` — so all it did was
  // re-render the whole tree on every token change.
  const tokenRef = useRef<string | null>(null);

  const api = useMemo(
    // The ref is read inside `getToken`, which the client calls when it builds a request
    // — never during render. The rule flags the closure because it is *constructed* here
    // and cannot see when it is invoked.
    // eslint-disable-next-line react-hooks/refs -- read at request time, not render time
    () => client ?? new ApiClient({ baseUrl: apiBaseUrl(), getToken: () => tokenRef.current }),
    [client],
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrap(): Promise<void> {
      setStatus('loading');
      const stored = await readToken();

      if (stored) {
        tokenRef.current = stored;
        try {
          const existing = await api.me();
          if (cancelled) return;
          setUser(existing);
          setStatus('ready');
          return;
        } catch (error) {
          if (error instanceof NetworkError) {
            // Offline with a token we cannot verify. Keep it — the cached feed is still
            // usable and re-verifying on every launch would make the app unusable on a
            // train (spec section 25).
            if (cancelled) return;
            setStatus('offline');
            return;
          }
          // A rejected token means the account is gone; fall through and make a new guest.
          await writeToken(null);
        }
      }

      try {
        const created = await api.createGuest(
          'ja-JP',
          Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Tokyo',
        );
        if (cancelled) return;
        await writeToken(created.accessToken);
        tokenRef.current = created.accessToken;
        setUser(created.user);
        setStatus('ready');
      } catch {
        if (!cancelled) setStatus('offline');
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [api, attempt]);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      // A failed refresh leaves the previous user in place rather than blanking the UI.
    }
  }, [api]);

  const signOut = useCallback(async () => {
    await writeToken(null);
    tokenRef.current = null;
    setUser(null);
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo(
    () => ({
      status,
      user,
      api,
      refreshUser,
      retry: () => setAttempt((n) => n + 1),
      signOut,
    }),
    [status, user, api, refreshUser, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (context === null) throw new Error('useSession must be used inside a <SessionProvider>');
  return context;
}

export function useApi(): ApiClient {
  return useSession().api;
}
