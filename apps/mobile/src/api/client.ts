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
  ActionResponse,
  AuthTokenResponse,
  CanvasResponse,
  CreateActionRequest,
  CreateExpressionRequest,
  CreateImpressionsRequest,
  CreateImpressionsResponse,
  CreateTranslationRequest,
  CreateTranslationResponse,
  ExpressionListResponse,
  ExpressionResponse,
  FeedResponse,
  FieldsResponse,
  HealthResponse,
  Interest,
  MathCardDetailResponse,
  MathCardListResponse,
  PaperListResponse,
  ReportRequest,
  ReportResponse,
  ReviewOutcome,
  ReviewQueueResponse,
  SavePaperRequest,
  SavedListQuery,
  MoveTileRequest,
  SavedListResponse,
  SavedPaperResponse,
  PaperRelationsResponse,
  SearchResponse,
  UndoResponse,
  UpdateSavedRequest,
  User,
  UserSettings,
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
    // Bound to the global object, not stored bare. Assigning `fetch` to a property and
    // calling it as `this.fetchImpl(...)` binds `this` to the client, which browsers
    // reject with "Illegal invocation" — and because that TypeError is thrown from inside
    // the request's try block, it surfaced to users as "offline" on every single call.
    this.fetchImpl = options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
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
      const error = (
        payload as {
          error?: { code?: string; message?: string; details?: Record<string, string[]> };
        }
      )?.error;
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

  papers(
    params: { limit?: number; cursor?: string; fieldId?: string } = {},
  ): Promise<PaperListResponse> {
    return this.request<PaperListResponse>('/papers', {
      query: { limit: params.limit, cursor: params.cursor, field_id: params.fieldId },
    });
  }

  updateSettings(settings: Partial<UserSettings>): Promise<User> {
    return this.request<User>('/me/settings', { method: 'PATCH', body: settings });
  }

  updateInterests(interests: Interest[]): Promise<User> {
    return this.request<User>('/me/interests', { method: 'PUT', body: { interests } });
  }

  // -- discover ------------------------------------------------------------------

  feed(params: { limit?: number; cursor?: string } = {}): Promise<FeedResponse> {
    return this.request<FeedResponse>('/feed', {
      query: { mode: 'discover', limit: params.limit, cursor: params.cursor },
    });
  }

  /**
   * Report that cards reached the screen. Fire-and-forget from the caller's point of
   * view, but the promise is returned so an offline queue can retry it — a lost
   * impression means a card the user already saw comes back (spec section 16).
   */
  recordImpressions(body: CreateImpressionsRequest): Promise<CreateImpressionsResponse> {
    return this.request<CreateImpressionsResponse>('/impressions', {
      method: 'POST',
      body,
    });
  }

  recordAction(body: CreateActionRequest): Promise<ActionResponse> {
    return this.request<ActionResponse>('/actions', { method: 'POST', body });
  }

  undoAction(actionId: string): Promise<UndoResponse> {
    return this.request<UndoResponse>(`/actions/${actionId}/undo`, { method: 'POST' });
  }

  /** What the Undo control would reverse, or null when there is nothing to undo. */
  undoableAction(): Promise<ActionResponse | null> {
    return this.request<ActionResponse | null>('/actions/undoable');
  }

  /**
   * Translate one selected span (spec section 7).
   *
   * The API enforces that this is a selection and not a document, refuses a span that
   * cuts through a formula, and refuses text whose licence does not permit sending it to
   * a provider — so those arrive here as `ApiError`s with codes the sheet turns into
   * sentences, not as silent failures.
   */
  translate(body: CreateTranslationRequest): Promise<CreateTranslationResponse> {
    return this.request<CreateTranslationResponse>('/translations', { method: 'POST', body });
  }

  /** Report that something on a maths card looks wrong (spec sections 12, 27). */
  reportMathCard(cardId: string, body: ReportRequest): Promise<ReportResponse> {
    return this.request<ReportResponse>(`/math-cards/${cardId}/feedback`, {
      method: 'POST',
      body,
    });
  }

  // -- saved ---------------------------------------------------------------------

  saved(query: SavedListQuery = {}): Promise<SavedListResponse> {
    return this.request<SavedListResponse>('/saved', {
      query: {
        status: query.status,
        reason: query.reason,
        fieldId: query.fieldId,
        sort: query.sort,
        limit: query.limit,
        cursor: query.cursor,
      },
    });
  }

  /**
   * Search the saved library (spec section 24) — not the corpus; see D-041.
   *
   * A blank query is sent rather than short-circuited on the client so that "not typed yet"
   * has one definition, on the server, instead of two that can drift apart.
   */
  searchSaved(query: string, limit = 30): Promise<SearchResponse> {
    return this.request<SearchResponse>('/search', { query: { q: query, limit } });
  }

  /**
   * How a paper sits among the reader's library (spec section 17).
   *
   * Authenticated, and deliberately so: the candidates start from the reader's own saved
   * papers, so two readers looking at the same paper see relations to *their* libraries.
   */
  paperRelations(paperId: string): Promise<PaperRelationsResponse> {
    return this.request<PaperRelationsResponse>(`/papers/${paperId}/relations`);
  }

  // -- canvas (spec section 13) --------------------------------------------------

  canvas(limit = 500): Promise<CanvasResponse> {
    return this.request<CanvasResponse>('/canvas', { query: { limit } });
  }

  /** Record where the reader put a tile. Returns the whole plane, already updated. */
  moveTile(paperId: string, body: MoveTileRequest): Promise<CanvasResponse> {
    return this.request<CanvasResponse>(`/canvas/${paperId}`, { method: 'PATCH', body });
  }

  savePaper(paperId: string, body: SavePaperRequest = {}): Promise<SavedPaperResponse> {
    return this.request<SavedPaperResponse>(`/saved/${paperId}`, { method: 'POST', body });
  }

  updateSaved(paperId: string, body: UpdateSavedRequest): Promise<SavedPaperResponse> {
    return this.request<SavedPaperResponse>(`/saved/${paperId}`, { method: 'PATCH', body });
  }

  removeSaved(paperId: string): Promise<void> {
    return this.request<void>(`/saved/${paperId}`, { method: 'DELETE' });
  }

  // -- maths ---------------------------------------------------------------------

  mathCards(query: { cardType?: string; limit?: number } = {}): Promise<MathCardListResponse> {
    return this.request<MathCardListResponse>('/math-cards', {
      query: { cardType: query.cardType, limit: query.limit },
    });
  }

  /**
   * One card with everything Focus Mode needs.
   *
   * `includeUnverified` is left off: spec section 12 hides transformations that passed no
   * check, and the response says how many were withheld so the screen can be honest about
   * the derivation being incomplete rather than silently short.
   */
  mathCard(cardId: string): Promise<MathCardDetailResponse> {
    return this.request<MathCardDetailResponse>(`/math-cards/${cardId}`);
  }

  // -- learn ---------------------------------------------------------------------

  saveExpression(body: CreateExpressionRequest): Promise<ExpressionResponse> {
    return this.request<ExpressionResponse>('/expressions', { method: 'POST', body });
  }

  expressions(
    params: { kind?: string; limit?: number; cursor?: string } = {},
  ): Promise<ExpressionListResponse> {
    return this.request<ExpressionListResponse>('/expressions', {
      query: { kind: params.kind, limit: params.limit, cursor: params.cursor },
    });
  }

  removeExpression(expressionId: string): Promise<void> {
    return this.request<void>(`/expressions/${expressionId}`, { method: 'DELETE' });
  }

  /** What is ready to be seen again (spec section 9: a nudge, not a backlog). */
  reviewQueue(limit = 5): Promise<ReviewQueueResponse> {
    return this.request<ReviewQueueResponse>('/learn/review', { query: { limit } });
  }

  submitReview(expressionId: string, outcome: ReviewOutcome): Promise<ExpressionResponse> {
    return this.request<ExpressionResponse>(`/learn/review/${expressionId}`, {
      method: 'POST',
      body: { outcome },
    });
  }
}
