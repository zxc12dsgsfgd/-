"""Create notification workflow foundation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0008_workflows';down_revision='0007_card_relations';branch_labels=None;depends_on=None
def upgrade():
    ident=mysql.BIGINT(unsigned=True); opts=dict(mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('workflows',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('trigger',sa.String(40),nullable=False),sa.Column('filter_value',sa.String(40),nullable=True),sa.Column('message',sa.String(1000),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),**opts)
    op.create_index('ix_workflows_owner_id','workflows',['owner_id'])
    op.create_table('workflow_events',sa.Column('id',sa.String(36),primary_key=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('trigger',sa.String(40),nullable=False),sa.Column('object_id',sa.BigInteger(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),**opts)
    op.create_index('ix_workflow_events_owner_id','workflow_events',['owner_id'])
    op.create_table('workflow_runs',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('workflow_id',ident,sa.ForeignKey('workflows.id',ondelete='SET NULL'),nullable=True),sa.Column('event_id',sa.String(36),sa.ForeignKey('workflow_events.id'),nullable=False),sa.Column('workflow_name',sa.String(200),nullable=False),sa.Column('result',sa.String(20),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.UniqueConstraint('workflow_id','event_id',name='uq_workflow_event'),**opts)
    for col in ('owner_id','workflow_id','event_id'):op.create_index('ix_workflow_runs_'+col,'workflow_runs',[col])
    op.create_table('notifications',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('run_id',ident,sa.ForeignKey('workflow_runs.id'),nullable=False,unique=True),sa.Column('message',sa.String(1000),nullable=False),sa.Column('read_at',sa.DateTime(),nullable=True),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),**opts)
    op.create_index('ix_notifications_owner_id','notifications',['owner_id'])
def downgrade():
    for table in ('notifications','workflow_runs','workflow_events','workflows'):op.drop_table(table)
