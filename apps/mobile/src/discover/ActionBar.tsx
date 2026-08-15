/**
 * Buttons equivalent to every swipe (spec sections 6, 20, 29).
 *
 * This is not a convenience: 左右スワイプとボタン操作が同等に働く is an MVP completion
 * criterion, and spec section 20 says a gesture may never be the only route to a feature.
 * The bar calls exactly the same handler the deck does, so the two cannot drift apart.
 */
import * as Haptics from 'expo-haptics';
import { Pressable, StyleSheet, View } from 'react-native';

import { Text } from '../components/Text';
import type { SwipeDirection } from './deck';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export interface ActionBarProps {
  locale: 'ja' | 'en';
  onAction: (direction: SwipeDirection) => void;
  disabled?: boolean;
  hapticsEnabled?: boolean;
}

interface ActionSpec {
  direction: SwipeDirection;
  labelKey: MessageKey;
  a11yKey: MessageKey;
  tone: 'secondary' | 'accent' | 'saved';
  glyph: string;
  haptic: 'selection' | 'light';
}

const ACTIONS: ActionSpec[] = [
  {
    direction: 'left',
    labelKey: 'discover.skip',
    a11yKey: 'a11y.skipButton',
    tone: 'secondary',
    glyph: '←',
    haptic: 'selection',
  },
  {
    // Spec section 20: the downward swipe needs a button too. Placed between skip and
    // open-source so the destructive-ish actions stay at the ends.
    direction: 'down',
    labelKey: 'discover.beforeRead',
    a11yKey: 'a11y.beforeReadButton',
    tone: 'secondary',
    glyph: '↓',
    haptic: 'selection',
  },
  {
    direction: 'up',
    labelKey: 'discover.read',
    a11yKey: 'a11y.openSourceButton',
    tone: 'accent',
    glyph: '↑',
    haptic: 'selection',
  },
  {
    direction: 'right',
    labelKey: 'discover.save',
    a11yKey: 'a11y.saveButton',
    tone: 'saved',
    glyph: '→',
    haptic: 'light',
  },
];

export function ActionBar({
  locale,
  onAction,
  disabled = false,
  hapticsEnabled = true,
}: ActionBarProps) {
  const theme = useTheme();
  const t = (key: MessageKey) => translate(locale, key);

  function press(action: ActionSpec) {
    if (hapticsEnabled) {
      // Haptics are an addition to the visual and text feedback, never the only signal,
      // and they are disableable (spec section 20).
      const style =
        action.haptic === 'light'
          ? Haptics.ImpactFeedbackStyle.Light
          : Haptics.ImpactFeedbackStyle.Soft;
      void Haptics.impactAsync(style).catch(() => {
        // Unsupported on this device or platform; not worth surfacing.
      });
    }
    onAction(action.direction);
  }

  return (
    <View style={[styles.bar, { gap: theme.spacing.md }]}>
      {ACTIONS.map((action) => (
        <Pressable
          key={action.direction}
          onPress={() => press(action)}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel={t(action.a11yKey)}
          accessibilityState={{ disabled }}
          hitSlop={8}
          style={({ pressed }) => [
            styles.button,
            {
              minHeight: theme.touchTarget,
              // `minWidth` only, with no cap, pushed the row past the screen edge at 2×
              // Dynamic Type: the left button was cut off and the right one hung outside.
              // These buttons are the non-gesture equivalent of the swipes (spec section
              // 20), so they are the last thing that may become unreachable. `flexShrink`
              // lets a button give up width, and the row wraps once shrinking is not
              // enough. Found by the visual-regression matrix, not by hand.
              minWidth: theme.touchTarget * 1.6,
              flexShrink: 1,
              borderRadius: theme.radius.chip,
              borderColor: theme.color.border,
              backgroundColor: theme.color.card,
              paddingHorizontal: theme.spacing.lg,
              opacity: disabled ? 0.4 : pressed ? 0.8 : 1,
            },
          ]}
        >
          {/* Arrow plus word: the direction is stated, not only implied by position. */}
          <Text variant="label" tone={action.tone}>
            {action.glyph} {t(action.labelKey)}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    alignItems: 'center',
  },
  button: {
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
