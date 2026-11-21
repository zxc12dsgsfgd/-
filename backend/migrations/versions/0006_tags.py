"""Create tags and resource associations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0006_tags'
down_revision='0005_notes_cards'
branch_labels=None
depends_on=None

def upgrade():
    ident=mysql.BIGINT(unsigned=True)
    opts=dict(mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('tags',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('name',sa.String(100),nullable=False),sa.Column('name_norm',sa.String(300,collation='utf8mb4_bin'),nullable=False),sa.UniqueConstraint('owner_id','name_norm',name='uq_tag_owner_name'),**opts)
    op.create_index('ix_tags_owner_id','tags',['owner_id'])
    op.create_table('paper_tags',sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),primary_key=True),sa.Column('tag_id',ident,sa.ForeignKey('tags.id'),primary_key=True),**opts)
    op.create_table('card_tags',sa.Column('card_id',ident,sa.ForeignKey('cards.id'),primary_key=True),sa.Column('tag_id',ident,sa.ForeignKey('tags.id'),primary_key=True),**opts)

def downgrade():
    op.drop_table('card_tags');op.drop_table('paper_tags');op.drop_table('tags')
