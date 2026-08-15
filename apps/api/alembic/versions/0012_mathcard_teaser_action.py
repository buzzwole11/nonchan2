"""Two schema notes for the maths cards' entrances (spec section 10).

Section 10 lists Discoverフィードへ低頻度で混ぜる as one of the maths cards' entrances, and
低頻度 needs a memory: without one, every page one would carry a card and the frequency
would be "always". Recorded as an action for the same reason `resurface_saved` was — the
audit trail should answer 「なぜこれが出てきたのか」 without this feature keeping books of
its own.

Revision ID: 0012_mathcard_teaser
Revises: 0011_explanations
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_mathcard_teaser"
down_revision: str | None = "0011_explanations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'less_similar', 'more_experimental', 'more_classic', "
    "'resurface_saved', 'undo')"
)
NEW_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'less_similar', 'more_experimental', 'more_classic', "
    "'resurface_saved', 'mathcard_teaser', 'undo')"
)


OLD_CANVAS_ENTITY = "entity_type IN ('paper', 'equation', 'expression')"
NEW_CANVAS_ENTITY = "entity_type IN ('paper', 'equation', 'expression', 'math_card')"


def upgrade() -> None:
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", NEW_ACTION_TYPE)
    # Section 10's Canvas上の独立タイル: a maths card is now something the plane can hold.
    op.drop_constraint("ck_canvas_entity_type", "canvas_positions", type_="check")
    op.create_check_constraint("ck_canvas_entity_type", "canvas_positions", NEW_CANVAS_ENTITY)


def downgrade() -> None:
    # The app's own notes, not something the reader did. Losing them only resets the
    # cooldown and the tile placement, which rebuild themselves.
    op.execute(sa.text("DELETE FROM actions WHERE action_type = 'mathcard_teaser'"))
    op.execute(sa.text("DELETE FROM canvas_positions WHERE entity_type = 'math_card'"))
    op.drop_constraint("ck_canvas_entity_type", "canvas_positions", type_="check")
    op.create_check_constraint("ck_canvas_entity_type", "canvas_positions", OLD_CANVAS_ENTITY)
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", OLD_ACTION_TYPE)
