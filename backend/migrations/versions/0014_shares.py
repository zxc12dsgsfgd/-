"""Create immutable shares and comments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0014_shares'
down_revision = '0013_ai_jobs'
branch_labels = None
depends_on = None


def upgrade():
    ident = mysql.BIGINT(unsigned=True)
    options = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    op.create_table('shares', sa.Column('id', ident, primary_key=True, autoincrement=True), sa.Column('owner_id', ident, sa.ForeignKey('users.id'), nullable=False), sa.Column('token_hash', mysql.BINARY(32), nullable=False, unique=True), sa.Column('expires_at', sa.DateTime(), nullable=False), sa.Column('revoked_at', sa.DateTime(), nullable=True), sa.Column('allow_comments', sa.Boolean(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()), **options)
    op.create_index('ix_shares_owner_id', 'shares', ['owner_id'])
    op.create_table('share_items', sa.Column('id', ident, primary_key=True, autoincrement=True), sa.Column('share_id', ident, sa.ForeignKey('shares.id'), nullable=False), sa.Column('item_type', sa.String(20), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False), **options)
    op.create_index('ix_share_items_share_id', 'share_items', ['share_id'])
    op.create_table('share_comments', sa.Column('id', ident, primary_key=True, autoincrement=True), sa.Column('share_id', ident, sa.ForeignKey('shares.id'), nullable=False), sa.Column('share_item_id', ident, sa.ForeignKey('share_items.id'), nullable=False), sa.Column('author_name', sa.String(100), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()), sa.Column('handled_at', sa.DateTime(), nullable=True), **options)
    op.create_index('ix_share_comments_share_id', 'share_comments', ['share_id'])


def downgrade():
    op.drop_table('share_comments')
    op.drop_table('share_items')
    op.drop_table('shares')
