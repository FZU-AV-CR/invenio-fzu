# SPDX-FileCopyrightText: 2016-2018 CERN.
# SPDX-License-Identifier: MIT

"""Create physica branch."""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1789039339'
down_revision = None
branch_labels = ('physica',)
depends_on = None


def upgrade():
    """Upgrade database."""
    pass


def downgrade():
    """Downgrade database."""
    pass
