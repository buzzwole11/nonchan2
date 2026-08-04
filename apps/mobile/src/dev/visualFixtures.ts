/**
 * Fixed content for the visual-regression gallery.
 *
 * **Everything here is frozen on purpose.** The real feed is randomised and the real API
 * is a network call, and a screenshot of either would differ on every run — which turns a
 * visual-regression suite into a thing people stop looking at. So the gallery renders the
 * app's real components against constants: the only thing that can change a baseline is a
 * change to the components or to the theme.
 *
 * The awkward cases are deliberate, because they are the ones that break silently:
 *
 * * A **long Japanese title** with no spaces, which cannot be wrapped at a word boundary.
 * * An **abstract with inline formulas**, so the maths renderer is in the frame.
 * * A paper with **no venue and unknown licence**, so the "missing" states are drawn.
 * * A **saved row carrying four chips**, which is what makes a row wrap at large type.
 */
import type { FeedItem, Paper, SavedEntry } from '@papermatch/shared-types';

const PROVENANCE = {
  sourceProvider: 'arxiv',
  acquiredAt: '2026-01-15T00:00:00Z',
  sourceUrl: 'https://example.invalid/abs/2601.00001',
  licenseId: 'CC-BY-4.0',
  licenseUrl: 'https://creativecommons.org/licenses/by/4.0/',
  abstractRedistributable: true,
  cachePolicy: 'full_cache',
} as const;

function paper(overrides: Partial<Paper> & Pick<Paper, 'id' | 'title' | 'abstract'>): Paper {
  return {
    canonicalId: `arXiv:${overrides.id}`,
    identifiers: [{ kind: 'arxiv', value: '2601.00001' }],
    abstractSegments: [],
    authors: [{ name: 'R. Almeida' }, { name: 'M. Zubkov' }],
    year: 2026,
    venue: 'arXiv (math.PR)',
    paperTypes: ['preprint'],
    primaryFieldId: 'math.PR',
    fieldWeights: { 'math.PR': 1 },
    openAccess: 'gold',
    retractionStatus: 'none',
    version: 'v1',
    englishLevel: 'intermediate',
    mathDensity: 3.2,
    equationCount: 14,
    estimatedReadingMinutes: 1.4,
    sourceUrl: PROVENANCE.sourceUrl,
    pdfUrl: null,
    provenance: { ...PROVENANCE },
    ...overrides,
  } as Paper;
}

const ORDINARY = paper({
  id: '11111111-1111-4111-8111-111111111111',
  title: 'Concentration for Non-Reversible Measures',
  abstract:
    'The mixing time measures how long a Markov chain needs before its law is close to ' +
    'stationarity. Standard log-Sobolev arguments fail because the measure is not ' +
    'uniformly log-concave. We construct a coupling that contracts a weighted metric. ' +
    'We show cutoff at time $t_{\\mathrm{mix}} = \\frac{1}{2\\lambda}\\log n$ with a ' +
    'window of order $1/\\lambda$. The bound removes an assumption that limited earlier ' +
    'applications.',
});

/** No spaces to break at, so this is where a fixed-width layout stops coping. */
const LONG_JAPANESE = paper({
  id: '22222222-2222-4222-8222-222222222222',
  title:
    '非可逆マルコフ連鎖における測度集中と混合時間の鋭い評価についての包括的な検討および今後の展望',
  abstract:
    'この論文では非可逆な設定における集中不等式を扱います。' +
    '従来の対数ソボレフ不等式に基づく議論は、測度が一様に対数凹でないために適用できません。' +
    '重み付き距離を縮小する結合を構成し、その縮小率を評価します。',
  venue: null,
  primaryFieldId: 'math.PR',
  provenance: { ...PROVENANCE, licenseId: null, licenseUrl: null, cachePolicy: 'metadata_only' },
});

function item(source: Paper, position: number, reasonText: string): FeedItem {
  return {
    paper: source,
    reasons: ['matches_field'],
    reasonText,
    position,
    pool: 'matched',
    scoreBreakdown: { interest: 0.82, quality: 0.4 },
  };
}

export const VISUAL_FEED: FeedItem[] = [
  item(ORDINARY, 0, '関心のある分野の最近の研究です。'),
  item(LONG_JAPANESE, 1, '保存した論文と近い内容です。'),
];

export const VISUAL_SAVED: SavedEntry[] = [
  {
    savedPaper: {
      paperId: ORDINARY.id,
      // Four at once: this is the row that wraps first at large type.
      reasons: ['interesting', 'math', 'read_later', 'research_related'],
      status: 'abstract_in_progress',
      priority: 2,
      notes: '集中不等式の測度論的な背景',
      savedAt: '2026-02-01T00:00:00Z',
      lastVisitedAt: '2026-02-03T00:00:00Z',
    },
    paper: ORDINARY,
  } as SavedEntry,
  {
    savedPaper: {
      paperId: LONG_JAPANESE.id,
      reasons: ['interesting'],
      status: 'unread',
      priority: 0,
      notes: null,
      savedAt: '2026-01-20T00:00:00Z',
      lastVisitedAt: null,
    },
    paper: LONG_JAPANESE,
  } as SavedEntry,
];

export const VISUAL_LATEX = String.raw`t_{\mathrm{mix}} = \frac{1}{2\lambda}\log n + O(1/\lambda)`;

/** Long enough to need the horizontal scroll that section 11 asks for. */
export const VISUAL_WIDE_LATEX = String.raw`\mathcal{L} = -\tfrac{1}{4}F_{\mu\nu}F^{\mu\nu} + i\bar{\psi}\gamma^{\mu}D_{\mu}\psi + |D_{\mu}\phi|^{2} - V(\phi)`;
