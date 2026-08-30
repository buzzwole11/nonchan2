import type { DerivationStepView, EquationView } from '@papermatch/shared-types';

import {
  DETAIL_LEVELS,
  FOCUS_TABS,
  derivationChain,
  derivationView,
  gradeAnswer,
  limitNotes,
  nextMoveQuestion,
  rationaleOpenByDefault,
  stepBetween,
  visibleSteps,
} from '../src/math/focus';

function equation(id: string, latex: string): EquationView {
  return {
    id,
    paperId: 'p1',
    latex,
    equationNumber: id,
    section: 'Appendix A',
    display: true,
    provenanceKind: 'original',
    verificationStatus: 'source_exact',
    renderable: true,
    refusalReasons: [],
    symbols: [],
  };
}

function step(
  id: string,
  from: string,
  to: string,
  operation: string,
  evidence: Record<string, unknown> | null = null,
): DerivationStepView {
  return {
    id,
    fromEquationId: from,
    toEquationId: to,
    latex: `${from} \\to ${to}`,
    operation,
    rationale: `${operation} の理由`,
    verificationStatus: 'mechanically_verified',
    provenanceKind: 'verified_step',
    renderable: true,
    evidence,
  };
}

// The Gaussian derivation as the API actually serves it.
const EQUATIONS = [
  equation('1', String.raw`I(a) = \int e^{-ax^2}dx`),
  equation('2', String.raw`I(a)^2 = \iint e^{-a(x^2+y^2)}dxdy`),
  equation('3', String.raw`I(a)^2 = \int_0^{2\pi}\int_0^\infty e^{-ar^2} r\,dr\,d\theta`),
  equation('4', String.raw`I(a) = \sqrt{\pi/a}`),
];
const STEPS = [
  step('s1', '1', '2', '同じ積分を2つ掛ける'),
  step('s2', '2', '3', '極座標へ変数変換する'),
  step('s3', '3', '4', '動径積分を実行する'),
];

describe('the tabs and levels the spec names', () => {
  it('has the five tabs of section 10', () => {
    expect([...FOCUS_TABS]).toEqual(['symbols', 'structure', 'derivation', 'meaning', 'limits']);
  });

  it('has the four detail levels of section 10', () => {
    expect(DETAIL_LEVELS).toHaveLength(4);
  });
});

describe('visibleSteps', () => {
  it('shows no individual operations at the shortest level', () => {
    // 最短 is the "I already know this one" view: the two ends, not a partial walk.
    expect(visibleSteps(STEPS, 'shortest')).toEqual([]);
  });

  it('shows everything at every other level', () => {
    for (const level of ['standard', 'line_by_line', 'beginner'] as const) {
      expect(visibleSteps(STEPS, level)).toHaveLength(3);
    }
  });

  it('never invents a step the card does not have', () => {
    // The slider chooses how much of the derivation to show, not how much to make up.
    // Every level has to be a subset of what was stored.
    const ids = new Set(STEPS.map((s) => s.id));
    for (const level of DETAIL_LEVELS) {
      for (const shown of visibleSteps(STEPS, level)) {
        expect(ids.has(shown.id)).toBe(true);
      }
    }
  });

  it('collapses to the two ends and says how many operations that hid', () => {
    const view = derivationView(EQUATIONS, STEPS, 'shortest');
    expect(view.equations.map((e) => e.id)).toEqual(['1', '4']);
    // Named rather than hidden: a gap with no count reads as a rendering fault.
    expect(view.collapsed).toBe(3);
  });

  it('shows the whole chain and collapses nothing at every other level', () => {
    for (const level of ['standard', 'line_by_line', 'beginner'] as const) {
      const view = derivationView(EQUATIONS, STEPS, level);
      expect(view.equations).toHaveLength(4);
      expect(view.collapsed).toBe(0);
    }
  });

  it('leaves a two-equation derivation alone even at the shortest level', () => {
    const view = derivationView(EQUATIONS.slice(0, 2), [STEPS[0]!], 'shortest');
    expect(view.equations).toHaveLength(2);
    expect(view.collapsed).toBe(0);
  });

  it('copes with a card that has no derivation at all', () => {
    expect(visibleSteps([], 'standard')).toEqual([]);
  });

  it('opens the reasons without being asked only for beginners', () => {
    expect(rationaleOpenByDefault('beginner')).toBe(true);
    expect(rationaleOpenByDefault('standard')).toBe(false);
  });
});

describe('derivationChain', () => {
  it('keeps the equations the steps actually connect', () => {
    expect(derivationChain(EQUATIONS, STEPS).map((e) => e.id)).toEqual(['1', '2', '3', '4']);
  });

  it('drops an equation no step touches', () => {
    const stray = equation('9', 'x = 1');
    const chain = derivationChain([...EQUATIONS, stray], STEPS);
    expect(chain.map((e) => e.id)).not.toContain('9');
  });

  it('shows every equation when the card is not a derivation', () => {
    // A definition card has equations and no steps; hiding them would leave it empty.
    expect(derivationChain(EQUATIONS, [])).toHaveLength(4);
  });
});

describe('stepBetween', () => {
  it('finds the operation on the arrow between two equations', () => {
    expect(stepBetween(STEPS, EQUATIONS[1]!, EQUATIONS[2]!)?.operation).toBe(
      '極座標へ変数変換する',
    );
  });

  it('returns null where the derivation does not connect them', () => {
    expect(stepBetween(STEPS, EQUATIONS[0]!, EQUATIONS[3]!)).toBeNull();
  });
});

describe('the understanding check', () => {
  it('asks which operation applies here, using the card own operations as distractors', () => {
    // Distractors from an unrelated derivation would be rejected on vocabulary alone,
    // which tests nothing. These are all plausible.
    const question = nextMoveQuestion(EQUATIONS, STEPS, 1);
    expect(question).not.toBeNull();
    expect(question!.answer).toBe('極座標へ変数変換する');
    expect(question!.options).toHaveLength(3);
    expect(question!.options).toContain('同じ積分を2つ掛ける');
    expect(question!.from.id).toBe('2');
  });

  it('is stable, so a reader can read the options twice', () => {
    const a = nextMoveQuestion(EQUATIONS, STEPS, 0);
    const b = nextMoveQuestion(EQUATIONS, STEPS, 0);
    expect(a!.options).toEqual(b!.options);
  });

  it('carries the reason that was already stored, rather than a new explanation', () => {
    expect(nextMoveQuestion(EQUATIONS, STEPS, 2)!.rationale).toBe('動径積分を実行する の理由');
  });

  it('declines to ask when there is nothing to choose between', () => {
    // A question with one option is not a question.
    expect(nextMoveQuestion(EQUATIONS, [STEPS[0]!], 0)).toBeNull();
  });

  it('declines when the step does not exist', () => {
    expect(nextMoveQuestion(EQUATIONS, STEPS, 99)).toBeNull();
  });

  it('answers with a sentence, never a score', () => {
    // Spec section 10: 派手な点数化はせず.
    const question = nextMoveQuestion(EQUATIONS, STEPS, 1)!;
    const right = gradeAnswer(question, '極座標へ変数変換する');
    const wrong = gradeAnswer(question, '同じ積分を2つ掛ける');

    expect(right.correct).toBe(true);
    expect(right.messageKey).toBe('math.check.correct');
    expect(wrong.correct).toBe(false);
    expect(wrong.messageKey).toBe('math.check.tryAgain');
    expect(Object.keys(right)).toEqual(['correct', 'messageKey']);
  });
});

describe('the limits tab', () => {
  const checked = step('s4', '1', '2', '展開する', {
    numeric: { passed: true, variables: { a: [0.2, 6], x: [-3, 3] } },
    dimensional: { passed: true, detail: "both sides are {'L': 2}" },
  });

  it('reports the region an identity was actually checked on', () => {
    // Sampling proves an identity *there*. Saying where stops a reader over-reading it.
    const [note] = limitNotes([checked]);
    expect(note!.ranges).toEqual(['a ∈ [0.2, 6]', 'x ∈ [-3, 3]']);
    expect(note!.dimensional).toContain('both sides');
  });

  it('says nothing about a step that carries no evidence', () => {
    // An unverified step has no checked region, and inventing one would describe a check
    // nobody performed.
    expect(limitNotes([step('s5', '1', '2', '再和する', null)])).toEqual([]);
  });

  it('keeps the verification status alongside, so the claim can be weighed', () => {
    expect(limitNotes([checked])[0]!.verificationStatus).toBe('mechanically_verified');
  });
});
