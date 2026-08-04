/**
 * Canvas: the Knowledge Canvas (spec section 13).
 *
 * The other half of section 14's pair — Saved is the orderly list, this is the plane you
 * look at. Positions come from the server and are never adjusted here; see
 * `src/canvas/CanvasPlane.tsx` for why that matters.
 *
 * **Zoom is a stepped control, not only a pinch.** Section 13 describes zoom levels and
 * section 20 requires a non-gesture equivalent for every gesture, so the buttons are the
 * primary control and pinch would be an addition rather than the only way in.
 *
 * **The filter narrows what is drawn, not where things are.** Hiding every field but one
 * leaves the remaining tiles exactly where they were, so the reader keeps their bearings
 * when they clear it — the plane is a place (section 13), and a filter that re-packed it
 * would make it a different place each time.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { CanvasTile } from '@papermatch/shared-types';

import { canvasQuery, queryKeys } from '../../src/api/queries';
import { useSession } from '../../src/api/session';
import { CanvasPlane, fieldsOnPlane } from '../../src/canvas/CanvasPlane';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { type MessageKey, translate } from '../../src/i18n';
import { useTheme } from '../../src/theme/ThemeProvider';

/** Section 13's zoom levels: 遠景 / 中景 / 近景 / 最接近. */
const ZOOM_STEPS = [1, 2.6, 4.6, 7.5] as const;

export default function CanvasScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { api, user } = useSession();
  const queryClient = useQueryClient();

  const [zoomIndex, setZoomIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fieldFilter, setFieldFilter] = useState<string | null>(null);

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const { data, isPending } = useQuery(canvasQuery(api));
  const allTiles = useMemo(() => data?.tiles ?? [], [data]);
  const tiles = useMemo(
    () => (fieldFilter === null ? allTiles : allTiles.filter((t) => t.clusterId === fieldFilter)),
    [allTiles, fieldFilter],
  );
  const fields = useMemo(() => fieldsOnPlane(allTiles), [allTiles]);
  const selected = tiles.find((tile) => tile.entityId === selectedId) ?? null;

  const planeHeight = Math.max(280, Math.round(width * 0.95));
  const scale = ZOOM_STEPS[zoomIndex] ?? 1;

  function select(tile: CanvasTile): void {
    setSelectedId((current) => (current === tile.entityId ? null : tile.entityId));
  }

  async function place(tile: CanvasTile, x: number, y: number): Promise<void> {
    const response = await api.moveTile(tile.entityId, { x, y });
    queryClient.setQueryData(queryKeys.canvas(), response);
  }

  if (isPending) {
    return (
      <View style={[styles.centre, { backgroundColor: theme.color.background }]}>
        <ActivityIndicator accessibilityLabel={t('common.loading')} color={theme.color.accent} />
      </View>
    );
  }

  if (allTiles.length === 0) {
    return (
      <View
        style={[
          styles.centre,
          {
            backgroundColor: theme.color.background,
            gap: theme.spacing.sm,
            padding: theme.spacing.xl,
          },
        ]}
      >
        <Text variant="label">{t('canvas.empty')}</Text>
        <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
          {t('canvas.emptyHint')}
        </Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: theme.color.background }}
      contentContainerStyle={{
        paddingTop: insets.top + theme.spacing.md,
        paddingBottom: insets.bottom + theme.spacing.xxl,
        gap: theme.spacing.sm,
      }}
    >
      <View style={{ paddingHorizontal: theme.spacing.screenHorizontal, gap: theme.spacing.xs }}>
        <Text variant="label" accessibilityRole="header">
          {t('canvas.title')}
        </Text>
        <Text variant="caption" tone="secondary">
          {t('canvas.count', { count: tiles.length, fields: fields.length })}
        </Text>
      </View>

      <CanvasPlane
        tiles={tiles}
        selectedId={selectedId}
        onSelect={select}
        locale={locale}
        scale={scale}
        width={width}
        height={planeHeight}
        labelFor={(tile) =>
          t('canvas.tile', { title: tile.paper.title, field: tile.clusterId ?? '—' })
        }
        hint={t('canvas.tileHint')}
        islandLabel={(island) => t('canvas.island', { field: island.fieldId, count: island.count })}
        onIslandPress={(fieldId) => {
          // Section 13's クラスタズーム: tapping an island narrows to it and steps in.
          setFieldFilter(fieldId);
          setZoomIndex((index) => Math.max(index, 1));
        }}
      />

      {/* Zoom as buttons: section 20 wants a non-gesture equivalent for every gesture, and
          here the buttons are the primary control rather than the fallback. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: theme.spacing.sm,
          paddingHorizontal: theme.spacing.screenHorizontal,
        }}
      >
        <Text variant="caption" tone="secondary">
          {t('canvas.zoom')}
        </Text>
        <PressableRow
          onPress={() => setZoomIndex((index) => Math.max(0, index - 1))}
          disabled={zoomIndex === 0}
          accessibilityLabel={t('canvas.zoomOut')}
        >
          <Text variant="label" tone="accent">
            −
          </Text>
        </PressableRow>
        <PressableRow
          onPress={() => setZoomIndex((index) => Math.min(ZOOM_STEPS.length - 1, index + 1))}
          disabled={zoomIndex === ZOOM_STEPS.length - 1}
          accessibilityLabel={t('canvas.zoomIn')}
        >
          <Text variant="label" tone="accent">
            +
          </Text>
        </PressableRow>
        <Text variant="caption" tone="secondary">
          {zoomIndex + 1} / {ZOOM_STEPS.length}
        </Text>
      </View>

      {/* Filtering hides tiles; it never moves the ones that stay. */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          paddingHorizontal: theme.spacing.screenHorizontal,
          gap: theme.spacing.sm,
        }}
      >
        <Chip
          label={t('canvas.allFields')}
          selected={fieldFilter === null}
          tone="accent"
          onPress={() => setFieldFilter(null)}
          accessibilityLabel={`${t('canvas.filter')}: ${t('canvas.allFields')}`}
        />
        {fields.map((field) => (
          <Chip
            key={field.id}
            label={`${field.id} (${field.count})`}
            selected={fieldFilter === field.id}
            tone="accent"
            onPress={() => setFieldFilter((current) => (current === field.id ? null : field.id))}
            accessibilityLabel={`${t('canvas.filter')}: ${field.id}`}
          />
        ))}
      </ScrollView>

      {selected !== null && (
        <View
          style={{
            marginHorizontal: theme.spacing.screenHorizontal,
            padding: theme.spacing.lg,
            gap: theme.spacing.sm,
            borderRadius: theme.radius.tile,
            borderWidth: StyleSheet.hairlineWidth,
            borderColor: theme.color.border,
            backgroundColor: theme.color.card,
          }}
          accessibilityLiveRegion="polite"
        >
          <Text variant="caption" tone="secondary">
            {t('canvas.selected')} · {selected.clusterId ?? '—'} · {selected.paper.year}
          </Text>
          <Text variant="body">{selected.paper.title}</Text>
          {selected.userOverride && (
            <Text variant="caption" tone="accent">
              {t('canvas.moved')}
            </Text>
          )}
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <PressableRow
              onPress={() => void WebBrowser.openBrowserAsync(selected.paper.sourceUrl)}
              accessibilityLabel={t('canvas.openPaper')}
              style={{ flex: 1 }}
            >
              <Text variant="caption" tone="accent">
                {t('canvas.openPaper')}
              </Text>
            </PressableRow>
            <PressableRow
              onPress={() => setSelectedId(null)}
              accessibilityLabel={t('canvas.clearSelection')}
              style={{ flex: 1 }}
            >
              <Text variant="caption" tone="secondary">
                {t('canvas.clearSelection')}
              </Text>
            </PressableRow>
          </View>
          {/* Placing a tile by hand without a drag gesture (section 20), and the reason
              these are buttons rather than only a drag: a drag is the one interaction a
              switch or keyboard user cannot perform at all. Each press nudges by one grid
              cell; the server records the position and every later layout leaves it. */}
          <Text variant="caption" tone="secondary">
            {t('canvas.move')}
          </Text>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            {(
              [
                ['canvas.moveUp', 0, -1],
                ['canvas.moveDown', 0, 1],
                ['canvas.moveLeft', -1, 0],
                ['canvas.moveRight', 1, 0],
              ] as const
            ).map(([key, dx, dy]) => (
              <PressableRow
                key={key}
                onPress={() => void place(selected, selected.x + dx, selected.y + dy)}
                accessibilityLabel={t(key)}
                style={{ flexGrow: 1 }}
              >
                <Text variant="caption" tone="accent">
                  {t(key)}
                </Text>
              </PressableRow>
            ))}
          </View>
        </View>
      )}

      <Text
        variant="caption"
        tone="secondary"
        style={{ paddingHorizontal: theme.spacing.screenHorizontal }}
      >
        {t('canvas.layout', { version: data?.layoutVersion ?? '' })}
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
