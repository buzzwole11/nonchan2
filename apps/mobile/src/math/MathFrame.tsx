/**
 * The native half of the formula renderer: a WebView holding one formula's document.
 *
 * Split from `MathView` on the platform for the same reason `AbstractFrame` is split:
 * `react-native-webview` has no web implementation and renders the words "does not support
 * this platform" where the formula should be. That mattered more here than it looks —
 * on-device verification is blocked (D-030), so the browser harness is the only place
 * Focus Mode and the full-screen view can be checked at all, and until this split existed
 * neither had ever been seen rendering.
 */
import { useCallback } from 'react';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

export interface MathFrameProps {
  html: string;
  height: number;
  onMessage: (raw: string) => void;
}

export function MathFrame({ html, height, onMessage }: MathFrameProps) {
  const handle = useCallback(
    (event: WebViewMessageEvent) => onMessage(event.nativeEvent.data),
    [onMessage],
  );

  return (
    <WebView
      source={{ html }}
      onMessage={handle}
      // Spec section 25: the WebView renders, it does not browse. The document is
      // self-contained and carries a policy forbidding loads; this refuses the navigation
      // itself, which is the barrier that does not depend on the document being ours.
      onShouldStartLoadWithRequest={(request) => request.url === 'about:blank'}
      originWhitelist={['about:']}
      javaScriptEnabled
      // Nothing to store, and nothing that should outlive the view.
      domStorageEnabled={false}
      incognito
      cacheEnabled={false}
      // The document sizes itself; a scrolling WebView inside a scrolling screen is the
      // classic way to make a list impossible to scroll.
      scrollEnabled={false}
      nestedScrollEnabled={false}
      showsHorizontalScrollIndicator={false}
      showsVerticalScrollIndicator={false}
      style={{ backgroundColor: 'transparent', height }}
      // Android renders a white box behind a transparent WebView without this.
      androidLayerType="software"
      // The view is one element to the platform; the label on the wrapper describes it.
      importantForAccessibility="no-hide-descendants"
    />
  );
}
