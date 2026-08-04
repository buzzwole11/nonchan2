/**
 * Saved: the Library View (spec sections 9, 14, 24).
 *
 * The orderly half of the pair in section 14 — sort, filter and search over the same rows
 * the Canvas will later place on a plane. Section 9 warns against the library becoming a
 * graveyard, so each row shows its reading state and its save reason rather than being an
 * undifferentiated list of titles.
 *
 * **Search lives here rather than on its own tab** because section 2's fifth job is
 * re-finding something already saved, which is the same activity as browsing the library —
 * see D-041 for why it does not search the corpus.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ActivityIndicator, FlatList, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  SAVED_SORT_KEYS,
  type Paper,
  type SavedPaper,
  type SavedSortKey,
  type SearchMatchField,
} from '@papermatch/shared-types';

import { queryKeys, savedQuery, searchQuery } from '../../src/api/queries';
import { useSession } from '../../src/api/session';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { useDebounced } from '../../src/components/useDebounced';
import { type MessageKey, translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

/** One list row, whichever list it came from — the card renders the same either way. */
interface Row {
  savedPaper: SavedPaper;
  paper: Paper;
  matchedField?: SearchMatchField;
}

export default function SavedScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { api, user } = useSession();
  const [sort, setSort] = useState<SavedSortKey>('recently_saved');
  const [query, setQuery] = useState('');
  const queryClient = useQueryClient();

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  // The offline fallback lives inside the query function (`savedQuery`), so the rows and
  // the offline flag always came from the same attempt and cannot disagree for a render.
  const { data, isPending } = useQuery(savedQuery(api, sort));
  const total = data?.rows.total ?? 0;
  const offline = data?.offline ?? false;

  // Debounced so that typing 「量子」 sends one request rather than three, two of which
  // would already be stale when they landed.
  const settled = useDebounced(query.trim());
  const searching = settled.length > 0;
  const search = useQuery(searchQuery(api, settled));

  // `isPending` is true for a disabled query too, so it cannot stand in for "loading" here;
  // `isFetching` is what actually distinguishes a request in flight.
  const loading = searching ? search.isFetching && search.data === undefined : isPending;
  const rows: Row[] | null = loading
    ? null
    : searching
      ? (search.data?.hits ?? [])
      : (data?.rows.saved ?? []);

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

    // The search results are a second view of the same library. Removing from only one
    // leaves the row visible in whichever list the reader is actually looking at.
    const searchKey = queryKeys.search(settled);
    const previousSearch = queryClient.getQueryData<typeof search.data>(searchKey);
    queryClient.setQueryData<typeof search.data>(searchKey, (current) =>
      current === undefined
        ? current
        : { ...current, hits: current.hits.filter((h) => h.savedPaper.paperId !== paperId) },
    );

    try {
      await api.removeSaved(paperId);
    } catch {
      queryClient.setQueryData(key, previous);
      queryClient.setQueryData(searchKey, previousSearch);
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
        <Text variant="caption" tone="secondary" accessibilityLiveRegion="polite">
          {searching && rows !== null
            ? t('search.count', { count: rows.length })
            : t('saved.count', { count: total })}
        </Text>
        {offline && (
          <Text variant="caption" tone="warning" accessibilityLiveRegion="polite">
            {t('saved.offline')}
          </Text>
        )}

        <View style={{ flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm }}>
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder={t('search.placeholder')}
            placeholderTextColor={theme.color.textSecondary}
            // Dynamic Type is applied from the token scale (spec section 22), so RN must not
            // scale a second time — the same rule the shared `Text` component follows.
            allowFontScaling={false}
            accessibilityLabel={t('search.label')}
            // The scope is stated to the screen reader as well as on screen: a search box
            // that silently covers less than the reader expects is the failure mode here.
            accessibilityHint={t('search.scope')}
            autoCorrect={false}
            autoCapitalize="none"
            returnKeyType="search"
            style={{
              flex: 1,
              minHeight: 44,
              paddingHorizontal: theme.spacing.md,
              borderRadius: theme.radius.tile,
              borderWidth: StyleSheet.hairlineWidth,
              borderColor: theme.color.border,
              backgroundColor: theme.color.card,
              color: theme.color.textPrimary,
              fontSize: theme.type('body').fontSize,
              lineHeight: theme.type('body').lineHeight,
              fontFamily: theme.type('body').fontFamily,
            }}
          />
          {query.length > 0 && (
            <PressableRow
              onPress={() => setQuery('')}
              accessibilityLabel={t('search.clear')}
              style={{ paddingHorizontal: theme.spacing.md }}
            >
              <Text variant="caption" tone="accent">
                {t('search.clear')}
              </Text>
            </PressableRow>
          )}
        </View>

        {/* Sorting is by which field matched while searching, so offering a sort key that
            has no effect would be a control that lies. */}
        {!searching && (
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
        )}
      </View>

      {rows === null ? (
        <View style={styles.centre}>
          <ActivityIndicator accessibilityLabel={t('common.loading')} color={theme.color.accent} />
        </View>
      ) : rows.length === 0 ? (
        // "Searched and found nothing" and "saved nothing yet" are different situations and
        // the second wording ("swipe right in Discover") is wrong advice for the first.
        <View style={[styles.centre, { gap: theme.spacing.sm, padding: theme.spacing.xl }]}>
          <Text variant="label" style={{ textAlign: 'center' }}>
            {searching ? t('search.none', { query: settled }) : t('saved.empty')}
          </Text>
          <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
            {searching
              ? search.isError
                ? t('search.offline')
                : t('search.scope')
              : t('saved.emptyHint')}
          </Text>
        </View>
      ) : (
        <FlatList
          data={rows}
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
                {/* Why this row came back. Section 6 requires a feed card to say why it is
                    there; a search result with no visible cause looks like a guess. */}
                {item.matchedField !== undefined && (
                  <Chip
                    label={t('search.matchedPrefix', {
                      field: t(`search.matched.${item.matchedField}` as MessageKey),
                    })}
                    tone="accent"
                  />
                )}
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
