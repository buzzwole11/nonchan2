/**
 * Before you read (spec section 8), as the reader meets it.
 *
 * The two spec instructions under test: everything generated carries its label, and an
 * empty section is a normal outcome with its reason shown — never an error state, because
 * the paper is fully readable without any of this.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react-native';
import type { PaperExplanationResponse } from '@papermatch/shared-types';

import type { ApiClient } from '../src/api/client';

import { BeforeReadSheet } from '../src/discover/BeforeReadSheet';
import { ThemeProvider } from '../src/theme/ThemeProvider';

const mockPaperExplanation = jest.fn<Promise<PaperExplanationResponse>, [string]>();

// `explanationQuery` lives in queries.ts, which also carries the offline-cache queries and
// through them AsyncStorage — a native module Jest does not have. The cache is not under
// test here.
// A jest.mock factory runs before imports, so the mock module can only be loaded there
// with require.
jest.mock('@react-native-async-storage/async-storage', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

const RESPONSE: PaperExplanationResponse = {
  paperId: 'p1',
  beforeYouRead: {
    kind: 'before_you_read',
    audience: '',
    items: [
      {
        kind: 'term',
        title: 'non-reversible',
        detail: 'We study non-reversible Markov chains.',
        source: 'abstract',
        fieldId: null,
      },
      {
        kind: 'background',
        title: 'マルコフ連鎖',
        detail: '状態が確率的に遷移する過程。',
        source: 'model',
        fieldId: null,
      },
    ],
    unavailableReason: null,
    provenanceKind: 'ai_explanation',
    generationProvider: 'anthropic',
    generationModel: 'claude-haiku-4-5-20251001',
    promptVersion: 'anthropic-v1',
  },
  whyItMatters: [
    {
      kind: 'why_it_matters',
      audience: 'beginner',
      items: [
        {
          kind: 'why',
          title: '新しい上界',
          detail: 'これまでより強い評価を与える。',
          source: 'model',
          fieldId: null,
        },
      ],
      unavailableReason: null,
      provenanceKind: 'ai_explanation',
      generationProvider: 'anthropic',
      generationModel: 'claude-haiku-4-5-20251001',
      promptVersion: 'anthropic-v1',
    },
    {
      kind: 'why_it_matters',
      audience: 'field_history',
      items: [],
      unavailableReason: 'Abstract が分野内での位置づけを述べていないため',
      provenanceKind: 'ai_explanation',
      generationProvider: 'anthropic',
      generationModel: 'claude-haiku-4-5-20251001',
      promptVersion: 'anthropic-v1',
    },
  ],
};

function renderSheet() {
  // `gcTime: 0` so the client holds no garbage-collection timers after unmount — those
  // are what jest reports as "a worker process has failed to exit gracefully".
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <BeforeReadSheet
          visible
          locale="ja"
          paperId="p1"
          paperTitle="Concentration for Non-Reversible Measures"
          onClose={jest.fn()}
          // The client is a prop, so the test injects a stub instead of mocking a module.
          // The hook this used to mock (`useApiClient`) was a dead Phase-0 path whose
          // requests were always unauthenticated — and mocking it is exactly why these
          // tests stayed green while the real sheet 401ed on every open.
          api={{ paperExplanation: mockPaperExplanation } as unknown as ApiClient}
        />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockPaperExplanation.mockReset();
});

// The first test in a suite pays the whole import graph's transform cost, and on a cold
// CI runner that alone has crossed jest's 5s default (passed at 334ms locally, timed out
// at 5s on CI). The budget covers the cold start, not slow assertions.
jest.setTimeout(15_000);

describe('BeforeReadSheet', () => {
  it('labels a generated item as AI and a quoted item as from the paper', async () => {
    // Section 0: the reader must be able to tell. The two kinds arrive mixed in one list,
    // so the label is per item — one banner would let a gloss borrow a quotation's
    // credibility.
    mockPaperExplanation.mockResolvedValue(RESPONSE);
    renderSheet();

    await waitFor(() => expect(screen.getByText('non-reversible')).toBeTruthy());
    expect(screen.getByText('論文本文より')).toBeTruthy();
    expect(screen.getAllByText('AI 生成').length).toBeGreaterThanOrEqual(2);
  });

  it('shows an empty reading with its reason instead of hiding it', async () => {
    // Four headings that are sometimes two would read as the app forgetting, and the
    // reason is itself information about the paper.
    mockPaperExplanation.mockResolvedValue(RESPONSE);
    renderSheet();

    await waitFor(() =>
      expect(screen.getByText('Abstract が分野内での位置づけを述べていないため')).toBeTruthy(),
    );
    expect(screen.getByText('分野史上の位置づけ')).toBeTruthy();
  });

  it('says the paper is unaffected when the explanation cannot load', async () => {
    mockPaperExplanation.mockRejectedValue(new Error('down'));
    renderSheet();

    await waitFor(() =>
      expect(screen.getByText('読み込めませんでした。論文はそのまま読めます。')).toBeTruthy(),
    );
    expect(screen.getByText('もう一度')).toBeTruthy();
  });

  it('says one sentence when every reading was refused for the same reason', async () => {
    // The default provider refuses all four with the same sentence. Rendering it per
    // audience printed the identical paragraph four times under four headings, which reads
    // as the screen being broken rather than as the app declining to guess. Found by
    // looking at the sheet in a browser.
    const reason = '「なぜ重要か」は論文の位置づけについての判断で、メタデータからは導けません';
    mockPaperExplanation.mockResolvedValue({
      ...RESPONSE,
      whyItMatters: RESPONSE.whyItMatters.map((section) => ({
        ...section,
        items: [],
        unavailableReason: reason,
      })),
    });
    renderSheet();

    await waitFor(() => expect(screen.getAllByText(reason).length).toBe(1));
    // And the four headings go with it: a heading over nothing is the same noise.
    expect(screen.queryByText('分野史上の位置づけ')).toBeNull();
  });

  it('keeps the four headings when the absences differ', async () => {
    // Four *different* absences are four different facts, and a reader deciding whether to
    // configure a model wants to see which ones a model would fill in.
    mockPaperExplanation.mockResolvedValue({
      ...RESPONSE,
      whyItMatters: RESPONSE.whyItMatters.map((section, index) => ({
        ...section,
        items: [],
        unavailableReason: `理由その${index}`,
      })),
    });
    renderSheet();

    await waitFor(() => expect(screen.getByText('理由その0')).toBeTruthy());
    expect(screen.getByText('分野史上の位置づけ')).toBeTruthy();
  });

  it('fetches nothing while closed', () => {
    // 強制表示しない, and also a model call per passing card nobody asked for.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
          <BeforeReadSheet
            visible={false}
            locale="ja"
            paperId="p1"
            paperTitle={null}
            onClose={jest.fn()}
            api={{ paperExplanation: mockPaperExplanation } as unknown as ApiClient}
          />
        </ThemeProvider>
      </QueryClientProvider>,
    );

    expect(mockPaperExplanation).not.toHaveBeenCalled();
  });
});
