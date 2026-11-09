"""\u0024{message}"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

\u0024{imports if imports else ""}

revision: str = \u0024{repr(up_revision)}
down_revision: str | None = \u0024{repr(down_revision)}
branch_labels: str | Sequence[str] | None = \u0024{repr(branch_labels)}
depends_on: str | Sequence[str] | None = \u0024{repr(depends_on)}


def upgrade() -> None:
    \u0024{"pass" if not upgrade_ops else upgrade_ops}


def downgrade() -> None:
    \u0024{"pass" if not downgrade_ops else downgrade_ops}
