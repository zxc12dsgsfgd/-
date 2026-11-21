"""Create AI job queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision='0013_ai_jobs';down_revision='0012_ai_drafts';branch_labels=None;depends_on=None
def upgrade():
    ident=mysql.BIGINT(unsigned=True)
    op.create_table('ai_jobs',sa.Column('id',ident,primary_key=True,autoincrement=True),sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),sa.Column('task_type',sa.String(30),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),sa.Column('base_url',sa.String(2048),nullable=False),sa.Column('model_name',sa.String(255),nullable=False),sa.Column('timeout_seconds',sa.Integer(),nullable=False),sa.Column('key_ciphertext',sa.LargeBinary(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('error_code',sa.String(50),nullable=True),sa.Column('draft_id',ident,sa.ForeignKey('drafts.id',ondelete='SET NULL'),nullable=True),sa.Column('started_at',sa.DateTime(),nullable=True),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_ai_jobs_owner_id','ai_jobs',['owner_id']);op.create_index('ix_ai_jobs_status','ai_jobs',['status'])
def downgrade():op.drop_table('ai_jobs')
