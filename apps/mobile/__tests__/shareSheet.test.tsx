/**
 * The share sheet (spec sections 15, 21).
 *
 * The unit tests next door cover what `buildShareCard` returns. What is left to check here
 * is that the screen the reader actually looks at agrees with what gets exported: the note
 * is off when the sheet opens, the sheet says so, and what the reader sees in the preview
 * is what lands on the clipboard.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { Paper, SavedPaper } from '@papermatch/shared-types';

import { ShareSheet } from '../src/share/ShareSheet';
import { ThemeProvider } from '../src/theme/ThemeProvider';

const NOTE = '集中不等式の測度論的な背景をあとで読む';

const PAPER = {
  id: '11111111-1111-4111-8111-111111111111',
  title: 'Concentration for Non-Reversible Measures',
  authors: [{ name: 'R. Almeida' }],
  year: 2026,
  venue: 'Annals of Probability',
  primaryFieldId: 'math.PR',
  sourceUrl: 'https://example.invalid/abs/2601.00001',
  provenance: { licenseId: 'CC-BY-4.0' },
} as unknown as Paper;

const SAVED = {
  paperId: PAPER.id,
  reasons: ['math'],
  status: 'unread',
  notes: NOTE,
} as unknown as SavedPaper;

function renderSheet() {
  const onClose = jest.fn();
  const copy = jest.fn<Promise<boolean>, [string]>().mockResolvedValue(true);
  render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <ShareSheet visible paper={PAPER} saved={SAVED} locale="ja" onClose={onClose} copy={copy} />
    </ThemeProvider>,
  );
  return { onClose, copy };
}

describe('ShareSheet', () => {
  it('opens with the reader’s note out of the preview', () => {
    // Section 21: 共有画像から私的データを既定で除外. The default is the feature — a reader
    // who has to notice and switch something off has already been failed.
    renderSheet();

    expect(screen.queryByText(NOTE)).toBeNull();
    expect(screen.getByText(PAPER.title)).toBeTruthy();
  });

  it('names what it left out rather than staying quiet about it', () => {
    // Silence is indistinguishable from having written no note at all.
    renderSheet();

    expect(screen.getByText('画像に含めていないもの: 自分のメモ、保存した理由')).toBeTruthy();
  });

  it('puts the note in only when the reader asks for it', () => {
    renderSheet();

    fireEvent.press(screen.getByLabelText('自分のメモ'));

    expect(screen.getByText(NOTE)).toBeTruthy();
  });

  it('exports what the preview showed, not something else', async () => {
    // A preview that disagreed with the export would be the worst place for a mismatch:
    // the reader checks it precisely because the share is irreversible.
    const { copy } = renderSheet();

    await act(async () => {
      fireEvent.press(screen.getByLabelText('画像（SVG）をコピー'));
    });

    const svg = copy.mock.calls[0]?.[0] ?? '';
    expect(svg).toContain('<svg');
    expect(svg).not.toContain('測度論的');
    expect(svg).toContain('example.invalid');
    expect(svg).toContain('CC-BY-4.0');
  });

  it('says so when the clipboard refuses instead of claiming success', async () => {
    const copy = jest.fn<Promise<boolean>, [string]>().mockResolvedValue(false);
    render(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <ShareSheet
          visible
          paper={PAPER}
          saved={SAVED}
          locale="ja"
          onClose={jest.fn()}
          copy={copy}
        />
      </ThemeProvider>,
    );

    await act(async () => {
      fireEvent.press(screen.getByLabelText('画像（SVG）をコピー'));
    });

    await waitFor(() => expect(screen.getByText('コピーできませんでした')).toBeTruthy());
  });
});
