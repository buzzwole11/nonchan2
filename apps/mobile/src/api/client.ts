/**
 * Typed API client.
 *
 * Request and response shapes come from `@papermatch/shared-types`, which the API also
 * mirrors — so a field renamed on the server breaks the client at compile time rather
 * than at runtime in front of a user.
 *
 * Spec section 25 requires the app to stay usable when the API is not: every call
 * distinguishes a *transport* failure (offline, timeout — the caller should fall back to
 * cache) from an *API* failure (a 4xx the caller must handle).
 */
import type {
  AuthTokenResponse,
  FieldsResponse,
  HealthResponse,
  PaperListResponse,
  User,
} from '@papermatch/shared-types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, string[]>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** The network could not be reached. Callers serve cached content instead. */
export class NetworkError extends Error {
  constructor(readonly cause: unknown) {
    super('The API could not be reached');
    this.name = 'NetworkError';
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns the current bearer token, or null while signed out. */
  getToken?: () => string | null;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getToken: () => string | null;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.getToken = options.getToken ?? (() => null);
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private url(path: string, query?: RequestOptions['query']): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) search.set(key, String(value));
    }
    const suffix = search.toString();
    return `${this.baseUrl}${path}${suffix ? `?${suffix}` : ''}`;
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    options.signal?.addEventListener('abort', () => controller.abort());

    const token = this.getToken();
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;

    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path, options.query), {
        method: options.method ?? 'GET',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (cause) {
      throw new NetworkError(cause);
    } finally {
      clearTimeout(timeout);
    }

    if (response.status === 204) return undefined as T;

    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const error = (payload as { error?: { code?: string; message?: string; details?: Record<string, string[]> } })?.error;
      throw new ApiError(
        response.status,
        error?.code ?? `http_${response.status}`,
        error?.message ?? response.statusText,
        error?.details,
      );
    }

    return payload as T;
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health');
  }

  createGuest(locale: string, timezone: string): Promise<AuthTokenResponse> {
    return this.request<AuthTokenResponse>('/auth/guest', {
      method: 'POST',
      body: { locale, timezone },
    });
  }

  me(): Promise<User> {
    return this.request<User>('/me');
  }

  fields(): Promise<FieldsResponse> {
    return this.request<FieldsResponse>('/fields');
  }

  papers(params: { limit?: number; cursor?: string; fieldId?: string } = {}): Promise<PaperListResponse> {
    return this.request<PaperListResponse>('/papers', {
      query: { limit: params.limit, cursor: params.cursor, field_id: params.fieldId },
    });
  }
}
