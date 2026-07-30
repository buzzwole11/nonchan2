/**
 * Onboarding answers, held across the five screens.
 *
 * Kept in a store rather than route params so a Back does not lose an answer, and so the
 * final screen can submit everything in two requests instead of one per step — a
 * half-applied onboarding is worse than none.
 */
import { create } from 'zustand';

import type {
  EnglishLevel,
  ExplorationLevel,
  Interest,
  MathLevel,
  PaperType,
} from '@papermatch/shared-types';

interface OnboardingState {
  fieldIds: string[];
  paperTypes: PaperType[];
  englishLevel: EnglishLevel;
  mathLevel: MathLevel;
  exploration: ExplorationLevel;
  toggleField: (fieldId: string) => void;
  togglePaperType: (type: PaperType) => void;
  setEnglishLevel: (level: EnglishLevel) => void;
  setMathLevel: (level: MathLevel) => void;
  setExploration: (level: ExplorationLevel) => void;
  reset: () => void;
  /** Interests in the shape `PUT /me/interests` expects (spec section 18). */
  toInterests: () => Interest[];
}

const DEFAULTS = {
  fieldIds: [] as string[],
  paperTypes: [] as PaperType[],
  englishLevel: 'intermediate' as EnglishLevel,
  mathLevel: 'level_2' as MathLevel,
  exploration: 'balanced' as ExplorationLevel,
};

/**
 * Interest strength from selection order: the first field chosen is the main one, later
 * ones are weaker. Spec section 18 distinguishes メイン / ときどき / 偶然の出会い, and asking
 * for that explicitly would add a sixth screen the section does not have.
 */
function strengthFor(index: number): { strength: number; mode: Interest['mode'] } {
  if (index === 0) return { strength: 1.0, mode: 'main' };
  if (index < 3) return { strength: 0.7, mode: 'main' };
  return { strength: 0.4, mode: 'occasional' };
}

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  ...DEFAULTS,

  toggleField: (fieldId) =>
    set((state) => ({
      fieldIds: state.fieldIds.includes(fieldId)
        ? state.fieldIds.filter((id) => id !== fieldId)
        : [...state.fieldIds, fieldId],
    })),

  togglePaperType: (type) =>
    set((state) => ({
      paperTypes: state.paperTypes.includes(type)
        ? state.paperTypes.filter((t) => t !== type)
        : [...state.paperTypes, type],
    })),

  setEnglishLevel: (englishLevel) => set({ englishLevel }),
  setMathLevel: (mathLevel) => set({ mathLevel }),
  setExploration: (exploration) => set({ exploration }),
  reset: () => set(DEFAULTS),

  toInterests: () =>
    get().fieldIds.map((fieldId, index) => ({ fieldId, ...strengthFor(index) })),
}));

export { strengthFor };
