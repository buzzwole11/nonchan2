/**
 * `react-native-webview` needs a native module, which jest has no binary for — importing it
 * unmocked fails the whole suite with `RNCWebViewModule could not be found`.
 *
 * The mock renders a plain view and, deliberately, **never posts a message**. That puts the
 * component under test in the state that matters: a renderer that has not reported in. What
 * the reader sees then is the plain-text fallback, which is exactly the behaviour worth
 * holding down in a unit test — the real rendering is checked in a browser, because a
 * jest-rendered WebView proves nothing about whether KaTeX typeset anything.
 */
import { View, type ViewProps } from 'react-native';

export interface WebViewMessageEvent {
  nativeEvent: { data: string };
}

export function WebView(props: ViewProps & { source?: unknown }) {
  return <View testID="webview-mock" {...props} />;
}

export default WebView;
