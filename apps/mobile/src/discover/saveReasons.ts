/**
 * The optional tags offered after a save (spec sections 6, 9).
 *
 * Section 9 is precise about the shape and it is easy to get wrong: 右スワイプの既定は
 * 「気になる」, and the tags below are 任意タグ. So **the save has already happened** by the
 * time any of this is on screen. Asking for a reason first would turn one gesture into a
 * decision, and a reader flicking through cards would stop flicking.
 *
 * That is why `interesting` is not one of the chips. It is what the swipe meant, it is
 * already stored, and offering it as a choice would imply the save is not final until
 * something is picked.
 */
import { SAVE_REASONS, type SaveReason } from '@papermatch/shared-types';

/**
 * The five tags section 9 lists, in its order.
 *
 * Derived from the shared vocabulary by removing the default rather than written out
 * again, so a sixth tag added to `enums.json` appears here instead of being silently
 * dropped — the failure that a hand-copied list produces is a control nobody can reach.
 */
export const OPTIONAL_SAVE_REASONS: readonly SaveReason[] = SAVE_REASONS.filter(
  (reason) => reason !== 'interesting',
);

/** The reason a right swipe means on its own (spec section 9). */
export const DEFAULT_SAVE_REASON: SaveReason = 'interesting';

/**
 * The reasons a paper should carry after a chip is tapped.
 *
 * `PATCH /saved/{id}` replaces the list rather than merging it, so this returns the whole
 * intended set and never a delta.
 */
export function toggleReason(current: readonly SaveReason[], reason: SaveReason): SaveReason[] {
  const without = current.filter((existing) => existing !== reason);
  const next = without.length === current.length ? [...current, reason] : without;

  // The default survives every combination of tags. It is why the card was saved, and a
  // reader who adds "formulas" has not stopped finding the paper interesting — dropping it
  // would also make the paper vanish from a "気になる" filter they never touched.
  return next.includes(DEFAULT_SAVE_REASON) ? next : [DEFAULT_SAVE_REASON, ...next];
}

/** Whether a tag is currently on, for the chip's pressed state. */
export function isReasonSelected(current: readonly SaveReason[], reason: SaveReason): boolean {
  return current.includes(reason);
}
