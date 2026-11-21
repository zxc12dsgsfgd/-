"""Allow imported evidence snapshots with no surviving source."""
from alembic import op
import sqlalchemy as sa

revision='0025_evidence_source'
down_revision='0024_reading_templates'
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column('evidence_links','source_id',existing_type=sa.BigInteger(),nullable=True)

def downgrade():
    # Never invent a source ID for evidence whose source is missing.
    connection=op.get_bind()
    if connection.execute(sa.text('SELECT 1 FROM evidence_links WHERE source_id IS NULL LIMIT 1')).first():
        raise RuntimeError('无法降级：存在无来源编号的证据关联')
    op.alter_column('evidence_links','source_id',existing_type=sa.BigInteger(),nullable=False)
