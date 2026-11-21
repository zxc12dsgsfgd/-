"""Record paper status transitions and scheduler failures."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0011_reports_failures';down_revision='0010_workflow_actions';branch_labels=None;depends_on=None
def upgrade():
    ident=mysql.BIGINT(unsigned=True);opts=dict(mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('paper_status_events',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),nullable=False),sa.Column('to_status',sa.String(20),nullable=False),sa.Column('occurred_at',sa.DateTime(),nullable=False),**opts)
    for col in ('owner_id','paper_id','occurred_at'):op.create_index('ix_paper_status_events_'+col,'paper_status_events',[col])
    op.create_table('scheduler_failures',sa.Column('event_id',sa.String(36),primary_key=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('workflow_id',ident,sa.ForeignKey('workflows.id',ondelete='SET NULL'),nullable=True),sa.Column('workflow_name',sa.String(200),nullable=False),sa.Column('object_id',sa.BigInteger(),nullable=False),sa.Column('error_code',sa.String(80),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('next_retry_at',sa.DateTime(),nullable=False),sa.Column('resolved_at',sa.DateTime(),nullable=True),sa.Column('updated_at',sa.DateTime(),nullable=False),**opts)
    op.create_index('ix_scheduler_failures_owner_id','scheduler_failures',['owner_id'])
def downgrade():
    op.drop_table('scheduler_failures');op.drop_table('paper_status_events')
