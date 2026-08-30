/**
 * The five feed controls of spec section 16.
 *
 * The tests that matter are about what these controls must *not* do: call the reader's
 * feedback 「嫌い」, claim to have done something they cannot do, or exist only as a gesture.
 */
import { fireEvent, render, screen } from '@testing-library/react-native';

import type { FeedItem } from '@papermatch/shared-types';

import { FeedbackSheet } from '../src/discover/FeedbackSheet';
import {
  FEEDBACK_CONTROLS,
  type FeedbackKind,
  feedbackRequest,
  firstAuthorName,
  needsReload,
  unavailableReason,
} from '../src/discover/feedback';
import { translate } from '../src/i18n';
import { ThemeProvider } from '../src/theme/ThemeProvider';

const item = {
  paper: {
    id: 'p1',
    title: 'Anomalous Transport in Kagome Metals',
    abstract: 'x',
    authors: [{ name: 'K. Aoki' }, { name: 'B. Novak' }],
    primaryFieldId: 'cond-mat',
    paperTypes: ['preprint'],
  },
  reasons: ['matches_field'],
  reasonText: '',
  position: 0,
  pool: 'matched',
  scoreBreakdown: {},
} as unknown as FeedItem;

function control(kind: FeedbackKind) {
  const found = FEEDBACK_CONTROLS.find((c) => c.kind === kind);
  if (found === undefined) throw new Error(`no control ${kind}`);
  return found;
}

// ------------------------------------------------------------------------ the vocabulary

describe('the controls', () => {
  it('covers exactly the five section 16 lists', () => {
    expect(FEEDBACK_CONTROLS.map((c) => c.kind)).toEqual([
      'hide_topic',
      'hide_author',
      'less_similar',
      'more_experimental',
      'more_classic',
    ]);
  });

  it("never calls the reader's feedback dislike, in either language", () => {
    // Section 16: 否定的フィードバックを「嫌い」と決めつけない。「今回は見送る」として扱う.
    const banned = ['嫌い', '興味なし', 'dislike', 'not interested', 'never show'];
    for (const locale of ['ja', 'en'] as const) {
      const strings = [
        translate(locale, 'feedback.intro'),
        ...FEEDBACK_CONTROLS.flatMap((c) => [
          translate(locale, c.labelKey),
          translate(locale, c.hintKey, { author: 'X' }),
        ]),
      ];
      for (const text of strings) {
        for (const word of banned) {
          expect(text.toLowerCase()).not.toContain(word.toLowerCase());
        }
      }
    }
  });

  it('promises reversibility up front, not only per row', () => {
    expect(translate('ja', 'feedback.intro')).toContain('取り消せます');
    expect(translate('en', 'feedback.intro').toLowerCase()).toContain('undone');
  });
});

// ---------------------------------------------------------------- what each control sends

describe('feedbackRequest', () => {
  it('sends the field the reader was actually looking at', () => {
    expect(feedbackRequest(control('hide_topic'), item)).toEqual({
      type: 'hide_topic',
      paperId: 'p1',
      payload: { fieldId: 'cond-mat' },
    });
  });

  it('sends the byline the card showed, not whatever the server would infer', () => {
    expect(feedbackRequest(control('hide_author'), item)).toEqual({
      type: 'hide_author',
      paperId: 'p1',
      payload: { authorName: 'K. Aoki' },
    });
  });

  it('sends the three mix controls without arguments', () => {
    for (const kind of ['less_similar', 'more_experimental', 'more_classic'] as const) {
      expect(feedbackRequest(control(kind), item)).toEqual({
        type: kind,
        paperId: 'p1',
        payload: {},
      });
    }
  });

  it('lets the three mix controls work with no card at all', () => {
    // They are requests about the feed, not about a paper — an empty deck is exactly when
    // a reader wants to change the mix.
    expect(feedbackRequest(control('more_classic'), null)).toEqual({
      type: 'more_classic',
      paperId: undefined,
      payload: {},
    });
  });

  it('refuses rather than sending a request that would change nothing', () => {
    const noAuthors = { ...item, paper: { ...item.paper, authors: [] } } as FeedItem;
    const noField = { ...item, paper: { ...item.paper, primaryFieldId: '' } } as FeedItem;
    expect(feedbackRequest(control('hide_author'), noAuthors)).toBeNull();
    expect(feedbackRequest(control('hide_topic'), noField)).toBeNull();
    expect(feedbackRequest(control('hide_topic'), null)).toBeNull();
  });
});

describe('unavailableReason', () => {
  it('gives a reason rather than a bare false', () => {
    expect(unavailableReason(control('hide_topic'), null)).toBe('feedback.needsCard');
    expect(
      unavailableReason(control('hide_author'), {
        ...item,
        paper: { ...item.paper, authors: [{ name: '  ' }] },
      } as FeedItem),
    ).toBe('feedback.noAuthor');
    expect(unavailableReason(control('more_classic'), null)).toBeNull();
  });
});

describe('firstAuthorName', () => {
  it('treats a blank name as no name', () => {
    expect(firstAuthorName(item)).toBe('K. Aoki');
    expect(
      firstAuthorName({ ...item, paper: { ...item.paper, authors: [] } } as FeedItem),
    ).toBeNull();
    expect(firstAuthorName(null)).toBeNull();
  });
});

describe('needsReload', () => {
  it('rebuilds the deck only for the controls that remove candidates', () => {
    // Reloading for a re-weighting would throw away fetched cards to make a change the
    // reader would not notice; not reloading after a hide leaves the deck full of what
    // they just asked to see less of.
    expect(needsReload('hide_topic')).toBe(true);
    expect(needsReload('hide_author')).toBe(true);
    expect(needsReload('less_similar')).toBe(false);
    expect(needsReload('more_experimental')).toBe(false);
    expect(needsReload('more_classic')).toBe(false);
  });
});

// ------------------------------------------------------------------------------ the sheet

describe('FeedbackSheet', () => {
  function renderSheet(overrides: Partial<React.ComponentProps<typeof FeedbackSheet>> = {}) {
    const onSend = jest.fn();
    const view = render(
      <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
        <FeedbackSheet
          visible
          locale="ja"
          item={item}
          status={{ kind: 'idle' }}
          onSend={onSend}
          onClose={() => undefined}
          {...overrides}
        />
      </ThemeProvider>,
    );
    return { ...view, onSend };
  }

  it('offers every control as a labelled button, not a gesture', () => {
    // Spec section 20: a gesture may never be the only route to a feature.
    renderSheet();
    for (const c of FEEDBACK_CONTROLS) {
      expect(screen.getByLabelText(new RegExp(translate('ja', c.labelKey)))).toBeTruthy();
    }
  });

  it('states the consequence in the same label as the name', () => {
    // A screen reader user choosing between five similar controls should not need a
    // second pass to find out what each one does.
    renderSheet();
    const label = screen.getByLabelText(/類似論文を減らす/).props.accessibilityLabel as string;
    expect(label).toContain(translate('ja', 'feedback.lessSimilarHint'));
  });

  it('names what each control would actually act on', () => {
    // The sheet covers the card, so "less of this topic" with no topic named asks the
    // reader to remember which paper they were looking at.
    renderSheet();
    expect(screen.getByLabelText(/K\. Aoki/)).toBeTruthy();
    expect(screen.getByLabelText(/cond-mat/)).toBeTruthy();
  });

  it('disables a control that cannot act and says why', () => {
    renderSheet({ item: null });
    const row = screen.getByLabelText(new RegExp(translate('ja', 'feedback.hideTopic')));
    expect(row.props.accessibilityState.disabled).toBe(true);
    // Both card-bound controls carry the reason — there are two of them, and a reader
    // seeing only one explained would think the other was broken.
    expect(screen.getAllByText(translate('ja', 'feedback.needsCard'))).toHaveLength(2);
    // The mix controls are still live: an empty deck is when the reader wants them.
    expect(
      screen.getByLabelText(new RegExp(translate('ja', 'feedback.moreClassic'))).props
        .accessibilityState.disabled,
    ).toBe(false);
  });

  it('reports the outcome in words, not by the deck quietly reordering', () => {
    renderSheet({ status: { kind: 'applied', control: 'more_classic' } });
    expect(screen.getByText(translate('ja', 'feedback.applied'))).toBeTruthy();

    renderSheet({ status: { kind: 'failed' } });
    expect(screen.getByText(translate('ja', 'feedback.failed'))).toBeTruthy();
  });

  it('passes the pressed control back', () => {
    const { onSend } = renderSheet();
    fireEvent.press(screen.getByLabelText(new RegExp(translate('ja', 'feedback.moreClassic'))));
    expect(onSend).toHaveBeenCalledWith(control('more_classic'));
  });
});
