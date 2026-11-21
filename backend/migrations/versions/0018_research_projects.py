"""Add owned research projects and resource links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0018_projects'
down_revision = '0017_rate_limits'
branch_labels = None
depends_on = None


def upgrade():
    ident = mysql.BIGINT(unsigned=True)
    op.create_table('research_projects',
        sa.Column('id', ident, primary_key=True, autoincrement=True),
        sa.Column('owner_id', ident, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_research_projects_owner_id', 'research_projects', ['owner_id'])
    for table, target in [('project_papers', 'papers'), ('project_cards', 'cards'),
                          ('project_plans', 'reading_plans'), ('project_drafts', 'drafts')]:
        op.create_table(table,
            sa.Column('project_id', ident, sa.ForeignKey('research_projects.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('resource_id', ident, sa.ForeignKey(f'{target}.id', ondelete='CASCADE'), primary_key=True),
            mysql_engine='InnoDB', mysql_charset='utf8mb4')


def downgrade():
    for table in ('project_drafts', 'project_plans', 'project_cards', 'project_papers'):
        op.drop_table(table)
    op.drop_index('ix_research_projects_owner_id', table_name='research_projects')
    op.drop_table('research_projects')
