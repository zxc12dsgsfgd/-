"""Create papers table for manual records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0003_papers"
down_revision = "0002_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("papers",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("owner_id", mysql.BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False), sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True), sa.Column("doi", sa.String(512), nullable=True),
        sa.Column("venue", sa.String(500), nullable=True), sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(2048), nullable=True), sa.Column("bibtex", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_papers_owner_id", "papers", ["owner_id"])
    op.create_index("ix_papers_owner_created_id", "papers", ["owner_id", "created_at", "id"])


def downgrade():
    op.drop_table("papers")
