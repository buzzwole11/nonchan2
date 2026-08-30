/**
 * A formula on its own, full screen (spec section 11: タップで全画面 / フォント拡大 / LaTeXコピー).
 *
 * The three things section 11 asks for here are all answers to the same problem: a formula
 * inline in a card is as large as the card lets it be, and some formulas do not fit. Full
 * screen gives it the width, the size control gives it the height, and copying the LaTeX
 * lets the reader take it somewhere that has neither.
 *
 * **The provenance label comes with it.** Section 11 requires every formula to carry where
 * it came from, and a full-screen view is exactly where that is easiest to lose: the
 * formula leaves the card that was labelling it. So the label is part of this sheet rather
 * than something the caller may or may not have drawn nearby.
 *
 * **Copy means the LaTeX, and only the LaTeX.** Section 11 lists コピー and LaTeXコピー
 * separately, which reads as "the formula as text" and "the source". For a formula those
 * are the same string: the canonical form *is* LaTeX (section 11's first line), and this
 * app has no LaTeX-to-Unicode converter. Two buttons that put identical text on the
 * clipboard would be a menu that lies about having a choice, so there is one button and it
 * says what it copies. If a plain-text rendering ever exists, it earns the second button
 * then.
 */
import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { Modal, ScrollView, StyleSheet, View } from 'react-native';

import type { ProvenanceKind } from '@papermatch/shared-types';

import { MathView } from './MathView';
import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/**
 * Multipliers on the reading font size, not absolute points.
 *
 * Section 22 already scales the whole app by the reader's Dynamic Type setting, and an
 * absolute size here would quietly undo that for the one element that most needs it. These
 * multiply whatever the reader has already chosen.
 */
export const FORMULA_SCALES = [1, 1.5, 2.25, 3.25] as const;

export const DEFAULT_SCALE_INDEX = 1;

export interface FormulaSheetProps {
  visible: boolean;
  latex: string;
  locale: 'ja' | 'en';
  onClose: () => void;
  provenanceKind?: ProvenanceKind;
  /** The server's verdict, passed through so a refused formula is not typeset here either. */
  renderable?: boolean;
  refusalReasons?: string[];
  /** Read instead of the markup (spec sections 11, 20). */
  accessibilityLabel?: string;
  /** Injectable for tests; the real one touches the system clipboard. */
  copy?: (text: string) => Promise<boolean>;
}

const PROVENANCE_KEY: Record<ProvenanceKind, MessageKey> = {
  original: 'provenance.original',
  verified_step: 'provenance.verifiedStep',
  ai_explanation: 'provenance.aiExplanation',
  assumption: 'provenance.assumption',
  human_reviewed: 'provenance.humanReviewed',
};

export function FormulaSheet({
  visible,
  latex,
  locale,
  onClose,
  provenanceKind,
  renderable = true,
  refusalReasons = [],
  accessibilityLabel,
  copy = Clipboard.setStringAsync,
}: FormulaSheetProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);
  const [scaleIndex, setScaleIndex] = useState<number>(DEFAULT_SCALE_INDEX);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [overflowing, setOverflowing] = useState(false);

  // No effect resets these on reopen. The provider keys the sheet by the formula, so a
  // different formula is a different component and starts fresh — a "copied" confirmation
  // left over from the previous formula would be a claim about the wrong string.

  async function onCopy(): Promise<void> {
    // `setStringAsync` reports whether the write landed, and a failure is reported rather
    // than swallowed: a reader who believes they copied the formula pastes whatever was on
    // the clipboard before into their notes and does not notice.
    try {
      setCopyState((await copy(latex)) ? 'copied' : 'failed');
    } catch {
      setCopyState('failed');
    }
  }

  const scale = FORMULA_SCALES[scaleIndex] ?? 1;

  return (
    <Modal
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
      accessibilityViewIsModal
      // Not `transparent`: this is the whole screen, which is the point of full screen.
      // A translucent sheet over the card would give the formula the same width it had.
      supportedOrientations={['portrait', 'landscape']}
    >
      <View style={{ flex: 1, backgroundColor: theme.color.background }}>
        <View
          style={[
            styles.header,
            {
              paddingHorizontal: theme.spacing.screenHorizontal,
              paddingTop: theme.spacing.xxl,
              paddingBottom: theme.spacing.sm,
            },
          ]}
        >
          <Text variant="label" accessibilityRole="header">
            {t('math.fullscreen.title')}
          </Text>
          <PressableRow onPress={onClose} accessibilityLabel={t('common.close')}>
            <Text variant="label" tone="accent">
              {t('common.close')}
            </Text>
          </PressableRow>
        </View>

        {provenanceKind !== undefined && (
          <Text
            variant="caption"
            tone="secondary"
            style={{ paddingHorizontal: theme.spacing.screenHorizontal }}
          >
            {t(PROVENANCE_KEY[provenanceKind])}
          </Text>
        )}

        {/* Vertical for a tall formula, horizontal inside the document for a wide one
            (spec section 11: 横スクロール). The formula is never cropped to fit. */}
        <ScrollView
          contentContainerStyle={{
            flexGrow: 1,
            justifyContent: 'center',
            padding: theme.spacing.screenHorizontal,
          }}
        >
          <MathView
            latex={latex}
            locale={locale}
            renderable={renderable}
            refusalReasons={refusalReasons}
            fontScale={scale}
            maxHeight={FULLSCREEN_MAX_HEIGHT}
            accessibilityLabel={accessibilityLabel}
            onOverflowChange={setOverflowing}
            // Already full screen; offering to open another one would stack sheets.
            zoomable={false}
          />
        </ScrollView>

        {/* A formula cut off at the screen edge with no cue reads as a rendering fault.
            The size steps below are the non-gesture way to see the whole thing (section
            20), so the caption points at them rather than only asking for a swipe. */}
        {overflowing && (
          <Text
            variant="caption"
            tone="secondary"
            accessibilityLiveRegion="polite"
            style={{ paddingHorizontal: theme.spacing.screenHorizontal }}
          >
            {t('math.fullscreen.wide')}
          </Text>
        )}

        <View
          style={{
            paddingHorizontal: theme.spacing.screenHorizontal,
            paddingBottom: theme.spacing.xxl,
            gap: theme.spacing.sm,
          }}
        >
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm }}>
            <Text variant="caption" tone="secondary">
              {t('math.fullscreen.size')}
            </Text>
            {/* `Chip` rather than a hand-rolled button: it already carries the selected
                state as a tick and a border as well as colour, which section 20 requires. */}
            {FORMULA_SCALES.map((value, index) => (
              <Chip
                key={value}
                label={String(index + 1)}
                selected={index === scaleIndex}
                tone="accent"
                onPress={() => setScaleIndex(index)}
                accessibilityLabel={t('math.fullscreen.sizeStep', { n: index + 1 })}
              />
            ))}
          </View>

          <PressableRow
            onPress={() => void onCopy()}
            accessibilityLabel={t('math.fullscreen.copyLatex')}
            style={{
              borderWidth: StyleSheet.hairlineWidth,
              borderColor: theme.color.border,
              borderRadius: theme.radius.tile,
              paddingVertical: theme.spacing.sm,
              alignItems: 'center',
            }}
          >
            <Text variant="body" tone="accent">
              {t('math.fullscreen.copyLatex')}
            </Text>
          </PressableRow>

          {copyState !== 'idle' && (
            <Text
              variant="caption"
              tone={copyState === 'copied' ? 'saved' : 'warning'}
              accessibilityLiveRegion="polite"
            >
              {t(copyState === 'copied' ? 'math.fullscreen.copied' : 'math.fullscreen.copyFailed')}
            </Text>
          )}

          {/* The source is visible as well as copyable. A reader checking the formula
              against the paper should not have to paste it somewhere to read it. */}
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Text variant="caption" tone="secondary" style={{ fontFamily: 'monospace' }}>
              {latex}
            </Text>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** Nearly the whole screen; the sheet's own scroll view handles what is left over. */
const FULLSCREEN_MAX_HEIGHT = 2000;

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
});
