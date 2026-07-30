import { Text as RNText, type TextProps as RNTextProps, type TextStyle } from 'react-native';

import type { tokens } from '@papermatch/design-tokens';

import { useTheme } from '../theme/ThemeProvider';

type TypographyRole = keyof typeof tokens.typography.scale;

export interface TextProps extends RNTextProps {
  /** Named `variant`, not `role`: React Native already uses `role` for ARIA. */
  variant?: TypographyRole;
  tone?: 'primary' | 'secondary' | 'accent' | 'warning' | 'saved';
}

/**
 * Typography-aware text.
 *
 * Size, line height and family come from the design tokens and are already multiplied by
 * the clamped Dynamic Type scale, so no screen hardcodes a font size (spec sections 19,
 * 20).
 */
export function Text({ variant = 'body', tone = 'primary', style, ...rest }: TextProps) {
  const theme = useTheme();
  const type = theme.type(variant);
  const color =
    tone === 'secondary'
      ? theme.color.textSecondary
      : tone === 'accent'
        ? theme.color.accent
        : tone === 'warning'
          ? theme.color.warning
          : tone === 'saved'
            ? theme.color.saved
            : theme.color.textPrimary;

  return (
    <RNText
      // Scaling is applied from the token scale, so RN must not scale a second time.
      allowFontScaling={false}
      style={[
        {
          color,
          fontSize: type.fontSize,
          lineHeight: type.lineHeight,
          fontWeight: type.fontWeight as TextStyle['fontWeight'],
        },
        style,
      ]}
      {...rest}
    />
  );
}
