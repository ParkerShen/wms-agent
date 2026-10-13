from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventoryBalance, InTransitInventory, SKU, Warehouse, WarehouseLocation


class InventoryNotFoundError(Exception):
    """Raised when either the requested warehouse code or SKU code is unknown."""


def query_inventory(session: Session, warehouse_code: str, sku_code: str) -> dict:
    """Return synthetic inventory totals and location rows for one warehouse/SKU.

    Available quantity is the project assumption ``good_on_hand - allocated -
    frozen``. In-transit stock is reported separately. A known warehouse/SKU with
    no balance or in-transit row returns zero quantities and no locations; unknown
    warehouse or SKU codes raise InventoryNotFoundError.
    """
    warehouse = session.scalar(select(Warehouse).where(Warehouse.code == warehouse_code))
    if warehouse is None:
        raise InventoryNotFoundError("Warehouse not found.")

    sku = session.scalar(select(SKU).where(SKU.code == sku_code))
    if sku is None:
        raise InventoryNotFoundError("SKU not found.")

    good_on_hand, allocated, frozen, balance_count = session.execute(
        select(
            func.coalesce(func.sum(InventoryBalance.good_on_hand), 0),
            func.coalesce(func.sum(InventoryBalance.allocated), 0),
            func.coalesce(func.sum(InventoryBalance.frozen), 0),
            func.count(InventoryBalance.id),
        )
        .join(WarehouseLocation, InventoryBalance.location_id == WarehouseLocation.id)
        .where(WarehouseLocation.warehouse_id == warehouse.id, InventoryBalance.sku_id == sku.id)
    ).one()

    location_rows = session.execute(
        select(
            WarehouseLocation.code,
            WarehouseLocation.area_code,
            WarehouseLocation.storage_type,
            InventoryBalance.good_on_hand,
            InventoryBalance.allocated,
            InventoryBalance.frozen,
        )
        .join(InventoryBalance, InventoryBalance.location_id == WarehouseLocation.id)
        .where(WarehouseLocation.warehouse_id == warehouse.id, InventoryBalance.sku_id == sku.id)
        .order_by(WarehouseLocation.code)
    ).all()

    in_transit = session.scalar(
        select(InTransitInventory.quantity).where(
            InTransitInventory.warehouse_id == warehouse.id,
            InTransitInventory.sku_id == sku.id,
        )
    )
    has_transit_record = in_transit is not None
    in_transit = in_transit or 0

    warehouse_data = {"code": warehouse.code, "name": warehouse.name}
    for field in ("name_en", "region", "region_cn", "country", "country_cn", "city", "city_cn"):
        value = getattr(warehouse, field)
        if value is not None:
            warehouse_data[field] = value

    sku_data = {"code": sku.code, "name": sku.name}
    for field in (
        "name_en", "category_code", "category_name", "category_name_en", "is_hazmat",
        "hazmat_class", "un_number", "is_oversized", "length_mm", "width_mm", "height_mm", "weight_g",
    ):
        value = getattr(sku, field)
        if value is not None:
            sku_data[field] = value

    locations = []
    for row in location_rows:
        location = {
            "code": row.code,
            "good_on_hand": row.good_on_hand,
            "allocated": row.allocated,
            "frozen": row.frozen,
            "available": row.good_on_hand - row.allocated - row.frozen,
        }
        if row.area_code is not None:
            location["area_code"] = row.area_code
        if row.storage_type is not None:
            location["storage_type"] = row.storage_type
        locations.append(location)

    return {
        "warehouse": warehouse_data,
        "sku": sku_data,
        "good_on_hand": good_on_hand,
        "allocated": allocated,
        "frozen": frozen,
        "available": good_on_hand - allocated - frozen,
        "in_transit": in_transit,
        "has_inventory_record": balance_count > 0 or has_transit_record,
        "locations": locations,
    }


def query_warehouses(session: Session) -> list[dict]:
    """Return the ordered warehouse rows from the current fictional showcase batch."""
    warehouses = session.scalars(
        select(Warehouse)
        .where(Warehouse.batch_id == "SHOWCASE-V2-20261013")
        .order_by(Warehouse.display_id)
    ).all()
    return [
        {
            "id": warehouse.display_id,
            "code": warehouse.code,
            "region": warehouse.region,
            "region_cn": warehouse.region_cn,
            "country": warehouse.country,
            "country_cn": warehouse.country_cn,
            "city": warehouse.city,
            "city_cn": warehouse.city_cn,
            "name": warehouse.name,
            "name_en": warehouse.name_en,
            "address": warehouse.address,
            "address_cn": warehouse.address_cn,
            "postal_code": warehouse.postal_code,
            "phone": warehouse.phone,
            "latitude": warehouse.latitude,
            "longitude": warehouse.longitude,
            "status": warehouse.status,
            "status_cn": warehouse.status_cn,
            "fictional_demo_data": True,
        }
        for warehouse in warehouses
    ]
