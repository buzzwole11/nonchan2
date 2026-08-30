/**
 * The other three Canvas styles (spec section 13).
 *
 * Section 13 lists four: Mosaic（色付きタイル）, Constellation（星と関係線）,
 * Landscape（分野の島・地形）, Spectrum（時系列の色帯）, and says Mosaic comes first. Mosaic
 * lives in `CanvasPlane.tsx`; these are the other three.
 *
 * **They are four ways of drawing one plane, not four planes.** Every style reads the same
 * tiles with the same server-assigned coordinates. Switching does not re-place anything, so
 * a reader who found a paper in Mosaic finds it in the same relative position in Landscape.
 * A style that re-laid the papers out would make the plane four different places and undo
 * the stability the coordinates exist for (D-048).
 *
 * **Constellation draws lines only where a relation actually exists.** Section 13 calls it
 * 星と関係線, and the relations come from the server's classifier, which refuses to assert
 * anything from similarity alone (section 17, D-053). So the lines are drawn from the
 * selected paper to the papers it is genuinely related to — and with nothing selected there
 * are no lines, because there is no set of edges we are entitled to draw. Joining nearby
 * stars because they look near would be a picture of the layout algorithm presented as a
 * picture of the literature.
 *
 * **Spectrum is bands of time, and it says which years are missing.** A reader whose library
 * jumps from 2014 to 2023 should see the gap rather than two bands sitting next to each
 * other as though the years were adjacent.
 */
import { Pressable, View } from 'react-native';

import { blendFieldColors, fieldColor, readableOn } from '@papermatch/design-tokens';
import type { CanvasTile, PaperRelationHit } from '@papermatch/shared-types';

import { islandsOf } from './CanvasPlane';
import { Text } from '../components/Text';
import { useTheme } from '../theme/ThemeProvider';

export const CANVAS_STYLES = ['mosaic', 'constellation', 'landscape', 'spectrum'] as const;

export type CanvasStyle = (typeof CANVAS_STYLES)[number];

export interface StyleViewProps {
  tiles: CanvasTile[];
  selectedId: string | null;
  onSelect: (tile: CanvasTile) => void;
  width: number;
  height: number;
  labelFor: (tile: CanvasTile) => string;
  /** Relations of the selected paper, for Constellation's lines. */
  relations?: PaperRelationHit[];
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

/** Plane coordinates → points inside a box, with a margin so nothing touches the edge. */
function projector(tiles: CanvasTile[], width: number, height: number, pad = 28) {
  const box = boundsOf(tiles);
  const spanX = Math.max(1, box.maxX - box.minX);
  const spanY = Math.max(1, box.maxY - box.minY);
  return (tile: CanvasTile) => ({
    left: pad + ((tile.x - box.minX) / spanX) * Math.max(1, width - pad * 2),
    top: pad + ((tile.y - box.minY) / spanY) * Math.max(1, height - pad * 2),
  });
}

function tileColor(tile: CanvasTile): string {
  const weights = tile.paper.fieldWeights ?? {};
  return blendFieldColors(
    Object.keys(weights).length > 0 ? weights : { [tile.clusterId ?? '']: 1 },
  );
}

// ------------------------------------------------------------------ Constellation

/** Star radius in points. Attention makes a star brighter and bigger, as in Mosaic. */
const STAR_MIN = 5;
const STAR_MAX = 13;

/** The tap target around a star, which is much larger than the star itself. */
const STAR_TAP = 30;

/**
 * Relations whose other end is not on the plane.
 *
 * The classifier's candidate pool reaches beyond the reader's library, so a paper can have a
 * well-evidenced relation to something they have never saved. There is no star to draw a
 * line to, and an empty sky with a selection reads as a broken feature — so the count is
 * reported and the caller says it out loud.
 */
export function offPlaneRelations(tiles: CanvasTile[], relations: PaperRelationHit[]): number {
  const onPlane = new Set(tiles.map((tile) => tile.paper.id));
  return relations.filter((relation) => !onPlane.has(relation.paper.id)).length;
}

export function ConstellationView({
  tiles,
  selectedId,
  onSelect,
  width,
  height,
  labelFor,
  relations = [],
}: StyleViewProps) {
  const theme = useTheme();
  const place = projector(tiles, width, height);
  const selected = tiles.find((tile) => tile.entityId === selectedId) ?? null;

  // Only papers the server actually classified as related to the selection. With nothing
  // selected this is empty and no lines are drawn — see the module comment.
  const linked = new Set(relations.map((relation) => relation.paper.id));

  return (
    <View
      style={{
        width,
        height,
        backgroundColor: theme.color.background,
        overflow: 'hidden',
      }}
    >
      {selected !== null &&
        tiles
          .filter((tile) => linked.has(tile.paper.id))
          .map((tile) => (
            <Line
              key={`line:${tile.entityId}`}
              from={place(selected)}
              to={place(tile)}
              color={theme.color.accent}
            />
          ))}

      {tiles.map((tile) => {
        const isSelected = tile.entityId === selectedId;
        // The selection ring is 2pt on each side, so a small star would be almost entirely
        // border. Selected stars grow enough to still read as a star inside their ring.
        const base = STAR_MIN + (STAR_MAX - STAR_MIN) * Math.max(0, Math.min(1, tile.weight));
        const size = isSelected ? base + 6 : base;
        const { left, top } = place(tile);
        return (
          <Pressable
            key={tile.entityId}
            onPress={() => onSelect(tile)}
            accessibilityRole="button"
            accessibilityLabel={labelFor(tile)}
            accessibilityState={{ selected: isSelected }}
            style={{
              position: 'absolute',
              // The tap target is the box; the star is drawn centred inside it, so a small
              // star is still reachable (section 20 asks for usable targets, not tiny ones).
              left: left - STAR_TAP / 2,
              top: top - STAR_TAP / 2,
              width: STAR_TAP,
              height: STAR_TAP,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                width: size,
                height: size,
                borderRadius: size / 2,
                backgroundColor: tileColor(tile),
                borderWidth: isSelected ? 2 : 0,
                borderColor: theme.color.textPrimary,
                // Selection is not carried by size alone; the rest dim (section 20).
                opacity: selected === null || isSelected || linked.has(tile.paper.id) ? 1 : 0.35,
              }}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * A straight line between two points, as a rotated one-pixel view.
 *
 * No SVG dependency: react-native-svg is not in the build, and a line is a rectangle with a
 * rotation. Good enough for edges between stars, and it costs nothing to render.
 */
function Line({
  from,
  to,
  color,
}: {
  from: { left: number; top: number };
  to: { left: number; top: number };
  color: string;
}) {
  const dx = to.left - from.left;
  const dy = to.top - from.top;
  const length = Math.hypot(dx, dy);
  if (length < 1) return null;
  return (
    <View
      pointerEvents="none"
      style={{
        position: 'absolute',
        left: from.left,
        top: from.top,
        width: length,
        height: 1,
        backgroundColor: color,
        opacity: 0.55,
        transform: [{ translateX: 0 }, { rotateZ: `${Math.atan2(dy, dx)}rad` }],
        transformOrigin: 'left center',
      }}
    />
  );
}

// ------------------------------------------------------------------ Landscape

/** Contour rings per island. Three reads as terrain without becoming a target symbol. */
const RINGS = 3;

export function LandscapeView({
  tiles,
  selectedId,
  onSelect,
  width,
  height,
  labelFor,
}: StyleViewProps) {
  const theme = useTheme();
  // A wider margin than the other styles: an island is drawn as rings around a centre, so
  // placing a centre 28pt from the edge puts half its terrain outside the plane.
  const place = projector(tiles, width, height, 70);
  const islands = islandsOf(tiles);
  const maxCount = islands.reduce((most, island) => Math.max(most, island.count), 1);

  return (
    <View style={{ width, height, backgroundColor: theme.color.background, overflow: 'hidden' }}>
      {islands.map((island) => {
        // The island's own centre of mass in plane units, projected the same way the tiles
        // are, so the terrain sits under the papers rather than beside them.
        const centre = place({ x: island.x, y: island.y } as CanvasTile);
        const base = 46 + 64 * Math.sqrt(island.count / maxCount);
        return (
          <View key={island.fieldId} pointerEvents="none">
            {Array.from({ length: RINGS }, (_, ring) => {
              const size = base * (1 - ring * 0.24);
              return (
                <View
                  key={ring}
                  style={{
                    position: 'absolute',
                    left: centre.left - size / 2,
                    top: centre.top - size / 2,
                    width: size,
                    height: size,
                    borderRadius: size / 2,
                    backgroundColor: island.color,
                    // Stacked translucency is what makes the rings read as height.
                    opacity: 0.14 + ring * 0.07,
                  }}
                />
              );
            })}
          </View>
        );
      })}

      {tiles.map((tile) => {
        const isSelected = tile.entityId === selectedId;
        const { left, top } = place(tile);
        const size = 16;
        return (
          <Pressable
            key={tile.entityId}
            onPress={() => onSelect(tile)}
            accessibilityRole="button"
            accessibilityLabel={labelFor(tile)}
            accessibilityState={{ selected: isSelected }}
            style={{
              position: 'absolute',
              left: left - STAR_TAP / 2,
              top: top - STAR_TAP / 2,
              width: STAR_TAP,
              height: STAR_TAP,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                width: size,
                height: size,
                borderRadius: 4,
                backgroundColor: tileColor(tile),
                borderWidth: isSelected ? 2 : 0,
                borderColor: theme.color.textPrimary,
              }}
            />
          </Pressable>
        );
      })}

      {/* Islands are named, not only coloured (section 20: 色だけで分野を表現しない). */}
      {islands.map((island) => {
        const centre = place({ x: island.x, y: island.y } as CanvasTile);
        return (
          <Text
            key={`label:${island.fieldId}`}
            variant="caption"
            style={{
              position: 'absolute',
              left: Math.max(2, centre.left - 50),
              top: centre.top + 22,
              width: 100,
              textAlign: 'center',
              color: theme.color.textSecondary,
              fontSize: 10,
            }}
            numberOfLines={1}
          >
            {island.fieldId}
          </Text>
        );
      })}
    </View>
  );
}

// ------------------------------------------------------------------ Spectrum

export interface YearBand {
  year: number;
  count: number;
  /** Null for an empty year: there is no mix of fields to blend, and a transparent hex
   *  literal here would be a colour decision made outside the token set. The view draws an
   *  empty band in the background colour. */
  color: string | null;
  /** True when no paper in the library has this year — a gap, drawn as one. */
  empty: boolean;
}

/**
 * Bands from the earliest year in the library to the latest, **including the empty ones**.
 *
 * A library that jumps 2014 → 2023 must not draw those two bands adjacent: that would say
 * the reader has been reading steadily when they have a nine-year hole. The gap is the
 * information here.
 */
export function yearBands(tiles: CanvasTile[]): YearBand[] {
  if (tiles.length === 0) return [];
  const byYear = new Map<number, CanvasTile[]>();
  for (const tile of tiles) {
    const year = tile.paper.year;
    byYear.set(year, [...(byYear.get(year) ?? []), tile]);
  }
  const years = [...byYear.keys()].sort((a, b) => a - b);
  const first = years[0] ?? 0;
  const last = years[years.length - 1] ?? first;

  const bands: YearBand[] = [];
  for (let year = first; year <= last; year += 1) {
    const members = byYear.get(year) ?? [];
    bands.push({
      year,
      count: members.length,
      color:
        members.length === 0
          ? null
          : blendFieldColors(
              members.reduce<Record<string, number>>((weights, tile) => {
                const id = tile.clusterId ?? '';
                weights[id] = (weights[id] ?? 0) + 1;
                return weights;
              }, {}),
            ),
      empty: members.length === 0,
    });
  }
  return bands;
}

export function SpectrumView({
  tiles,
  selectedId,
  onSelect,
  width,
  height,
  labelFor,
}: StyleViewProps) {
  const theme = useTheme();
  const bands = yearBands(tiles);
  const bandHeight = Math.max(18, Math.min(46, Math.floor(height / Math.max(1, bands.length))));
  // Fits its bands rather than filling the plane's height. A library spanning two years is
  // two bands, and reserving a screen of empty space under them says the view failed to load.
  const used = Math.min(height, bandHeight * bands.length);

  return (
    <View
      style={{ width, height: used, backgroundColor: theme.color.background, overflow: 'hidden' }}
    >
      {bands.map((band, index) => {
        const members = tiles.filter((tile) => tile.paper.year === band.year);
        return (
          <View
            key={band.year}
            style={{
              position: 'absolute',
              left: 0,
              top: index * bandHeight,
              width,
              height: bandHeight,
              flexDirection: 'row',
              alignItems: 'center',
              paddingHorizontal: 8,
              gap: 4,
              // An empty year is drawn as an empty band rather than skipped, so the gap in
              // the reader's library is visible as a gap.
              backgroundColor: band.color ?? theme.color.background,
              opacity: band.empty ? 0.5 : 1,
            }}
          >
            <Text
              variant="caption"
              style={{
                width: 42,
                fontSize: 10,
                color: band.color === null ? theme.color.textSecondary : readableOn(band.color),
              }}
            >
              {band.year}
            </Text>
            {members.map((tile) => {
              const isSelected = tile.entityId === selectedId;
              return (
                <Pressable
                  key={tile.entityId}
                  onPress={() => onSelect(tile)}
                  accessibilityRole="button"
                  accessibilityLabel={labelFor(tile)}
                  accessibilityState={{ selected: isSelected }}
                  style={{
                    width: Math.max(12, bandHeight - 12),
                    height: Math.max(12, bandHeight - 12),
                    borderRadius: 3,
                    backgroundColor: fieldColor(tile.clusterId),
                    borderWidth: isSelected ? 2 : 0,
                    borderColor: theme.color.textPrimary,
                  }}
                />
              );
            })}
          </View>
        );
      })}
    </View>
  );
}
