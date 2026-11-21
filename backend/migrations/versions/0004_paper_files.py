"""Create private paper file records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0004_paper_files'
down_revision = '0003_papers'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('paper_files',
        sa.Column('id', mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column('owner_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('paper_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('papers.id'), nullable=False),
        sa.Column('storage_key', sa.String(64), nullable=False, unique=True),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_paper_files_owner_id', 'paper_files', ['owner_id'])
    op.create_index('ix_paper_files_paper_id', 'paper_files', ['paper_id'])


def downgrade():
    op.drop_table('paper_files')
