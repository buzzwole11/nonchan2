import { ApiClient, ApiError, NetworkError } from '../src/api/client';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `status ${status}`,
    json: async () => body,
  } as unknown as Response;
}

describe('ApiClient', () => {
  it('sends the bearer token when one is available', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      getToken: () => 'token-123',
      fetchImpl: async (url, init) => {
        calls.push({ url: String(url), init: init as RequestInit });
        return jsonResponse(200, { status: 'ok' });
      },
    });

    await client.health();

    expect(calls[0]?.url).toBe('http://api.test/health');
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer token-123');
  });

  it('omits the Authorization header while signed out', async () => {
    let headers: Record<string, string> = {};
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (_url, init) => {
        headers = (init as RequestInit).headers as Record<string, string>;
        return jsonResponse(200, {});
      },
    });

    await client.health();
    expect(headers.Authorization).toBeUndefined();
  });

  it('strips trailing slashes from the base URL', async () => {
    let url = '';
    const client = new ApiClient({
      baseUrl: 'http://api.test///',
      fetchImpl: async (requested) => {
        url = String(requested);
        return jsonResponse(200, {});
      },
    });
    await client.health();
    expect(url).toBe('http://api.test/health');
  });

  it('serialises query parameters and drops undefined ones', async () => {
    let url = '';
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (requested) => {
        url = String(requested);
        return jsonResponse(200, { papers: [], nextCursor: null });
      },
    });

    await client.papers({ limit: 20, fieldId: 'hep-th' });
    expect(url).toContain('limit=20');
    expect(url).toContain('field_id=hep-th');
    expect(url).not.toContain('cursor=');
  });

  it('turns a structured API error into an ApiError with its code', async () => {
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () =>
        jsonResponse(422, {
          error: { code: 'unknown_field_ids', message: 'nope', details: { fieldIds: ['x'] } },
        }),
    });

    await expect(client.fields()).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      code: 'unknown_field_ids',
    });
  });

  it('still produces an ApiError when the body is not the expected shape', async () => {
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () => jsonResponse(500, 'not json at all'),
    });

    await expect(client.fields()).rejects.toBeInstanceOf(ApiError);
  });

  it('reports a transport failure as NetworkError so callers can fall back to cache', async () => {
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () => {
        throw new TypeError('Failed to fetch');
      },
    });

    await expect(client.health()).rejects.toBeInstanceOf(NetworkError);
  });

  it('calls the global fetch with the right receiver', async () => {
    // A browser's `fetch` throws "Illegal invocation" when called with `this` set to
    // anything but the global object. Storing it bare on the instance and calling
    // `this.fetchImpl(...)` did exactly that, and the resulting TypeError was reported to
    // the user as being offline.
    const strictFetch = function (this: unknown) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError('Illegal invocation');
      }
      return Promise.resolve(jsonResponse(200, { status: 'ok' }));
    } as unknown as typeof fetch;

    const original = globalThis.fetch;
    globalThis.fetch = strictFetch;
    try {
      const client = new ApiClient({ baseUrl: 'http://api.test' });
      await expect(client.health()).resolves.toEqual({ status: 'ok' });
    } finally {
      globalThis.fetch = original;
    }
  });

  it('asks the feed for the discover mode explicitly', async () => {
    let url = '';
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (requested) => {
        url = String(requested);
        return jsonResponse(200, { items: [], nextCursor: null, degraded: false });
      },
    });

    await client.feed({ limit: 20 });
    expect(url).toContain('mode=discover');
    expect(url).toContain('limit=20');
  });

  it('posts impressions as a batch', async () => {
    let body: unknown;
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (_url, init) => {
        body = JSON.parse((init as RequestInit).body as string);
        return jsonResponse(201, { recorded: 2 });
      },
    });

    const result = await client.recordImpressions({
      impressions: [{ paperId: 'a', position: 0 }, { paperId: 'b', position: 1, dwellMs: 4200 }],
    });

    expect(result.recorded).toBe(2);
    expect(body).toEqual({
      impressions: [{ paperId: 'a', position: 0 }, { paperId: 'b', position: 1, dwellMs: 4200 }],
    });
  });

  it('undoes by action id', async () => {
    let url = '';
    let method = '';
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (requested, init) => {
        url = String(requested);
        method = (init as RequestInit).method ?? 'GET';
        return jsonResponse(201, {
          undo: { id: 'u1', type: 'undo' },
          undoneActionId: 'a1',
          restoredPaperId: 'p1',
        });
      },
    });

    const result = await client.undoAction('a1');
    expect(url).toBe('http://api.test/actions/a1/undo');
    expect(method).toBe('POST');
    expect(result.restoredPaperId).toBe('p1');
  });

  it('returns null when there is nothing to undo', async () => {
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () => jsonResponse(200, null),
    });
    await expect(client.undoableAction()).resolves.toBeNull();
  });

  it('handles a 204 from removing a saved paper', async () => {
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () =>
        ({ ok: true, status: 204, statusText: 'No Content' }) as unknown as Response,
    });
    await expect(client.removeSaved('p1')).resolves.toBeUndefined();
  });

  it('passes saved-library filters through as query parameters', async () => {
    let url = '';
    const client = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async (requested) => {
        url = String(requested);
        return jsonResponse(200, { saved: [], nextCursor: null, total: 0 });
      },
    });

    await client.saved({ status: 'unread', reason: 'math', sort: 'year', limit: 20 });
    expect(url).toContain('status=unread');
    expect(url).toContain('reason=math');
    expect(url).toContain('sort=year');
  });

  it('distinguishes a NetworkError from an ApiError', async () => {
    const failing = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () => {
        throw new Error('offline');
      },
    });
    const rejecting = new ApiClient({
      baseUrl: 'http://api.test',
      fetchImpl: async () => jsonResponse(404, { error: { code: 'paper_not_found' } }),
    });

    await expect(failing.health()).rejects.not.toBeInstanceOf(ApiError);
    await expect(rejecting.health()).rejects.not.toBeInstanceOf(NetworkError);
  });
});
