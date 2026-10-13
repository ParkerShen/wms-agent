"""require nonempty order number

Revision ID: 2731be87fa98
Revises: 5dff32ec4b1f
Create Date: 2026-10-10 18:47:36.399338

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2731be87fa98'
down_revision = '5dff32ec4b1f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_orders_order_no_nonempty",
        "orders",
        "length(order_no) > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_order_no_nonempty", "orders", type_="check")
