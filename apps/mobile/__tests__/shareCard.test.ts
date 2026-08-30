/**
 * The shareable card (spec sections 15, 21).
 *
 * Almost every test is about something staying *out* of the image. A card that leaks a
 * reader's note cannot be un-shared, so the defaults are the feature and the assertions
 * that matter are the negative ones.
 */
import type { Paper, SavedPaper } from '@papermatch/shared-types';

import { buildShareCard, shareCardSvg } from '../src/share/shareCard';

const PAPER = {
  id: '11111111-1111-4111-8111-111111111111',
  canonicalId: 'arXiv:2601.00001',
  identifiers: [],
  title: 'Concentration for Non-Reversible Measures',
  abstract: 'x',
  authors: [{ name: 'R. Almeida' }, { name: 'M. Zubkov' }],
  year: 2026,
  venue: 'Annals of Probability',
  paperTypes: ['preprint'],
  primaryFieldId: 'math.PR',
  fieldWeights: { 'math.PR': 1 },
  openAccess: 'gold',
  retractionStatus: 'none',
  version: 'v1',
  englishLevel: 'intermediate',
  mathDensity: 1,
  equationCount: 4,
  estimatedReadingMinutes: 1,
  sourceUrl: 'https://example.invalid/abs/2601.00001',
  pdfUrl: null,
  provenance: {
    sourceProvider: 'arxiv',
    acquiredAt: '2026-01-01T00:00:00Z',
    sourceUrl: 'https://example.invalid/abs/2601.00001',
    licenseId: 'CC-BY-4.0',
    licenseUrl: null,
    abstractRedistributable: true,
    cachePolicy: 'full_cache',
  },
} as unknown as Paper;

const SAVED = {
  paperId: PAPER.id,
  reasons: ['interesting', 'math'],
  status: 'unread',
  priority: 0,
  notes: '集中不等式の測度論的な背景をあとで読む',
  savedAt: '2026-02-01T00:00:00Z',
  lastVisitedAt: null,
} as unknown as SavedPaper;

// ---------------------------------------------------------------- what stays out

describe('the defaults', () => {
  it('leaves the reader’s note out of the card', () => {
    // Spec section 21: 共有画像から私的データを既定で除外. A card already on someone
    // else's timeline cannot be taken back.
    const card = buildShareCard(PAPER, SAVED);

    expect(card.notes).toBeNull();
  });

  it('leaves the save reasons out of the card', () => {
    // Why someone saved a paper is about them, not about the paper.
    expect(buildShareCard(PAPER, SAVED).reasons).toBeNull();
  });

  it('keeps the paper’s own metadata in', () => {
    const card = buildShareCard(PAPER, SAVED);

    expect(card.title).toBe(PAPER.title);
    expect(card.authors).toContain('R. Almeida');
    expect(card.year).toBe(2026);
    expect(card.venue).toBe('Annals of Probability');
  });

  it('never puts a note in the rendered image either', () => {
    const svg = shareCardSvg(buildShareCard(PAPER, SAVED));

    expect(svg).not.toContain('測度論的');
  });
});

describe('what the card reports about itself', () => {
  it('names the private fields it withheld', () => {
    // Silence would be indistinguishable from the reader having written nothing.
    expect(buildShareCard(PAPER, SAVED).omitted).toEqual(['notes', 'reasons']);
  });

  it('reports nothing withheld when there was nothing private to withhold', () => {
    const bare = { ...SAVED, notes: null, reasons: [] } as unknown as SavedPaper;

    expect(buildShareCard(PAPER, bare).omitted).toEqual([]);
  });

  it('does not count a blank note as something withheld', () => {
    const blank = { ...SAVED, notes: '   ', reasons: [] } as unknown as SavedPaper;

    expect(buildShareCard(PAPER, blank).omitted).toEqual([]);
  });

  it('reports nothing withheld when the reader asked for both', () => {
    const card = buildShareCard(PAPER, SAVED, { includeNotes: true, includeReasons: true });

    expect(card.omitted).toEqual([]);
    expect(card.notes).toContain('集中不等式');
    expect(card.reasons).toEqual(['interesting', 'math']);
  });
});

// ---------------------------------------------------------------- what is never optional

describe('attribution', () => {
  it('always carries the source URL', () => {
    // Section 21: 原文リンクを明示. An image of someone's work that does not say where it
    // came from is what the rule exists to prevent.
    const card = buildShareCard(PAPER, SAVED, {
      includeTitle: false,
      includeAuthors: false,
      includeYear: false,
      includeVenue: false,
    });

    expect(card.sourceUrl).toBe(PAPER.sourceUrl);
    expect(shareCardSvg(card)).toContain('example.invalid');
  });

  it('always carries the licence, and says so when it is unknown', () => {
    const unlicensed = {
      ...PAPER,
      provenance: { ...PAPER.provenance, licenseId: null },
    } as unknown as Paper;

    expect(buildShareCard(PAPER, null).licenseId).toBe('CC-BY-4.0');
    expect(shareCardSvg(buildShareCard(unlicensed, null))).toContain('ライセンス不明');
  });
});

// ---------------------------------------------------------------- rendering

describe('the SVG', () => {
  it('escapes text rather than letting it break the document', () => {
    // A share image travels furthest from the person who could notice it is broken.
    const awkward = { ...PAPER, title: 'Bounds on <script> & "quotes"' } as unknown as Paper;

    const svg = shareCardSvg(buildShareCard(awkward, null));

    expect(svg).not.toContain('<script>');
    expect(svg).toContain('&lt;script&gt;');
    expect(svg).toContain('&amp;');
  });

  it('crops a long note rather than letting it run off the card', () => {
    const chatty = { ...SAVED, notes: 'あ'.repeat(400) } as unknown as SavedPaper;

    const card = buildShareCard(PAPER, chatty, { includeNotes: true });

    expect(card.notes).not.toBeNull();
    expect((card.notes ?? '').length).toBeLessThanOrEqual(141);
    expect(card.notes?.endsWith('…')).toBe(true);
  });

  it('shortens a long author list instead of listing everyone', () => {
    const crowded = {
      ...PAPER,
      authors: [1, 2, 3, 4, 5, 6].map((n) => ({ name: `Author ${n}` })),
    } as unknown as Paper;

    expect(buildShareCard(crowded, null).authors).toContain('ほか');
  });

  it('renders with no saved entry at all', () => {
    const svg = shareCardSvg(buildShareCard(PAPER, null));

    expect(svg).toContain('<svg');
    expect(svg).toContain('</svg>');
    expect(svg).toContain('Concentration');
  });

  it('produces a card even when every optional field is off', () => {
    const svg = shareCardSvg(
      buildShareCard(PAPER, SAVED, {
        includeTitle: false,
        includeAuthors: false,
        includeYear: false,
        includeVenue: false,
      }),
    );

    expect(svg).toContain('<svg');
    expect(svg).toContain('example.invalid');
  });
});
