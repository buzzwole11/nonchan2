/**
 * One full-screen formula view for the whole app (spec section 11: タップで全画面).
 *
 * A sheet per formula would mean a `Modal` per rendered equation — the derivation tab alone
 * has six or seven — and only one can ever be open. One provider at the root keeps that to
 * a single instance and, more importantly, makes every formula in the app tappable without
 * each screen having to remember to wire it up. Section 11 lists 全画面 as a property of
 * formulas, not of one screen.
 */
import { useCallback, useMemo, useState } from 'react';

import { FormulaSheet } from './FormulaSheet';
import { FormulaZoomContext, type FormulaZoomRequest } from './formulaZoom';

export function FormulaZoomProvider({
  children,
  locale,
}: {
  children: React.ReactNode;
  locale: 'ja' | 'en';
}) {
  const [request, setRequest] = useState<FormulaZoomRequest | null>(null);

  const open = useCallback((next: FormulaZoomRequest) => setRequest(next), []);
  const close = useCallback(() => setRequest(null), []);

  // The sheet stays mounted with the last formula while closing so the dismissal animates
  // rather than the content vanishing a frame early.
  const shown = useMemo(() => request, [request]);

  return (
    <FormulaZoomContext.Provider value={open}>
      {children}
      {shown !== null && (
        <FormulaSheet
          // Keyed by the formula so opening a different one remounts the sheet: its size
          // step and its "copied" confirmation are about *that* formula and must not carry
          // over. This is why the sheet needs no reset effect.
          key={shown.latex}
          visible
          latex={shown.latex}
          locale={locale}
          provenanceKind={shown.provenanceKind}
          renderable={shown.renderable}
          refusalReasons={shown.refusalReasons}
          accessibilityLabel={shown.accessibilityLabel}
          onClose={close}
        />
      )}
    </FormulaZoomContext.Provider>
  );
}
