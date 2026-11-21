"""Add workflow action configuration."""
from alembic import op
import sqlalchemy as sa
revision='0010_workflow_actions';down_revision='0009_reading_plans';branch_labels=None;depends_on=None
def upgrade():
    op.add_column('workflows',sa.Column('action_type',sa.String(30),nullable=False,server_default='notify'))
    op.add_column('workflows',sa.Column('action_value',sa.String(100),nullable=True))
def downgrade():
    op.drop_column('workflows','action_value');op.drop_column('workflows','action_type')
