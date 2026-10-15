"""Read-only discovery queries for the fictional bilingual showcase catalog."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventoryBalance, InTransitInventory, SKU, Warehouse, WarehouseLocation


SHOWCASE_BATCH_ID = "SHOWCASE-V2-20261013"
MAX_PAGE_SIZE = 5
WAREHOUSE_PAGE_SIZE = 10


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _page(items: list[dict], offset: int, limit: int, total: int) -> dict:
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    return {
        "status": "ok",
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
    }


def _resolve(
    query: str,
    rows: list,
    aliases,
    identity,
) -> dict:
    normalized_query = _normalize(query)
    if not normalized_query:
        return {"status": "not_found", "query": query, "candidates": []}
    exact = [row for row in rows if normalized_query in {_normalize(alias) for alias in aliases(row) if alias}]
    matches = exact or [
        row
        for row in rows
        if any(
            normalized_query in _normalize(alias)
            or _normalize(alias) in normalized_query
            or "".join(normalized_query.split()) in "".join(_normalize(alias).split())
            or "".join(_normalize(alias).split()) in "".join(normalized_query.split())
            for alias in aliases(row)
            if alias
        )
    ]
    if not matches:
        return {"status": "not_found", "query": query, "candidates": []}
    if len(matches) > 1:
        candidates = [identity(row) for row in matches[:5]]
        return {
            "status": "ambiguous",
            "query": query,
            "candidate_count": len(matches),
            "candidates_truncated": len(matches) > len(candidates),
            "candidates": candidates,
        }
    return {"status": "ok", "entity": matches[0]}


def _warehouse_aliases(warehouse: Warehouse) -> tuple[str | None, ...]:
    city_cn = warehouse.city_cn or ""
    city = warehouse.city or ""
    return (
        warehouse.code,
        warehouse.name,
        warehouse.name_en,
        city,
        city_cn,
        f"{city_cn}仓",
        f"{city_cn}仓库",
        f"{city} warehouse",
        f"{city} warehouse center",
    )


def _warehouse_identity(warehouse: Warehouse) -> dict:
    return {
        "code": warehouse.code,
        "name": warehouse.name,
        "name_en": warehouse.name_en,
        "city": warehouse.city,
        "city_cn": warehouse.city_cn,
        "country_cn": warehouse.country_cn,
    }


def _product_aliases(sku: SKU) -> tuple[str | None, ...]:
    return (
        sku.code,
        sku.name,
        sku.name_en,
        sku.category_name,
        sku.category_name_en,
    )


def _product_identity(sku: SKU) -> dict:
    return {
        "code": sku.code,
        "name": sku.name,
        "name_en": sku.name_en,
        "category_name": sku.category_name,
    }


def _resolve_warehouse(session: Session, query: str) -> dict:
    rows = session.scalars(
        select(Warehouse)
        .where(Warehouse.batch_id == SHOWCASE_BATCH_ID)
        .order_by(Warehouse.display_id)
    ).all()
    return _resolve(query, rows, _warehouse_aliases, _warehouse_identity)


def _resolve_product(session: Session, query: str) -> dict:
    rows = session.scalars(
        select(SKU)
        .where(SKU.batch_id == SHOWCASE_BATCH_ID)
        .order_by(SKU.code)
    ).all()
    return _resolve(query, rows, _product_aliases, _product_identity)


def list_showcase_warehouses(session: Session, offset: int = 0, limit: int = 10) -> dict:
    """Return one bounded page of warehouses from the current fictional batch."""
    limit = min(limit, WAREHOUSE_PAGE_SIZE)
    query = select(Warehouse).where(Warehouse.batch_id == SHOWCASE_BATCH_ID)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(Warehouse.display_id).offset(offset).limit(limit)
    ).all()
    items = [_warehouse_identity(row) for row in rows]
    return _page(items, 0, len(items), total) | {
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total,
        "next_offset": offset + len(items) if offset + len(items) < total else None,
    }


def _products_for_warehouse(session: Session, warehouse_id: int) -> list[dict]:
    balance_rows = session.execute(
        select(
            SKU.id,
            SKU.code,
            SKU.name,
            SKU.name_en,
            SKU.category_name,
            func.sum(InventoryBalance.good_on_hand).label("good_on_hand"),
            func.sum(InventoryBalance.allocated).label("allocated"),
            func.sum(InventoryBalance.frozen).label("frozen"),
            func.count(InventoryBalance.id).label("location_count"),
        )
        .join(InventoryBalance, InventoryBalance.sku_id == SKU.id)
        .join(WarehouseLocation, InventoryBalance.location_id == WarehouseLocation.id)
        .where(
            SKU.batch_id == SHOWCASE_BATCH_ID,
            WarehouseLocation.batch_id == SHOWCASE_BATCH_ID,
            InventoryBalance.batch_id == SHOWCASE_BATCH_ID,
            WarehouseLocation.warehouse_id == warehouse_id,
        )
        .group_by(SKU.id, SKU.code, SKU.name, SKU.name_en, SKU.category_name)
    ).all()
    products = {
        row.id: {
            "code": row.code,
            "name": row.name,
            "name_en": row.name_en,
            "category_name": row.category_name,
            "good_on_hand": int(row.good_on_hand or 0),
            "available": int(row.good_on_hand or 0) - int(row.allocated or 0) - int(row.frozen or 0),
            "in_transit": 0,
            "location_count": int(row.location_count or 0),
        }
        for row in balance_rows
    }
    transit_rows = session.execute(
        select(
            SKU.id,
            SKU.code,
            SKU.name,
            SKU.name_en,
            SKU.category_name,
            func.sum(InTransitInventory.quantity).label("quantity"),
        )
        .join(InTransitInventory, InTransitInventory.sku_id == SKU.id)
        .where(
            SKU.batch_id == SHOWCASE_BATCH_ID,
            InTransitInventory.batch_id == SHOWCASE_BATCH_ID,
            InTransitInventory.warehouse_id == warehouse_id,
        )
        .group_by(SKU.id, SKU.code, SKU.name, SKU.name_en, SKU.category_name)
    ).all()
    for row in transit_rows:
        product = products.setdefault(
            row.id,
            {
                "code": row.code,
                "name": row.name,
                "name_en": row.name_en,
                "category_name": row.category_name,
                "good_on_hand": 0,
                "available": 0,
                "in_transit": 0,
                "location_count": 0,
            },
        )
        product["in_transit"] = int(row.quantity or 0)
    return sorted(
        (item for item in products.values() if item["good_on_hand"] > 0 or item["in_transit"] > 0),
        key=lambda item: item["code"],
    )


def list_products_at_warehouse(
    session: Session, warehouse_query: str, offset: int = 0, limit: int = 10
) -> dict:
    """Find one fictional warehouse and return products with on-hand or transit stock."""
    resolved = _resolve_warehouse(session, warehouse_query)
    if resolved["status"] != "ok":
        return resolved
    warehouse = resolved["entity"]
    items = _products_for_warehouse(session, warehouse.id)
    return {
        "status": "ok",
        "warehouse": _warehouse_identity(warehouse),
        **_page(items, offset, limit, len(items)),
    }


def _warehouses_for_product(session: Session, sku_id: int) -> list[dict]:
    balance_rows = session.execute(
        select(
            Warehouse.id,
            Warehouse.code,
            Warehouse.name,
            Warehouse.name_en,
            Warehouse.city,
            Warehouse.city_cn,
            Warehouse.country_cn,
            func.sum(InventoryBalance.good_on_hand).label("good_on_hand"),
            func.sum(InventoryBalance.allocated).label("allocated"),
            func.sum(InventoryBalance.frozen).label("frozen"),
            func.count(InventoryBalance.id).label("location_count"),
        )
        .join(WarehouseLocation, WarehouseLocation.warehouse_id == Warehouse.id)
        .join(InventoryBalance, InventoryBalance.location_id == WarehouseLocation.id)
        .where(
            Warehouse.batch_id == SHOWCASE_BATCH_ID,
            WarehouseLocation.batch_id == SHOWCASE_BATCH_ID,
            InventoryBalance.batch_id == SHOWCASE_BATCH_ID,
            InventoryBalance.sku_id == sku_id,
        )
        .group_by(Warehouse.id, Warehouse.code, Warehouse.name, Warehouse.name_en, Warehouse.city, Warehouse.city_cn, Warehouse.country_cn)
    ).all()
    warehouses = {
        row.id: {
            "code": row.code,
            "name": row.name,
            "name_en": row.name_en,
            "city": row.city,
            "city_cn": row.city_cn,
            "country_cn": row.country_cn,
            "good_on_hand": int(row.good_on_hand or 0),
            "available": int(row.good_on_hand or 0) - int(row.allocated or 0) - int(row.frozen or 0),
            "in_transit": 0,
            "location_count": int(row.location_count or 0),
        }
        for row in balance_rows
    }
    transit_rows = session.execute(
        select(
            Warehouse.id,
            Warehouse.code,
            Warehouse.name,
            Warehouse.name_en,
            Warehouse.city,
            Warehouse.city_cn,
            Warehouse.country_cn,
            func.sum(InTransitInventory.quantity).label("quantity"),
        )
        .join(InTransitInventory, InTransitInventory.warehouse_id == Warehouse.id)
        .where(
            Warehouse.batch_id == SHOWCASE_BATCH_ID,
            InTransitInventory.batch_id == SHOWCASE_BATCH_ID,
            InTransitInventory.sku_id == sku_id,
        )
        .group_by(Warehouse.id, Warehouse.code, Warehouse.name, Warehouse.name_en, Warehouse.city, Warehouse.city_cn, Warehouse.country_cn)
    ).all()
    for row in transit_rows:
        warehouse = warehouses.setdefault(
            row.id,
            {
                "code": row.code,
                "name": row.name,
                "name_en": row.name_en,
                "city": row.city,
                "city_cn": row.city_cn,
                "country_cn": row.country_cn,
                "good_on_hand": 0,
                "available": 0,
                "in_transit": 0,
                "location_count": 0,
            },
        )
        warehouse["in_transit"] = int(row.quantity or 0)
    return sorted(
        (item for item in warehouses.values() if item["good_on_hand"] > 0 or item["in_transit"] > 0),
        key=lambda item: item["code"],
    )


def find_warehouses_for_product(
    session: Session, product_query: str, offset: int = 0, limit: int = 10
) -> dict:
    """Resolve one product and list showcase warehouses with its on-hand or transit stock."""
    resolved = _resolve_product(session, product_query)
    if resolved["status"] != "ok":
        return resolved
    sku = resolved["entity"]
    warehouses = _warehouses_for_product(session, sku.id)
    return {
        "status": "ok",
        "product": _product_identity(sku),
        **_page(warehouses, offset, limit, len(warehouses)),
    }
