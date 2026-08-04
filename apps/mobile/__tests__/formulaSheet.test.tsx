/**
 * The full-screen formula view (spec section 11: タップで全画面 / フォント拡大 / LaTeXコピー).
 *
 * What is worth holding down here is not that a modal opens. It is that the formula does
 * not lose anything on the way in — its provenance label, its exact LaTeX — and that the
 * reader is never told a copy succeeded when it did not.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { FormulaSheet, FORMULA_SCALES, DEFAULT_SCALE_INDEX } from '../src/math/FormulaSheet';
import { FormulaZoomProvider } from '../src/math/FormulaZoomProvider';
import { MathView } from '../src/math/MathView';
import { ThemeProvider } from '../src/theme/ThemeProvider';

const LATEX = String.raw`\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}`;

function renderSheet(props: Partial<React.ComponentProps<typeof FormulaSheet>> = {}) {
  const onClose = jest.fn();
  const copy = jest.fn<Promise<boolean>, [string]>().mockResolvedValue(true);
  render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <FormulaSheet visible latex={LATEX} locale="ja" onClose={onClose} copy={copy} {...props} />
    </ThemeProvider>,
  );
  return { onClose, copy };
}

describe('FormulaSheet', () => {
  it('copies the LaTeX exactly, with no re-escaping', async () => {
    // The canonical form is the LaTeX string (section 11). A copy that normalised
    // backslashes would paste something that no longer typesets.
    const { copy } = renderSheet();

    await act(async () => {
      fireEvent.press(screen.getByLabelText('LaTeX をコピー'));
    });

    expect(copy).toHaveBeenCalledWith(LATEX);
  });

  it('confirms the copy only after it has actually landed', async () => {
    renderSheet();
    expect(screen.queryByText('LaTeX をコピーしました')).toBeNull();

    await act(async () => {
      fireEvent.press(screen.getByLabelText('LaTeX をコピー'));
    });

    await waitFor(() => expect(screen.getByText('LaTeX をコピーしました')).toBeTruthy());
  });

  it('says so when the clipboard refuses rather than claiming success', async () => {
    // A reader who believes they copied the formula pastes the previous clipboard contents
    // into their notes and does not notice.
    const copy = jest.fn<Promise<boolean>, [string]>().mockResolvedValue(false);
    renderSheet({ copy });

    await act(async () => {
      fireEvent.press(screen.getByLabelText('LaTeX をコピー'));
    });

    await waitFor(() => expect(screen.getByText('コピーできませんでした')).toBeTruthy());
  });

  it('says so when the clipboard throws', async () => {
    const copy = jest.fn<Promise<boolean>, [string]>().mockRejectedValue(new Error('denied'));
    renderSheet({ copy });

    await act(async () => {
      fireEvent.press(screen.getByLabelText('LaTeX をコピー'));
    });

    await waitFor(() => expect(screen.getByText('コピーできませんでした')).toBeTruthy());
  });

  it('keeps the provenance label with the formula', () => {
    // Section 11 requires a formula to say where it came from, and full screen is where
    // that is easiest to lose: the formula has left the card that was labelling it.
    renderSheet({ provenanceKind: 'ai_explanation' });

    expect(screen.getByText('AI による説明')).toBeTruthy();
  });

  it('shows the source as text as well as offering to copy it', () => {
    // A reader checking the formula against the paper should not have to paste it
    // somewhere else to read it.
    renderSheet();

    expect(screen.getByText(LATEX)).toBeTruthy();
  });

  it('offers every size step and starts on the default', () => {
    renderSheet();

    for (let index = 0; index < FORMULA_SCALES.length; index += 1) {
      expect(screen.getByLabelText(`大きさ ${index + 1} 段階目`)).toBeTruthy();
    }
    expect(
      screen.getByLabelText(`大きさ ${DEFAULT_SCALE_INDEX + 1} 段階目`).props.accessibilityState
        .checked,
    ).toBe(true);
  });

  it('changes the selected size step when one is chosen', () => {
    renderSheet();

    fireEvent.press(screen.getByLabelText('大きさ 4 段階目'));

    expect(screen.getByLabelText('大きさ 4 段階目').props.accessibilityState.checked).toBe(true);
    expect(screen.getByLabelText('大きさ 1 段階目').props.accessibilityState.checked).toBe(false);
  });

  it('says nothing about overflow until the renderer reports some', () => {
    // The mock WebView never posts a message, which is the state before the formula has
    // been measured. Announcing "wider than the screen" then would be a guess.
    renderSheet();

    expect(screen.queryByText(/横スクロールできます/)).toBeNull();
  });

  it('does not typeset a formula the server refused, here either', () => {
    // The refusal is a server decision (D-027); a second surface must not quietly overrule
    // it by starting a renderer of its own.
    renderSheet({ renderable: false, refusalReasons: ['\\write18'] });

    expect(screen.queryByTestId('webview-mock')).toBeNull();
    // Twice: the fallback shows the source in place of the rendering, and the sheet shows
    // it again next to the copy button.
    expect(screen.getAllByText(LATEX)).toHaveLength(2);
  });
});

describe('MathView with a zoom provider', () => {
  function renderWithProvider(props: Partial<React.ComponentProps<typeof MathView>> = {}) {
    render(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <FormulaZoomProvider locale="ja">
          <MathView latex={LATEX} locale="ja" {...props} />
        </FormulaZoomProvider>
      </ThemeProvider>,
    );
  }

  it('announces the formula as a button once it can be opened', () => {
    // Announcing `image` would tell a screen reader there is nothing to activate.
    renderWithProvider();

    expect(screen.getByLabelText('数式').props.accessibilityRole).toBe('button');
  });

  it('is not a button without a provider, rather than a button that does nothing', () => {
    render(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <MathView latex={LATEX} locale="ja" />
      </ThemeProvider>,
    );

    expect(screen.getByLabelText('数式').props.accessibilityRole).toBe('image');
  });

  it('carries the provenance through to the full-screen view', () => {
    renderWithProvider({ provenanceKind: 'verified_step' });

    fireEvent.press(screen.getByLabelText('数式'));

    expect(screen.getByText('検証済みの補完')).toBeTruthy();
  });

  it('lets a refused formula be opened too', () => {
    // This is the case where copying the source matters most: the reader cannot see it
    // typeset and has to take it somewhere that can.
    renderWithProvider({ renderable: false, refusalReasons: ['\\write18'] });

    fireEvent.press(screen.getByLabelText('タップすると全画面で表示します'));

    expect(screen.getByLabelText('LaTeX をコピー')).toBeTruthy();
  });
});
