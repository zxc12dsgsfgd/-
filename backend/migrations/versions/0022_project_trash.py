"""Keep deleted research projects in the user's trash."""
from alembic import op
import sqlalchemy as sa

revision = '0022_project_trash'
down_revision = '0021_card_trash'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('research_projects', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_research_projects_deleted_at', 'research_projects', ['deleted_at'])


def downgrade():
    op.drop_index('ix_research_projects_deleted_at', table_name='research_projects')
    op.drop_column('research_projects', 'deleted_at')
