"""add international warehouse and product attributes

Revision ID: 9ac42b7de613
Revises: 2731be87fa98
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9ac42b7de613"
down_revision = "2731be87fa98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    warehouse_columns = (
        sa.Column("display_id", sa.Integer(), nullable=True),
        sa.Column("name_en", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("region_cn", sa.String(length=80), nullable=True),
        sa.Column("country", sa.String(length=3), nullable=True),
        sa.Column("country_cn", sa.String(length=80), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("city_cn", sa.String(length=100), nullable=True),
        sa.Column("address", sa.String(length=240), nullable=True),
        sa.Column("address_cn", sa.String(length=240), nullable=True),
        sa.Column("postal_code", sa.String(length=24), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=True),
        sa.Column("status_cn", sa.String(length=24), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
    )
    for column in warehouse_columns:
        op.add_column("warehouses", column)
    op.create_unique_constraint("uq_warehouses_display_id", "warehouses", ["display_id"])
    op.create_check_constraint(
        "ck_warehouses_latitude_range",
        "warehouses",
        "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
    )
    op.create_check_constraint(
        "ck_warehouses_longitude_range",
        "warehouses",
        "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
    )
    op.create_index("ix_warehouses_batch_id", "warehouses", ["batch_id"])

    sku_columns = (
        sa.Column("name_en", sa.String(length=160), nullable=True),
        sa.Column("category_code", sa.String(length=40), nullable=True),
        sa.Column("category_name", sa.String(length=80), nullable=True),
        sa.Column("category_name_en", sa.String(length=80), nullable=True),
        sa.Column("is_hazmat", sa.Boolean(), nullable=True),
        sa.Column("hazmat_class", sa.String(length=40), nullable=True),
        sa.Column("un_number", sa.String(length=12), nullable=True),
        sa.Column("is_oversized", sa.Boolean(), nullable=True),
        sa.Column("length_mm", sa.Integer(), nullable=True),
        sa.Column("width_mm", sa.Integer(), nullable=True),
        sa.Column("height_mm", sa.Integer(), nullable=True),
        sa.Column("weight_g", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
    )
    for column in sku_columns:
        op.add_column("skus", column)
    op.create_check_constraint("ck_skus_code_nonempty", "skus", "length(code) > 0")
    op.create_check_constraint("ck_skus_code_length", "skus", "length(code) <= 80")
    op.create_check_constraint("ck_skus_name_en_length", "skus", "length(name_en) <= 160")
    op.create_check_constraint("ck_skus_category_code_length", "skus", "length(category_code) <= 40")
    op.create_check_constraint(
        "ck_skus_dimensions_positive",
        "skus",
        "(length_mm IS NULL OR length_mm > 0) AND "
        "(width_mm IS NULL OR width_mm > 0) AND "
        "(height_mm IS NULL OR height_mm > 0)",
    )
    op.create_check_constraint("ck_skus_weight_positive", "skus", "weight_g IS NULL OR weight_g > 0")
    op.create_check_constraint(
        "ck_skus_hazmat_class_required",
        "skus",
        "is_hazmat IS NOT TRUE OR hazmat_class IS NOT NULL",
    )
    op.create_index("ix_skus_batch_id", "skus", ["batch_id"])

    op.add_column("warehouse_locations", sa.Column("area_code", sa.String(length=24), nullable=True))
    op.add_column("warehouse_locations", sa.Column("storage_type", sa.String(length=24), nullable=True))
    op.add_column("warehouse_locations", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_index("ix_warehouse_locations_batch_id", "warehouse_locations", ["batch_id"])

    op.add_column("orders", sa.Column("warehouse_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_orders_warehouse_id_warehouses",
        "orders",
        "warehouses",
        ["warehouse_id"],
        ["id"],
    )
    op.create_index("ix_orders_warehouse_id", "orders", ["warehouse_id"])
    op.create_index("ix_orders_batch_id", "orders", ["batch_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint("line_no > 0", name="ck_order_items_line_no_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_nonnegative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "line_no", name="uq_order_items_order_line"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_sku_id", "order_items", ["sku_id"])
    op.create_index("ix_order_items_batch_id", "order_items", ["batch_id"])

    for table in (
        "inventory_balances",
        "in_transit_inventory",
        "order_tracking_events",
        "order_exceptions",
    ):
        op.add_column(table, sa.Column("batch_id", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_batch_id", table, ["batch_id"])


def downgrade() -> None:
    for table in (
        "inventory_balances",
        "in_transit_inventory",
        "order_tracking_events",
        "order_exceptions",
    ):
        op.drop_index(f"ix_{table}_batch_id", table_name=table)
        op.drop_column(table, "batch_id")

    op.drop_index("ix_order_items_batch_id", table_name="order_items")
    op.drop_index("ix_order_items_sku_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_batch_id", table_name="orders")
    op.drop_index("ix_orders_warehouse_id", table_name="orders")
    op.drop_constraint("fk_orders_warehouse_id_warehouses", "orders", type_="foreignkey")
    op.drop_column("orders", "batch_id")
    op.drop_column("orders", "warehouse_id")

    op.drop_index("ix_warehouse_locations_batch_id", table_name="warehouse_locations")
    op.drop_column("warehouse_locations", "batch_id")
    op.drop_column("warehouse_locations", "storage_type")
    op.drop_column("warehouse_locations", "area_code")

    for constraint in (
        "ck_skus_hazmat_class_required",
        "ck_skus_weight_positive",
        "ck_skus_dimensions_positive",
        "ck_skus_category_code_length",
        "ck_skus_name_en_length",
        "ck_skus_code_length",
        "ck_skus_code_nonempty",
    ):
        op.drop_constraint(constraint, "skus", type_="check")
    op.drop_index("ix_skus_batch_id", table_name="skus")
    for column in (
        "batch_id",
        "weight_g",
        "height_mm",
        "width_mm",
        "length_mm",
        "is_oversized",
        "un_number",
        "hazmat_class",
        "is_hazmat",
        "category_name_en",
        "category_name",
        "category_code",
        "name_en",
    ):
        op.drop_column("skus", column)

    op.drop_index("ix_warehouses_batch_id", table_name="warehouses")
    op.drop_constraint("ck_warehouses_longitude_range", "warehouses", type_="check")
    op.drop_constraint("ck_warehouses_latitude_range", "warehouses", type_="check")
    op.drop_constraint("uq_warehouses_display_id", "warehouses", type_="unique")
    for column in (
        "batch_id",
        "status_cn",
        "status",
        "longitude",
        "latitude",
        "phone",
        "postal_code",
        "address_cn",
        "address",
        "city_cn",
        "city",
        "country_cn",
        "country",
        "region_cn",
        "region",
        "name_en",
        "display_id",
    ):
        op.drop_column("warehouses", column)
