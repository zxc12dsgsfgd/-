"""Keep deleted papers and attachments until explicitly purged."""
from alembic import op
import sqlalchemy as sa

revision = '0023_paper_trash'
down_revision = '0022_project_trash'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_papers_deleted_at', 'papers', ['deleted_at'])


def downgrade():
    op.drop_index('ix_papers_deleted_at', table_name='papers')
    op.drop_column('papers', 'deleted_at')
