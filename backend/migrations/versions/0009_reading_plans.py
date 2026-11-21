"""Create reading plans and items."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0009_reading_plans';down_revision='0008_workflows';branch_labels=None;depends_on=None
def upgrade():
    ident=mysql.BIGINT(unsigned=True);opts=dict(mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('reading_plans',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('start_date',sa.Date(),nullable=False),sa.Column('end_date',sa.Date(),nullable=True),sa.Column('target_count',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),**opts)
    op.create_index('ix_reading_plans_owner_id','reading_plans',['owner_id'])
    op.create_table('reading_plan_items',sa.Column('plan_id',ident,sa.ForeignKey('reading_plans.id'),primary_key=True),sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),primary_key=True),**opts)
def downgrade():
    op.drop_table('reading_plan_items');op.drop_table('reading_plans')
