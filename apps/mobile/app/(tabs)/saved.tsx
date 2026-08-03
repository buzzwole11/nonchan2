/**
 * Saved: the Library View (spec sections 9, 14).
 *
 * The orderly half of the pair in section 14 — sort and filter over the same rows the
 * Canvas will later place on a plane. Section 9 warns against the library becoming a
 * graveyard, so each row shows its reading state and its save reason rather than being an
 * undifferentiated list of titles.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ActivityIndicator, FlatList, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { SAVED_SORT_KEYS, type SavedSortKey } from '@papermatch/shared-types';

import { queryKeys, savedQuery } from '../../src/api/queries';
import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function SavedScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { api, user } = useSession();
  const [sort, setSort] = useState<SavedSortKey>('recently_saved');
  const queryClient = useQueryClient();

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  // The offline fallback lives inside the query function (`savedQuery`), so the rows and
  // the offline flag always came from the same attempt and cannot disagree for a render.
  const { data, isPending } = useQuery(savedQuery(api, sort));
  const entries = isPending ? null : (data?.rows.saved ?? []);
  const total = data?.rows.total ?? 0;
  const offline = data?.offline ?? false;

  async function remove(paperId: string): Promise<void> {
    // Optimistic: the row disappears immediately and is restored if the call fails, so the
    // list never lags behind the tap. Written straight into the cache rather than into
    // component state, because the cache is what the screen renders from now.
    const key = queryKeys.saved(sort);
    const previous = queryClient.getQueryData<typeof data>(key);
    queryClient.setQueryData<typeof data>(key, (current) =>
      current === undefined
        ? current
        : {
            ...current,
            rows: {
              saved: current.rows.saved.filter((e) => e.savedPaper.paperId !== paperId),
              total: Math.max(0, current.rows.total - 1),
            },
          },
    );
    try {
      await api.removeSaved(paperId);
    } catch {
      queryClient.setQueryData(key, previous);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.background }}>
      <View
        style={{
          paddingTop: insets.top + theme.spacing.md,
          paddingHorizontal: theme.spacing.screenHorizontal,
          gap: theme.spacing.sm,
        }}
      >
        <Text variant="label" accessibilityRole="header">
          {t('saved.title')}
        </Text>
        <Text variant="caption" tone="secondary">
          {t('saved.count', { count: total })}
        </Text>
        {offline && (
          <Text variant="caption" tone="warning" accessibilityLiveRegion="polite">
            {t('saved.offline')}
          </Text>
        )}

        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
            {SAVED_SORT_KEYS.map((key) => (
              <Chip
                key={key}
                label={t(`sort.${key}` as MessageKey)}
                selected={key === sort}
                tone="accent"
                onPress={() => setSort(key)}
                accessibilityLabel={`${t('saved.sort')}: ${t(`sort.${key}` as MessageKey)}`}
              />
            ))}
          </View>
        </ScrollView>
      </View>

      {entries === null ? (
        <View style={styles.centre}>
          <ActivityIndicator accessibilityLabel={t('common.loading')} color={theme.color.accent} />
        </View>
      ) : entries.length === 0 ? (
        <View style={[styles.centre, { gap: theme.spacing.sm, padding: theme.spacing.xl }]}>
          <Text variant="label">{t('saved.empty')}</Text>
          <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
            {t('saved.emptyHint')}
          </Text>
        </View>
      ) : (
        <FlatList
          data={entries}
          keyExtractor={(entry) => entry.savedPaper.paperId}
          contentContainerStyle={{
            padding: theme.spacing.screenHorizontal,
            gap: theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.xxl,
          }}
          renderItem={({ item }) => (
            <View
              style={{
                backgroundColor: theme.color.card,
                borderColor: theme.color.border,
                borderWidth: StyleSheet.hairlineWidth,
                borderRadius: theme.radius.tile,
                padding: theme.spacing.lg,
                gap: theme.spacing.sm,
              }}
            >
              <Text variant="caption" tone="secondary">
                {item.paper.primaryFieldId} · {item.paper.year}
              </Text>
              <Text variant="body">{item.paper.title}</Text>

              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
                <Chip
                  label={t(`savedStatus.${item.savedPaper.status}` as MessageKey)}
                  tone={item.savedPaper.status === 'finished' ? 'saved' : 'neutral'}
                />
                {item.savedPaper.reasons.map((reason) => (
                  <Chip key={reason} label={t(`saveReason.${reason}` as MessageKey)} />
                ))}
              </View>

              <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
                <PressableRow
                  onPress={() => void WebBrowser.openBrowserAsync(item.paper.sourceUrl)}
                  accessibilityLabel={`${t('a11y.openSourceButton')}: ${item.paper.title}`}
                  style={{ flex: 1 }}
                >
                  <Text variant="caption" tone="accent">
                    {t('discover.read')}
                  </Text>
                </PressableRow>
                <PressableRow
                  onPress={() => void remove(item.savedPaper.paperId)}
                  accessibilityLabel={`${t('saved.remove')}: ${item.paper.title}`}
                  style={{ flex: 1 }}
                >
                  <Text variant="caption" tone="warning">
                    {t('saved.remove')}
                  </Text>
                </PressableRow>
              </View>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  centre: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
