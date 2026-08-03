import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { createQueryClient } from '../src/api/queries';
import { SessionProvider } from '../src/api/session';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';

function ThemedStack() {
  const theme = useTheme();

  return (
    <>
      <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: theme.color.background },
          // Reduce Motion turns screen transitions into a fade (spec section 20).
          animation: theme.reduceMotion ? 'fade' : 'default',
          animationDuration: theme.duration('base'),
        }}
      />
    </>
  );
}

// One client for the life of the app. Built outside the component so a re-render never
// throws the cache away — which on a screen that fetches on mount looks like a reload loop.
const queryClient = createQueryClient();

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SessionProvider>
              <ThemedStack />
            </SessionProvider>
          </QueryClientProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
