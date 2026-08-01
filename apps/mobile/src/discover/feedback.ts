/**
 * The five feed controls of spec section 16, as data.
 *
 * Section 16 lists 「この話題を減らす」「この著者をしばらく表示しない」「類似論文を減らす」
 * 「実験系を増やす」「古典的論文を増やす」 and then says the thing that shapes all of them:
 *
 *   否定的フィードバックを「嫌い」と決めつけない。「今回は見送る」として扱う。
 *
 * Three consequences are encoded here rather than left to the component.
 *
 * **Every control is undoable.** The server derives all five from the action log and counts
 * only actions that are not undone, so the sheet always hands back an action id and the
 * same Undo affordance the swipe deck uses covers them.
 *
 * **Two of them are about *this card*; three are about the mix.** `hide_topic` and
 * `hide_author` need a paper to read a field or a byline from, so they are unavailable
 * — visibly, with a reason — when there is no card. The other three are requests about the
 * feed and can be sent from an empty deck.
 *
 * **A control that would do nothing says so.** Hiding the author of a paper with no named
 * authors is a button that reports success and changes nothing, which is worse than one
 * that is plainly not available.
 */
import type { FeedItem } from '@papermatch/shared-types';

import type { MessageKey } from '../i18n';

export const FEEDBACK_KINDS = [
  'hide_topic',
  'hide_author',
  'less_similar',
  'more_experimental',
  'more_classic',
] as const;

export type FeedbackKind = (typeof FEEDBACK_KINDS)[number];

export interface FeedbackControl {
  kind: FeedbackKind;
  labelKey: MessageKey;
  /** What the reader is told this actually does. Section 16: not 「嫌い」 but 「今回は見送る」. */
  hintKey: MessageKey;
  /** True when the control acts on the card in front of the reader. */
  needsCard: boolean;
}

export const FEEDBACK_CONTROLS: FeedbackControl[] = [
  {
    kind: 'hide_topic',
    labelKey: 'feedback.hideTopic',
    hintKey: 'feedback.hideTopicHint',
    needsCard: true,
  },
  {
    kind: 'hide_author',
    labelKey: 'feedback.hideAuthor',
    hintKey: 'feedback.hideAuthorHint',
    needsCard: true,
  },
  {
    kind: 'less_similar',
    labelKey: 'feedback.lessSimilar',
    hintKey: 'feedback.lessSimilarHint',
    needsCard: false,
  },
  {
    kind: 'more_experimental',
    labelKey: 'feedback.moreExperimental',
    hintKey: 'feedback.moreExperimentalHint',
    needsCard: false,
  },
  {
    kind: 'more_classic',
    labelKey: 'feedback.moreClassic',
    hintKey: 'feedback.moreClassicHint',
    needsCard: false,
  },
];

export interface FeedbackRequest {
  type: FeedbackKind;
  paperId?: string;
  payload: Record<string, unknown>;
}

/** The author a `hide_author` would actually suppress, or null when there is not one. */
export function firstAuthorName(item: FeedItem | null): string | null {
  const name = item?.paper.authors?.[0]?.name;
  return typeof name === 'string' && name.trim().length > 0 ? name.trim() : null;
}

/**
 * Whether the control can do anything right now.
 *
 * Returning a reason rather than a boolean: a control greyed out with no explanation is a
 * bug report waiting to happen, and the sheet shows the reason next to the row.
 */
export function unavailableReason(
  control: FeedbackControl,
  item: FeedItem | null,
): MessageKey | null {
  if (!control.needsCard) return null;
  if (item === null) return 'feedback.needsCard';
  // Truthiness rather than a null check: the API declares `primaryFieldId` as a string, but
  // the column is nullable and a paper the classifier could not place arrives with it empty.
  if (control.kind === 'hide_topic' && !item.paper.primaryFieldId) {
    return 'feedback.noField';
  }
  if (control.kind === 'hide_author' && firstAuthorName(item) === null) {
    return 'feedback.noAuthor';
  }
  return null;
}

/**
 * The request body for one control.
 *
 * The field and the author name are sent explicitly even though the server would fall back
 * to the card's own values. What the reader was shown and what the server would infer can
 * differ — a card displays one byline, the record may carry a different first author after
 * a merge — and the audit log should record what they actually asked to hide.
 */
export function feedbackRequest(
  control: FeedbackControl,
  item: FeedItem | null,
): FeedbackRequest | null {
  if (unavailableReason(control, item) !== null) return null;

  if (control.kind === 'hide_topic' && item !== null) {
    return {
      type: 'hide_topic',
      paperId: item.paper.id,
      payload: { fieldId: item.paper.primaryFieldId },
    };
  }
  if (control.kind === 'hide_author' && item !== null) {
    return {
      type: 'hide_author',
      paperId: item.paper.id,
      payload: { authorName: firstAuthorName(item) },
    };
  }
  // The three mix controls carry no arguments: they are about the feed, not about a paper.
  // The card id rides along only so the reader's own history says where they pressed it.
  return { type: control.kind, paperId: item?.paper.id, payload: {} };
}

/**
 * Controls whose effect is visible only after the deck is rebuilt.
 *
 * `hide_topic` and `hide_author` remove candidates outright, so leaving the current deck in
 * place would show the reader more of exactly what they just asked to see less of. The
 * three mix controls only re-weight, and reloading for those would throw away the cards
 * already fetched to make a change the reader would not notice.
 */
export function needsReload(kind: FeedbackKind): boolean {
  return kind === 'hide_topic' || kind === 'hide_author';
}
