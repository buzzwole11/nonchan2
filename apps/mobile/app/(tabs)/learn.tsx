/**
 * Learn (spec section 5).
 *
 * Present and empty rather than absent: the tab is part of the app's shape, and saying
 * what arrives here is more useful than hiding it until Phase 2.
 */
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '../../src/components/Text';
import { translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function LearnScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: theme.color.background,
        paddingTop: insets.top + theme.spacing.xl,
        paddingHorizontal: theme.spacing.screenHorizontal,
        gap: theme.spacing.md,
      }}
    >
      <Text variant="label" accessibilityRole="header">
        {translate('ja', 'learn.title')}
      </Text>
      <Text variant="caption" tone="secondary">
        {translate('ja', 'learn.comingSoon')}
      </Text>
    </View>
  );
}
