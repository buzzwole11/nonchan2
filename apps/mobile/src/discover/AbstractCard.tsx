/**
 * The Abstract card (spec section 6).
 *
 * Layout follows the section directly: metadata chips on top, the original English
 * abstract as the body, identifiers and counts at the bottom. The abstract is the
 * protagonist — translation and explanation are additions below it, never replacements
 * (spec section 3: Original first).
 *
 * Sentences are individually tappable so a range can be selected with exact offsets; see
 * `src/reading/sentences.ts` for why selection works this way.
 */
import { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import type { FeedItem, Paper } from '@papermatch/shared-types';

import { Chip } from '../components/Chip';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { type SelectionRange, isSelected, splitSentences } from '../reading/sentences';
import { useTheme } from '../theme/ThemeProvider';

export interface AbstractCardProps {
  item: FeedItem;
  locale: 'ja' | 'en';
  selection: SelectionRange | null;
  onSelectSentence: (index: number) => void;
  onOpenSource: () => void;
  /** Rendered flat and non-interactive when it is the card behind the current one. */
  behind?: boolean;
}

function readingMinutes(paper: Paper): string {
  return `${paper.estimatedReadingMinutes.toFixed(1)}`;
}

/** Formula density as a three-step word, never a bare number (spec section 6). */
function densityLabel(density: number): string {
  if (density <= 0.5) return '—';
  if (density <= 2.5) return '·';
  if (density <= 5) return '··';
  return '···';
}

export function AbstractCard({
  item,
  locale,
  selection,
  onSelectSentence,
  onOpenSource,
  behind = false,
}: AbstractCardProps) {
  const theme = useTheme();
  const { paper } = item;
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const sentences = useMemo(() => splitSentences(paper.abstract), [paper.abstract]);

  const primaryIdentifier =
    paper.identifiers.find((i) => i.kind === 'doi') ??
    paper.identifiers.find((i) => i.kind === 'arxiv') ??
    null;

  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.color.card,
          borderColor: theme.color.border,
          borderRadius: theme.radius.card,
          padding: theme.spacing.cardPadding,
          // Themed, not a literal: a black shadow is invisible against the dark card
          // surface, and the stack depth is the only cue that a second card is behind
          // this one.
          shadowColor: theme.color.shadow,
          shadowOpacity: behind ? 0 : theme.elevation.card.shadowOpacity,
          shadowRadius: theme.elevation.card.shadowRadius,
          shadowOffset: { width: 0, height: theme.elevation.card.shadowOffsetY },
          elevation: behind ? 0 : theme.elevation.card.elevation,
        },
      ]}
      // The card behind is decorative; announcing it would read the same paper twice.
      // All three props are needed: iOS reads the first, Android the second, and
      // react-native-web maps neither — without `aria-hidden` the browser's accessibility
      // tree contains both papers, which was visible in the exported web build.
      accessibilityElementsHidden={behind}
      importantForAccessibility={behind ? 'no-hide-descendants' : 'yes'}
      aria-hidden={behind || undefined}
    >
      {/* -- header ------------------------------------------------------------- */}
      <View style={[styles.chipRow, { gap: theme.spacing.sm }]}>
        <Chip label={paper.primaryFieldId ?? '—'} tone="accent" />
        {paper.paperTypes.slice(0, 2).map((type) => (
          <Chip key={type} label={t(`paperType.${type}` as MessageKey)} />
        ))}
        <Chip label={String(paper.year)} />
        <Chip label={t('paper.readingMinutes', { minutes: readingMinutes(paper) })} />
        <Chip
          label={t(`english.${paper.englishLevel}` as MessageKey)}
          accessibilityLabel={`${t('card.englishLevel')}: ${t(`english.${paper.englishLevel}` as MessageKey)}`}
        />
        <Chip
          label={`∑ ${densityLabel(paper.mathDensity)}`}
          accessibilityLabel={`${t('card.mathDensity')}: ${densityLabel(paper.mathDensity)}`}
        />
        {/* Open access is stated in words; a green dot alone would not survive greyscale. */}
        <Chip
          label={paper.openAccess === 'closed' ? t('card.notOpenAccess') : t('card.openAccess')}
          tone={paper.openAccess === 'closed' ? 'warning' : 'saved'}
        />
      </View>

      {/* -- why this card ------------------------------------------------------ */}
      <View style={{ marginTop: theme.spacing.md }}>
        <Text
          variant="caption"
          tone="secondary"
          accessibilityLabel={`${t('discover.whyThis')}: ${item.reasonText}`}
        >
          {item.reasonText}
        </Text>
      </View>

      {/* -- title and authors -------------------------------------------------- */}
      <View style={{ marginTop: theme.spacing.lg, gap: theme.spacing.xs }}>
        <Text variant="title" accessibilityRole="header">
          {paper.title}
        </Text>
        <Text variant="caption" tone="secondary">
          {paper.authors.map((a) => a.name).join(', ')}
        </Text>
        <Text variant="caption" tone="secondary">
          {paper.venue ?? '—'}
        </Text>
      </View>

      {/* -- abstract ----------------------------------------------------------- */}
      <ScrollView
        style={{ marginTop: theme.spacing.lg }}
        contentContainerStyle={{ paddingBottom: theme.spacing.md }}
        scrollEnabled={!behind}
      >
        <Text variant="caption" tone="secondary" style={{ marginBottom: theme.spacing.sm }}>
          {t('discover.tapToTranslate')}
        </Text>
        {/*
          Nested <Text>, not a row of Pressables.

          Sentences have to flow into one paragraph and wrap at the card edge. Laid out as
          separate flex children they each became one unwrappable line, and the abstract —
          the body of the card in spec section 6 — was clipped after about forty
          characters. Nested text is the only structure that gives per-sentence tap
          targets *and* ordinary line breaking; each child keeps its own accessibility
          role and label, so every sentence is still reachable individually.
        */}
        <Text variant="abstract">
          {sentences.map((sentence) => {
            const active = isSelected(selection, sentence.index);
            return (
              <Text
                key={sentence.index}
                variant="abstract"
                onPress={behind ? undefined : () => onSelectSentence(sentence.index)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                accessibilityLabel={sentence.text}
                accessibilityHint={t('discover.tapToTranslate')}
                style={
                  active
                    ? {
                        // Tint *and* underline: the selection has to survive greyscale
                        // and colour-blindness (spec section 20).
                        backgroundColor: theme.color.translationSurface,
                        textDecorationLine: 'underline',
                      }
                    : undefined
                }
              >
                {sentence.text}{' '}
              </Text>
            );
          })}
        </Text>
      </ScrollView>

      {/* -- footer ------------------------------------------------------------- */}
      <View
        style={[
          styles.footer,
          {
            borderTopColor: theme.color.border,
            paddingTop: theme.spacing.md,
            gap: theme.spacing.sm,
          },
        ]}
      >
        <Text variant="caption" tone="secondary">
          {t('card.equations', { count: paper.equationCount })}
        </Text>
        <Pressable
          onPress={onOpenSource}
          disabled={behind}
          accessibilityRole="link"
          accessibilityLabel={t('a11y.openSourceButton')}
          hitSlop={8}
        >
          <Text variant="caption" tone="accent">
            {primaryIdentifier
              ? `${primaryIdentifier.kind}: ${primaryIdentifier.value}`
              : paper.sourceUrl}
          </Text>
        </Pressable>
        <Text variant="caption" tone="secondary">
          {paper.provenance.licenseId ?? t('paper.licenseUnknown')}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    borderWidth: StyleSheet.hairlineWidth,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
});
