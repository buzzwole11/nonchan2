/**
 * Choosing a way through a paper (spec section 17).
 *
 * Four routes — 全体を知る / 数式を追う / 結果だけ見る / 引用に使えるか確認 — over the same
 * material, selected differently. The server decides what is on each route; this shows it.
 *
 * **A step the app holds and a step it does not are drawn differently, on purpose.** A held
 * step shows its content: the abstract sentence, the equation's number, the licence. An
 * unheld step is the last one on every route and is the handover to the original paper. The
 * app has never seen a paper's body, so section 17's example route — Figure 1, the
 * introduction's first paragraphs — stops here. Drawing the two the same way would let a
 * reader believe the route covers the paper, and they would find out otherwise while
 * scrolling a PDF looking for something we never claimed to have checked.
 *
 * **The route says what it does not cover** rather than trailing off. 「本文は含まれません」
 * is a short sentence and it is the difference between a route the reader can trust and one
 * they stop trusting the first time it runs out.
 */
import { useState } from 'react';
import { Modal, ScrollView, StyleSheet, View } from 'react-native';

import type { Paper, ReadingPurpose, ReadingRoute, ReadingStep } from '@papermatch/shared-types';

import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export interface ReadingPathSheetProps {
  visible: boolean;
  paper: Paper;
  routes: ReadingRoute[];
  locale: 'ja' | 'en';
  loading?: boolean;
  onClose: () => void;
  onOpenSource: (url: string) => void;
}

export function ReadingPathSheet({
  visible,
  paper,
  routes,
  locale,
  loading = false,
  onClose,
  onOpenSource,
}: ReadingPathSheetProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const [purpose, setPurpose] = useState<ReadingPurpose>('overview');
  const route = routes.find((candidate) => candidate.purpose === purpose) ?? null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View
          style={{
            backgroundColor: theme.color.card,
            borderTopLeftRadius: theme.radius.sheet,
            borderTopRightRadius: theme.radius.sheet,
            padding: theme.spacing.lg,
            gap: theme.spacing.sm,
            maxHeight: '88%',
          }}
        >
          <View style={styles.header}>
            <Text variant="label" accessibilityRole="header">
              {t('readingPath.heading')}
            </Text>
            <PressableRow onPress={onClose} accessibilityLabel={t('common.close')}>
              <Text variant="label" tone="accent">
                {t('common.close')}
              </Text>
            </PressableRow>
          </View>

          <Text variant="caption" tone="secondary" numberOfLines={2}>
            {paper.title}
          </Text>

          <ScrollView contentContainerStyle={{ gap: theme.spacing.sm }}>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
              {routes.map((candidate) => (
                <Chip
                  key={candidate.purpose}
                  label={t(`readingPurpose.${candidate.purpose}` as MessageKey)}
                  selected={candidate.purpose === purpose}
                  tone="accent"
                  onPress={() => setPurpose(candidate.purpose)}
                  accessibilityLabel={t(`readingPurpose.${candidate.purpose}` as MessageKey)}
                />
              ))}
            </View>

            {loading && (
              <Text variant="caption" tone="secondary">
                {t('common.loading')}
              </Text>
            )}

            {route !== null && (
              <View style={{ gap: theme.spacing.xs }}>
                {route.steps.map((step, index) => (
                  <StepRow
                    key={`${step.kind}:${step.labelKey}:${index}`}
                    step={step}
                    index={index}
                    paper={paper}
                    locale={locale}
                    onOpenSource={onOpenSource}
                  />
                ))}

                {/* Named, not left to be discovered. A route that quietly stops at the
                    abstract is one the reader stops trusting the first time they notice. */}
                {route.missing.includes('full_text') && (
                  <Text variant="caption" tone="secondary">
                    {t('readingPath.noFullText')}
                  </Text>
                )}
                {route.missing.includes('equations') && (
                  <Text variant="caption" tone="secondary">
                    {t('readingPath.noEquations')}
                  </Text>
                )}
                {route.missing.includes('abstract_segments') && (
                  <Text variant="caption" tone="secondary">
                    {t('readingPath.noSegments')}
                  </Text>
                )}
              </View>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function StepRow({
  step,
  index,
  paper,
  locale,
  onOpenSource,
}: {
  step: ReadingStep;
  index: number;
  paper: Paper;
  locale: 'ja' | 'en';
  onOpenSource: (url: string) => void;
}) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const label = t(step.labelKey as MessageKey);

  // The abstract sentence itself, sliced by the offsets the server segmented. Showing the
  // text rather than only its role is the whole value of a held step.
  const excerpt =
    step.kind === 'abstract_segment' && step.start !== null && step.end !== null
      ? paper.abstract.slice(step.start, step.end).trim()
      : null;

  const detail =
    step.kind === 'equation'
      ? (step.equationNumber ?? t('readingPath.unnumbered'))
      : step.kind === 'metadata'
        ? (step.detail ?? t('readingPath.unknown'))
        : null;

  const body = (
    <View
      style={{
        gap: 2,
        paddingVertical: theme.spacing.xs,
        paddingLeft: theme.spacing.sm,
        borderLeftWidth: 2,
        // The handover to the original is marked, not merely last. A reader scanning the
        // list should see where the app's knowledge stops without reading to the end.
        borderLeftColor: step.held ? theme.color.border : theme.color.accent,
      }}
    >
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs }}>
        <Text variant="caption" tone="secondary">
          {index + 1}.
        </Text>
        <Text variant="caption">{label}</Text>
        {detail !== null && <Chip label={detail} />}
      </View>
      {excerpt !== null && excerpt.length > 0 && (
        <Text variant="caption" tone="secondary" numberOfLines={4}>
          {excerpt}
        </Text>
      )}
    </View>
  );

  if (step.held || step.detail === null) return body;

  return (
    <PressableRow
      onPress={() => onOpenSource(step.detail as string)}
      accessibilityLabel={`${label}: ${paper.title}`}
      accessibilityHint={t('readingPath.opensExternally')}
    >
      {body}
    </PressableRow>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
});
