import type { ReactNode } from 'react';
import { Pressable, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';

export interface PressableRowProps {
  children: ReactNode;
  onPress?: () => void;
  /** Required: spec section 20 forbids controls that a screen reader cannot name. */
  accessibilityLabel: string;
  accessibilityHint?: string;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * A row-shaped button that always meets the minimum touch target and always carries an
 * accessibility label. Using this instead of a bare `Pressable` makes the accessible
 * path the path of least resistance.
 */
export function PressableRow({
  children,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  disabled = false,
  style,
}: PressableRowProps) {
  const theme = useTheme();

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled }}
      // Extends the tappable area without changing the layout.
      hitSlop={8}
      style={({ pressed }) => [
        styles.base,
        {
          minHeight: theme.touchTarget,
          paddingHorizontal: theme.spacing.lg,
          paddingVertical: theme.spacing.md,
          borderRadius: theme.radius.tile,
          backgroundColor: theme.color.card,
          borderColor: theme.color.border,
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
        },
        style,
      ]}
    >
      <View style={styles.content}>{children}</View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
});
