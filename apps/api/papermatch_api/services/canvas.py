"""Placing saved things on the Canvas plane (spec section 13).

Section 13 asks for tiles positioned by semantic closeness, and then constrains that
almost completely:

* 新規論文は近い領域に加える — a new paper lands near what it resembles.
* **全体再配置を最小化** — adding one must not rearrange the rest.
* 手動配置を尊重 — a tile the reader dragged stays where they put it.
* 配置アルゴリズムの版を保持 — the layout version is stored so a re-layout is reversible.

**Those constraints rule out t-SNE and UMAP, which is the whole design decision here.**
Both are the obvious answer to "project 512 dimensions onto a plane" and both are wrong
for this: their output depends on the entire input set, so adding one paper moves every
other tile, and neither is deterministic between runs. A canvas whose tiles wander every
time the reader saves something is not a place — and section 13 is explicitly asking for a
place, something you can come back to and recognise.

**So the projection does not look at the data at all.** A field anchors to a fixed point
on a circle derived from its id, and the embedding is projected through a fixed
pseudo-random basis seeded by a constant. Neither depends on which papers exist, so
existing tiles cannot move: stability is structural rather than something re-run and
hoped for. The cost is that the picture is less prettily clustered than UMAP's would be —
paid knowingly, because section 13's requirement is a stable plane, not the tightest
possible clusters. The embeddings are hashed bag-of-words anyway (D-016), so the clusters
a neighbour-embedding method would find are not there to be found.

**A mosaic needs tiles not to overlap, and resolving collisions by pushing would undo all
of the above.** So placement quantises to a grid and claims the nearest *free* cell. A new
tile can only ever take a cell nobody holds, so nothing is displaced — the packing is
tight and no existing tile moves.

**Islands come from the taxonomy, not from a hash of the field id.** Hashing to an angle
was the first attempt and it produced islands sitting on top of each other: measured over
the fourteen seeded fields, sixteen of the ninety-one pairs overlapped and `cond-mat` was
one unit from `math.NT`. Independent angles on a circle collide — the birthday problem —
and a plane whose islands overlap is lying about the grouping it exists to show. So a
top-level field takes an evenly spaced slot on the ring and its children sit in a smaller
ring around it. That is separated by construction, and closer to what section 13 means by
分野島: physics is one island with high-energy theory and condensed matter as
neighbourhoods inside it.

The cost is that anchors depend on the taxonomy's shape, so **changing the taxonomy is a
layout change**. That is exactly what section 13's 配置アルゴリズムの版を保持 is for:
positions are keyed by `layout_version`, so a taxonomy edit means bumping the version and
the old plane survives beside the new one rather than being silently rewritten.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    CanvasPosition,
    Embedding,
    Field,
    Paper,
    SavedPaper,
    User,
)

__all__ = [
    "GRID_STEP",
    "LAYOUT_VERSION",
    "PlacedTile",
    "field_anchor",
    "layout_for",
    "personal_weight",
    "project",
    "taxonomy_map",
    "tile_size",
]

#: Bumped whenever placement changes. Stored on every row so a re-layout can be told apart
#: from the previous one and rolled back (section 13: 配置アルゴリズムの版を保持).
LAYOUT_VERSION = "mosaic-v1"

#: Distance between grid cells, in the same arbitrary units as the anchors. The client
#: scales; what matters here is that positions are on a lattice so tiles can abut.
GRID_STEP = 1.0

#: How far a field island sits from the origin. Large enough that islands separate, small
#: enough that the whole plane is still one view at the far zoom level (section 13's 遠景).
_ANCHOR_RADIUS = 24.0

#: How far a paper may sit from its field's anchor. Bounded so a paper never drifts into
#: a neighbouring island — the island *is* the field, and a tile in the wrong one is a
#: worse lie than a tile in a slightly wrong place within the right one.
_SPREAD = 3.0

#: The fewest slots a ring is divided into. With only three disciplines, dividing the
#: circle into a fixed twelve put them at 0°, 30° and 60° — all in one quadrant, with
#: their subfield rings overlapping. Spacing is therefore over the actual count, with this
#: as a floor so two siblings are never placed on opposite sides of a tiny ring.
_MIN_RING_SLOTS = 3

#: How far a subfield sits from its discipline's centre. Larger than `_SPREAD` so
#: neighbourhoods within an island stay apart, and small enough that they stay inside it.
_CHILD_RADIUS = 8.0

#: Seeds the projection basis. A constant, never the data: a basis derived from the corpus
#: would shift as the corpus grew, which is the failure this module exists to avoid.
_BASIS_SEED = "papermatch.canvas.mosaic-v1"

#: Where the size scale saturates. Section 13 asks for サイズは対数圧縮 so that one paper a
#: reader has opened forty times does not dwarf everything around it.
_WEIGHT_SATURATION = 40.0


@dataclass(frozen=True)
class PlacedTile:
    entity_type: str
    entity_id: uuid.UUID
    x: float
    y: float
    cluster_id: str | None
    #: 0..1, already log-compressed. The client turns this into a tile area.
    weight: float
    user_override: bool
    #: When the reader saved it. Section 13's 年月スライダーで保存履歴を再生 needs this on the
    #: tile: the plane is what gets replayed, and a second request per tile to find out when
    #: each one arrived would make the slider unusable.
    saved_at: datetime


def _hash_unit(text: str, salt: str) -> float:
    """A stable number in [0, 1) from a string. Same input, same output, forever."""
    digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _slot_angle(index: int, count: int) -> float:
    """Evenly spread ``count`` items around a circle.

    Over the actual count rather than a fixed number of slots: three items in a
    twelve-slot ring occupy a quarter of it and crowd, which is what made the first
    version's islands overlap.
    """
    return math.tau * index / max(count, _MIN_RING_SLOTS)


def taxonomy_map(session: Session) -> dict[str, str | None]:
    """Field id to parent id, which is what `field_anchor` needs to build the islands."""
    return {field.id: field.parent_id for field in session.execute(select(Field)).scalars()}


def field_anchor(
    field_id: str | None, taxonomy: Mapping[str, str | None] | None = None
) -> tuple[float, float]:
    """The centre of a field's island.

    With a ``taxonomy`` — field id to parent id — a discipline takes an evenly spaced slot
    on the ring and a subfield sits in a smaller ring around its parent. Islands are then
    separated by construction, and a subfield is visibly *inside* its discipline.

    Without one, or for a field the taxonomy has never heard of, the id is hashed. That is
    the older behaviour and it is fine for the rare stray, but it is not good enough as
    the general rule: independent hashed angles collide, and colliding islands misreport
    the grouping.

    Papers with no field at all share one anchor rather than being scattered: "we do not
    know" is one place, not a hundred.
    """
    key = field_id or "__unknown__"
    if taxonomy is None or key not in taxonomy:
        angle = _hash_unit(key, "angle") * math.tau
        radius = _ANCHOR_RADIUS * (0.55 if _hash_unit(key, "ring") < 0.5 else 1.0)
        return (radius * math.cos(angle), radius * math.sin(angle))

    parent = taxonomy.get(key)
    if parent is None:
        roots = sorted(name for name, owner in taxonomy.items() if owner is None)
        angle = _slot_angle(roots.index(key), len(roots))
        return (_ANCHOR_RADIUS * math.cos(angle), _ANCHOR_RADIUS * math.sin(angle))

    parent_x, parent_y = field_anchor(parent, taxonomy)
    siblings = sorted(name for name, owner in taxonomy.items() if owner == parent)
    angle = _slot_angle(siblings.index(key), len(siblings))
    return (parent_x + _CHILD_RADIUS * math.cos(angle), parent_y + _CHILD_RADIUS * math.sin(angle))


def _basis(dimensions: int) -> tuple[list[float], list[float]]:
    """Two fixed pseudo-random unit vectors, generated from the seed and nothing else."""
    axes: list[list[float]] = []
    for axis in ("x", "y"):
        raw = [
            _hash_unit(f"{axis}:{index}", _BASIS_SEED) * 2.0 - 1.0 for index in range(dimensions)
        ]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        axes.append([value / norm for value in raw])
    return axes[0], axes[1]


def project(vector: list[float]) -> tuple[float, float]:
    """Project an embedding onto the fixed plane, in [-1, 1] per axis.

    A Johnson–Lindenstrauss style projection: it preserves relative distances in
    expectation while depending on nothing but the vector itself. Two similar papers land
    near each other, and neither moves when a third arrives.
    """
    if not vector:
        return (0.0, 0.0)
    axis_x, axis_y = _basis(len(vector))
    x = sum(a * b for a, b in zip(vector, axis_x, strict=False))
    y = sum(a * b for a, b in zip(vector, axis_y, strict=False))
    # The embeddings are L2-normalised (D-016), so a projection onto a unit axis is
    # already within [-1, 1]; the clamp guards a caller that passes something else.
    return (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))


def personal_weight(saved: SavedPaper, *, visits: int = 0) -> float:
    """How much this paper matters to this reader, in [0, 1].

    Section 13 lists 保存強度・滞在時間・再訪回数・翻訳回数・数式展開回数・明示的重要度 as
    candidates. Only the ones actually recorded are used: a weight that pretended to
    include dwell time while reading a column nobody fills would be a number with a
    misleading name.

    Log-compressed, because section 13 asks for it and because the alternative is one tile
    the size of a field island.
    """
    raw = 1.0 + float(saved.priority) + float(visits)
    if saved.last_visited_at is not None:
        raw += 1.0
    return min(1.0, math.log1p(raw) / math.log1p(_WEIGHT_SATURATION))


def tile_size(weight: float, *, minimum: float = 0.45, maximum: float = 0.95) -> float:
    """Tile edge length as a fraction of the grid step.

    **Never above 1.** Placement guarantees distinct *cells*, so a tile wider than its cell
    overlaps its neighbour no matter how carefully it was placed — which is what the first
    version did, and the plane came out with tiles sitting on top of each other despite the
    layout being correct. Capping below 1 is what makes the mosaic a mosaic.
    """
    return minimum + (maximum - minimum) * max(0.0, min(1.0, weight))


def _cell(x: float, y: float) -> tuple[int, int]:
    return (round(x / GRID_STEP), round(y / GRID_STEP))


def _spiral(cell: tuple[int, int], taken: set[tuple[int, int]]) -> tuple[int, int]:
    """The nearest free cell to ``cell``, searching outwards.

    Outwards from the *wanted* cell rather than by displacing whoever holds it: a new tile
    may only take a cell nobody has, which is what keeps every existing tile still.
    """
    if cell not in taken:
        return cell
    column, row = cell
    for ring in range(1, 64):
        for offset in range(-ring, ring + 1):
            for candidate in (
                (column + offset, row - ring),
                (column + offset, row + ring),
                (column - ring, row + offset),
                (column + ring, row + offset),
            ):
                if candidate not in taken:
                    return candidate
    # 64 rings is over sixteen thousand cells; a library that large has other problems.
    return (column, row + 64)


def layout_for(session: Session, user: User, *, limit: int = 500) -> list[PlacedTile]:
    """Positions for this reader's saved papers, creating only what is missing.

    Existing rows are returned untouched. That is the point: a reader who saves a paper
    sees one new tile appear, not a plane that has rearranged itself while they were away.
    """
    rows = list(
        session.execute(
            select(SavedPaper, Paper)
            .join(Paper, Paper.id == SavedPaper.paper_id)
            .where(SavedPaper.user_id == user.id)
            .order_by(SavedPaper.saved_at.asc())
            .limit(limit)
        ).all()
    )
    if not rows:
        return []

    existing = {
        position.entity_id: position
        for position in session.execute(
            select(CanvasPosition).where(
                CanvasPosition.user_id == user.id,
                CanvasPosition.entity_type == "paper",
                CanvasPosition.layout_version == LAYOUT_VERSION,
            )
        ).scalars()
    }
    taken = {_cell(position.x, position.y) for position in existing.values()}

    paper_ids = [paper.id for _, paper in rows]
    vectors = {
        embedding.entity_id: list(embedding.vector_json)
        for embedding in session.execute(
            select(Embedding).where(
                Embedding.entity_type == "paper", Embedding.entity_id.in_(paper_ids)
            )
        ).scalars()
    }

    taxonomy = taxonomy_map(session)

    tiles: list[PlacedTile] = []
    for saved, paper in rows:
        position = existing.get(paper.id)
        if position is None:
            anchor_x, anchor_y = field_anchor(paper.primary_field_id, taxonomy)
            offset_x, offset_y = project(vectors.get(paper.id, []))
            column, row = _spiral(
                _cell(anchor_x + offset_x * _SPREAD, anchor_y + offset_y * _SPREAD), taken
            )
            taken.add((column, row))
            position = CanvasPosition(
                user_id=user.id,
                entity_type="paper",
                entity_id=paper.id,
                x=column * GRID_STEP,
                y=row * GRID_STEP,
                cluster_id=paper.primary_field_id,
                layout_version=LAYOUT_VERSION,
                user_override=False,
            )
            session.add(position)
            existing[paper.id] = position

        tiles.append(
            PlacedTile(
                entity_type="paper",
                entity_id=paper.id,
                x=position.x,
                y=position.y,
                cluster_id=position.cluster_id,
                weight=personal_weight(saved),
                user_override=position.user_override,
                saved_at=saved.saved_at,
            )
        )

    session.flush()
    return tiles


def move_tile(
    session: Session, user: User, entity_id: uuid.UUID, *, x: float, y: float
) -> CanvasPosition:
    """Record that the reader put a tile somewhere (section 13: 手動配置を尊重).

    Sets `user_override`, which every future layout reads before it considers placing
    anything: a re-layout that quietly undid a reader's arrangement would make the plane
    untrustworthy in the way section 13 is trying to prevent.
    """
    position = session.execute(
        select(CanvasPosition).where(
            CanvasPosition.user_id == user.id,
            CanvasPosition.entity_type == "paper",
            CanvasPosition.entity_id == entity_id,
            CanvasPosition.layout_version == LAYOUT_VERSION,
        )
    ).scalar_one_or_none()

    if position is None:
        position = CanvasPosition(
            user_id=user.id,
            entity_type="paper",
            entity_id=entity_id,
            x=x,
            y=y,
            layout_version=LAYOUT_VERSION,
        )
        session.add(position)
    else:
        position.x = x
        position.y = y

    position.user_override = True
    session.flush()
    return position
