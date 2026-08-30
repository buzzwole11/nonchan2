/**
 * Shared frame for the five onboarding questions (spec section 18).
 *
 * The section asks exactly five things before the first card, so the frame carries the
 * step counter and the Back / Next pair and each screen supplies only its question. "Set
 * up later" is always available: spec section 4 puts the first card close, and a
 * five-screen wall before anything happens is the opposite of that.
 */
import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export const ONBOARDING_STEPS = 5;

export interface OnboardingStepProps {
  step: number;
  titleKey: MessageKey;
  hintKey: MessageKey;
  locale: 'ja' | 'en';
  children: ReactNode;
  onBack?: () => void;
  onNext: () => void;
  onSkip: () => void;
  nextDisabled?: boolean;
  /** Shown under the controls when Next is blocked, so the block is explained. */
  blockedReasonKey?: MessageKey;
}

export function OnboardingStep({
  step,
  titleKey,
  hintKey,
  locale,
  children,
  onBack,
  onNext,
  onSkip,
  nextDisabled = false,
  blockedReasonKey,
}: OnboardingStepProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.background }}>
      <ScrollView
        contentContainerStyle={{
          paddingHorizontal: theme.spacing.screenHorizontal,
          paddingTop: insets.top + theme.spacing.xl,
          paddingBottom: theme.spacing.xl,
          gap: theme.spacing.lg,
        }}
      >
        <Text variant="caption" tone="secondary">
          {t('onboarding.step', { current: step, total: ONBOARDING_STEPS })}
        </Text>
        <Text variant="title" accessibilityRole="header">
          {t(titleKey)}
        </Text>
        <Text variant="caption" tone="secondary">
          {t(hintKey)}
        </Text>
        <View style={{ gap: theme.spacing.sm }}>{children}</View>
      </ScrollView>

      <View
        style={[
          styles.controls,
          {
            paddingHorizontal: theme.spacing.screenHorizontal,
            paddingBottom: insets.bottom + theme.spacing.lg,
            paddingTop: theme.spacing.md,
            borderTopColor: theme.color.border,
            gap: theme.spacing.sm,
          },
        ]}
      >
        {nextDisabled && blockedReasonKey !== undefined && (
          <Text variant="caption" tone="warning">
            {t(blockedReasonKey)}
          </Text>
        )}
        <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
          {onBack !== undefined && (
            <PressableRow
              onPress={onBack}
              accessibilityLabel={t('onboarding.back')}
              style={{ flex: 1 }}
            >
              <Text variant="label" tone="secondary">
                {t('onboarding.back')}
              </Text>
            </PressableRow>
          )}
          <PressableRow
            onPress={onNext}
            disabled={nextDisabled}
            accessibilityLabel={t(
              step === ONBOARDING_STEPS ? 'onboarding.done' : 'onboarding.next',
            )}
            style={{
              flex: 2,
              backgroundColor: theme.color.accent,
              borderColor: theme.color.accent,
            }}
          >
            <Text variant="label" style={{ color: theme.color.card }}>
              {t(step === ONBOARDING_STEPS ? 'onboarding.done' : 'onboarding.next')}
            </Text>
          </PressableRow>
        </View>
        <PressableRow
          onPress={onSkip}
          accessibilityLabel={t('onboarding.skip')}
          style={{ borderWidth: 0, backgroundColor: 'transparent' }}
        >
          <Text variant="caption" tone="secondary">
            {t('onboarding.skip')}
          </Text>
        </PressableRow>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  controls: {
    borderTopWidth: StyleSheet.hairlineWidth,
  },
});
