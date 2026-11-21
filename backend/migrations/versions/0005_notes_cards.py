"""Create notes, cards and card history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0005_notes_cards'
down_revision = '0004_paper_files'
branch_labels = None
depends_on = None


def upgrade():
    ident = mysql.BIGINT(unsigned=True)
    common = dict(mysql_engine='InnoDB', mysql_charset='utf8mb4')
    timestamps = lambda: [sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp())]
    op.create_table('paper_notes',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),nullable=False),sa.Column('content',sa.Text(),nullable=False),*timestamps(),**common)
    op.create_index('ix_paper_notes_owner_id','paper_notes',['owner_id']); op.create_index('ix_paper_notes_paper_id','paper_notes',['paper_id'])
    op.create_table('cards',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),nullable=True),sa.Column('source_title_snapshot',sa.String(500),nullable=True),sa.Column('title',sa.String(500),nullable=False),sa.Column('type',sa.String(20),nullable=False),sa.Column('content',sa.Text(),nullable=False),sa.Column('source_page',sa.Integer(),nullable=True),sa.Column('source_excerpt',sa.Text(),nullable=True),sa.Column('note',sa.Text(),nullable=True),sa.Column('version',sa.Integer(),nullable=False),*timestamps(),**common)
    op.create_index('ix_cards_owner_id','cards',['owner_id']);op.create_index('ix_cards_paper_id','cards',['paper_id'])
    op.create_table('card_versions',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('card_id',ident,sa.ForeignKey('cards.id'),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.UniqueConstraint('card_id','version',name='uq_card_version'),**common)
    op.create_index('ix_card_versions_owner_id','card_versions',['owner_id']);op.create_index('ix_card_versions_card_id','card_versions',['card_id'])


def downgrade():
    op.drop_table('card_versions'); op.drop_table('cards'); op.drop_table('paper_notes')
