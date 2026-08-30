import { type ReactNode, createContext, useContext, useEffect, useMemo, useState } from 'react';
import { AccessibilityInfo, PixelRatio, useColorScheme } from 'react-native';

import { type AppTheme, type ColorSchemePreference, buildTheme } from './theme';

interface ThemeContextValue {
  theme: AppTheme;
  preference: ColorSchemePreference;
  setPreference: (preference: ColorSchemePreference) => void;
  /** Overrides the OS Reduce Motion setting; spec section 18 makes this user-settable. */
  setReduceMotionOverride: (value: boolean | null) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export interface ThemeProviderProps {
  children: ReactNode;
  /** Test seam: lets tests drive the accessibility inputs without an OS. */
  initialPreference?: ColorSchemePreference;
  forceReduceMotion?: boolean;
  forceFontScale?: number;
}

export function ThemeProvider({
  children,
  initialPreference = 'system',
  forceReduceMotion,
  forceFontScale,
}: ThemeProviderProps) {
  const systemScheme = useColorScheme();
  const [preference, setPreference] = useState<ColorSchemePreference>(initialPreference);
  const [osReduceMotion, setOsReduceMotion] = useState(false);
  const [reduceMotionOverride, setReduceMotionOverride] = useState<boolean | null>(null);

  useEffect(() => {
    if (forceReduceMotion !== undefined) return undefined;

    let active = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (active) setOsReduceMotion(enabled);
      })
      .catch(() => {
        // A platform that cannot report the setting is treated as "motion allowed";
        // the user can still force it on in settings.
      });

    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      setOsReduceMotion,
    );
    return () => {
      active = false;
      subscription.remove();
    };
  }, [forceReduceMotion]);

  const fontScale = forceFontScale ?? PixelRatio.getFontScale();
  const reduceMotion = forceReduceMotion ?? reduceMotionOverride ?? osReduceMotion;

  const theme = useMemo(
    () => buildTheme({ preference, systemScheme, reduceMotion, fontScale }),
    [preference, systemScheme, reduceMotion, fontScale],
  );

  const value = useMemo(
    () => ({ theme, preference, setPreference, setReduceMotionOverride }),
    [theme, preference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): AppTheme {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error('useTheme must be used inside a <ThemeProvider>');
  }
  return context.theme;
}

export function useThemeControls(): Omit<ThemeContextValue, 'theme'> {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error('useThemeControls must be used inside a <ThemeProvider>');
  }
  const { theme: _theme, ...controls } = context;
  return controls;
}
