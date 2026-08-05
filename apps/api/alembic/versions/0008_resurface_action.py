"""An action type for a saved paper being brought back (spec section 9).

Section 9's 保存を墓場にしない再提示 needs to remember which papers it has already reminded
the reader about, or it reminds them of the same one every session.

Recorded as an action rather than in a column of its own, so it is in the same audit trail
as everything else the app did on the reader's behalf — and so 「なぜこれがまた出てきたのか」
has an answer that does not depend on this feature's own bookkeeping.

Revision ID: 0008_resurface_action
Revises: 0007_login_and_notifications
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_resurface_action"
down_revision: str | None = "0007_login_and_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'less_similar', 'more_experimental', 'more_classic', "
    "'undo')"
)
NEW_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'less_similar', 'more_experimental', 'more_classic', "
    "'resurface_saved', 'undo')"
)


def upgrade() -> None:
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", NEW_ACTION_TYPE)


def downgrade() -> None:
    # These rows are the app's own note that it re-presented something, not a request the
    # reader made. Deleting them loses only the cooldown, which rebuilds itself.
    op.execute(sa.text("DELETE FROM actions WHERE action_type = 'resurface_saved'"))
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", OLD_ACTION_TYPE)
