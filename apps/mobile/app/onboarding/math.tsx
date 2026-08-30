/** Onboarding step 4: maths level (spec section 18, Level 0-4). */
import { useRouter } from 'expo-router';

import { MATH_LEVELS, type MathLevel } from '@papermatch/shared-types';

import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { OnboardingStep } from '../../src/onboarding/OnboardingStep';
import { useOnboardingStore } from '../../src/onboarding/store';

export default function MathStep() {
  const router = useRouter();
  const { mathLevel, setMathLevel } = useOnboardingStore();

  return (
    <OnboardingStep
      step={4}
      titleKey="onboarding.math.title"
      hintKey="onboarding.math.hint"
      locale="ja"
      onBack={() => router.back()}
      onNext={() => router.push('/onboarding/exploration')}
      onSkip={() => router.replace('/(tabs)')}
    >
      {MATH_LEVELS.map((level, index) => {
        const label = translate('ja', `math.${level}` as MessageKey);
        const selected = mathLevel === level;
        return (
          <PressableRow
            key={level}
            onPress={() => setMathLevel(level as MathLevel)}
            accessibilityLabel={`Level ${index}: ${label}`}
          >
            <Text>{`Level ${index} · ${label}`}</Text>
            <Text tone={selected ? 'accent' : 'secondary'}>{selected ? '✓' : ''}</Text>
          </PressableRow>
        );
      })}
    </OnboardingStep>
  );
}
