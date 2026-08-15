/**
 * Before you read, and Why it matters (spec section 8), behind the downward swipe.
 *
 * Section 8 shapes this sheet with two instructions:
 *
 * * **強制表示しない.** The sheet opens only when asked — a downward swipe or its button —
 *   and an empty section is a normal outcome with its reason printed, not an error state.
 *   The paper is fully readable without anything on this screen.
 * * **AI生成であることを明示する.** Every item carries a label saying where it came from:
 *   `AI 生成` for model output, `論文本文より` for a phrase quoted from the abstract itself,
 *   `分野` for a taxonomy fact. The label sits on the item, not in a footnote, because the
 *   three kinds arrive mixed in one list and a single banner would let a generated gloss
 *   borrow the credibility of a quotation (spec section 0).
 *
 * The four Why-it-matters readings render in the spec's order. Ones that came back empty
 * show their reason in place rather than disappearing: four headings that are sometimes two
 * would read as the app forgetting, and the reason ("this needs the abstract to position
 * the work, and it does not") is itself information about the paper.
 */
import { Modal, ScrollView, StyleSheet, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import type { ExplanationItem, ExplanationSection } from '@papermatch/shared-types';

import { explanationQuery } from '../api/queries';
import { useApiClient } from '../api/useApi';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export interface BeforeReadSheetProps {
  visible: boolean;
  locale: 'ja' | 'en';
  paperId: string | null;
  paperTitle: string | null;
  onClose: () => void;
  /**
   * False while the stored token is still being read back at start-up.
   *
   * Passed in rather than read from the session here: this sheet is presentational, and a
   * component that reaches for the session is one its tests have to stand a whole provider
   * up for. `saved.tsx` gates its queries the same way, for the same reason.
   *
   * Defaults to true so a caller that has no session concept (the visual harness) renders
   * normally.
   */
  ready?: boolean;
}

export function BeforeReadSheet({
  visible,
  locale,
  paperId,
  paperTitle,
  onClose,
  ready = true,
}: BeforeReadSheetProps) {
  const theme = useTheme();
  const t = (key: MessageKey) => translate(locale, key);

  return (
    <Modal
      visible={visible}
      animationType={theme.reduceMotion ? 'fade' : 'slide'}
      transparent
      onRequestClose={onClose}
      accessibilityViewIsModal
    >
      <View style={styles.backdrop}>
        <View
          style={[
            styles.sheet,
            {
              backgroundColor: theme.color.card,
              borderTopLeftRadius: theme.radius.card,
              borderTopRightRadius: theme.radius.card,
              padding: theme.spacing.screenHorizontal,
              gap: theme.spacing.sm,
            },
          ]}
        >
          <Text variant="label" accessibilityRole="header">
            {t('explain.title')}
          </Text>
          {paperTitle !== null && (
            <Text variant="caption" tone="secondary" numberOfLines={2}>
              {paperTitle}
            </Text>
          )}

          {/* Content only mounts while the sheet is open, so nothing is fetched for cards
              that merely scroll past (spec sections 8, 25). */}
          {visible && <SheetBody locale={locale} paperId={paperId} ready={ready} />}

          <PressableRow onPress={onClose} accessibilityLabel={t('explain.close')}>
            <Text>{t('explain.close')}</Text>
          </PressableRow>
        </View>
      </View>
    </Modal>
  );
}

function SheetBody({
  locale,
  paperId,
  ready,
}: {
  locale: 'ja' | 'en';
  paperId: string | null;
  ready: boolean;
}) {
  const api = useApiClient();
  const t = (key: MessageKey) => translate(locale, key);
  const query = useQuery(explanationQuery(api, paperId, ready));

  // Waiting for the session looks the same to a reader as waiting for the answer, and it
  // is: both end with the explanation appearing. Reporting it as a failure would not.
  if (query.isPending || !ready) {
    return (
      <Text tone="secondary" accessibilityLiveRegion="polite">
        {t('explain.loading')}
      </Text>
    );
  }

  if (query.isError || query.data === undefined) {
    return (
      <View style={styles.block}>
        {/* The paper is unaffected, and the message says so: an explanation failing to
            load must not read as the card being broken. */}
        <Text tone="secondary" accessibilityLiveRegion="polite">
          {t('explain.loadFailed')}
        </Text>
        <PressableRow onPress={() => void query.refetch()} accessibilityLabel={t('explain.retry')}>
          <Text>{t('explain.retry')}</Text>
        </PressableRow>
      </View>
    );
  }

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
      <Section
        locale={locale}
        heading={t('explain.beforeYouRead')}
        section={query.data.beforeYouRead}
      />
      <Text variant="label" accessibilityRole="header">
        {t('explain.whyItMatters')}
      </Text>
      <WhyItMatters locale={locale} sections={query.data.whyItMatters} />
    </ScrollView>
  );
}

/**
 * Section 8's four readings — or, when none of them could be answered, one sentence.
 *
 * The default provider refuses all four for the same reason (it will not invent a claim
 * about what a paper means to somebody). Rendering that per audience printed the identical
 * paragraph four times under four headings, which reads as the screen being broken rather
 * than as the app declining to guess. Found by looking at it.
 *
 * The collapse is conditional on the reasons actually matching: four *different* absences
 * are four different facts, and a reader deciding whether to configure a model wants to
 * see which ones a model would fill in.
 */
function WhyItMatters({
  locale,
  sections,
}: {
  locale: 'ja' | 'en';
  sections: ExplanationSection[];
}) {
  const reasons = new Set(
    sections.map((section) =>
      section.items.length === 0 ? (section.unavailableReason ?? '') : '',
    ),
  );
  const allEmptyForOneReason =
    sections.length > 0 &&
    sections.every((section) => section.items.length === 0 && section.unavailableReason) &&
    reasons.size === 1;

  if (allEmptyForOneReason) {
    return (
      <View style={styles.block}>
        <Text variant="caption" tone="secondary">
          {sections[0]?.unavailableReason}
        </Text>
      </View>
    );
  }

  return (
    <>
      {sections.map((section) => (
        <Section
          key={section.audience}
          locale={locale}
          heading={audienceLabel(locale, section.audience)}
          section={section}
        />
      ))}
    </>
  );
}

function Section({
  locale,
  heading,
  section,
}: {
  locale: 'ja' | 'en';
  heading: string;
  section: ExplanationSection;
}) {
  return (
    <View style={styles.block}>
      <Text variant="body" accessibilityRole="header">
        {heading}
      </Text>
      {section.items.map((item, index) => (
        <Item key={`${item.kind}-${index}`} locale={locale} item={item} />
      ))}
      {section.items.length === 0 && (
        // An empty section is a normal outcome (強制表示しない), and the reason is what
        // stops it reading as a fault. The server supplies one whenever it has nothing.
        <Text variant="caption" tone="secondary">
          {section.unavailableReason ?? translate(locale, 'explain.loadFailed')}
        </Text>
      )}
    </View>
  );
}

function Item({ locale, item }: { locale: 'ja' | 'en'; item: ExplanationItem }) {
  const theme = useTheme();
  return (
    <View style={styles.item}>
      <View style={styles.itemHeader}>
        <Text style={styles.itemTitle}>{item.title}</Text>
        {/* On the item, not in a footnote: the kinds arrive mixed, and one banner would
            let a generated gloss borrow the credibility of a quotation (spec section 0). */}
        <Text
          variant="caption"
          tone="secondary"
          style={[styles.badge, { borderColor: theme.color.border }]}
        >
          {sourceLabel(locale, item.source)}
        </Text>
      </View>
      {item.detail !== null && (
        <Text variant="caption" tone="secondary">
          {item.detail}
        </Text>
      )}
    </View>
  );
}

function sourceLabel(locale: 'ja' | 'en', source: ExplanationItem['source']): string {
  if (source === 'abstract') return translate(locale, 'explain.quotedLabel');
  if (source === 'taxonomy') return translate(locale, 'explain.taxonomyLabel');
  return translate(locale, 'explain.aiLabel');
}

function audienceLabel(locale: 'ja' | 'en', audience: ExplanationSection['audience']): string {
  const keys: Partial<Record<string, MessageKey>> = {
    beginner: 'explain.audience.beginner',
    researcher: 'explain.audience.researcher',
    application: 'explain.audience.application',
    field_history: 'explain.audience.field_history',
  };
  const key = keys[audience];
  return key === undefined ? audience : translate(locale, key);
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  sheet: {
    maxHeight: '85%',
  },
  scroll: { flexGrow: 0 },
  scrollContent: { gap: 16, paddingVertical: 8 },
  block: { gap: 8 },
  item: { gap: 2 },
  itemHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  itemTitle: { flexShrink: 1 },
  badge: {
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 6,
    paddingVertical: 1,
    overflow: 'hidden',
  },
});
