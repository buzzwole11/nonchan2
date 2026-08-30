/**
 * The native half of the abstract renderer: a WebView holding one document.
 *
 * Split from `AbstractBody` on the platform, because `react-native-webview` has no web
 * implementation — on web it renders the words "does not support this platform" where the
 * abstract should be. `AbstractFrame.web.tsx` renders the same document in an iframe.
 */
import { useCallback, useMemo } from 'react';
import { type StyleProp, View, type ViewStyle } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

import { selectionScript } from '../math/abstractDocument';

export interface AbstractFrameProps {
  html: string;
  height: number;
  /** Sentences currently selected; pushed in without rebuilding the document. */
  selected: readonly number[];
  onMessage: (raw: string) => void;
  style?: StyleProp<ViewStyle>;
}

export function AbstractFrame({ html, height, selected, onMessage, style }: AbstractFrameProps) {
  const handle = useCallback(
    (event: WebViewMessageEvent) => onMessage(event.nativeEvent.data),
    [onMessage],
  );

  // Re-injected whenever the selection changes. Rebuilding the document instead would
  // re-parse the whole KaTeX runtime on every tap.
  const injected = useMemo(() => selectionScript(selected), [selected]);

  return (
    <View style={[{ height }, style]} pointerEvents="box-none">
      <WebView
        originWhitelist={['about:blank']}
        source={{ html }}
        // Spec section 25: the WebView renders, it does not browse. An abstract has no
        // links to follow, so every navigation attempt is refused.
        onShouldStartLoadWithRequest={(request) => request.url === 'about:blank'}
        injectedJavaScript={injected}
        onMessage={handle}
        // The document sizes itself; a scrolling WebView inside a scrolling card traps the
        // gesture and the deck stops swiping.
        scrollEnabled={false}
        nestedScrollEnabled={false}
        // Android draws a white box behind a transparent WebView without this.
        opaque={false}
        backgroundColor="transparent"
        style={{ backgroundColor: 'transparent', height }}
      />
    </View>
  );
}
