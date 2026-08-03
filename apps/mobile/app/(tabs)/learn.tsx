/**
 * Learn: the personal expression dictionary and its review nudge (spec sections 5, 9).
 *
 * The review half sits at the top because that is the point of the tab — spec section 9's
 * 保存を墓場にしない. The dictionary below it is the archive; the thing above it is the
 * re-encounter.
 *
 * The meaning stays hidden until asked for. Showing both at once turns a recall prompt
 * into a reading exercise, and the reason an expression is here at all is that someone
 * wanted to remember it.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { ReviewOutcome } from '@papermatch/shared-types';

import { learnQuery, mathCardsQuery, queryKeys } from '../../src/api/queries';
import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function LearnScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { api, user } = useSession();

  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();

  const { data, isPending } = useQuery(learnQuery(api));
  const due = isPending ? null : (data?.due ?? []);
  const totalDue = data?.totalDue ?? 0;
  const all = data?.expressions ?? [];
  const total = data?.total ?? 0;

  /** Edit the cached lists in place; the cache is what this screen renders from. */
  const patch = (change: (current: NonNullable<typeof data>) => NonNullable<typeof data>) =>
    queryClient.setQueryData<typeof data>(queryKeys.review(), (current) =>
      current === undefined ? current : change(current),
    );

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const current = due?.[0] ?? null;

  async function answer(outcome: ReviewOutcome): Promise<void> {
    if (current === null || busy) return;
    setBusy(true);
    try {
      await api.submitReview(current.id, outcome);
      // Drop the card locally so the next prompt appears at once, rather than making the
      // reader wait on a refetch between two one-line questions.
      patch((current) => ({
        ...current,
        due: current.due.slice(1),
        totalDue: Math.max(0, current.totalDue - 1),
      }));
      setRevealed(false);
    } catch {
      // Leave the card in place; the answer simply did not stick.
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string): Promise<void> {
    const previous = queryClient.getQueryData<typeof data>(queryKeys.review());
    patch((current) => ({
      ...current,
      expressions: current.expressions.filter((row) => row.id !== id),
      total: Math.max(0, current.total - 1),
    }));
    try {
      await api.removeExpression(id);
    } catch {
      queryClient.setQueryData(queryKeys.review(), previous);
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
      <Text variant="title" accessibilityRole="header">
        {t('learn.title')}
      </Text>

      {/* -- review ---------------------------------------------------------- */}
      <View style={{ gap: theme.spacing.sm }}>
        <Text variant="label" accessibilityRole="header">
          {t('learn.review')}
        </Text>

        {due === null ? (
          <ActivityIndicator accessibilityLabel={t('common.loading')} color={theme.color.accent} />
        ) : current === null ? (
          <View style={{ gap: theme.spacing.xs }}>
            <Text variant="caption" tone="secondary">
              {t('learn.noDue')}
            </Text>
            <Text variant="caption" tone="secondary">
              {t('learn.noDueHint')}
            </Text>
          </View>
        ) : (
          <View
            style={[
              styles.card,
              {
                backgroundColor: theme.color.translationSurface,
                borderColor: theme.color.border,
                borderRadius: theme.radius.card,
                padding: theme.spacing.cardPadding,
                gap: theme.spacing.md,
              },
            ]}
          >
            <Text variant="caption" tone="secondary">
              {t('learn.due', { count: totalDue })}
            </Text>
            <Text variant="abstract">{current.phrase}</Text>

            {current.context !== null && (
              <Text variant="caption" tone="secondary">
                {current.context}
              </Text>
            )}

            {revealed ? (
              <Text variant="body">{current.meaning || '—'}</Text>
            ) : (
              <PressableRow
                onPress={() => setRevealed(true)}
                accessibilityLabel={t('learn.showMeaning')}
              >
                <Text tone="accent">{t('learn.showMeaning')}</Text>
              </PressableRow>
            )}

            {/* Two answers, no score. Spec section 9: 評価や罰ではなく. */}
            <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
              <PressableRow
                onPress={() => void answer('again')}
                disabled={busy}
                accessibilityLabel={t('learn.again')}
                style={{ flex: 1 }}
              >
                <Text tone="secondary">{t('learn.again')}</Text>
              </PressableRow>
              <PressableRow
                onPress={() => void answer('got_it')}
                disabled={busy}
                accessibilityLabel={t('learn.gotIt')}
                style={{ flex: 1 }}
              >
                <Text tone="saved">{t('learn.gotIt')}</Text>
              </PressableRow>
            </View>
          </View>
        )}
      </View>

      {/* -- dictionary ------------------------------------------------------ */}
      <View style={{ gap: theme.spacing.sm }}>
        <Text variant="label" accessibilityRole="header">
          {t('learn.expressions')}
        </Text>
        <Text variant="caption" tone="secondary">
          {t('learn.total', { count: total })}
        </Text>

        {all.length === 0 ? (
          <View style={{ gap: theme.spacing.xs }}>
            <Text variant="caption" tone="secondary">
              {t('learn.empty')}
            </Text>
            <Text variant="caption" tone="secondary">
              {t('learn.emptyHint')}
            </Text>
          </View>
        ) : (
          all.map((expression) => (
            <View
              key={expression.id}
              style={[
                styles.card,
                {
                  backgroundColor: theme.color.card,
                  borderColor: theme.color.border,
                  borderRadius: theme.radius.tile,
                  padding: theme.spacing.lg,
                  gap: theme.spacing.xs,
                },
              ]}
            >
              <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
                <Chip label={t(`kind.${expression.kind}` as MessageKey)} />
                <Chip label={t('learn.reviewCount', { count: expression.reviewCount })} />
              </View>
              <Text variant="body">{expression.phrase}</Text>
              <Text variant="caption" tone="secondary">
                {expression.meaning || '—'}
              </Text>
              {expression.context !== null && (
                <Text variant="caption" tone="secondary">
                  {expression.context}
                </Text>
              )}
              <PressableRow
                onPress={() => void remove(expression.id)}
                accessibilityLabel={`${t('learn.remove')}: ${expression.phrase}`}
                style={{ borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0 }}
              >
                <Text variant="caption" tone="warning">
                  {t('learn.remove')}
                </Text>
              </PressableRow>
            </View>
          ))
        )}
      </View>

      <MathCards locale={locale} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: StyleSheet.hairlineWidth,
  },
});

/**
 * Maths cards, reachable from Learn.
 *
 * Spec section 10 lists four ways into a card and this is the one that needs nothing else
 * built first: 保存した論文に数式カードがある場合に通知 needs notifications, the Discover
 * mix needs the recommender, and the Canvas tile needs the Canvas. Learn already exists
 * and is where a reader goes to revisit something.
 */
function MathCards({ locale }: { locale: 'ja' | 'en' }) {
  const theme = useTheme();
  const { api } = useSession();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const { data: cards } = useQuery(mathCardsQuery(api));

  if (cards === undefined || cards.length === 0) return null;

  return (
    <View style={{ gap: theme.spacing.sm, marginTop: theme.spacing.xl }}>
      <Text variant="label" accessibilityRole="header">
        {t('learn.mathCards')}
      </Text>
      {cards.map((card) => (
        <Link key={card.id} href={`/math/${card.id}`} asChild>
          <PressableRow accessibilityLabel={card.title}>
            <View style={{ gap: theme.spacing.xs }}>
              <Text variant="caption" tone="secondary">
                {t(`mathCardType.${card.cardType}` as MessageKey)}
              </Text>
              <Text>{card.title}</Text>
            </View>
          </PressableRow>
        </Link>
      ))}
    </View>
  );
}
