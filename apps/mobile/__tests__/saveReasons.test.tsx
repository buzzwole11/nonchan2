/**
 * The optional tags offered after a save (spec sections 6, 9).
 *
 * The tests that matter are about *when* they appear and what they imply. Section 9 makes
 * the save unconditional — 右スワイプの既定は「気になる」, tags are 任意 — so a chip row that
 * looked like a required step, or that could change whether the paper is saved, would be
 * the wrong feature no matter how it renders.
 */
import { fireEvent, render, screen } from '@testing-library/react-native';

import { SAVE_REASONS } from '@papermatch/shared-types';

import { UndoToast } from '../src/discover/UndoToast';
import type { PendingUndo } from '../src/discover/deck';
import {
  DEFAULT_SAVE_REASON,
  OPTIONAL_SAVE_REASONS,
  isReasonSelected,
  toggleReason,
} from '../src/discover/saveReasons';
import { translate } from '../src/i18n';
import { ThemeProvider } from '../src/theme/ThemeProvider';

// ------------------------------------------------------------------------ the vocabulary

describe('the tags on offer', () => {
  it('is the shared vocabulary minus the default, not a hand-copied list', () => {
    // A copied list goes stale silently: a tag added to enums.json would exist everywhere
    // except the one screen where a reader could pick it.
    expect([DEFAULT_SAVE_REASON, ...OPTIONAL_SAVE_REASONS].sort()).toEqual(
      [...SAVE_REASONS].sort(),
    );
  });

  it('covers the five section 9 names', () => {
    expect(OPTIONAL_SAVE_REASONS).toEqual([
      'read_later',
      'english_expression',
      'math',
      'research_related',
      'vague_interest',
    ]);
  });

  it('does not offer the default as a choice', () => {
    // It is what the swipe already meant. Offering it would imply the save is not final
    // until something is picked.
    expect(OPTIONAL_SAVE_REASONS).not.toContain(DEFAULT_SAVE_REASON);
  });

  it('has a name in both languages for every tag', () => {
    for (const locale of ['ja', 'en'] as const) {
      for (const reason of SAVE_REASONS) {
        expect(translate(locale, `saveReason.${reason}`)).toBeTruthy();
      }
    }
  });
});

// --------------------------------------------------------------------------- toggling

describe('toggleReason', () => {
  it('adds a tag', () => {
    expect(toggleReason(['interesting'], 'math')).toEqual(['interesting', 'math']);
  });

  it('removes one that is already on', () => {
    expect(toggleReason(['interesting', 'math'], 'math')).toEqual(['interesting']);
  });

  it('keeps the default through every combination', () => {
    // PATCH replaces the list, so dropping it here would drop it on the server — and the
    // paper would vanish from a 「気になる」 filter the reader never touched.
    expect(toggleReason([], 'math')).toContain(DEFAULT_SAVE_REASON);
    expect(toggleReason(['math'], 'read_later')).toContain(DEFAULT_SAVE_REASON);
  });

  it('returns the whole intended set, never a delta', () => {
    // `PATCH /saved/{id}` replaces rather than merges.
    const next = toggleReason(['interesting', 'math'], 'read_later');
    expect(next).toEqual(['interesting', 'math', 'read_later']);
  });

  it('reports what is on', () => {
    expect(isReasonSelected(['interesting', 'math'], 'math')).toBe(true);
    expect(isReasonSelected(['interesting'], 'math')).toBe(false);
  });
});

// ------------------------------------------------------------------------ in the toast

const item = {
  paper: { id: 'p1', title: 'Spectral Gaps in Sparse Expanders' },
} as unknown as PendingUndo['item'];

function renderToast(overrides: Partial<React.ComponentProps<typeof UndoToast>> = {}) {
  const onToggleReason = jest.fn();
  const pending: PendingUndo = { item, actionId: 'a1', actionType: 'save' };
  render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <UndoToast
        pending={pending}
        locale="ja"
        onUndo={() => undefined}
        onDismiss={() => undefined}
        reasons={['interesting']}
        onToggleReason={onToggleReason}
        {...overrides}
      />
    </ThemeProvider>,
  );
  return { onToggleReason };
}

describe('UndoToast', () => {
  it('offers every optional tag as a labelled button', () => {
    renderToast();
    for (const reason of OPTIONAL_SAVE_REASONS) {
      expect(
        screen.getByLabelText(new RegExp(translate('ja', `saveReason.${reason}`))),
      ).toBeTruthy();
    }
  });

  it('still offers Undo, so the save is reversible from the same place', () => {
    renderToast();
    expect(screen.getByLabelText(translate('ja', 'a11y.undoButton'))).toBeTruthy();
  });

  it('shows no tags after a skip', () => {
    // There is nothing to tag; the paper was not saved.
    renderToast({ pending: { item, actionId: 'a1', actionType: 'skip' } });
    expect(screen.queryByLabelText(new RegExp(translate('ja', 'saveReason.math')))).toBeNull();
  });

  it('shows no tags until the server has confirmed the save', () => {
    // Tagging a row the server has not accepted yet would PATCH something that is not
    // there. The same reason Undo is disabled until `actionId` arrives.
    renderToast({ pending: { item, actionId: null, actionType: 'save' } });
    expect(screen.queryByLabelText(new RegExp(translate('ja', 'saveReason.math')))).toBeNull();
  });

  it('passes the tag back rather than deciding for itself', () => {
    const { onToggleReason } = renderToast();
    fireEvent.press(screen.getByLabelText(new RegExp(translate('ja', 'saveReason.math'))));
    expect(onToggleReason).toHaveBeenCalledWith('math');
  });

  it('says which tags are on in words, not only by colour', () => {
    // Spec section 20: state has to survive greyscale and a screen reader.
    renderToast({ reasons: ['interesting', 'math'] });
    const label = screen.getByLabelText(new RegExp(translate('ja', 'saveReason.math'))).props
      .accessibilityLabel as string;
    expect(label).toContain(translate('ja', 'save.tagOn'));
  });
});
