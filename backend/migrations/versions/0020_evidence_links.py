"""Preserve manually managed evidence and its change history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0020_evidence_links'
down_revision = '0019_card_evidence'
branch_labels = None
depends_on = None


def upgrade():
    ident = mysql.BIGINT(unsigned=True)
    op.create_table('evidence_links',
        sa.Column('id', ident, primary_key=True, autoincrement=True),
        sa.Column('owner_id', ident, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('card_id', ident, sa.ForeignKey('cards.id', ondelete='CASCADE'), nullable=True),
        sa.Column('draft_id', ident, sa.ForeignKey('drafts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('source_type', sa.String(20), nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=False),
        sa.Column('source_snapshot', sa.JSON(), nullable=False),
        sa.Column('location', sa.String(200), nullable=False),
        sa.Column('excerpt', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('removed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint('(card_id IS NULL) <> (draft_id IS NULL)', name='ck_evidence_parent'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    for name in ('owner_id', 'card_id', 'draft_id'):
        op.create_index(f'ix_evidence_links_{name}', 'evidence_links', [name])
    op.create_table('evidence_changes',
        sa.Column('id', ident, primary_key=True, autoincrement=True),
        sa.Column('owner_id', ident, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('link_id', ident, sa.ForeignKey('evidence_links.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    for name in ('owner_id', 'link_id'):
        op.create_index(f'ix_evidence_changes_{name}', 'evidence_changes', [name])


def downgrade():
    op.drop_table('evidence_changes')
    op.drop_table('evidence_links')
