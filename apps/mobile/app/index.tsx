/**
 * Phase 0 foundation screen.
 *
 * Deliberately not a mock: it talks to the real API through the typed client, so the
 * boundary between UI and live data is exercised from day one (spec section 0:
 * UIはモックではなく、MVPから実データに接続可能な境界を持たせる). Onboarding and the
 * Discover deck replace this screen in Phase 1.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { HealthResponse, Paper } from '@papermatch/shared-types';

import { NetworkError } from '../src/api/client';
import { useApiClient } from '../src/api/useApi';
import { PressableRow } from '../src/components/PressableRow';
import { Text } from '../src/components/Text';
import { translate } from '../src/i18n';
import { useTheme, useThemeControls } from '../src/theme/ThemeProvider';
import type { ColorSchemePreference } from '../src/theme/theme';

type ApiState =
  | { kind: 'loading' }
  | { kind: 'ready'; health: HealthResponse; papers: Paper[] }
  | { kind: 'offline' };

const THEME_OPTIONS: ColorSchemePreference[] = ['system', 'light', 'dark'];

export default function FoundationScreen() {
  const theme = useTheme();
  const { preference, setPreference } = useThemeControls();
  const insets = useSafeAreaInsets();
  const api = useApiClient();
  const [state, setState] = useState<ApiState>({ kind: 'loading' });

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const [health, papers] = await Promise.all([api.health(), api.papers({ limit: 5 })]);
      setState({ kind: 'ready', health, papers: papers.papers });
    } catch (error) {
      // Spec section 25: an unreachable API is a state the UI shows calmly, not a crash.
      if (error instanceof NetworkError) {
        setState({ kind: 'offline' });
        return;
      }
      setState({ kind: 'offline' });
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const t = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
    translate('ja', key, params);

  return (
    <ScrollView
      style={{ backgroundColor: theme.color.background }}
      contentContainerStyle={[
        styles.container,
        {
          paddingHorizontal: theme.spacing.screenHorizontal,
          paddingTop: insets.top + theme.spacing.xl,
          paddingBottom: insets.bottom + theme.spacing.xxl,
          gap: theme.spacing.lg,
        },
      ]}
    >
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="title" accessibilityRole="header">
          {t('app.name')}
        </Text>
        <Text variant="caption" tone="secondary">
          {t('app.tagline')}
        </Text>
      </View>

      <View
        style={[
          styles.card,
          {
            backgroundColor: theme.color.card,
            borderColor: theme.color.border,
            borderRadius: theme.radius.card,
            padding: theme.spacing.cardPadding,
            gap: theme.spacing.md,
          },
        ]}
      >
        <Text variant="label" accessibilityRole="header">
          {t('status.title')}
        </Text>
        <Text variant="caption" tone="secondary">
          {t('status.description')}
        </Text>

        {state.kind === 'loading' ? (
          <ActivityIndicator accessibilityLabel={t('status.api')} color={theme.color.accent} />
        ) : state.kind === 'offline' ? (
          <View style={{ gap: theme.spacing.sm }}>
            {/* Wording and an icon-free label: colour alone never carries the state. */}
            <Text tone="warning">{t('status.api.offline')}</Text>
            <PressableRow onPress={() => void load()} accessibilityLabel={t('status.retry')}>
              <Text tone="accent">{t('status.retry')}</Text>
            </PressableRow>
          </View>
        ) : (
          <View style={{ gap: theme.spacing.sm }}>
            <Row
              label={t('status.api')}
              value={
                state.health.status === 'ok' ? t('status.api.ok') : t('status.api.degraded')
              }
              tone={state.health.status === 'ok' ? 'saved' : 'warning'}
            />
            <Row
              label={t('status.papers')}
              value={t('status.papersLoaded', { count: state.papers.length })}
            />
            {state.papers.slice(0, 3).map((paper) => (
              <View key={paper.canonicalId} style={{ gap: 2 }}>
                <Text variant="caption">{paper.title}</Text>
                <Text variant="caption" tone="secondary">
                  {paper.year} · {paper.venue ?? '—'} ·{' '}
                  {paper.provenance.licenseId ?? t('paper.licenseUnknown')}
                </Text>
              </View>
            ))}
          </View>
        )}
      </View>

      <View
        style={[
          styles.card,
          {
            backgroundColor: theme.color.card,
            borderColor: theme.color.border,
            borderRadius: theme.radius.card,
            padding: theme.spacing.cardPadding,
            gap: theme.spacing.md,
          },
        ]}
      >
        <Text variant="label" accessibilityRole="header">
          {t('status.theme')}
        </Text>
        <View style={{ gap: theme.spacing.sm }}>
          {THEME_OPTIONS.map((option) => (
            <PressableRow
              key={option}
              onPress={() => setPreference(option)}
              accessibilityLabel={t(`theme.${option}` as Parameters<typeof translate>[1])}
            >
              <Text>{t(`theme.${option}` as Parameters<typeof translate>[1])}</Text>
              {/* A checkmark, not just a colour change (spec section 20). */}
              <Text tone={preference === option ? 'accent' : 'secondary'}>
                {preference === option ? '✓' : ''}
              </Text>
            </PressableRow>
          ))}
        </View>

        <Row
          label={t('status.reduceMotion')}
          value={theme.reduceMotion ? t('status.on') : t('status.off')}
        />
        <Row label={t('status.fontScale')} value={`×${theme.fontScale.toFixed(2)}`} />
      </View>
    </ScrollView>
  );
}

function Row({
  label,
  value,
  tone = 'primary',
}: {
  label: string;
  value: string;
  tone?: 'primary' | 'secondary' | 'accent' | 'warning' | 'saved';
}) {
  return (
    <View style={styles.row} accessibilityLabel={`${label}: ${value}`}>
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Text variant="caption" tone={tone}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
  },
  card: {
    borderWidth: StyleSheet.hairlineWidth,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
});
