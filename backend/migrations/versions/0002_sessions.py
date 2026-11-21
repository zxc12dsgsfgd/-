"""Create server-side login sessions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0002_sessions"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade():
    op.drop_table("sessions")
