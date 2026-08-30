/**
 * The four roles around the selected paper (spec sections 13, 17).
 *
 * Section 13 asks for 基礎、対立、後続、類似を方向別に表示 on selection, and section 17 says
 * what a role is allowed to be asserted from. This renders the server's answer; it does not
 * classify anything itself, because a second classifier on the client would be a second set
 * of rules to keep honest.
 *
 * **Grouped by role, in a fixed order.** Foundational, follow-up, contrasting, related —
 * oldest ground first, then what came after, then the disagreements, then everything else.
 * The order does not change with the data, so the reader learns where to look instead of
 * re-reading the headings each time.
 *
 * **Every relation says why it is there.** Section 17 requires the evidence to be kept, and
 * keeping it in the database while showing the reader only a label would satisfy the letter
 * of that and none of the point. Each row states the basis — cited in the references, the
 * paper says so, or the abstracts read alike — and a contrast shows the sentence itself.
 *
 * **A confidence number is not shown.** "0.85" tells a reader nothing they can act on, and
 * invites them to compare two numbers that came from different kinds of evidence. The basis
 * is the honest summary and it is a phrase, not a score.
 *
 * **Empty is a real answer.** Nothing in the reader's library relates to this paper on any
 * evidence we have — said plainly, rather than padded out with whatever looked closest.
 */
import { View } from 'react-native';

import type { PaperRelationHit, RelationType } from '@papermatch/shared-types';

import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/** Fixed, so the reader learns the shape of the panel rather than re-reading it. */
const ORDER: RelationType[] = ['foundational', 'follow_up', 'contrasting', 'related'];

export interface RelationListProps {
  relations: PaperRelationHit[];
  locale: 'ja' | 'en';
  loading?: boolean;
  onSelect?: (paperId: string) => void;
}

export function RelationList({ relations, locale, loading = false, onSelect }: RelationListProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  if (loading) {
    return (
      <Text variant="caption" tone="secondary">
        {t('common.loading')}
      </Text>
    );
  }

  if (relations.length === 0) {
    return (
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="caption" tone="secondary" accessibilityLiveRegion="polite">
          {t('relations.none')}
        </Text>
        {/* Said out loud, because "no relations" and "we did not look" are different
            things and the reader cannot tell them apart from an empty list. */}
        <Text variant="caption" tone="secondary">
          {t('relations.noneHint')}
        </Text>
      </View>
    );
  }

  const grouped = ORDER.map((type) => ({
    type,
    items: relations.filter((relation) => relation.relationType === type),
  })).filter((group) => group.items.length > 0);

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text variant="caption" tone="secondary">
        {t('relations.heading')}
      </Text>
      {grouped.map((group) => (
        <View key={group.type} style={{ gap: theme.spacing.xs }}>
          <Text variant="caption" tone="accent" accessibilityRole="header">
            {t(`relation.${group.type}` as MessageKey)}
          </Text>
          {group.items.map((relation) => (
            <RelationRow
              key={`${group.type}:${relation.paper.id}`}
              relation={relation}
              locale={locale}
              onSelect={onSelect}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

function RelationRow({
  relation,
  locale,
  onSelect,
}: {
  relation: PaperRelationHit;
  locale: 'ja' | 'en';
  onSelect?: (paperId: string) => void;
}) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const snippet = relation.evidence.mention?.snippet ?? null;

  const row = (
    <View
      style={{
        gap: 2,
        paddingVertical: theme.spacing.xs,
        borderLeftWidth: 2,
        borderLeftColor: theme.color.border,
        paddingLeft: theme.spacing.sm,
      }}
    >
      <Text variant="caption">{relation.paper.title}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs }}>
        <Chip label={t(`relationBasis.${relation.basis}` as MessageKey)} />
        <Chip label={String(relation.paper.year)} />
      </View>
      {/* The sentence, not a paraphrase of it. A reader told two papers disagree should be
          able to check that claim against what was actually written. */}
      {snippet !== null && (
        <Text variant="caption" tone="secondary" numberOfLines={3}>
          {t('relations.quoted', { snippet })}
        </Text>
      )}
    </View>
  );

  if (onSelect === undefined) return row;
  return (
    <PressableRow
      onPress={() => onSelect(relation.paper.id)}
      accessibilityLabel={`${t(`relation.${relation.relationType}` as MessageKey)}: ${relation.paper.title}`}
      accessibilityHint={t(`relationBasis.${relation.basis}` as MessageKey)}
    >
      {row}
    </PressableRow>
  );
}
