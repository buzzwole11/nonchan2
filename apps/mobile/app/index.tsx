/**
 * Entry route.
 *
 * Waits for the guest session, then sends a user with no interests to onboarding and
 * everyone else to the deck. Spec section 4 puts the first card close, so this screen is
 * a redirect with a spinner, never a landing page.
 *
 * The spinner used to be the whole loading state. On a device pointed at an API that is
 * not there, that is up to ten seconds of a silent circle before the offline notice
 * arrives — indistinguishable, from the outside, from an app that has hung. So the wait
 * now says what it is waiting for, and both waiting states keep the development link
 * reachable, because the screen it leads to needs neither the API nor a database and is
 * exactly what someone is trying to open when the API is missing.
 */
import { Link, Redirect } from 'expo-router';
import { ActivityIndicator, Platform, View } from 'react-native';

import { apiBaseUrl } from '../src/api/useApi';
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
      <Centred>
        <ActivityIndicator
          accessibilityLabel={translate('ja', 'common.loading')}
          color={theme.color.accent}
        />
        <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
          {translate('ja', 'status.connecting')}
        </Text>
        <DevDiagnostics />
      </Centred>
    );
  }

  if (status === 'offline' && user === null) {
    // No account and no network: onboarding needs the field list, and the deck needs a
    // token, so neither can start. Say so and offer a retry rather than looping.
    return (
      <Centred>
        <Text tone="warning" style={{ textAlign: 'center' }}>
          {translate('ja', 'status.api.offline')}
        </Text>
        <PressableRow onPress={retry} accessibilityLabel={translate('ja', 'common.retry')}>
          <Text tone="accent">{translate('ja', 'common.retry')}</Text>
        </PressableRow>
        <DevDiagnostics />
      </Centred>
    );
  }

  const needsOnboarding = user !== null && user.interests.length === 0;
  return <Redirect href={needsOnboarding ? '/onboarding/fields' : '/(tabs)'} />;
}

function Centred({ children }: { children: React.ReactNode }) {
  const theme = useTheme();
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
      {children}
    </View>
  );
}

/**
 * Where the app is trying to connect, and a way into the formula-renderer check.
 *
 * The address is worth showing during development because the commonest way to get stuck
 * here is invisible otherwise: `localhost` on a phone means the phone, so an app pointed
 * there waits for a server that is on the developer's machine. `apiBaseUrl` now follows the
 * Expo dev server's host, which removes that case — but a tunnel, or a build with no dev
 * server behind it, can still land on localhost, and on a phone that is always wrong.
 * Printing the address turns "nothing happens" into "it is asking the wrong host".
 *
 * `__DEV__` is false in a production build, so none of this ships.
 */
function DevDiagnostics() {
  const theme = useTheme();
  if (!__DEV__) return null;

  const base = apiBaseUrl();
  // On the web the browser and the API share a machine, so localhost is the right answer.
  const pointingAtItself = Platform.OS !== 'web' && /\/\/(localhost|127\.0\.0\.1)\b/.test(base);

  return (
    <View style={{ alignItems: 'center', gap: theme.spacing.xs }}>
      <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
        API: {base}
      </Text>
      {pointingAtItself && (
        <Text variant="caption" tone="warning" style={{ textAlign: 'center' }}>
          実機では localhost は端末自身を指します。開発サーバーの host を取得できていません。
          apps/mobile/app.json の expo.extra.apiBaseUrl に開発マシンの LAN IP を書いてください。
        </Text>
      )}
      <Link href="/dev/math" asChild>
        <PressableRow accessibilityLabel="開発用: 数式レンダラの確認">
          <Text tone="accent">開発用: 数式レンダラの確認 →</Text>
        </PressableRow>
      </Link>
    </View>
  );
}
