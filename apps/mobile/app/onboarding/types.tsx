/** Onboarding step 2: kinds of paper (spec section 18: 論文種別). */
import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { PAPER_TYPES, type PaperType } from '@papermatch/shared-types';

import { Chip } from '../../src/components/Chip';
import { type MessageKey, translate } from '../../src/i18n';
import { OnboardingStep } from '../../src/onboarding/OnboardingStep';
import { useOnboardingStore } from '../../src/onboarding/store';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function TypesStep() {
  const router = useRouter();
  const theme = useTheme();
  const { paperTypes, togglePaperType } = useOnboardingStore();

  return (
    <OnboardingStep
      step={2}
      titleKey="onboarding.types.title"
      hintKey="onboarding.types.hint"
      locale="ja"
      onBack={() => router.back()}
      onNext={() => router.push('/onboarding/english')}
      onSkip={() => router.replace('/(tabs)')}
    >
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
        {PAPER_TYPES.map((type) => (
          <Chip
            key={type}
            label={translate('ja', `paperType.${type}` as MessageKey)}
            selected={paperTypes.includes(type as PaperType)}
            tone="accent"
            onPress={() => togglePaperType(type as PaperType)}
          />
        ))}
      </View>
    </OnboardingStep>
  );
}
