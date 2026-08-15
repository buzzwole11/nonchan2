/**
 * The Mosaic plane (spec section 13).
 *
 * Section 13 asks for tiles whose position is semantic, whose colour is the field, whose
 * size is personal attention, and which lift when selected while their neighbours ease
 * away. This draws that. Where the tiles *go* is the server's decision
 * (`services/canvas.py`) — the plane never invents a coordinate, because a client that
 * nudged positions would undo the stability the whole design is built on.
 *
 * **Selection is a transform, not a re-layout.** A selected tile scales to 1.15× and its
 * neighbours shift a little outward, but the underlying coordinates never change. When the
 * selection clears everything returns exactly where it was, because it never left.
 *
 * **Reduce Motion removes the movement, not the meaning** (spec section 20). With it on,
 * the selected tile is still marked — border, elevation, and the panel below — it simply
 * does not travel to get there. The neighbour easing is pure decoration and is skipped
 * entirely.
 *
 * **Colour is not the only carrier.** A tile also states its field as text once it is big
 * enough to hold one, the selected tile is named in the panel below the plane, and every
 * tile has an accessibility label with its title and field. A reader who cannot separate
 * two hues still gets the same information.
 *
 * **The far zoom level draws islands, not tiles, and that is section 13's instruction
 * rather than a shortcut.** 遠景：分野島と件数. Trying to draw individual tiles at a scale
 * where the whole plane fits a phone was the first attempt: one grid cell came out about
 * five points across, every tile hit the minimum tap size, and they overlapped each other
 * even though the layout underneath had placed them in distinct cells. Islands are what
 * fits at that scale and what a reader can actually read there.
 *
 * **Zooming in means the plane no longer fits, so it pans.** At the third step the plane
 * is around 1600 points across on a 420-point screen. The first version clipped it and
 * centred on the middle, which drew an *empty* plane while the header said eight tiles —
 * they were all outside the viewport. Tiles are therefore laid out in content coordinates
 * inside a two-axis scroll view, so everything placed is reachable.
 */
import { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { blendFieldColors, fieldColor, readableOn } from '@papermatch/design-tokens';
import type { CanvasTile } from '@papermatch/shared-types';

import { useMorphTarget } from './MorphTargets';
import { Text } from '../components/Text';
import { useTheme } from '../theme/ThemeProvider';

/** Section 13: タイルが約1.15倍で浮く. */
export const SELECTED_SCALE = 1.15;

/** How far a neighbour eases away from the selection, in plane units. */
const NEIGHBOUR_SHIFT = 0.45;

/**
 * Tile edge as a fraction of one grid cell. Mirrors `tile_size` on the server.
 *
 * **Capped below 1 on purpose.** Placement guarantees distinct cells, so anything wider
 * than a cell overlaps its neighbour however carefully it was placed — the first version
 * sized tiles in points independently of the grid and the plane came out with tiles on top
 * of each other while the layout underneath was perfectly correct.
 */
const TILE_MIN = 0.45;
const TILE_MAX = 0.95;

/** Below this a tap target is unreliable, so the plane switches to islands instead. */
const MIN_TAP_SIZE = 28;

/**
 * Bounds on points per plane unit.
 *
 * The upper bound is not cosmetic. Fitting the plane to the viewport divides by the span
 * of the tiles, and a reader filtered down to two neighbouring papers has a span of about
 * one unit — the fit came out at roughly 2500 points per unit, the tiles were drawn wider
 * than the screen, and the plane appeared **empty** while the header cheerfully said two
 * tiles. The lower bound stops a very spread-out plane from collapsing to dots.
 */
const MIN_UNIT = 6;
const MAX_UNIT = 118;

/** Neighbours further than this are left alone; the gesture is local, not global. */
const NEIGHBOUR_RADIUS = 6;

export interface Island {
  fieldId: string;
  x: number;
  y: number;
  count: number;
  color: string;
}

/**
 * Group tiles into their field islands, at the island's own centre of mass.
 *
 * Centre of mass rather than the field's anchor, because the anchor is where the field
 * *would* sit and this is where the reader's papers actually are — an island drawn away
 * from its own tiles would move as soon as they zoomed in.
 */
export function islandsOf(tiles: CanvasTile[]): Island[] {
  const groups = new Map<string, CanvasTile[]>();
  for (const tile of tiles) {
    const id = tile.clusterId ?? '';
    groups.set(id, [...(groups.get(id) ?? []), tile]);
  }
  return [...groups.entries()]
    .filter(([id]) => id !== '')
    .map(([fieldId, members]) => ({
      fieldId,
      x: members.reduce((sum, t) => sum + t.x, 0) / members.length,
      y: members.reduce((sum, t) => sum + t.y, 0) / members.length,
      count: members.length,
      color: fieldColor(fieldId),
    }))
    .sort((a, b) => b.count - a.count || a.fieldId.localeCompare(b.fieldId));
}

/**
 * An island's diameter.
 *
 * Shared by the circle that is drawn and by the morph endpoint the plane registers for it,
 * so the shape that lands cannot be a different size from the one underneath it.
 */
function islandDiameter(count: number, maxCount: number): number {
  return 34 + 26 * Math.sqrt(count / maxCount);
}

/** A tile's side, in points. Tied to the cell so tiles abut instead of overlapping. */
function tileSide(unit: number, weight: number, isSelected: boolean): number {
  const fraction = TILE_MIN + (TILE_MAX - TILE_MIN) * Math.max(0, Math.min(1, weight));
  return unit * fraction * (isSelected ? SELECTED_SCALE : 1);
}

/** A tile's colour: the paper's field mix, or its cluster when the paper carries no weights. */
function tileColor(tile: CanvasTile): string {
  const weights = tile.paper.fieldWeights ?? {};
  return blendFieldColors(
    Object.keys(weights).length > 0 ? weights : { [tile.clusterId ?? '']: 1 },
  );
}

export interface CanvasPlaneProps {
  tiles: CanvasTile[];
  selectedId: string | null;
  onSelect: (tile: CanvasTile) => void;
  locale: 'ja' | 'en';
  /** Plane units per point. The screen owns zoom; the plane just draws at this scale. */
  scale: number;
  /** Screen size, so the plane can centre itself on the tiles it was given. */
  width: number;
  height: number;
  labelFor: (tile: CanvasTile) => string;
  hint: string;
  /** Names an island for a screen reader, e.g. "math.PR, 3 papers". */
  islandLabel: (island: Island) => string;
  /** Tapping an island filters to it, which is section 13's クラスタズーム. */
  onIslandPress?: (fieldId: string) => void;
}

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function boundsOf(tiles: CanvasTile[]): Bounds {
  return tiles.reduce<Bounds>(
    (box, tile) => ({
      minX: Math.min(box.minX, tile.x),
      minY: Math.min(box.minY, tile.y),
      maxX: Math.max(box.maxX, tile.x),
      maxY: Math.max(box.maxY, tile.y),
    }),
    { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity },
  );
}

/**
 * How far a tile is nudged because something near it is selected.
 *
 * Falls off with distance so the effect reads as the selection making room rather than the
 * plane rearranging. Returns zero for the selected tile itself, which lifts instead.
 */
export function neighbourOffset(
  tile: CanvasTile,
  selected: CanvasTile | null,
): { dx: number; dy: number } {
  if (selected === null || selected.entityId === tile.entityId) return { dx: 0, dy: 0 };

  const dx = tile.x - selected.x;
  const dy = tile.y - selected.y;
  const distance = Math.hypot(dx, dy);
  if (distance === 0 || distance > NEIGHBOUR_RADIUS) return { dx: 0, dy: 0 };

  const falloff = (1 - distance / NEIGHBOUR_RADIUS) * NEIGHBOUR_SHIFT;
  return { dx: (dx / distance) * falloff, dy: (dy / distance) * falloff };
}

export function CanvasPlane({
  tiles,
  selectedId,
  onSelect,
  scale,
  width,
  height,
  labelFor,
  hint,
  islandLabel,
  onIslandPress,
}: CanvasPlaneProps) {
  const theme = useTheme();
  const selected = tiles.find((tile) => tile.entityId === selectedId) ?? null;

  const centre = useMemo(() => {
    if (tiles.length === 0) return { x: 0, y: 0 };
    const box = boundsOf(tiles);
    return { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 };
  }, [tiles]);

  // Points per plane unit, chosen so everything on the plane is visible at zoom 1 and the
  // zoom steps magnify from there. Fitting rather than a fixed scale means a reader with
  // three saved papers is not looking at three dots in the middle of an empty field.
  const fit = useMemo(() => {
    if (tiles.length === 0) return 1;
    const box = boundsOf(tiles);
    const spanX = Math.max(1, box.maxX - box.minX);
    const spanY = Math.max(1, box.maxY - box.minY);
    return Math.min((width * 0.82) / spanX, (height * 0.82) / spanY);
  }, [tiles, width, height]);

  const unit = Math.max(MIN_UNIT, Math.min(MAX_UNIT, fit * scale));

  // One cell too small to hold a tap target means individual tiles cannot be drawn here.
  // Section 13's answer at that scale is 分野島と件数, so that is what gets drawn.
  const asIslands = unit * TILE_MAX < MIN_TAP_SIZE;
  const islands = useMemo(() => (asIslands ? islandsOf(tiles) : []), [asIslands, tiles]);
  const maxCount = islands.reduce((most, island) => Math.max(most, island.count), 1);

  // Where the selected paper is on the plane, and what shape it is drawn as, so the morph
  // between the Library row and here lands on the real thing rather than an approximation
  // of it (section 14).
  //
  // At island scale the paper has no tile of its own — but it is not nowhere: it is in its
  // field's island, and that is an honest destination. Refusing to morph here would mean the
  // ordinary case, switching to Canvas at the zoom it opens at, never got the continuous
  // transformation at all.
  const selectedField = selected?.clusterId ?? null;
  const selectedIsland = islands.find((island) => island.fieldId === selectedField) ?? null;
  const morphShape =
    asIslands && selectedIsland !== null
      ? {
          radius: islandDiameter(selectedIsland.count, maxCount) / 2,
          color: selectedIsland.color,
        }
      : selected !== null
        ? {
            radius: Math.min(tileSide(unit, selected.weight, true) / 4, theme.radius.tile),
            color: tileColor(selected),
          }
        : { radius: 0, color: theme.color.background };
  // Only the selected paper is a morph endpoint (section 14 morphs 選択中のタイル), so this is
  // one hook at the top rather than one per tile.
  const morphRef = useMorphTarget(selectedId, morphShape);

  if (asIslands) {
    // Islands are drawn to fit, so this view never scrolls.
    return (
      <View style={{ width, height, overflow: 'hidden', backgroundColor: theme.color.background }}>
        {islands.map((island) => {
          const size = islandDiameter(island.count, maxCount);
          return (
            <Pressable
              key={island.fieldId}
              ref={island.fieldId === selectedField ? morphRef : undefined}
              onPress={() => onIslandPress?.(island.fieldId)}
              accessibilityRole="button"
              accessibilityLabel={islandLabel(island)}
              style={{
                position: 'absolute',
                left: width / 2 + (island.x - centre.x) * unit - size / 2,
                top: height / 2 + (island.y - centre.y) * unit - size / 2,
                width: size,
                height: size,
                borderRadius: size / 2,
                backgroundColor: island.color,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* The count is on the island, so the far view answers "how much of what"
                  without a legend and without relying on size alone. */}
              <Text variant="caption" style={{ color: readableOn(island.color), fontSize: 12 }}>
                {island.count}
              </Text>
            </Pressable>
          );
        })}
      </View>
    );
  }

  const box = boundsOf(tiles);
  const pad = unit * 1.5;
  // At least the viewport, so a small plane still fills the frame rather than huddling in
  // a corner of a scroll area sized to nothing.
  const contentWidth = Math.max(width, (box.maxX - box.minX) * unit + pad * 2);
  const contentHeight = Math.max(height, (box.maxY - box.minY) * unit + pad * 2);
  const originX = (contentWidth - (box.maxX - box.minX) * unit) / 2;
  const originY = (contentHeight - (box.maxY - box.minY) * unit) / 2;

  return (
    <ScrollView
      horizontal
      style={{ width, height, backgroundColor: theme.color.background }}
      contentContainerStyle={{ width: contentWidth }}
      showsHorizontalScrollIndicator
    >
      <ScrollView
        style={{ width: contentWidth, height }}
        contentContainerStyle={{ height: contentHeight }}
        showsVerticalScrollIndicator
        nestedScrollEnabled
      >
        <View style={{ width: contentWidth, height: contentHeight }}>
          {tiles.map((tile) => {
            const isSelected = tile.entityId === selectedId;
            const nudge = theme.reduceMotion ? { dx: 0, dy: 0 } : neighbourOffset(tile, selected);
            // A fraction of one cell, from the reader's own attention (section 13), then the
            // selection lift. Tied to the cell so tiles abut instead of overlapping.
            const size = tileSide(unit, tile.weight, isSelected);
            const left = originX + (tile.x + nudge.dx - box.minX) * unit - size / 2;
            const top = originY + (tile.y + nudge.dy - box.minY) * unit - size / 2;

            const colour = tileColor(tile);
            // Section 10's 独立タイル: a maths card is drawn in its paper's colour (it
            // belongs to the reader's library) but visibly as a different kind of thing —
            // a dashed border and a ∑ where a paper tile shows its field. Shape, not
            // colour, carries the distinction (spec section 20: 色覚多様性).
            const isMathCard = tile.entityType === 'math_card';

            return (
              <Pressable
                key={tile.entityId}
                ref={isSelected ? morphRef : undefined}
                onPress={() => onSelect(tile)}
                accessibilityRole="button"
                accessibilityLabel={labelFor(tile)}
                accessibilityHint={hint}
                accessibilityState={{ selected: isSelected }}
                style={{
                  position: 'absolute',
                  left,
                  top,
                  width: size,
                  height: size,
                  borderRadius: Math.min(size / 4, theme.radius.tile),
                  backgroundColor: colour,
                  // The selected tile is marked by border and elevation as well as by having
                  // moved, so Reduce Motion loses nothing but the movement.
                  borderWidth: isSelected ? 3 : isMathCard ? 1 : StyleSheet.hairlineWidth,
                  borderColor: isSelected ? theme.color.textPrimary : theme.color.border,
                  borderStyle: isMathCard ? 'dashed' : 'solid',
                  // Dimming the rest is section 13's 背景が暗くなる, done by fading the tiles
                  // rather than overlaying the plane, so the selected tile stays fully legible.
                  opacity: selected === null || isSelected ? 1 : 0.45,
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 2,
                }}
              >
                {/* Only once the tile can hold it. A clipped label is worse than none. */}
                {size >= 34 && (
                  <Text
                    variant="caption"
                    style={{
                      color: readableOn(colour),
                      fontSize: Math.min(11, size / 4),
                      textAlign: 'center',
                    }}
                    numberOfLines={2}
                  >
                    {isMathCard ? '∑' : (tile.clusterId ?? '')}
                  </Text>
                )}
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
    </ScrollView>
  );
}

/** Exported for the legend, which lists the fields actually on the plane. */
export function fieldsOnPlane(tiles: CanvasTile[]): { id: string; color: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const tile of tiles) {
    const id = tile.clusterId ?? '';
    counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([id]) => id !== '')
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([id, count]) => ({ id, color: fieldColor(id), count }));
}
