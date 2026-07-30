/**
 * Deck UI: the card and the buttons that must match the gestures.
 *
 * Spec section 29 makes 左右スワイプとボタン操作が同等に働く a completion criterion, and
 * section 20 requires every gesture to have a labelled control. Both are asserted here
 * rather than left to a manual pass.
 */
import { fireEvent, render, screen } from '@testing-library/react-native';

import type { FeedItem } from '@papermatch/shared-types';

import { AbstractCard } from '../src/discover/AbstractCard';
import { ActionBar } from '../src/discover/ActionBar';
import { UndoToast } from '../src/discover/UndoToast';
import { ThemeProvider } from '../src/theme/ThemeProvider';

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn().mockResolvedValue(undefined),
  ImpactFeedbackStyle: { Light: 'light', Soft: 'soft' },
}));

const ABSTRACT =
  'Flat bands amplify interaction effects. Measured resistivities scale as ' +
  '$\\rho(T) \\propto T$ over two decades. This identifies a clear signature.';

const item: FeedItem = {
  paper: {
    id: 'p1',
    canonicalId: 'arxiv:2401.01234',
    identifiers: [{ kind: 'arxiv', value: '2401.01234' }],
    title: 'Anomalous Transport in Kagome Metals',
    abstract: ABSTRACT,
    abstractSegments: [],
    authors: [{ name: 'K. Aoki' }, { name: 'B. Novak' }],
    year: 2025,
    venue: 'Physical Review B',
    paperTypes: ['preprint', 'original'],
    primaryFieldId: 'cond-mat',
    fieldWeights: { 'cond-mat': 0.7 },
    openAccess: 'green',
    retractionStatus: 'none',
    version: 'v1',
    englishLevel: 'advanced',
    mathDensity: 3.2,
    equationCount: 12,
    estimatedReadingMinutes: 1.4,
    sourceUrl: 'https://arxiv.org/abs/2401.01234',
    pdfUrl: null,
    provenance: {
      sourceProvider: 'arxiv',
      acquiredAt: '2025-01-01T00:00:00Z',
      sourceUrl: 'https://arxiv.org/abs/2401.01234',
      licenseId: 'CC-BY-4.0',
      licenseUrl: null,
      abstractRedistributable: true,
      cachePolicy: 'full_cache',
    },
  },
  reasons: ['matches_field', 'recent'],
  reasonText: '選んだ分野に一致します。最近の研究です。',
  position: 0,
  pool: 'matched',
  scoreBreakdown: { interest: 1 },
} as unknown as FeedItem;

function withTheme(ui: React.ReactElement, reduceMotion = false) {
  return render(
    <ThemeProvider initialPreference="light" forceReduceMotion={reduceMotion} forceFontScale={1}>
      {ui}
    </ThemeProvider>,
  );
}

describe('AbstractCard', () => {
  const noop = () => undefined;

  function renderCard(overrides: Partial<React.ComponentProps<typeof AbstractCard>> = {}) {
    return withTheme(
      <AbstractCard
        item={item}
        locale="ja"
        selection={null}
        onSelectSentence={noop}
        onOpenSource={noop}
        {...overrides}
      />,
    );
  }

  it('shows the original title, authors and venue', () => {
    renderCard();
    expect(screen.getByText('Anomalous Transport in Kagome Metals')).toBeTruthy();
    expect(screen.getByText('K. Aoki, B. Novak')).toBeTruthy();
    expect(screen.getByText('Physical Review B')).toBeTruthy();
  });

  it('states why the card was recommended, in words', () => {
    renderCard();
    expect(screen.getByText('選んだ分野に一致します。最近の研究です。')).toBeTruthy();
  });

  it('shows the licence, so provenance is on the card itself', () => {
    renderCard();
    expect(screen.getByText('CC-BY-4.0')).toBeTruthy();
  });

  it('renders the abstract as individually selectable sentences', () => {
    renderCard();
    // Three sentences: the one containing $\rho(T) \propto T$ must not have been split at
    // the decimal-free period inside the maths.
    expect(screen.getByText(/Flat bands amplify interaction effects\./)).toBeTruthy();
    expect(screen.getByText(/rho\(T\)/)).toBeTruthy();
    expect(screen.getByText(/This identifies a clear signature\./)).toBeTruthy();
  });

  it('reports a sentence tap with its index', () => {
    const onSelectSentence = jest.fn();
    renderCard({ onSelectSentence });
    fireEvent.press(screen.getByLabelText('Flat bands amplify interaction effects.'));
    expect(onSelectSentence).toHaveBeenCalledWith(0);
  });

  it('marks a selected sentence as selected for assistive technology', () => {
    renderCard({ selection: { from: 0, to: 0 } });
    const sentence = screen.getByLabelText('Flat bands amplify interaction effects.');
    expect(sentence.props.accessibilityState.selected).toBe(true);
  });

  it('opens the source from the identifier line', () => {
    const onOpenSource = jest.fn();
    renderCard({ onOpenSource });
    fireEvent.press(screen.getByLabelText('原論文を開く'));
    expect(onOpenSource).toHaveBeenCalled();
  });

  it('hides the card behind from assistive technology', () => {
    // Announcing the same paper twice — once for the visible card and once for the one
    // peeking out beneath it — would make the deck unusable with a screen reader.
    renderCard({ behind: true });
    expect(screen.queryByLabelText('原論文を開く')).toBeNull();

    screen.unmount();
    renderCard();
    expect(screen.queryByLabelText('原論文を開く')).not.toBeNull();
  });

  it('says in words whether the paper is open access', () => {
    renderCard();
    expect(screen.getByText('OA')).toBeTruthy();
  });
});

describe('ActionBar', () => {
  it('offers a labelled button for every swipe (spec section 20)', () => {
    withTheme(<ActionBar locale="ja" onAction={() => undefined} />);
    expect(screen.getByLabelText('この論文を見送る')).toBeTruthy();
    expect(screen.getByLabelText('この論文を保存する')).toBeTruthy();
    expect(screen.getByLabelText('原論文を開く')).toBeTruthy();
  });

  it('calls the same handler the deck does, with the same direction', () => {
    const onAction = jest.fn();
    withTheme(<ActionBar locale="ja" onAction={onAction} />);

    fireEvent.press(screen.getByLabelText('この論文を見送る'));
    fireEvent.press(screen.getByLabelText('この論文を保存する'));
    fireEvent.press(screen.getByLabelText('原論文を開く'));

    expect(onAction.mock.calls.map((c) => c[0])).toEqual(['left', 'right', 'up']);
  });

  it('reports its disabled state rather than only looking dimmer', () => {
    withTheme(<ActionBar locale="ja" onAction={() => undefined} disabled />);
    expect(screen.getByLabelText('この論文を見送る').props.accessibilityState.disabled).toBe(true);
  });

  it('does not fire haptics when the user turned them off', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const haptics = require('expo-haptics');
    haptics.impactAsync.mockClear();

    withTheme(<ActionBar locale="ja" onAction={() => undefined} hapticsEnabled={false} />);
    fireEvent.press(screen.getByLabelText('この論文を保存する'));
    expect(haptics.impactAsync).not.toHaveBeenCalled();
  });
});

describe('UndoToast', () => {
  const pending = { item, actionId: 'act-1', actionType: 'skip' as const };

  it('offers Undo once the action is confirmed', () => {
    const onUndo = jest.fn();
    withTheme(
      <UndoToast pending={pending} locale="ja" onUndo={onUndo} onDismiss={() => undefined} />,
    );
    fireEvent.press(screen.getByLabelText('直前の操作を取り消す'));
    expect(onUndo).toHaveBeenCalled();
  });

  it('disables Undo while the action is still in flight', () => {
    withTheme(
      <UndoToast
        pending={{ ...pending, actionId: null }}
        locale="ja"
        onUndo={() => undefined}
        onDismiss={() => undefined}
      />,
    );
    // There is no server-side action to reverse yet, so the control must not pretend.
    expect(screen.getByLabelText('直前の操作を取り消す').props.accessibilityState.disabled).toBe(
      true,
    );
  });

  it('names the paper it would restore', () => {
    withTheme(
      <UndoToast
        pending={pending}
        locale="ja"
        onUndo={() => undefined}
        onDismiss={() => undefined}
      />,
    );
    expect(screen.getByText('Anomalous Transport in Kagome Metals')).toBeTruthy();
  });
});
