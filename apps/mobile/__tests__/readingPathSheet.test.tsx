/**
 * Ways through a paper (spec section 17).
 *
 * The server decides what is on each route and its tests cover that. What is left here is
 * the part a reader can be misled by: whether the screen distinguishes a step whose content
 * the app has from a step that is really "go and open the PDF".
 */
import { fireEvent, render, screen } from '@testing-library/react-native';

import type { Paper, ReadingRoute } from '@papermatch/shared-types';

import { ReadingPathSheet } from '../src/reading/ReadingPathSheet';
import { ThemeProvider } from '../src/theme/ThemeProvider';

const ABSTRACT =
  'Concentration inequalities bound deviations. The constant is unknown for this family. ' +
  'We combine a spectral argument with a coupling. We prove a bound with no log factor.';

const PAPER = {
  id: '11111111-1111-4111-8111-111111111111',
  title: 'Concentration for Non-Reversible Measures',
  abstract: ABSTRACT,
  sourceUrl: 'https://example.invalid/abs/1',
} as unknown as Paper;

const ROUTES = [
  {
    purpose: 'overview',
    steps: [
      {
        kind: 'abstract_segment',
        labelKey: 'section.background',
        held: true,
        section: 'background',
        start: 0,
        end: 45,
        equationId: null,
        equationNumber: null,
        detail: null,
      },
      {
        kind: 'external',
        labelKey: 'readingPath.open.overview',
        held: false,
        section: null,
        start: null,
        end: null,
        equationId: null,
        equationNumber: null,
        detail: 'https://example.invalid/abs/1',
      },
    ],
    missing: ['full_text'],
  },
  {
    purpose: 'follow_math',
    steps: [
      {
        kind: 'external',
        labelKey: 'readingPath.open.follow_math',
        held: false,
        section: null,
        start: null,
        end: null,
        equationId: null,
        equationNumber: null,
        detail: 'https://example.invalid/abs/1',
      },
    ],
    missing: ['equations', 'full_text'],
  },
  {
    purpose: 'results_only',
    steps: [],
    missing: ['full_text'],
  },
  {
    purpose: 'citation_check',
    steps: [
      {
        kind: 'metadata',
        labelKey: 'readingPath.license',
        held: true,
        section: null,
        start: null,
        end: null,
        equationId: null,
        equationNumber: null,
        detail: null,
      },
    ],
    missing: ['full_text'],
  },
] as unknown as ReadingRoute[];

function renderSheet(routes: ReadingRoute[] = ROUTES) {
  const onOpenSource = jest.fn();
  render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <ReadingPathSheet
        visible
        paper={PAPER}
        routes={routes}
        locale="ja"
        onClose={jest.fn()}
        onOpenSource={onOpenSource}
      />
    </ThemeProvider>,
  );
  return { onOpenSource };
}

describe('what the route promises', () => {
  it('says the body of the paper is not included', () => {
    // Section 17's example route walks through figures and the introduction. The app has
    // never seen either, and a route that trailed off without saying so would be trusted
    // until the first time it ran out.
    renderSheet();

    expect(screen.getByText(/本文は含まれません/)).toBeTruthy();
  });

  it('shows the abstract sentence for a step it actually holds', () => {
    renderSheet();

    expect(screen.getByText(/Concentration inequalities bound deviations/)).toBeTruthy();
  });

  it('hands over to the original rather than pretending to have it', () => {
    const { onOpenSource } = renderSheet();

    fireEvent.press(screen.getByLabelText(/原論文で全体を確認する/));

    expect(onOpenSource).toHaveBeenCalledWith('https://example.invalid/abs/1');
  });

  it('does not make a held step pressable as though it opened something', () => {
    // The abstract sentence is already on screen; a tap target on it would suggest there is
    // more behind it.
    renderSheet();

    expect(screen.queryByLabelText(/背景: Concentration for Non-Reversible/)).toBeNull();
  });
});

describe('choosing a purpose', () => {
  it('offers all four', () => {
    renderSheet();

    // By label rather than by text: a selected chip renders its text with a tick prepended,
    // so the visible string is not the same for the four.
    for (const label of ['全体を知る', '数式を追う', '結果だけ見る', '引用に使えるか確認']) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it('switches the steps when the purpose changes', () => {
    renderSheet();
    expect(screen.getByText(/Concentration inequalities bound deviations/)).toBeTruthy();

    fireEvent.press(screen.getByLabelText('数式を追う'));

    expect(screen.queryByText(/Concentration inequalities bound deviations/)).toBeNull();
  });

  it('says when a paper has no equations rather than showing an empty maths route', () => {
    renderSheet();

    fireEvent.press(screen.getByLabelText('数式を追う'));

    expect(screen.getByText('この論文からは数式を取り出せていません。')).toBeTruthy();
  });

  it('names a missing licence rather than leaving the row blank', () => {
    // Section 21: not knowing the terms is the answer that should stop someone reusing it.
    renderSheet();

    fireEvent.press(screen.getByLabelText('引用に使えるか確認'));

    expect(screen.getByText('不明')).toBeTruthy();
  });
});
