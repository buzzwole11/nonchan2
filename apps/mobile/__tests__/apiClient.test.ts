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
