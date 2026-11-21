"""Classify card content and retain source-link state without asserting verification."""
from alembic import op
import sqlalchemy as sa

revision = '0019_card_evidence'
down_revision = '0018_projects'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cards', sa.Column('content_kind', sa.String(20), nullable=False, server_default='unspecified'))
    op.add_column('cards', sa.Column('verification_status', sa.String(20), nullable=False, server_default='pending'))
    op.add_column('cards', sa.Column('source_state', sa.String(20), nullable=False, server_default='none'))
    op.execute("UPDATE cards SET source_state = CASE WHEN paper_id IS NOT NULL THEN 'linked' WHEN source_title_snapshot IS NOT NULL THEN 'unavailable' ELSE 'none' END")


def downgrade():
    op.drop_column('cards', 'source_state')
    op.drop_column('cards', 'verification_status')
    op.drop_column('cards', 'content_kind')
