/**
 * A rendered formula (spec sections 11, 20, 25).
 *
 * Deliberately thin. Everything that decides *what* is rendered lives in `document.ts`,
 * which is a pure function and is tested both as text and by rendering its output in a
 * real browser. This component only owns the three things that need a native view:
 *
 * * **Sizing.** A WebView has no intrinsic height, so it collapses to nothing unless it is
 *   told. The document posts its measured height back once KaTeX has laid the formula out,
 *   and that is what sets the view's height.
 * * **Not navigating.** Spec section 25 restricts WebView navigation. A formula has no
 *   business loading a page, so every navigation after the first is refused — even though
 *   the document is self-contained and has a policy forbidding it. Three independent
 *   barriers for the same thing, because this is the one component in the app that
 *   executes untrusted content.
 * * **Accessibility.** The WebView is one element to the platform, so the label comes from
 *   here; the MathML inside is what a screen reader reads on the web, but VoiceOver and
 *   TalkBack address the native view.
 *
 * When the server has already refused the formula (`renderable === false`), no WebView is
 * created at all: the LaTeX source is shown as text with the reason. That is spec section
 * 11's fallback and it costs nothing to reach — no engine is started for a string we have
 * already decided not to typeset.
 */

import { useCallback, useMemo, useState } from 'react';
import { ScrollView, View, type StyleProp, type ViewStyle } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';
import { MATH_MESSAGE_KIND, type MathRenderResult, buildMathDocument } from './document';

export interface MathViewProps {
  latex: string;
  locale: 'ja' | 'en';
  /** The server's verdict. `false` means show the source without starting a renderer. */
  renderable?: boolean;
  /** Why the server refused, for the caption under the source. */
  refusalReasons?: string[];
  display?: boolean;
  /** Read instead of the formula's markup (spec sections 11, 20). */
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}

/** Before the document reports its real height; roughly one display equation. */
const INITIAL_HEIGHT = 64;

/** A formula taller than this scrolls rather than pushing everything else off screen. */
const MAX_HEIGHT = 520;

export function MathView({
  latex,
  locale,
  renderable = true,
  refusalReasons = [],
  display = true,
  accessibilityLabel,
  style,
}: MathViewProps) {
  const theme = useTheme();
  const [height, setHeight] = useState(INITIAL_HEIGHT);
  const [failed, setFailed] = useState(false);
  const t = (key: MessageKey) => translate(locale, key);

  const html = useMemo(
    () =>
      buildMathDocument(latex, {
        display,
        // Already multiplied by the clamped Dynamic Type scale, so the formula grows with
        // the text around it (spec section 20).
        fontSize: theme.type('abstract').fontSize,
        color: theme.color.textPrimary,
        backgroundColor: 'transparent',
        ariaLabel: accessibilityLabel,
      }),
    [latex, display, theme, accessibilityLabel],
  );

  const onMessage = useCallback((event: WebViewMessageEvent) => {
    let result: MathRenderResult & { kind?: string };
    try {
      result = JSON.parse(event.nativeEvent.data);
    } catch {
      // Not ours, or malformed. Leaving the height alone is the safe outcome — a bad
      // number here is a formula clipped in half.
      return;
    }
    if (result.kind !== MATH_MESSAGE_KIND) return;
    if (typeof result.height === 'number' && result.height > 0) {
      setHeight(Math.min(result.height + 4, MAX_HEIGHT));
    }
    setFailed(result.ok === false);
  }, []);

  if (!renderable) {
    return (
      <SourceFallback
        latex={latex}
        caption={t('math.refused')}
        detail={refusalReasons.join(', ')}
        style={style}
      />
    );
  }

  return (
    <View style={style}>
      <View
        style={{ height }}
        accessible
        accessibilityRole="image"
        accessibilityLabel={accessibilityLabel ?? t('math.formula')}
      >
        <WebView
          source={{ html }}
          onMessage={onMessage}
          // Spec section 25: the WebView renders, it does not browse. The document is
          // self-contained and carries a policy forbidding loads; this refuses the
          // navigation itself, which is the barrier that does not depend on the document
          // being the one we built.
          onShouldStartLoadWithRequest={(request) => request.url === 'about:blank'}
          originWhitelist={['about:']}
          javaScriptEnabled
          // Nothing to store, and nothing that should outlive the view.
          domStorageEnabled={false}
          incognito
          cacheEnabled={false}
          // The document sizes itself; a scrolling WebView inside a scrolling screen is
          // the classic way to make a list impossible to scroll.
          scrollEnabled={false}
          nestedScrollEnabled={false}
          showsHorizontalScrollIndicator={false}
          showsVerticalScrollIndicator={false}
          style={{ backgroundColor: 'transparent', height }}
          // Android renders a white box behind a transparent WebView without this.
          androidLayerType="software"
          // The view is one element to the platform; the label above describes it.
          importantForAccessibility="no-hide-descendants"
        />
      </View>
      {failed && (
        <Text variant="caption" tone="warning" accessibilityLiveRegion="polite">
          {t('math.renderFailed')}
        </Text>
      )}
    </View>
  );
}

/**
 * Spec section 11: 失敗時は整形済みLaTeXソースと原文リンク.
 *
 * Shown rather than hidden. A reader who can see the source can still check it against the
 * paper; an empty space tells them nothing, and silently omitting a formula from a
 * derivation would make the derivation look complete when it is not.
 */
function SourceFallback({
  latex,
  caption,
  detail,
  style,
}: {
  latex: string;
  caption: string;
  detail?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const theme = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: theme.color.formulaSurface,
          borderRadius: theme.radius.tile,
          padding: theme.spacing.md,
          gap: theme.spacing.xs,
        },
        style,
      ]}
    >
      <Text variant="caption" tone="secondary">
        {caption}
        {detail ? ` (${detail})` : ''}
      </Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <Text variant="caption" style={{ fontFamily: 'monospace' }} accessibilityLabel={latex}>
          {latex}
        </Text>
      </ScrollView>
    </View>
  );
}
