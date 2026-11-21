"""Create encrypted AI configuration and drafts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0012_ai_drafts';down_revision='0011_reports_failures';branch_labels=None;depends_on=None
def upgrade():
    ident=mysql.BIGINT(unsigned=True);opts=dict(mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('ai_configs',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False,unique=True),sa.Column('base_url',sa.String(2048),nullable=False),sa.Column('model_name',sa.String(255),nullable=False),sa.Column('timeout_seconds',sa.Integer(),nullable=False),sa.Column('key_ciphertext',sa.LargeBinary(),nullable=False),**opts)
    op.create_table('drafts',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('task_type',sa.String(30),nullable=False),sa.Column('title',sa.String(500),nullable=False),sa.Column('content',sa.Text(),nullable=False),sa.Column('sources',sa.JSON(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),sa.Column('updated_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),**opts)
    op.create_index('ix_drafts_owner_id','drafts',['owner_id'])
def downgrade():op.drop_table('drafts');op.drop_table('ai_configs')
