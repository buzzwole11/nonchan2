/**
 * The rules behind Focus Mode (spec section 10).
 *
 * Kept as pure functions so the parts that decide *what a reader is shown* can be tested
 * without a renderer — which matters more than usual here, because the formula itself is
 * drawn by a WebView that cannot run in the test environment.
 *
 * Two of these rules are about not overstating what is known:
 *
 * * **The detail slider never invents a step.** Section 10 offers 最短 / 標準 / 一行ずつ /
 *   初学者向け, and it is tempting to read that as four levels of explanation. It is not:
 *   it is four amounts of *the derivation that exists*. A level that promised more than
 *   the card contains would have to fabricate it.
 * * **The understanding check is built from the card, not generated.** Section 10 lists
 *   穴埋め and 次の一手; both are answerable from the derivation already stored. Nothing
 *   here calls a model, so nothing here can be wrong in a way the card is not already
 *   wrong — and section 10's 派手な点数化はせず means the result is a sentence, not a score.
 */

import type { DerivationStepView, EquationView } from '@papermatch/shared-types';

export const FOCUS_TABS = ['symbols', 'structure', 'derivation', 'meaning', 'limits'] as const;
export type FocusTab = (typeof FOCUS_TABS)[number];

/** Spec section 10: 最短 / 標準 / 一行ずつ / 初学者向け. */
export const DETAIL_LEVELS = ['shortest', 'standard', 'line_by_line', 'beginner'] as const;
export type DetailLevel = (typeof DETAIL_LEVELS)[number];

/**
 * How much of the derivation a level shows.
 *
 * `shortest` shows no individual operations — it is the "I already know this one" view,
 * and what it offers is the two ends of the argument. `standard`, `line_by_line` and
 * `beginner` all show every step the card has; what changes between them is whether each
 * operation's reason is open by default, because a step is the finest thing that exists.
 * A level that showed something smaller would have to invent intermediate algebra that
 * nobody checked.
 */
export function visibleSteps(
  steps: DerivationStepView[],
  level: DetailLevel,
): DerivationStepView[] {
  if (steps.length === 0) return [];
  return level === 'shortest' ? [] : steps;
}

export interface DerivationView {
  /** The equations to render, in order. */
  equations: EquationView[];
  /** Operations not shown at this level, so the gap can be named rather than hidden. */
  collapsed: number;
}

/**
 * What the derivation looks like at a given level.
 *
 * At `shortest` this is the first and last equation with a count of the operations between
 * them. Showing all four equations with only the outer arrows — which is what filtering the
 * steps alone produced — leaves a hole in the middle that reads as a rendering fault rather
 * than as a deliberate summary. Naming the number of omitted operations is the honest form
 * of the same idea.
 */
export function derivationView(
  equations: EquationView[],
  steps: DerivationStepView[],
  level: DetailLevel,
): DerivationView {
  const chain = derivationChain(equations, steps);
  if (level !== 'shortest' || chain.length <= 2) {
    return { equations: chain, collapsed: 0 };
  }
  return {
    equations: [chain[0]!, chain[chain.length - 1]!],
    collapsed: steps.length,
  };
}

/** Whether a level opens every 「なぜ?」 without being asked. */
export function rationaleOpenByDefault(level: DetailLevel): boolean {
  return level === 'beginner';
}

/**
 * Equations in the order the derivation walks them.
 *
 * The card stores its equations in order, but a step names its endpoints by id, so a card
 * whose steps skip an equation would otherwise show it in the middle of a chain it is not
 * part of.
 */
export function derivationChain(
  equations: EquationView[],
  steps: DerivationStepView[],
): EquationView[] {
  if (steps.length === 0) return equations;
  const used = new Set<string>();
  for (const step of steps) {
    used.add(step.fromEquationId);
    used.add(step.toEquationId);
  }
  return equations.filter((e) => used.has(e.id));
}

/**
 * The step that takes a reader from one equation to the next, if there is one.
 *
 * Section 10 puts the operation on the arrow *between* two equations, so the screen needs
 * to ask "what happens here" for each gap rather than iterating steps on their own.
 */
export function stepBetween(
  steps: DerivationStepView[],
  from: EquationView,
  to: EquationView,
): DerivationStepView | null {
  return steps.find((s) => s.fromEquationId === from.id && s.toEquationId === to.id) ?? null;
}

// ------------------------------------------------------------------ understanding check

export interface NextMoveQuestion {
  kind: 'next_move';
  /** The equation the reader is standing on. */
  from: EquationView;
  /** Options in a stable order; exactly one is right. */
  options: string[];
  answer: string;
  /** Shown after answering — the reason that was already stored with the step. */
  rationale: string;
}

/**
 * Spec section 10's 次の一手, built from the derivation itself.
 *
 * The distractors are the other operations in the same card. That is deliberate: an
 * operation from an unrelated derivation would be rejected on vocabulary alone, which
 * tests nothing. Operations from the same card are all plausible, so answering means
 * knowing which one applies *here*.
 *
 * Returns `null` when the card has fewer than two distinct operations, because a question
 * with one option is not a question.
 */
export function nextMoveQuestion(
  equations: EquationView[],
  steps: DerivationStepView[],
  stepIndex: number,
): NextMoveQuestion | null {
  const step = steps[stepIndex];
  if (step === undefined) return null;

  const from = equations.find((e) => e.id === step.fromEquationId);
  if (from === undefined) return null;

  const others = steps
    .filter((s) => s.id !== step.id && s.operation !== step.operation)
    .map((s) => s.operation);
  const distractors = Array.from(new Set(others)).slice(0, 3);
  if (distractors.length === 0) return null;

  // Sorted rather than shuffled: a question that reorders itself on every render is a
  // question the reader cannot re-read, and there is no randomness available here that
  // would survive a re-render anyway.
  const options = [...distractors, step.operation].sort((a, b) => a.localeCompare(b, 'ja'));

  return {
    kind: 'next_move',
    from,
    options,
    answer: step.operation,
    rationale: step.rationale,
  };
}

export interface CheckOutcome {
  correct: boolean;
  /** Section 10: 派手な点数化はせず — a sentence, never a score. */
  messageKey: 'math.check.correct' | 'math.check.tryAgain';
}

export function gradeAnswer(question: NextMoveQuestion, chosen: string): CheckOutcome {
  const correct = chosen === question.answer;
  return {
    correct,
    messageKey: correct ? 'math.check.correct' : 'math.check.tryAgain',
  };
}

// ------------------------------------------------------------------------------ limits

/**
 * What the 極限 tab has to show, drawn from the checks that actually ran.
 *
 * Section 10 lists 極限 as a tab of its own. Everything it can honestly say comes from a
 * step's recorded evidence — the region an identity was sampled on, and whether the
 * dimensions balanced. A tab that made claims beyond that would be describing checks
 * nobody performed.
 */
export interface LimitNote {
  operation: string;
  /** e.g. `a ∈ [0.2, 6]` — the region the identity was actually checked on. */
  ranges: string[];
  dimensional: string | null;
  verificationStatus: string;
}

export function limitNotes(steps: DerivationStepView[]): LimitNote[] {
  const notes: LimitNote[] = [];
  for (const step of steps) {
    const evidence = step.evidence ?? {};
    const numeric = (evidence as Record<string, unknown>).numeric as
      { variables?: Record<string, number[]> } | undefined;
    const dimensional = (evidence as Record<string, unknown>).dimensional as
      { detail?: string } | undefined;

    const ranges = Object.entries(numeric?.variables ?? {}).map(
      ([name, [low, high]]) => `${name} ∈ [${low}, ${high}]`,
    );
    if (ranges.length === 0 && !dimensional?.detail) continue;

    notes.push({
      operation: step.operation,
      ranges,
      dimensional: dimensional?.detail ?? null,
      verificationStatus: step.verificationStatus,
    });
  }
  return notes;
}
