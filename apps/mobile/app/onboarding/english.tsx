/** Onboarding step 3: English level (spec section 18). */
import { useRouter } from 'expo-router';

import { ENGLISH_LEVELS, type EnglishLevel } from '@papermatch/shared-types';

import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { OnboardingStep } from '../../src/onboarding/OnboardingStep';
import { useOnboardingStore } from '../../src/onboarding/store';

export default function EnglishStep() {
  const router = useRouter();
  const { englishLevel, setEnglishLevel } = useOnboardingStore();

  return (
    <OnboardingStep
      step={3}
      titleKey="onboarding.english.title"
      hintKey="onboarding.english.hint"
      locale="ja"
      onBack={() => router.back()}
      onNext={() => router.push('/onboarding/math')}
      onSkip={() => router.replace('/(tabs)')}
    >
      {ENGLISH_LEVELS.map((level) => {
        const label = translate('ja', `english.${level}` as MessageKey);
        const selected = englishLevel === level;
        return (
          <PressableRow
            key={level}
            onPress={() => setEnglishLevel(level as EnglishLevel)}
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
