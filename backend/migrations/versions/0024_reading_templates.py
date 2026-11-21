"""Add owned reading templates and structured paper notes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0024_reading_templates'
down_revision = '0023_paper_trash'
branch_labels = None
depends_on = None


def upgrade():
    ident=mysql.BIGINT(unsigned=True)
    op.create_table('reading_templates',sa.Column('id',ident,primary_key=True,autoincrement=True),
        sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('name',sa.String(200),nullable=False),sa.Column('fields',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),
        sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_reading_templates_owner_id','reading_templates',['owner_id'])
    op.create_table('structured_notes',sa.Column('id',ident,primary_key=True,autoincrement=True),
        sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),nullable=False),
        sa.Column('template_name',sa.String(200),nullable=False),sa.Column('fields',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),
        sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_structured_notes_owner_id','structured_notes',['owner_id'])
    op.create_index('ix_structured_notes_paper_id','structured_notes',['paper_id'])


def downgrade():
    op.drop_table('structured_notes')
    op.drop_table('reading_templates')
