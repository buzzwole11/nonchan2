/**
 * Entry route.
 *
 * Waits for the guest session, then sends a user with no interests to onboarding and
 * everyone else to the deck. Spec section 4 puts the first card close, so this screen is
 * a redirect with a spinner, never a landing page.
 */
import { Redirect } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { useSession } from '../src/api/session';
import { PressableRow } from '../src/components/PressableRow';
import { Text } from '../src/components/Text';
import { translate } from '../src/i18n';
import { useTheme } from '../src/theme/ThemeProvider';

export default function Entry() {
  const theme = useTheme();
  const { status, user, retry } = useSession();

  if (status === 'loading') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.color.background }}>
        <ActivityIndicator
          accessibilityLabel={translate('ja', 'common.loading')}
          color={theme.color.accent}
        />
      </View>
    );
  }

  if (status === 'offline' && user === null) {
    // No account and no network: onboarding needs the field list, and the deck needs a
    // token, so neither can start. Say so and offer a retry rather than looping.
    return (
      <View
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          gap: theme.spacing.md,
          padding: theme.spacing.xl,
          backgroundColor: theme.color.background,
        }}
      >
        <Text tone="warning" style={{ textAlign: 'center' }}>
          {translate('ja', 'status.api.offline')}
        </Text>
        <PressableRow onPress={retry} accessibilityLabel={translate('ja', 'common.retry')}>
          <Text tone="accent">{translate('ja', 'common.retry')}</Text>
        </PressableRow>
      </View>
    );
  }

  const needsOnboarding = user !== null && user.interests.length === 0;
  return <Redirect href={needsOnboarding ? '/onboarding/fields' : '/(tabs)'} />;
}
