"""Record synchronous workflow failures after business rollback."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0016_sync_failures'
down_revision = '0015_ai_rate_index'
branch_labels = None
depends_on = None


def upgrade():
    ident = mysql.BIGINT(unsigned=True)
    op.create_table('workflow_sync_failures',
        sa.Column('id', ident, primary_key=True, autoincrement=True),
        sa.Column('owner_id', ident, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('workflow_name', sa.String(200), nullable=False),
        sa.Column('trigger', sa.String(40), nullable=False),
        sa.Column('object_id', sa.BigInteger(), nullable=True),
        sa.Column('error_code', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_workflow_sync_failures_owner_id', 'workflow_sync_failures', ['owner_id'])


def downgrade():
    op.drop_table('workflow_sync_failures')
