/**
 * Spec section 11's three tiers, as a thing that actually happens: KaTeX → MathJax → source.
 *
 * The two documents are tested as text elsewhere. What is tested here is the escalation
 * between them, which is the part that can be wrong in ways no document test would see —
 * escalating on the wrong message, escalating and never coming back, or telling the reader
 * a formula failed while the next tier was still to be tried.
 */

import { act, render, screen } from '@testing-library/react-native';

import { MATH_MESSAGE_KIND } from '../src/math/document';
import { MathView } from '../src/math/MathView';
import { ThemeProvider } from '../src/theme/ThemeProvider';

/** The last document each frame was handed, and the callback to answer it with. */
const frames: { html: string; onMessage: (raw: string) => void }[] = [];

jest.mock('../src/math/MathFrame', () => {
  const { View } = jest.requireActual('react-native');
  return {
    MathFrame: (props: { html: string; height: number; onMessage: (raw: string) => void }) => {
      frames.push({ html: props.html, onMessage: props.onMessage });
      return <View testID="math-frame" />;
    },
  };
});

const LATEX = String.raw`\buildrel \rm def \over =`;

/** What the reader is told once every tier has failed. */
const RENDER_FAILED = '数式を組版できなかったため、LaTeX ソースを表示しています';

function renderView(latex = LATEX) {
  return render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <MathView latex={latex} locale="ja" zoomable={false} />
    </ThemeProvider>,
  );
}

/** The document currently mounted. */
const current = () => frames[frames.length - 1]!;

const reply = (result: Record<string, unknown>) =>
  act(() => {
    current().onMessage(JSON.stringify({ kind: MATH_MESSAGE_KIND, height: 40, ...result }));
  });

// Keyed on the configuration block each document writes for its own engine. A bare
// `includes('MathJax')` looked equivalent and was not — KaTeX's minified script mentions
// MathJax itself, so every document matched and the first assertion here passed for the
// wrong reason.
const engineOf = (html: string) =>
  html.includes('window.MathJax = {') ? 'mathjax' : html.includes('katex.render(') ? 'katex' : '?';

beforeEach(() => {
  frames.length = 0;
});

describe('the three tiers', () => {
  it('starts with KaTeX', () => {
    // A tenth of MathJax's size and enough for almost every formula, so the common path
    // must never parse the larger one.
    renderView();

    expect(engineOf(current().html)).toBe('katex');
  });

  it('escalates to MathJax when KaTeX refuses the formula', () => {
    renderView();

    reply({ engine: 'katex', ok: false, error: 'Undefined control sequence' });

    expect(engineOf(current().html)).toBe('mathjax');
  });

  it('says nothing to the reader while the next tier is still to be tried', () => {
    // "Could not render" followed by a rendered formula is worse than a moment's silence.
    renderView();

    reply({ engine: 'katex', ok: false, error: 'Undefined control sequence' });

    expect(screen.queryByText(RENDER_FAILED)).toBeNull();
  });

  it('tells the reader only once MathJax has failed too', () => {
    renderView();

    reply({ engine: 'katex', ok: false, error: 'Undefined control sequence' });
    reply({ engine: 'mathjax', ok: false, error: 'Missing close brace' });

    expect(screen.getByText(RENDER_FAILED)).toBeTruthy();
    // And it stays on MathJax rather than cycling back to the first tier, which would
    // re-run both engines on every message.
    expect(engineOf(current().html)).toBe('mathjax');
  });

  it('ignores a message from the document it has already replaced', () => {
    // The KaTeX frame can post again after escalation — a resize, a late height. Acting on
    // it would take the view back to a tier it had left.
    renderView();
    reply({ engine: 'katex', ok: false, error: 'Undefined control sequence' });

    const mathjaxFrame = current();
    act(() => {
      mathjaxFrame.onMessage(
        JSON.stringify({ kind: MATH_MESSAGE_KIND, engine: 'katex', ok: false, height: 999 }),
      );
    });

    expect(screen.queryByText(RENDER_FAILED)).toBeNull();
    expect(engineOf(current().html)).toBe('mathjax');
  });

  it('starts the next formula back at the first tier', () => {
    // Otherwise one hard equation makes every later formula in the same view pay MathJax's
    // parse cost.
    const view = renderView();
    reply({ engine: 'katex', ok: false, error: 'Undefined control sequence' });
    expect(engineOf(current().html)).toBe('mathjax');

    view.rerender(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <MathView latex={String.raw`E = mc^2`} locale="ja" zoomable={false} />
      </ThemeProvider>,
    );

    expect(engineOf(current().html)).toBe('katex');
  });

  it('never starts an engine for a formula the server already refused', () => {
    // Spec section 11's last tier reached directly: no WebView, no renderer, just the
    // source and the reason.
    render(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <MathView latex={LATEX} locale="ja" renderable={false} refusalReasons={['\\href']} />
      </ThemeProvider>,
    );

    expect(frames).toHaveLength(0);
    expect(screen.getByText(LATEX)).toBeTruthy();
  });
});
