/** Onboarding step 1: research fields (spec section 18). */
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';

import type { Field } from '@papermatch/shared-types';

import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { Text } from '../../src/components/Text';
import { OnboardingStep } from '../../src/onboarding/OnboardingStep';
import { useOnboardingStore } from '../../src/onboarding/store';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function FieldsStep() {
  const router = useRouter();
  const theme = useTheme();
  const { api } = useSession();
  const { fieldIds, toggleField } = useOnboardingStore();
  const [fields, setFields] = useState<Field[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .fields()
      .then((response) => {
        if (!cancelled) setFields(response.fields);
      })
      .catch(() => {
        if (!cancelled) setFields([]);
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const roots = (fields ?? []).filter((f) => f.parentId === null);

  return (
    <OnboardingStep
      step={1}
      titleKey="onboarding.fields.title"
      hintKey="onboarding.fields.hint"
      locale="ja"
      onNext={() => router.push('/onboarding/types')}
      onSkip={() => router.replace('/(tabs)')}
      nextDisabled={fieldIds.length === 0}
      blockedReasonKey="onboarding.needsField"
    >
      {fields === null && <ActivityIndicator color={theme.color.accent} />}
      {roots.map((root) => (
        <View key={root.id} style={{ gap: theme.spacing.sm, marginBottom: theme.spacing.md }}>
          <Text variant="label">{root.label.ja}</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
            {(fields ?? [])
              .filter((f) => f.parentId === root.id)
              .map((field) => (
                <Chip
                  key={field.id}
                  label={field.label.ja}
                  selected={fieldIds.includes(field.id)}
                  tone="accent"
                  onPress={() => toggleField(field.id)}
                />
              ))}
          </View>
        </View>
      ))}
    </OnboardingStep>
  );
}
