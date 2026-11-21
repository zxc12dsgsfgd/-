"""Keep deleted cards in the user's trash."""
from alembic import op
import sqlalchemy as sa

revision = '0021_card_trash'
down_revision = '0020_evidence_links'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cards', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_cards_deleted_at', 'cards', ['deleted_at'])


def downgrade():
    op.drop_index('ix_cards_deleted_at', table_name='cards')
    op.drop_column('cards', 'deleted_at')
