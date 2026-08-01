/**
 * The web half of the abstract renderer: an iframe holding the same document.
 *
 * `react-native-webview` has no web implementation, so without this the web build shows
 * "does not support this platform" where the abstract should be — which also means the
 * browser harness could not check the one screen that matters most.
 *
 * A **blob URL**, not `srcdoc`. The document carries `default-src 'none'` in a meta CSP;
 * under `srcdoc` the frame inherits the parent's origin, the inline script never runs, and
 * KaTeX silently falls back to printing LaTeX source — exactly the bug this replaces. A
 * blob URL gives the document its own origin and the CSP applies to it.
 *
 * The frame is sandboxed, so the parent cannot reach into it and it cannot reach out. That
 * is why the selection is sent as a message rather than by calling a function on the
 * frame's window.
 */
import { createElement, useEffect, useMemo, useRef } from 'react';
import { type StyleProp, View, type ViewStyle } from 'react-native';

import { selectionMessage } from '../math/abstractDocument';

export interface AbstractFrameProps {
  html: string;
  height: number;
  selected: readonly number[];
  onMessage: (raw: string) => void;
  style?: StyleProp<ViewStyle>;
}

export function AbstractFrame({ html, height, selected, onMessage, style }: AbstractFrameProps) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  const url = useMemo(() => URL.createObjectURL(new Blob([html], { type: 'text/html' })), [html]);

  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      // Only this frame's own window. Anything on the page can post a message.
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      if (typeof event.data === 'string') onMessage(event.data);
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [onMessage]);

  const message = selectionMessage(selected);
  useEffect(() => {
    // '*' as the target origin because a sandboxed frame's origin is opaque and cannot be
    // named. Nothing secret travels this way — it is a list of sentence indices.
    frame.current?.contentWindow?.postMessage(message, '*');
  }, [message, url]);

  return (
    <View style={[{ height }, style]}>
      {createElement('iframe', {
        ref: frame,
        src: url,
        title: '',
        sandbox: 'allow-scripts',
        style: { width: '100%', height, border: 0, background: 'transparent', display: 'block' },
      })}
    </View>
  );
}
