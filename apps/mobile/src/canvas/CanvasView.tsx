/**
 * The Canvas view of the saved library (spec sections 13, 14).
 *
 * Not a tab of its own. Section 14 makes Canvas and Library two *views of the same data*
 * with a switch between them — 「SavedをLibraryまたはCanvasで閲覧」 — and section 1 asks for
 * the two to be 滑らかに切り替えられる. Two separate tabs would have made them two places
 * holding the same papers, which is a different product.
 *
 * Positions come from the server and are never adjusted here; see `CanvasPlane.tsx`.
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

import { canvasQuery, queryKeys, relationsQuery } from '../api/queries';
import { useSession } from '../api/session';
import { CanvasPlane, fieldsOnPlane } from './CanvasPlane';
import {
  CANVAS_STYLES,
  ConstellationView,
  LandscapeView,
  SpectrumView,
  offPlaneRelations,
  type CanvasStyle,
} from './CanvasStyles';
import { fieldBreadth, timelineSteps, visibleAt } from './timeline';
import { RelationList } from './RelationList';
import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/** Section 13's zoom levels: 遠景 / 中景 / 近景 / 最接近. */
const ZOOM_STEPS = [1, 2.6, 4.6, 7.5] as const;

export interface CanvasViewProps {
  /**
   * The paper the reader has selected, shared with the Library view.
   *
   * Section 14 asks that switching between the two 位置関係を失わない — so the selection is
   * owned by the screen and handed to whichever view is showing, rather than each view
   * keeping its own and losing the reader's place at the switch.
   */
  selectedId: string | null;
  onSelectedChange: (paperId: string | null) => void;
}

export function CanvasView({ selectedId, onSelectedChange }: CanvasViewProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { api, user } = useSession();
  const queryClient = useQueryClient();

  const [zoomIndex, setZoomIndex] = useState(0);
  const [fieldFilter, setFieldFilter] = useState<string | null>(null);
  // Section 13's four styles. All four read the same coordinates; switching never re-places.
  const [style, setStyle] = useState<CanvasStyle>('mosaic');
  // The history slider's position, or null for "everything" — the position it opens at, so
  // the plane is complete until the reader chooses to wind it back.
  const [replayIndex, setReplayIndex] = useState<number | null>(null);

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const { data, isPending } = useQuery(canvasQuery(api));
  const allTiles = useMemo(() => data?.tiles ?? [], [data]);
  const filtered = useMemo(
    () => (fieldFilter === null ? allTiles : allTiles.filter((t) => t.clusterId === fieldFilter)),
    [allTiles, fieldFilter],
  );
  // Built from the whole library, not the filtered subset: the months a reader was saving in
  // do not change because they narrowed to one field, and a slider whose length moved with
  // an unrelated filter would be unusable.
  const steps = useMemo(() => timelineSteps(allTiles), [allTiles]);
  const breadth = useMemo(() => fieldBreadth(allTiles, steps), [allTiles, steps]);
  const cutoff = replayIndex === null ? null : (steps[replayIndex]?.cutoff ?? null);
  const tiles = useMemo(() => visibleAt(filtered, cutoff), [filtered, cutoff]);
  const fields = useMemo(() => fieldsOnPlane(allTiles), [allTiles]);
  const selected = tiles.find((tile) => tile.entityId === selectedId) ?? null;
  // Fetched per selection rather than for the whole plane: the server classifies against the
  // reader's library each time, and doing that for every tile would be a request per tile
  // for panels that are never opened.
  const relations = useQuery(relationsQuery(api, selected?.paper.id ?? null));

  const planeHeight = Math.max(280, Math.round(width * 0.95));
  const offPlane = offPlaneRelations(tiles, relations.data?.relations ?? []);
  const labelFor = (tile: CanvasTile) =>
    t('canvas.tile', { title: tile.paper.title, field: tile.clusterId ?? '—' });
  const scale = ZOOM_STEPS[zoomIndex] ?? 1;

  function select(tile: CanvasTile): void {
    onSelectedChange(selectedId === tile.entityId ? null : tile.entityId);
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
        paddingBottom: insets.bottom + theme.spacing.xxl,
        gap: theme.spacing.sm,
      }}
    >
      <Text
        variant="caption"
        tone="secondary"
        style={{ paddingHorizontal: theme.spacing.screenHorizontal }}
      >
        {t('canvas.count', { count: tiles.length, fields: fields.length })}
      </Text>

      {/* Section 13's four Canvas styles. Four ways of drawing one plane — the coordinates
          are the server's and none of these touch them, so a paper found in Mosaic is in
          the same relative place in Landscape. */}
      <View
        style={{
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: theme.spacing.sm,
          paddingHorizontal: theme.spacing.screenHorizontal,
        }}
      >
        {CANVAS_STYLES.map((candidate) => (
          <Chip
            key={candidate}
            label={t(`canvasStyle.${candidate}` as MessageKey)}
            selected={candidate === style}
            tone="accent"
            onPress={() => setStyle(candidate)}
            accessibilityLabel={`${t('canvas.style')}: ${t(`canvasStyle.${candidate}` as MessageKey)}`}
          />
        ))}
      </View>

      {style === 'mosaic' ? (
        <CanvasPlane
          tiles={tiles}
          selectedId={selectedId}
          onSelect={select}
          locale={locale}
          scale={scale}
          width={width}
          height={planeHeight}
          labelFor={labelFor}
          hint={t('canvas.tileHint')}
          islandLabel={(island) =>
            t('canvas.island', { field: island.fieldId, count: island.count })
          }
          onIslandPress={(fieldId) => {
            // Section 13's クラスタズーム: tapping an island narrows to it and steps in.
            setFieldFilter(fieldId);
            setZoomIndex((index) => Math.max(index, 1));
          }}
        />
      ) : tiles.length === 0 ? (
        <View style={{ width, height: planeHeight, ...styles.centre }}>
          <Text variant="caption" tone="secondary">
            {t('canvas.noneInRange')}
          </Text>
        </View>
      ) : style === 'constellation' ? (
        <ConstellationView
          tiles={tiles}
          selectedId={selectedId}
          onSelect={select}
          width={width}
          height={planeHeight}
          labelFor={labelFor}
          relations={relations.data?.relations ?? []}
        />
      ) : style === 'landscape' ? (
        <LandscapeView
          tiles={tiles}
          selectedId={selectedId}
          onSelect={select}
          width={width}
          height={planeHeight}
          labelFor={labelFor}
        />
      ) : (
        <SpectrumView
          tiles={tiles}
          selectedId={selectedId}
          onSelect={select}
          width={width}
          height={planeHeight}
          labelFor={labelFor}
        />
      )}

      {/* Constellation draws an edge only where the classifier found one (section 17), so
          with nothing selected there are no lines to draw. Said, rather than left as an
          empty sky the reader reads as a broken feature. */}
      {style === 'constellation' && (
        <Text
          variant="caption"
          tone="secondary"
          style={{ paddingHorizontal: theme.spacing.screenHorizontal }}
          accessibilityLiveRegion="polite"
        >
          {selected === null
            ? t('canvas.constellationHint')
            : offPlane > 0
              ? // A relation to a paper the reader has not saved has no star to reach. Said,
                // rather than leaving a selected star with no lines looking broken.
                t('canvas.constellationOffPlane', { count: offPlane })
              : t('canvas.constellationLines', {
                  count: (relations.data?.relations.length ?? 0) - offPlane,
                })}
        </Text>
      )}

      {/* Section 13: 年月スライダーで保存履歴を再生. Buttons rather than a drag: a slider is a
          gesture, and section 20 wants every gesture to have an equivalent. */}
      {steps.length > 1 && (
        <View
          style={{
            paddingHorizontal: theme.spacing.screenHorizontal,
            gap: theme.spacing.xs,
          }}
        >
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: theme.spacing.sm,
            }}
          >
            <Text variant="caption" tone="secondary">
              {t('canvas.replay')}
            </Text>
            <PressableRow
              onPress={() =>
                setReplayIndex((index) => Math.max(0, (index ?? steps.length - 1) - 1))
              }
              accessibilityLabel={t('canvas.replayBack')}
            >
              <Text variant="label" tone="accent">
                −
              </Text>
            </PressableRow>
            <PressableRow
              onPress={() =>
                setReplayIndex((index) =>
                  index === null || index >= steps.length - 1 ? null : index + 1,
                )
              }
              accessibilityLabel={t('canvas.replayForward')}
            >
              <Text variant="label" tone="accent">
                ＋
              </Text>
            </PressableRow>
            <Text variant="caption" tone="secondary" accessibilityLiveRegion="polite">
              {replayIndex === null
                ? t('canvas.replayAll')
                : t('canvas.replayAt', {
                    year: steps[replayIndex]?.year ?? 0,
                    month: steps[replayIndex]?.month ?? 0,
                  })}
            </Text>
            {replayIndex !== null && (
              <PressableRow
                onPress={() => setReplayIndex(null)}
                accessibilityLabel={t('canvas.replayReset')}
              >
                <Text variant="caption" tone="secondary">
                  {t('canvas.replayReset')}
                </Text>
              </PressableRow>
            )}
          </View>
          {/* Section 13 asks for 関心領域の拡大を客観的に表示 — a count of fields, not an
              impression. The paper count grows even when someone reads one corner forever. */}
          <Text variant="caption" tone="secondary">
            {t('canvas.breadth', {
              count: replayIndex === null ? fields.length : (breadth[replayIndex] ?? 0),
            })}
          </Text>
        </View>
      )}

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
              onPress={() => onSelectedChange(null)}
              accessibilityLabel={t('canvas.clearSelection')}
              style={{ flex: 1 }}
            >
              <Text variant="caption" tone="secondary">
                {t('canvas.clearSelection')}
              </Text>
            </PressableRow>
          </View>
          {/* Section 13: 基礎、対立、後続、類似を方向別に表示. The panel already names the
              paper; this says what it sits next to, and on what evidence. */}
          <RelationList
            relations={relations.data?.relations ?? []}
            locale={locale}
            loading={relations.isFetching && relations.data === undefined}
            onSelect={onSelectedChange}
          />

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
