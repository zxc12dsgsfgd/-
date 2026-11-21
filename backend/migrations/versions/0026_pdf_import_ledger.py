"""Track reserved files for recoverable PDF import batches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision='0026_pdf_import'
down_revision='0025_evidence_source'
branch_labels=None
depends_on=None

def upgrade():
    ident=mysql.BIGINT(unsigned=True)
    op.create_table('pdf_import_batches',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('owner_id',ident,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('archive_sha256',sa.String(64),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.current_timestamp()),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_pdf_import_batches_owner_id','pdf_import_batches',['owner_id'])
    op.create_index('ix_pdf_import_batches_status','pdf_import_batches',['status'])
    op.create_table('pdf_import_items',sa.Column('id',ident,primary_key=True,autoincrement=True),
        sa.Column('batch_id',sa.String(32),sa.ForeignKey('pdf_import_batches.id'),nullable=False),
        sa.Column('paper_id',ident,sa.ForeignKey('papers.id'),nullable=False),
        sa.Column('storage_key',sa.String(64),nullable=False,unique=True),
        sa.Column('original_name',sa.String(255),nullable=False),sa.Column('size_bytes',sa.BigInteger(),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_pdf_import_items_batch_id','pdf_import_items',['batch_id'])
    op.create_index('ix_pdf_import_items_paper_id','pdf_import_items',['paper_id'])

def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM pdf_import_batches WHERE status != 'completed' LIMIT 1")).first():
        raise RuntimeError('无法降级：存在未完成的 PDF 导入批次')
    op.drop_table('pdf_import_items')
    op.drop_table('pdf_import_batches')
