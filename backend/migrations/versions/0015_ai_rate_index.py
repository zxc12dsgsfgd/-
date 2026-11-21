"""Index AI job timestamps for per-user request limits."""
from alembic import op

revision = '0015_ai_rate_index'
down_revision = '0014_shares'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_ai_jobs_owner_created', 'ai_jobs', ['owner_id', 'created_at'])


def downgrade():
    op.drop_index('ix_ai_jobs_owner_created', table_name='ai_jobs')
