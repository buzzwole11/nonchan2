/**
 * Profile: reading preferences, display and data (spec sections 18, 20, 25).
 *
 * Everything onboarding asked for is changeable here — a setup screen the user cannot
 * revisit is a trap — plus the accessibility switches from section 20 and the data
 * controls from section 25.
 */
import { Link } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  ENGLISH_LEVELS,
  EXPLORATION_LEVELS,
  NOTIFICATION_PRESETS,
  MATH_LEVELS,
  type EnglishLevel,
  type ExplorationLevel,
  type NotificationPreset,
  type MathLevel,
} from '@papermatch/shared-types';

import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { clearCache } from '../../src/offline/cache';
import { useTheme, useThemeControls } from '../../src/theme/ThemeProvider';
import type { ColorSchemePreference } from '../../src/theme/theme';

const THEME_OPTIONS: ColorSchemePreference[] = ['system', 'light', 'dark'];

/**
 * Declared at module scope, not inside the screen.
 *
 * A component defined during render is a new type on every render, so React unmounts
 * the whole subtree and mounts a fresh one — the settings chips below would lose focus
 * mid-interaction, which for a screen reader user means being thrown back to the top of
 * the section on every toggle.
 */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text variant="label" accessibilityRole="header">
        {title}
      </Text>
      {children}
    </View>
  );
}

export default function ProfileScreen() {
  const theme = useTheme();
  const { preference, setPreference } = useThemeControls();
  const insets = useSafeAreaInsets();
  const { api, user, refreshUser } = useSession();
  const [cacheCleared, setCacheCleared] = useState(false);

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey) => translate(locale, key);

  async function patch(settings: Parameters<typeof api.updateSettings>[0]): Promise<void> {
    try {
      await api.updateSettings(settings);
      await refreshUser();
    } catch {
      // The switch snaps back on the next render because the source of truth is the
      // server's copy of the settings, not local state.
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: theme.color.background }}
      contentContainerStyle={{
        paddingTop: insets.top + theme.spacing.xl,
        paddingHorizontal: theme.spacing.screenHorizontal,
        paddingBottom: insets.bottom + theme.spacing.xxl,
        gap: theme.spacing.xl,
      }}
    >
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="title" accessibilityRole="header">
          {t('profile.title')}
        </Text>
        {user?.isGuest === true && (
          <Text variant="caption" tone="secondary">
            {t('profile.guest')}
          </Text>
        )}
      </View>

      <Section title={t('profile.reading')}>
        <Text variant="caption" tone="secondary">
          {t('onboarding.english.title')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {ENGLISH_LEVELS.map((level) => (
            <Chip
              key={level}
              label={t(`english.${level}` as MessageKey)}
              selected={user?.settings.englishLevel === level}
              tone="accent"
              onPress={() => void patch({ englishLevel: level as EnglishLevel })}
            />
          ))}
        </View>

        <Text variant="caption" tone="secondary">
          {t('onboarding.math.title')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {MATH_LEVELS.map((level) => (
            <Chip
              key={level}
              label={t(`math.${level}` as MessageKey)}
              selected={user?.settings.mathLevel === level}
              tone="accent"
              onPress={() => void patch({ mathLevel: level as MathLevel })}
            />
          ))}
        </View>

        <Text variant="caption" tone="secondary">
          {t('onboarding.exploration.title')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {EXPLORATION_LEVELS.map((level) => (
            <Chip
              key={level}
              label={t(`exploration.${level}` as MessageKey)}
              selected={user?.settings.exploration === level}
              tone="accent"
              onPress={() => void patch({ exploration: level as ExplorationLevel })}
            />
          ))}
        </View>
      </Section>

      {/* Section 26's プリセット. The saved default is `quiet` rather than the most
          talkative option: a default that notifies is a decision made on the reader's
          behalf about their attention, and 「通知なし」 is one tap away. */}
      <Section title={t('profile.notifications')}>
        <Text variant="caption" tone="secondary">
          {t('notify.explainer')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {NOTIFICATION_PRESETS.map((preset) => (
            <Chip
              key={preset}
              label={t(`notify.${preset}` as MessageKey)}
              selected={(user?.settings.notificationPreset ?? 'quiet') === preset}
              tone="accent"
              onPress={() => void patch({ notificationPreset: preset as NotificationPreset })}
              accessibilityLabel={`${t('profile.notifications')}: ${t(`notify.${preset}` as MessageKey)}`}
            />
          ))}
        </View>
        {/* Said plainly rather than left for someone to discover by waiting for one. */}
        <Text variant="caption" tone="secondary">
          {t('notify.notYetDelivered')}
        </Text>
      </Section>

      <Section title={t('profile.display')}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {THEME_OPTIONS.map((option) => (
            <Chip
              key={option}
              label={t(`theme.${option}` as MessageKey)}
              selected={preference === option}
              tone="accent"
              onPress={() => setPreference(option)}
            />
          ))}
        </View>

        <View
          style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <Text>{t('status.reduceMotion')}</Text>
          <Switch
            value={user?.settings.reduceMotion ?? theme.reduceMotion}
            onValueChange={(value) => void patch({ reduceMotion: value })}
            accessibilityLabel={t('status.reduceMotion')}
          />
        </View>

        <View
          style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}
        >
          {/* Spec section 20: haptics must be disableable. */}
          <Text>Haptics</Text>
          <Switch
            value={user?.settings.hapticsEnabled ?? true}
            onValueChange={(value) => void patch({ hapticsEnabled: value })}
            accessibilityLabel="Haptics"
          />
        </View>

        <Text variant="caption" tone="secondary">
          {t('status.fontScale')}: ×{theme.fontScale.toFixed(2)}
        </Text>
      </Section>

      {/* `__DEV__` is false in a production build, so this never ships. The same screen is
          reachable from the offline entry screen, which is where someone lands when they
          are checking the renderer without a database running. */}
      {__DEV__ && (
        <Section title="開発用">
          <Link href="/dev/math" asChild>
            <PressableRow accessibilityLabel="数式レンダラの確認">
              <Text tone="accent">数式レンダラの確認 →</Text>
            </PressableRow>
          </Link>
        </Section>
      )}

      <Section title={t('profile.data')}>
        <PressableRow
          onPress={() => {
            void clearCache().then(() => setCacheCleared(true));
          }}
          accessibilityLabel={t('profile.clearCache')}
        >
          <Text tone="warning">{t('profile.clearCache')}</Text>
        </PressableRow>
        {cacheCleared && (
          <Text variant="caption" tone="secondary" accessibilityLiveRegion="polite">
            {t('profile.cacheCleared')}
          </Text>
        )}
      </Section>
    </ScrollView>
  );
}
