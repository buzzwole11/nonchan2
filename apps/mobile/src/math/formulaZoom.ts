/**
 * The context a formula uses to ask for a full-screen view of itself (spec section 11).
 *
 * Split from the provider so that `MathView` can read it without importing the sheet — the
 * sheet renders a `MathView`, and the two importing each other is a cycle that works until
 * the bundler orders the modules differently.
 *
 * There is no default provider. A `MathView` outside one is simply not tappable, which is
 * the right outcome for the places a formula appears without a screen to open over it.
 */
import { createContext, useContext } from 'react';

import type { ProvenanceKind } from '@papermatch/shared-types';

export interface FormulaZoomRequest {
  latex: string;
  /** Carried through so the full-screen view can still say where the formula came from. */
  provenanceKind?: ProvenanceKind;
  renderable?: boolean;
  refusalReasons?: string[];
  accessibilityLabel?: string;
}

export type OpenFormula = (request: FormulaZoomRequest) => void;

export const FormulaZoomContext = createContext<OpenFormula | null>(null);

export function useFormulaZoom(): OpenFormula | null {
  return useContext(FormulaZoomContext);
}
