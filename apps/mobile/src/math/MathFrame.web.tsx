/**
 * The web half of the formula renderer: an iframe holding the same document.
 *
 * A **blob URL**, not `srcdoc` — the same finding as `AbstractFrame.web.tsx` (D-035). The
 * document carries `default-src 'none'` in a meta CSP; under `srcdoc` the frame inherits
 * the parent's origin, the inline script never runs, and KaTeX quietly prints LaTeX source
 * instead of typesetting it. A blob URL gives the document its own origin so its own policy
 * applies.
 *
 * The frame is sandboxed with `allow-scripts` only, so it has an opaque origin and cannot
 * reach the parent. The height message therefore arrives by `postMessage` rather than by
 * reading the frame's document, which the sandbox forbids.
 */
import { createElement, useEffect, useRef } from 'react';
import { View } from 'react-native';

import { useDocumentUrl } from './useDocumentUrl.web';

export interface MathFrameProps {
  html: string;
  height: number;
  onMessage: (raw: string) => void;
}

export function MathFrame({ html, height, onMessage }: MathFrameProps) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  // Revocation is deferred until a successor loads — see `useDocumentUrl` for the
  // freeze/re-attach race this avoids. A formula document is rebuilt on every theme or
  // font-size change, so this frame runs the same risk as the abstract's.
  const { url, onFrameLoad } = useDocumentUrl(html);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      // Only this frame's own window. Anything on the page can post a message, and the
      // number in one of these sets the height of a formula.
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      if (typeof event.data === 'string') onMessage(event.data);
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [onMessage]);

  return (
    // Wrapped rather than returned bare, matching `AbstractFrame.web.tsx`: the height comes
    // from the native side and the frame fills it.
    <View style={{ height }} pointerEvents="box-none">
      {createElement('iframe', {
        ref: frame,
        key: url,
        src: url,
        onLoad: onFrameLoad,
        title: '',
        sandbox: 'allow-scripts',
        style: {
          width: '100%',
          height,
          border: 0,
          background: 'transparent',
          display: 'block',
          // The formula's own document scrolls horizontally when it is too wide (section
          // 11); the frame must not add a second scrollbar around it.
          overflow: 'hidden',
        },
      })}
    </View>
  );
}
