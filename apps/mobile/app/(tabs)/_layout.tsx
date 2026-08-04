/**
 * Bottom navigation (spec section 5): Discover / Saved / Learn / Profile.
 *
 * Learn is a Phase 2 surface. It is present but honest about being empty rather than
 * hidden, so the shape of the app is visible from the start.
 */
import { Tabs } from 'expo-router';

import { Text } from '../../src/components/Text';
import { translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

function TabIcon({ glyph, focused }: { glyph: string; focused: boolean }) {
  // A glyph plus the always-visible label: the icon is never the only cue.
  return (
    <Text variant="caption" tone={focused ? 'accent' : 'secondary'}>
      {glyph}
    </Text>
  );
}

export default function TabsLayout() {
  const theme = useTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.color.accent,
        tabBarInactiveTintColor: theme.color.textSecondary,
        tabBarStyle: {
          backgroundColor: theme.color.card,
          borderTopColor: theme.color.border,
        },
        // Always visible, never icon-only (spec section 20).
        tabBarShowLabel: true,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: translate('ja', 'nav.discover'),
          tabBarIcon: ({ focused }) => <TabIcon glyph="◎" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="saved"
        options={{
          title: translate('ja', 'nav.saved'),
          tabBarIcon: ({ focused }) => <TabIcon glyph="★" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="canvas"
        options={{
          title: translate('ja', 'nav.canvas'),
          tabBarIcon: ({ focused }) => <TabIcon glyph="◇" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="learn"
        options={{
          title: translate('ja', 'nav.learn'),
          tabBarIcon: ({ focused }) => <TabIcon glyph="✎" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: translate('ja', 'nav.profile'),
          tabBarIcon: ({ focused }) => <TabIcon glyph="⚙" focused={focused} />,
        }}
      />
    </Tabs>
  );
}
