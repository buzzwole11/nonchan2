/**
 * How this paper's equations depend on each other (spec section 28, Phase 7).
 *
 * The server builds the graph from rows somebody wrote down: a symbol's recorded definition,
 * or a derivation step. Nothing here is inferred from two equations resembling each other —
 * an edge saying "this follows from that" is a mathematical claim, and sharing a `\lambda`
 * is not evidence for one.
 *
 * **Drawn as a list, not a node diagram.** A force-directed picture of eight equations is
 * pretty and unreadable at 390pt, and it is unusable with a screen reader — section 20 asks
 * for the information to survive without the picture, and here the list *is* the
 * information: this equation, that one, and what connects them.
 *
 * **An unverified edge is labelled, not hidden.** Section 12 hides unverified derivation
 * steps from the derivation view by default, but a graph with an edge missing is a graph
 * that quietly asserts the two equations are unrelated. Here it is shown with its status, so
 * the reader sees the link and how much it is worth.
 *
 * **Equations with no edges are named.** A stray node with nothing attached looks like a
 * rendering fault; saying "these are not connected to anything recorded" is the truth.
 */
import { View } from 'react-native';

import type { EquationGraphResponse } from '@papermatch/shared-types';

import { Chip } from '../components/Chip';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/** Verification statuses that mean the link was actually checked. */
const CHECKED = new Set([
  'source_exact',
  'mechanically_verified',
  'dimensionally_checked',
  'numerically_spot_checked',
  'human_reviewed',
]);

export interface EquationGraphTabProps {
  graph: EquationGraphResponse | undefined;
  loading: boolean;
  locale: 'ja' | 'en';
}

export function EquationGraphTab({ graph, loading, locale }: EquationGraphTabProps) {
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

  if (graph === undefined || graph.nodes.length === 0) {
    return (
      <Text variant="caption" tone="secondary">
        {t('graph.noEquations')}
      </Text>
    );
  }

  const label = (id: string): string => {
    const node = graph.nodes.find((candidate) => candidate.equationId === id);
    if (node === undefined) return '—';
    return node.equationNumber === null
      ? t('graph.unnumbered')
      : t('graph.equation', { number: node.equationNumber });
  };

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text variant="caption" tone="secondary">
        {t('graph.explainer')}
      </Text>

      {graph.edges.length === 0 ? (
        // Not an empty panel. "No recorded dependency" and "the feature is broken" look the
        // same otherwise, and the first is the common case for a paper with no symbol table.
        <Text variant="caption" tone="secondary">
          {t('graph.noEdges')}
        </Text>
      ) : (
        graph.edges.map((edge, index) => (
          <View
            key={`${edge.fromEquationId}:${edge.toEquationId}:${edge.kind}:${index}`}
            style={{
              gap: 2,
              paddingLeft: theme.spacing.sm,
              borderLeftWidth: 2,
              borderLeftColor: CHECKED.has(edge.verificationStatus)
                ? theme.color.accent
                : theme.color.warning,
            }}
          >
            <Text variant="caption">
              {t('graph.edge', {
                from: label(edge.fromEquationId),
                to: label(edge.toEquationId),
              })}
            </Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs }}>
              <Chip label={t(`graph.kind.${edge.kind}` as MessageKey)} />
              <Chip label={edge.label} />
              {/* The status travels with the edge rather than being implied by its
                  presence — an unverified link shown as though it were checked is the
                  failure section 12 is about. */}
              <Chip
                label={t(`verification.${edge.verificationStatus}` as MessageKey)}
                tone={CHECKED.has(edge.verificationStatus) ? 'saved' : 'warning'}
              />
            </View>
          </View>
        ))
      )}

      {graph.isolated.length > 0 && (
        <Text variant="caption" tone="secondary">
          {t('graph.isolated', { count: graph.isolated.length })}
        </Text>
      )}
    </View>
  );
}
