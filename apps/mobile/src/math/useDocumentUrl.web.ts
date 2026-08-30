/**
 * Blob-URL lifetime for a document shown in an iframe (web builds only).
 *
 * The obvious pattern — revoke the old URL as soon as the new one replaces it — is wrong
 * in one specific, reproducible way: when a screen is frozen by the navigator and later
 * re-attached, the browser *reloads the iframe from its current src*. If that reload races
 * a theme-driven document swap, the frame can end up loading the URL that was just
 * revoked, and it renders Chromium's "may have been moved, edited, or deleted" page where
 * the content should be. Found by switching to the dark theme from another tab and coming
 * back; the frame's error page still carried the revoked URL in its title.
 *
 * So a URL is only revoked once a *successor* document has actually loaded (`onFrameLoad`),
 * and everything outstanding is revoked on unmount. Between those moments an old URL stays
 * alive, which costs a few KB and buys the guarantee that whatever URL the browser decides
 * to (re)load is a live one.
 *
 * Callers should also key the iframe element on the URL: a new document then gets a new
 * element, so its load cannot be coalesced away by a navigation the old element had in
 * flight.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';

export function useDocumentUrl(html: string): { url: string; onFrameLoad: () => void } {
  const url = useMemo(() => URL.createObjectURL(new Blob([html], { type: 'text/html' })), [html]);
  const outstanding = useRef<string[]>([]);

  useEffect(() => {
    outstanding.current.push(url);
  }, [url]);

  // Unmount only: whatever is left — including URLs from renders that never loaded.
  useEffect(
    () => () => {
      for (const old of outstanding.current) URL.revokeObjectURL(old);
      outstanding.current = [];
    },
    [],
  );

  const onFrameLoad = useCallback(() => {
    // The current document is on screen, so every predecessor is now unreachable.
    while (outstanding.current.length > 0 && outstanding.current[0] !== url) {
      const old = outstanding.current.shift();
      if (old !== undefined) URL.revokeObjectURL(old);
    }
  }, [url]);

  return { url, onFrameLoad };
}
