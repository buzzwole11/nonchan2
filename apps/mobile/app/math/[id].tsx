/**
 * Focus Mode (spec section 10).
 *
 * "数式を中央に大きく表示し、周囲を暗くする" — the formula is the screen, and everything
 * else is a tab underneath it. The dimming is the point rather than decoration: this is
 * the one place in the app where a reader is meant to stop and look at one thing.
 *
 * Three things here are shaped by what the data can honestly support.
 *
 * * **The detail slider chooses how much of the derivation to show, not how much to
 *   explain.** There is no level that produces steps the card does not contain.
 * * **Withheld steps are named.** Section 12 hides transformations that passed no check;
 *   the header says how many are missing so the derivation cannot read as complete.
 * * **The 極限 tab reports the region each identity was checked on**, taken from the
 *   evidence stored with the step. It makes no claim beyond the checks that ran.
 */

import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type {
  DerivationStepView,
  EquationView,
  MathCardDetailResponse,
} from '@papermatch/shared-types';

import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { MathView } from '../../src/math/MathView';
import {
  DETAIL_LEVELS,
  FOCUS_TABS,
  type DetailLevel,
  type DerivationView,
  type FocusTab,
  derivationView,
  gradeAnswer,
  limitNotes,
  nextMoveQuestion,
  rationaleOpenByDefault,
  stepBetween,
  visibleSteps,
} from '../../src/math/focus';
import { ReportSheet, type ReportStatus } from '../../src/math/ReportSheet';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function FocusModeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { api, user } = useSession();

  const [card, setCard] = useState<MathCardDetailResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<FocusTab>('derivation');
  const [detail, setDetail] = useState<DetailLevel>('standard');
  const [reportOpen, setReportOpen] = useState(false);
  const [reportStatus, setReportStatus] = useState<ReportStatus>({ kind: 'idle' });

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = useCallback(
    (key: MessageKey, params?: Record<string, string | number>) => translate(locale, key, params),
    [locale],
  );

  const load = useCallback(async () => {
    if (typeof id !== 'string') return;
    try {
      setCard(await api.mathCard(id));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount; see DECISIONS.md D-026
    void load();
  }, [load]);

  if (failed) {
    return (
      <Centred>
        <Text tone="warning">{t('math.loadFailed')}</Text>
        <PressableRow onPress={() => void load()} accessibilityLabel={t('common.retry')}>
          <Text tone="accent">{t('common.retry')}</Text>
        </PressableRow>
      </Centred>
    );
  }

  if (card === null) {
    return (
      <Centred>
        <ActivityIndicator accessibilityLabel={t('common.loading')} color={theme.color.accent} />
      </Centred>
    );
  }

  const view = derivationView(card.equations, card.steps, detail);
  const shown = visibleSteps(card.steps, detail);
  const lead = view.equations[0];

  return (
    <>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView
        style={{ backgroundColor: theme.color.background }}
        contentContainerStyle={{
          paddingTop: insets.top + theme.spacing.lg,
          paddingBottom: insets.bottom + theme.spacing.xxl,
          gap: theme.spacing.lg,
        }}
      >
        {/* -- the formula, centred and lifted out of everything else ---------------- */}
        <View
          style={{
            backgroundColor: theme.color.formulaSurface,
            paddingVertical: theme.spacing.xl,
            paddingHorizontal: theme.spacing.screenHorizontal,
            gap: theme.spacing.sm,
          }}
        >
          <Text variant="caption" tone="secondary">
            {t(`mathCardType.${card.card.cardType}` as MessageKey)}
          </Text>
          <Text variant="title" accessibilityRole="header">
            {card.card.title}
          </Text>
          {lead !== undefined && (
            <MathView
              latex={lead.latex}
              locale={locale}
              renderable={lead.renderable}
              refusalReasons={lead.refusalReasons}
              accessibilityLabel={card.card.title}
            />
          )}
          <ProvenanceLine card={card} t={t} />
        </View>

        {/* -- tabs ------------------------------------------------------------------ */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{
            paddingHorizontal: theme.spacing.screenHorizontal,
            gap: theme.spacing.sm,
          }}
        >
          {FOCUS_TABS.map((name) => (
            <Chip
              key={name}
              label={t(`math.tab.${name}` as MessageKey)}
              selected={tab === name}
              tone="accent"
              onPress={() => setTab(name)}
            />
          ))}
        </ScrollView>

        <View
          style={{
            paddingHorizontal: theme.spacing.screenHorizontal,
            gap: theme.spacing.md,
          }}
        >
          {tab === 'derivation' && (
            <DerivationTab
              card={card}
              view={view}
              shown={shown}
              detail={detail}
              onDetail={setDetail}
              locale={locale}
              t={t}
            />
          )}
          {tab === 'symbols' && <SymbolsTab equations={view.equations} t={t} />}
          {tab === 'structure' && <StructureTab chain={view.equations} locale={locale} />}
          {tab === 'meaning' && <MeaningTab card={card} t={t} />}
          {tab === 'limits' && <LimitsTab steps={card.steps} t={t} />}

          {/* Section 12 requires AI説明は数式的真偽を保証しないことを明示する. Saying the
              content might be wrong and then offering nowhere to disagree is half a
              promise, so the way to disagree sits on the same screen as the label. */}
          <PressableRow
            onPress={() => {
              setReportStatus({ kind: 'idle' });
              setReportOpen(true);
            }}
            accessibilityLabel={t('report.open')}
            style={{ marginTop: theme.spacing.lg }}
          >
            <Text variant="caption" tone="secondary">
              {t('report.open')}
            </Text>
          </PressableRow>
        </View>
      </ScrollView>

      <ReportSheet
        visible={reportOpen}
        locale={locale}
        status={reportStatus}
        onSend={(reason, note) => {
          if (typeof id !== 'string') return;
          setReportStatus({ kind: 'sending' });
          void api
            .reportMathCard(id, { reason, detail: note.trim() || undefined })
            .then((response) =>
              setReportStatus({ kind: 'recorded', already: response.alreadyReported }),
            )
            .catch(() => setReportStatus({ kind: 'failed' }));
        }}
        onClose={() => setReportOpen(false)}
      />
    </>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  const theme = useTheme();
  return (
    <View
      style={{
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: theme.spacing.md,
        backgroundColor: theme.color.background,
      }}
    >
      {children}
    </View>
  );
}

/** Spec section 11: provenance is never signalled by colour alone. */
function ProvenanceLine({
  card,
  t,
}: {
  card: MathCardDetailResponse;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      <Chip label={t(`provenance.${card.card.provenanceKind}` as MessageKey)} />
      {card.card.reviewStatus === 'draft' && <Chip label={t('math.notReviewed')} tone="warning" />}
      {card.hiddenStepCount > 0 && (
        <Chip
          label={t('math.hiddenSteps', { count: card.hiddenStepCount })}
          tone="warning"
          accessibilityLabel={t('math.hiddenSteps', { count: card.hiddenStepCount })}
        />
      )}
    </View>
  );
}

function DerivationTab({
  card,
  view,
  shown,
  detail,
  onDetail,
  locale,
  t,
}: {
  card: MathCardDetailResponse;
  view: DerivationView;
  shown: DerivationStepView[];
  detail: DetailLevel;
  onDetail: (level: DetailLevel) => void;
  locale: 'ja' | 'en';
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();

  if (card.steps.length === 0) {
    return (
      <Text variant="caption" tone="secondary">
        {t('math.noDerivation')}
      </Text>
    );
  }

  return (
    <View style={{ gap: theme.spacing.md }}>
      {/* Spec section 10: 詳細度スライダー. Chips rather than a slider — the levels are
          named states, and a slider would make them look continuous. */}
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="caption" tone="secondary">
          {t('math.detail')}
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          {DETAIL_LEVELS.map((level) => (
            <Chip
              key={level}
              label={t(`math.detail.${level}` as MessageKey)}
              selected={detail === level}
              tone="accent"
              onPress={() => onDetail(level)}
            />
          ))}
        </View>
      </View>

      {view.equations.map((equation, index) => {
        const next = view.equations[index + 1];
        const between = next === undefined ? null : stepBetween(shown, equation, next);
        return (
          <View key={equation.id} style={{ gap: theme.spacing.sm }}>
            <View style={{ gap: theme.spacing.xs }}>
              <Text variant="caption" tone="secondary">
                {t('math.step', { n: index + 1 })}
                {equation.equationNumber === null ? '' : ` · (${equation.equationNumber})`}
              </Text>
              <MathView
                latex={equation.latex}
                locale={locale}
                renderable={equation.renderable}
                refusalReasons={equation.refusalReasons}
              />
            </View>
            {between !== null && <Operation step={between} detail={detail} locale={locale} t={t} />}
            {between === null && next !== undefined && view.collapsed > 0 && (
              // Named, not hidden: a gap with no explanation reads as a rendering fault.
              <Text variant="caption" tone="secondary">
                ↓ {t('math.collapsed', { count: view.collapsed })}
              </Text>
            )}
          </View>
        );
      })}

      <UnderstandingCheck card={card} t={t} />
    </View>
  );
}

/** One arrow between two equations: what happened, and — on request — why. */
function Operation({
  step,
  detail,
  locale,
  t,
}: {
  step: DerivationStepView;
  detail: DetailLevel;
  locale: 'ja' | 'en';
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();
  const [open, setOpen] = useState(rationaleOpenByDefault(detail));

  return (
    <View
      style={{
        borderLeftWidth: 2,
        borderLeftColor: theme.color.border,
        paddingLeft: theme.spacing.md,
        gap: theme.spacing.xs,
      }}
    >
      <Text variant="caption" tone="accent">
        ↓ {step.operation}
      </Text>
      <MathView latex={step.latex} locale={locale} renderable={step.renderable} display={false} />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
        <Chip label={t(`verification.${step.verificationStatus}` as MessageKey)} tone="saved" />
        {/* Spec section 10: 各操作にWhy?ボタン. */}
        <PressableRow onPress={() => setOpen((value) => !value)} accessibilityLabel={t('math.why')}>
          <Text variant="caption" tone="accent">
            {open ? t('math.why.hide') : t('math.why')}
          </Text>
        </PressableRow>
      </View>
      {open && (
        <Text variant="caption" tone="secondary">
          {step.rationale}
        </Text>
      )}
    </View>
  );
}

/** Spec section 10: 理解チェック — 派手な点数化はせず. */
function UnderstandingCheck({
  card,
  t,
}: {
  card: MathCardDetailResponse;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();
  const [chosen, setChosen] = useState<string | null>(null);
  const question = nextMoveQuestion(card.equations, card.steps, 1);
  if (question === null) return null;

  const outcome = chosen === null ? null : gradeAnswer(question, chosen);

  return (
    <View
      style={{
        backgroundColor: theme.color.card,
        borderRadius: theme.radius.tile,
        padding: theme.spacing.md,
        gap: theme.spacing.sm,
      }}
    >
      <Text variant="label" accessibilityRole="header">
        {t('math.check.title')}
      </Text>
      <Text variant="caption" tone="secondary">
        {t('math.check.nextMove')}
      </Text>
      <View style={{ gap: theme.spacing.sm }}>
        {question.options.map((option) => (
          <PressableRow key={option} onPress={() => setChosen(option)} accessibilityLabel={option}>
            <Text variant="caption">{option}</Text>
          </PressableRow>
        ))}
      </View>
      {outcome !== null && (
        <View style={{ gap: theme.spacing.xs }} accessibilityLiveRegion="polite">
          <Text variant="caption" tone={outcome.correct ? 'saved' : 'warning'}>
            {t(outcome.messageKey)}
          </Text>
          {outcome.correct && (
            <Text variant="caption" tone="secondary">
              {question.rationale}
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

/** Spec section 10: 記号タップ — 意味 / 一般的な意味 / 単位 / 適用スコープ. */
function SymbolsTab({
  equations,
  t,
}: {
  equations: EquationView[];
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();
  const symbols = equations.flatMap((e) => e.symbols);

  if (symbols.length === 0) {
    return (
      <Text variant="caption" tone="secondary">
        {t('math.noSymbols')}
      </Text>
    );
  }

  return (
    <View style={{ gap: theme.spacing.md }}>
      {symbols.map((symbol) => (
        <View
          key={`${symbol.symbol}-${symbol.localMeaning}`}
          style={{
            backgroundColor: theme.color.card,
            borderRadius: theme.radius.tile,
            padding: theme.spacing.md,
            gap: theme.spacing.xs,
          }}
        >
          <Text variant="label">{symbol.symbol}</Text>
          <Text variant="caption">{symbol.localMeaning}</Text>
          {symbol.generalMeaning !== null && (
            <Text variant="caption" tone="secondary">
              {t('math.symbol.general')}: {symbol.generalMeaning}
            </Text>
          )}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
            {symbol.unit !== null && <Chip label={`${t('math.symbol.unit')}: ${symbol.unit}`} />}
            <Chip label={t(`math.scope.${symbol.scope}` as MessageKey)} />
            <Chip label={t(`provenance.${symbol.provenanceKind}` as MessageKey)} />
          </View>
        </View>
      ))}
    </View>
  );
}

/** The shape of the argument: which equations it moves between. */
function StructureTab({ chain, locale }: { chain: EquationView[]; locale: 'ja' | 'en' }) {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.spacing.md }}>
      {chain.map((equation, index) => (
        <View key={equation.id} style={{ gap: theme.spacing.xs }}>
          <Text variant="caption" tone="secondary">
            {index + 1}
            {equation.section === null ? '' : ` · ${equation.section}`}
          </Text>
          <MathView
            latex={equation.latex}
            locale={locale}
            renderable={equation.renderable}
            refusalReasons={equation.refusalReasons}
          />
        </View>
      ))}
    </View>
  );
}

function MeaningTab({
  card,
  t,
}: {
  card: MathCardDetailResponse;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();
  const summary = typeof card.card.body.summary === 'string' ? card.card.body.summary : null;
  const why = typeof card.card.body.whyItMatters === 'string' ? card.card.body.whyItMatters : null;

  return (
    <View style={{ gap: theme.spacing.md }}>
      {summary !== null && <Text>{summary}</Text>}
      {why !== null && (
        <View style={{ gap: theme.spacing.xs }}>
          <Text variant="label">{t('math.whyItMatters')}</Text>
          <Text variant="caption" tone="secondary">
            {why}
          </Text>
        </View>
      )}
      {/* The prose above was written by a model, and section 11 says so in words. */}
      <Chip label={t(`provenance.${card.card.provenanceKind}` as MessageKey)} />
    </View>
  );
}

/** Spec section 10's 極限 tab: what was checked, and where. */
function LimitsTab({
  steps,
  t,
}: {
  steps: DerivationStepView[];
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}) {
  const theme = useTheme();
  const notes = limitNotes(steps);

  if (notes.length === 0) {
    return (
      <Text variant="caption" tone="secondary">
        {t('math.noLimits')}
      </Text>
    );
  }

  return (
    <View style={{ gap: theme.spacing.md }}>
      <Text variant="caption" tone="secondary">
        {t('math.limits.explainer')}
      </Text>
      {notes.map((note) => (
        <View
          key={note.operation}
          style={{
            backgroundColor: theme.color.card,
            borderRadius: theme.radius.tile,
            padding: theme.spacing.md,
            gap: theme.spacing.xs,
          }}
        >
          <Text variant="caption">{note.operation}</Text>
          {note.ranges.map((range) => (
            <Text key={range} variant="caption" tone="secondary">
              {range}
            </Text>
          ))}
          {note.dimensional !== null && (
            <Text variant="caption" tone="secondary">
              {note.dimensional}
            </Text>
          )}
          <Chip label={t(`verification.${note.verificationStatus}` as MessageKey)} tone="saved" />
        </View>
      ))}
    </View>
  );
}
