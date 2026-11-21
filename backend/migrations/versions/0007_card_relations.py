"""Create card relations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0007_card_relations'
down_revision='0006_tags'
branch_labels=None
depends_on=None

def upgrade():
    ident=mysql.BIGINT(unsigned=True)
    op.create_table('card_relations',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('source_card_id',ident,sa.ForeignKey('cards.id'),nullable=False),sa.Column('target_card_id',ident,sa.ForeignKey('cards.id'),nullable=False),sa.Column('relation_type',sa.String(20),nullable=False),sa.UniqueConstraint('owner_id','source_card_id','target_card_id','relation_type',name='uq_card_relation'),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_card_relations_owner_id','card_relations',['owner_id']);op.create_index('ix_card_relations_source_card_id','card_relations',['source_card_id']);op.create_index('ix_card_relations_target_card_id','card_relations',['target_card_id'])

def downgrade():op.drop_table('card_relations')
