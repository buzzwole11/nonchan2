/**
 * Onboarding step 5: exploration level, and the point where everything is submitted.
 *
 * The five answers go to the server in two requests. If either fails the user is not
 * trapped here — the app moves on and Profile keeps the same controls, because being stuck
 * on the last onboarding screen because the network blinked is worse than starting with
 * defaults (spec section 25).
 */
import { useRouter } from 'expo-router';
import { useState } from 'react';

import { EXPLORATION_LEVELS, type ExplorationLevel } from '@papermatch/shared-types';

import { useSession } from '../../src/api/session';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { OnboardingStep } from '../../src/onboarding/OnboardingStep';
import { useOnboardingStore } from '../../src/onboarding/store';

export default function ExplorationStep() {
  const router = useRouter();
  const { api, refreshUser } = useSession();
  const store = useOnboardingStore();
  const [submitting, setSubmitting] = useState(false);

  async function finish(): Promise<void> {
    setSubmitting(true);
    const interests = store.toInterests();
    try {
      if (interests.length > 0) await api.updateInterests(interests);
      await api.updateSettings({
        englishLevel: store.englishLevel,
        mathLevel: store.mathLevel,
        exploration: store.exploration,
      });
      await refreshUser();
    } catch {
      // Answers stay in the store; Profile offers the same controls.
    } finally {
      setSubmitting(false);
      router.replace('/(tabs)');
    }
  }

  return (
    <OnboardingStep
      step={5}
      titleKey="onboarding.exploration.title"
      hintKey="onboarding.exploration.hint"
      locale="ja"
      onBack={() => router.back()}
      onNext={() => void finish()}
      onSkip={() => router.replace('/(tabs)')}
      nextDisabled={submitting}
    >
      {EXPLORATION_LEVELS.map((level) => {
        const label = translate('ja', `exploration.${level}` as MessageKey);
        const selected = store.exploration === level;
        return (
          <PressableRow
            key={level}
            onPress={() => store.setExploration(level as ExplorationLevel)}
            accessibilityLabel={label}
          >
            <Text>{label}</Text>
            <Text tone={selected ? 'accent' : 'secondary'}>{selected ? '✓' : ''}</Text>
          </PressableRow>
        );
      })}
    </OnboardingStep>
  );
}
