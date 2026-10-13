from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_warehouses_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_warehouses_longitude_range",
        ),
        UniqueConstraint("display_id", name="uq_warehouses_display_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_id: Mapped[int | None] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(80))
    region_cn: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(3))
    country_cn: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(100))
    city_cn: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(240))
    address_cn: Mapped[str | None] = mapped_column(String(240))
    postal_code: Mapped[str | None] = mapped_column(String(24))
    phone: Mapped[str | None] = mapped_column(String(40))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(24))
    status_cn: Mapped[str | None] = mapped_column(String(24))
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class SKU(Base):
    __tablename__ = "skus"
    __table_args__ = (
        CheckConstraint(
            "length(code) > 0",
            name="ck_skus_code_nonempty",
        ),
        CheckConstraint(
            "length(code) <= 80",
            name="ck_skus_code_length",
        ),
        CheckConstraint(
            "length(name_en) <= 160",
            name="ck_skus_name_en_length",
        ),
        CheckConstraint(
            "length(category_code) <= 40",
            name="ck_skus_category_code_length",
        ),
        CheckConstraint(
            "(length_mm IS NULL OR length_mm > 0) AND "
            "(width_mm IS NULL OR width_mm > 0) AND "
            "(height_mm IS NULL OR height_mm > 0)",
            name="ck_skus_dimensions_positive",
        ),
        CheckConstraint(
            "weight_g IS NULL OR weight_g > 0",
            name="ck_skus_weight_positive",
        ),
        CheckConstraint(
            "is_hazmat IS NOT TRUE OR hazmat_class IS NOT NULL",
            name="ck_skus_hazmat_class_required",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(160))
    category_code: Mapped[str | None] = mapped_column(String(40))
    category_name: Mapped[str | None] = mapped_column(String(80))
    category_name_en: Mapped[str | None] = mapped_column(String(80))
    is_hazmat: Mapped[bool | None] = mapped_column(Boolean)
    hazmat_class: Mapped[str | None] = mapped_column(String(40))
    un_number: Mapped[str | None] = mapped_column(String(12))
    is_oversized: Mapped[bool | None] = mapped_column(Boolean)
    length_mm: Mapped[int | None] = mapped_column(Integer)
    width_mm: Mapped[int | None] = mapped_column(Integer)
    height_mm: Mapped[int | None] = mapped_column(Integer)
    weight_g: Mapped[int | None] = mapped_column(Integer)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class WarehouseLocation(Base):
    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_warehouse_locations_warehouse_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    area_code: Mapped[str | None] = mapped_column(String(24))
    storage_type: Mapped[str | None] = mapped_column(String(24))
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("length(order_no) > 0", name="ck_orders_order_no_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status_text: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_order_items_order_line"),
        CheckConstraint("line_no > 0", name="ck_order_items_line_no_positive"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OrderException(Base):
    __tablename__ = "order_exceptions"
    __table_args__ = (
        UniqueConstraint("order_id", "record_key", name="uq_order_exceptions_order_record_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_key: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OrderTrackingEvent(Base):
    __tablename__ = "order_tracking_events"
    __table_args__ = (
        UniqueConstraint("order_id", "record_key", name="uq_order_tracking_events_order_record_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_key: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    carrier: Mapped[str | None] = mapped_column(String(120))
    tracking_no: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("location_id", "sku_id", name="uq_inventory_balances_location_sku"),
        CheckConstraint("good_on_hand >= 0", name="ck_inventory_balances_good_on_hand_nonnegative"),
        CheckConstraint("allocated >= 0", name="ck_inventory_balances_allocated_nonnegative"),
        CheckConstraint("frozen >= 0", name="ck_inventory_balances_frozen_nonnegative"),
        CheckConstraint(
            "allocated + frozen <= good_on_hand",
            name="ck_inventory_balances_allocated_frozen_within_good_on_hand",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_locations.id"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    good_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frozen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class InTransitInventory(Base):
    __tablename__ = "in_transit_inventory"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "sku_id", name="uq_in_transit_inventory_warehouse_sku"),
        CheckConstraint("quantity >= 0", name="ck_in_transit_inventory_quantity_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
