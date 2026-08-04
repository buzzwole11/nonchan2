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
import {
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import type { ProvenanceKind } from '@papermatch/shared-types';

import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';
import { MATH_MESSAGE_KIND, type MathRenderResult, buildMathDocument } from './document';
import { MathFrame } from './MathFrame';
import { useFormulaZoom } from './formulaZoom';

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
  /** Told when the formula turned out wider than its space, so a caller can say so. */
  onOverflowChange?: (overflow: boolean) => void;
  /**
   * Multiplier on the reading font size (spec section 11: フォント拡大).
   *
   * A multiplier and not a point size, so the reader's Dynamic Type setting still applies —
   * an absolute size would silently override it for the one element that most needs it.
   */
  fontScale?: number;
  /** Raise for a full-screen view, where nothing is competing for the space. */
  maxHeight?: number;
  /** Where the formula came from, so the full-screen view can keep saying so. */
  provenanceKind?: ProvenanceKind;
  /**
   * Set false inside the full-screen view itself, which must not offer to open another one.
   * Elsewhere the tap is wired automatically when a `FormulaZoomProvider` is above.
   */
  zoomable?: boolean;
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
  onOverflowChange,
  fontScale = 1,
  maxHeight = MAX_HEIGHT,
  provenanceKind,
  zoomable = true,
  style,
}: MathViewProps) {
  const theme = useTheme();
  const [height, setHeight] = useState(INITIAL_HEIGHT);
  const [failed, setFailed] = useState(false);
  const t = (key: MessageKey) => translate(locale, key);

  // No provider above means no screen to open over, so the formula is simply not tappable
  // rather than tappable-and-doing-nothing.
  const zoom = useFormulaZoom();
  const onPress =
    zoomable && zoom !== null
      ? () =>
          zoom({
            latex,
            provenanceKind,
            renderable,
            refusalReasons,
            accessibilityLabel,
          })
      : undefined;

  const html = useMemo(
    () =>
      buildMathDocument(latex, {
        display,
        // Already multiplied by the clamped Dynamic Type scale, so the formula grows with
        // the text around it (spec section 20); `fontScale` is the reader's own zoom on top.
        fontSize: theme.type('abstract').fontSize * fontScale,
        color: theme.color.textPrimary,
        backgroundColor: 'transparent',
        ariaLabel: accessibilityLabel,
      }),
    [latex, display, theme, accessibilityLabel, fontScale],
  );

  const onMessage = useCallback(
    (raw: string) => {
      let result: MathRenderResult & { kind?: string };
      try {
        result = JSON.parse(raw);
      } catch {
        // Not ours, or malformed. Leaving the height alone is the safe outcome — a bad
        // number here is a formula clipped in half.
        return;
      }
      if (result.kind !== MATH_MESSAGE_KIND) return;
      if (typeof result.height === 'number' && result.height > 0) {
        setHeight(Math.min(result.height + 4, maxHeight));
      }
      setFailed(result.ok === false);
      onOverflowChange?.(result.overflow === true);
    },
    [maxHeight, onOverflowChange],
  );

  if (!renderable) {
    return (
      <SourceFallback
        latex={latex}
        caption={t('math.refused')}
        detail={refusalReasons.join(', ')}
        style={style}
        onPress={onPress}
        openLabel={t('math.fullscreen.open')}
      />
    );
  }

  return (
    <View style={style}>
      {/* `Pressable` and not `View`, even though the overlay below is what catches most
          taps. A screen reader activates *this* element, so an `onPress` that lived only on
          the overlay would leave the formula announcing itself as a button and doing
          nothing when double-tapped. */}
      <Pressable
        style={{ height }}
        onPress={onPress}
        accessible
        // A formula that opens full screen is a button, and saying `image` would tell a
        // screen reader there is nothing to activate here.
        accessibilityRole={onPress === undefined ? 'image' : 'button'}
        accessibilityHint={onPress === undefined ? undefined : t('math.fullscreen.open')}
        accessibilityLabel={accessibilityLabel ?? t('math.formula')}
      >
        <MathFrame html={html} height={height} onMessage={onMessage} />
        {/* The renderer consumes its own touches, so a finger landing on the formula never
            reaches the Pressable around it. This layer catches those. Hidden from the
            screen reader because the element around it already carries the label, the role
            and the hint — announcing the same formula twice is worse than not making it
            tappable at all. */}
        {onPress !== undefined && (
          <Pressable
            onPress={onPress}
            style={StyleSheet.absoluteFill}
            importantForAccessibility="no-hide-descendants"
            accessibilityElementsHidden
          />
        )}
      </Pressable>
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
  onPress,
  openLabel,
}: {
  latex: string;
  caption: string;
  detail?: string;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  openLabel?: string;
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
      {/* A refused formula is the case where copying the source matters most: the reader
          cannot see it typeset here and has to take it somewhere that can. */}
      {onPress !== undefined && (
        <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={openLabel}>
          <Text variant="caption" tone="accent">
            {openLabel}
          </Text>
        </Pressable>
      )}
    </View>
  );
}
