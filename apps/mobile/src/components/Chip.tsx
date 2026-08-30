import { Pressable, StyleSheet, View } from 'react-native';

import { Text } from './Text';
import { useTheme } from '../theme/ThemeProvider';

export interface ChipProps {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  accessibilityLabel?: string;
  tone?: 'neutral' | 'accent' | 'saved' | 'warning';
}

/**
 * A metadata or choice chip.
 *
 * Selection is shown by a check mark and a border weight as well as colour, because
 * spec section 20 forbids colour being the only carrier of meaning — and a selected chip
 * that only changes hue is invisible in greyscale and to a colour-blind reader.
 */
export function Chip({
  label,
  selected = false,
  onPress,
  accessibilityLabel,
  tone = 'neutral',
}: ChipProps) {
  const theme = useTheme();
  const accent =
    tone === 'accent'
      ? theme.color.accent
      : tone === 'saved'
        ? theme.color.saved
        : tone === 'warning'
          ? theme.color.warning
          : theme.color.textSecondary;

  const body = (
    <View
      style={[
        styles.chip,
        {
          borderRadius: theme.radius.chip,
          borderColor: selected ? accent : theme.color.border,
          borderWidth: selected ? 2 : StyleSheet.hairlineWidth,
          backgroundColor: selected ? `${accent}18` : 'transparent',
          paddingHorizontal: theme.spacing.md,
          paddingVertical: theme.spacing.xs + 2,
          minHeight: onPress ? theme.touchTarget : undefined,
        },
      ]}
    >
      <Text
        variant="caption"
        tone={selected ? (tone === 'neutral' ? 'primary' : tone) : 'secondary'}
      >
        {selected ? `✓ ${label}` : label}
      </Text>
    </View>
  );

  if (onPress === undefined) return body;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={accessibilityLabel ?? label}
      hitSlop={6}
    >
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    alignSelf: 'flex-start',
    justifyContent: 'center',
  },
});
