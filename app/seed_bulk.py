"""Deterministic showcase data with a separately guarded legacy replacement path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine
from app.models import (
    InventoryBalance,
    InTransitInventory,
    Order,
    OrderException,
    OrderItem,
    OrderTrackingEvent,
    SKU,
    Warehouse,
    WarehouseLocation,
)
from app.synthetic_catalog import COLORS, MATERIALS, PRODUCT_FAMILIES, WAREHOUSES


LEGACY_V1_PREFIX = "DEMO-BULK-V1-"
# Kept for compatibility with the old batch audit tests; never displayed in new records.
BULK_PREFIX = LEGACY_V1_PREFIX
SHOWCASE_BATCH_ID = "SHOWCASE-V2-20261013"
BATCH_SIZE = 1000
EXPECTED_DATABASE = "yuncang"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5433

WAREHOUSE_COUNT = 50
SKU_COUNT = 2_000
LOCATION_COUNT = 500
BALANCE_COUNT = 10_000
IN_TRANSIT_COUNT = 2_000
ORDER_COUNT = 10_000
ORDER_ITEM_COUNT = 15_000
TRACKING_EVENT_COUNT = 8_000
ORDER_EXCEPTION_COUNT = 500

EXPECTED_COUNTS = {
    "warehouses": WAREHOUSE_COUNT,
    "skus": SKU_COUNT,
    "locations": LOCATION_COUNT,
    "balances": BALANCE_COUNT,
    "in_transit": IN_TRANSIT_COUNT,
    "orders": ORDER_COUNT,
    "order_items": ORDER_ITEM_COUNT,
    "tracking_events": TRACKING_EVENT_COUNT,
    "order_exceptions": ORDER_EXCEPTION_COUNT,
}
TOTAL_ROW_COUNT = sum(EXPECTED_COUNTS.values())
LEGACY_COUNTS = {
    "warehouses": 3,
    "skus": 1_000,
    "locations": 300,
    "balances": 20_000,
    "in_transit": 3_000,
    "orders": 10_000,
    "tracking_events": 12_000,
    "order_exceptions": 1_000,
}
LEGACY_TOTAL_ROW_COUNT = sum(LEGACY_COUNTS.values())


class BulkSeedConflictError(RuntimeError):
    """Raised when a batch is partial, modified, or has unexpected dependencies."""


class BulkSeedTargetError(RuntimeError):
    """Raised when the configured database is not the intended local sandbox."""


class BackupError(RuntimeError):
    """Raised when a verified pre-change backup cannot be created."""


def _localized_warehouse_name(city: str, city_cn: str, country_code: str) -> tuple[str, str]:
    suffix_en = "Regional Fulfillment Centre" if country_code in {"GB", "AU", "CA"} else "Regional Fulfillment Center"
    return f"{city} {suffix_en}", f"{city_cn}国际物流中心"


def _warehouse_rows() -> list[dict[str, Any]]:
    rows = []
    for index, warehouse in enumerate(WAREHOUSES, start=1):
        name_en, name_cn = _localized_warehouse_name(warehouse.city, warehouse.city_cn, warehouse.country)
        district_en = ("Harbor Commerce Park" if index % 2 else "Meridian Logistics Park")
        district_cn = ("港湾商贸园区" if index % 2 else "子午线物流园区")
        status, status_cn = ("ramping", "试运营") if index % 13 == 0 else ("operational", "运营中")
        rows.append(
            {
                "display_id": index,
                "code": warehouse.code,
                "name": name_cn,
                "name_en": name_en,
                "region": warehouse.region,
                "region_cn": warehouse.region_cn,
                "country": warehouse.country,
                "country_cn": warehouse.country_cn,
                "city": warehouse.city,
                "city_cn": warehouse.city_cn,
                "address": f"Unit {index % 28 + 1}, {district_en}, {warehouse.city}",
                "address_cn": f"{warehouse.city_cn}{district_cn}{index % 28 + 1}号单元",
                "postal_code": f"ZX{index:02d} {index * 37 % 900 + 100:03d}",
                # +999 is an unassigned international calling code; these are display-only test values.
                "phone": f"+999-555-{index:02d}-{(index * 173) % 10_000:04d}",
                "latitude": round(warehouse.latitude + ((index % 5) - 2) * 0.0041, 6),
                "longitude": round(warehouse.longitude + ((index % 7) - 3) * 0.0037, 6),
                "status": status,
                "status_cn": status_cn,
                "batch_id": SHOWCASE_BATCH_ID,
            }
        )
    if len(rows) != WAREHOUSE_COUNT or len({row["code"] for row in rows}) != WAREHOUSE_COUNT:
        raise AssertionError("Warehouse catalog must contain 50 unique codes")
    return rows


def _variant_name(family: tuple, variant: int) -> tuple[str, str]:
    base_en, base_cn = family[3], family[4]
    color_key, color_cn, color_en = COLORS[variant % len(COLORS)]
    material_key, material_cn, material_en = MATERIALS[(variant // len(COLORS)) % len(MATERIALS)]
    pack = 1 + (variant // (len(COLORS) * len(MATERIALS))) % 3
    pack_en = f"{pack}-piece"
    pack_cn = f"{pack}件装"
    return (
        f"{base_en}, {color_en}, {material_en}, {pack_en}",
        f"{base_cn}（{color_cn}、{material_cn}、{pack_cn}）",
    )


def _sku_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(SKU_COUNT):
        family_index = index % len(PRODUCT_FAMILIES)
        variant = index // len(PRODUCT_FAMILIES)
        family = PRODUCT_FAMILIES[family_index]
        (
            category_code,
            category_cn,
            category_en,
            _base_en,
            _base_cn,
            material_en,
            material_cn,
            hazmat_class,
            un_number,
            oversized,
        ) = family
        name_en, name_cn = _variant_name(family, variant)
        scale = 1 + (variant % 7)
        length_mm = 120 + ((family_index * 173 + variant * 29) % 1_100)
        width_mm = 90 + ((family_index * 89 + variant * 31) % 850)
        height_mm = 45 + ((family_index * 67 + variant * 23) % 680)
        if oversized:
            length_mm = 1_100 + ((family_index * 73 + variant * 31) % 1_600)
            width_mm = 500 + ((family_index * 41 + variant * 17) % 900)
            height_mm = 350 + ((family_index * 53 + variant * 19) % 1_000)
        weight_g = 220 + ((family_index * 1_733 + variant * 619) % 19_000)
        if oversized:
            weight_g = 8_000 + ((family_index * 2_137 + variant * 1_201) % 62_000)
        if hazmat_class:
            weight_g = 300 + ((family_index * 311 + variant * 137) % 4_000)
        rows.append(
            {
                "code": f"YC-{category_code}-{family_index + 1:02d}-{variant + 1:03d}",
                "name": name_cn,
                "name_en": name_en,
                "category_code": category_code,
                "category_name": category_cn,
                "category_name_en": category_en,
                "is_hazmat": bool(hazmat_class),
                "hazmat_class": hazmat_class,
                "un_number": un_number,
                "is_oversized": oversized,
                "length_mm": length_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "weight_g": weight_g,
                "batch_id": SHOWCASE_BATCH_ID,
            }
        )
    if len({row["code"] for row in rows}) != SKU_COUNT:
        raise AssertionError("Generated SKU codes are not unique")
    return rows


def _location_rows() -> list[dict[str, Any]]:
    rows = []
    for warehouse_index, warehouse in enumerate(WAREHOUSES):
        for slot in range(10):
            if slot < 6:
                area_code, storage_type = "RACK", "STANDARD"
            elif slot < 8:
                area_code, storage_type = "DG-CAGE", "HAZMAT"
            else:
                area_code, storage_type = "BULK", "OVERSIZED"
            rows.append(
                {
                    "warehouse_code": warehouse.code,
                    "code": f"{warehouse.code}-{area_code}-{slot + 1:02d}-01-01",
                    "area_code": area_code,
                    "storage_type": storage_type,
                    "batch_id": SHOWCASE_BATCH_ID,
                    "warehouse_index": warehouse_index,
                    "slot": slot,
                }
            )
    if len(rows) != LOCATION_COUNT:
        raise AssertionError("Unexpected generated location count")
    return rows


def _inventory_rows(skus: list[dict[str, Any]], locations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sku_pools = {
        "STANDARD": [i for i, sku in enumerate(skus) if not sku["is_hazmat"] and not sku["is_oversized"]],
        "HAZMAT": [i for i, sku in enumerate(skus) if sku["is_hazmat"]],
        "OVERSIZED": [i for i, sku in enumerate(skus) if sku["is_oversized"] and not sku["is_hazmat"]],
    }
    balances = []
    for location_index, location in enumerate(locations):
        pool = sku_pools[location["storage_type"]]
        selected = [pool[(location_index * 17 + slot * 53) % len(pool)] for slot in range(20)]
        if len(set(selected)) != 20:
            raise AssertionError("Duplicate SKU assignment within a storage location")
        for slot, sku_index in enumerate(selected):
            good_on_hand = 18 + (location_index * 41 + slot * 23) % 440
            allocated = (location_index * 7 + slot * 3) % min(18, good_on_hand + 1)
            frozen = (location_index * 5 + slot * 2) % min(9, good_on_hand - allocated + 1)
            balances.append(
                {
                    "location_code": location["code"],
                    "sku_code": skus[sku_index]["code"],
                    "good_on_hand": good_on_hand,
                    "allocated": allocated,
                    "frozen": frozen,
                    "batch_id": SHOWCASE_BATCH_ID,
                }
            )
    transit = [
        {
            "warehouse_code": WAREHOUSES[warehouse_index].code,
            "sku_code": skus[warehouse_index * 40 + sku_offset]["code"],
            "quantity": 12 + ((warehouse_index * 97 + sku_offset * 31) % 460),
            "batch_id": SHOWCASE_BATCH_ID,
        }
        for warehouse_index in range(WAREHOUSE_COUNT)
        for sku_offset in range(40)
    ]
    if len(balances) != BALANCE_COUNT or len(transit) != IN_TRANSIT_COUNT:
        raise AssertionError("Unexpected generated inventory record count")
    return balances, transit


STATUS_CYCLE = (
    ("CREATED", "已创建"),
    ("PROCESSING", "处理中"),
    ("PICKING", "拣货中"),
    ("SHIPPED", "已出库"),
    ("IN_TRANSIT", "运输中"),
)
EVENTS_BY_STATUS = {
    "CREATED": ("ORDER_RECEIVED", "Order received and queued for processing"),
    "PROCESSING": ("INVENTORY_ALLOCATED", "Inventory allocated to this order"),
    "PICKING": ("PICKING_STARTED", "Warehouse picking task started"),
    "SHIPPED": ("CARRIER_PICKUP", "Parcel collected by the carrier"),
    "IN_TRANSIT": ("DEPARTED_ORIGIN", "Shipment departed the origin facility"),
}
EXCEPTION_CYCLE = (
    ("ADDRESS_REVIEW", "Recipient delivery details are pending a format review"),
    ("CUSTOMS_DOCUMENT", "A shipment document requires an additional review"),
    ("INVENTORY_SHORTAGE", "A line item is awaiting inventory confirmation"),
    ("DELIVERY_ATTEMPT", "Carrier recorded an unsuccessful delivery attempt"),
    ("HAZMAT_DOCUMENT", "A handling document is awaiting carrier review"),
)
CURRENCY_BY_COUNTRY = {
    "US": "USD", "CA": "CAD", "MX": "MXN", "GB": "GBP", "DE": "EUR", "FR": "EUR",
    "NL": "EUR", "PL": "PLN", "ES": "EUR", "SE": "SEK", "IT": "EUR", "AU": "AUD",
    "JP": "JPY", "KR": "KRW", "SG": "SGD", "CN": "CNY", "IN": "INR", "TH": "THB",
    "VN": "VND", "MY": "MYR", "ID": "IDR", "AE": "AED", "SA": "SAR", "TR": "TRY",
    "ZA": "ZAR", "KE": "KES", "BR": "BRL", "CL": "CLP", "AR": "ARS", "CO": "COP",
}


def _order_rows(skus: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    base_time = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    warehouses = {row.code: row for row in WAREHOUSES}
    per_warehouse = Counter()
    orders: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for index in range(ORDER_COUNT):
        warehouse = WAREHOUSES[index % WAREHOUSE_COUNT]
        per_warehouse[warehouse.code] += 1
        created_at = base_time + timedelta(minutes=index * 19)
        status_code, status_text = STATUS_CYCLE[index % len(STATUS_CYCLE)]
        order_no = f"{warehouse.code}-{created_at:%Y%m%d}-{per_warehouse[warehouse.code]:06d}"
        updated_at = created_at + timedelta(hours=2 + (index % 37))
        orders.append(
            {
                "order_no": order_no,
                "status_code": status_code,
                "status_text": status_text,
                "created_at": created_at,
                "status_updated_at": updated_at,
                "warehouse_code": warehouse.code,
                "batch_id": SHOWCASE_BATCH_ID,
            }
        )
        line_count = 2 if index < 5_000 else 1
        currency = CURRENCY_BY_COUNTRY[warehouse.country]
        for line_index in range(line_count):
            sku_index = (index * 13 + line_index * 791) % SKU_COUNT
            price_minor = 875 + ((sku_index * 379 + index * 83 + line_index * 1_157) % 74_000)
            unit_price = Decimal(price_minor) / Decimal(100)
            if currency in {"JPY", "KRW", "VND", "CLP", "COP"}:
                unit_price = Decimal(100 + (price_minor * 3) % 120_000)
            items.append(
                {
                    "order_no": order_no,
                    "sku_code": skus[sku_index]["code"],
                    "line_no": line_index + 1,
                    "quantity": 1 + (index * 3 + line_index * 2) % 6,
                    "unit_price": unit_price,
                    "currency": currency,
                    "batch_id": SHOWCASE_BATCH_ID,
                }
            )

        if index < 6_000:
            event_type, detail = EVENTS_BY_STATUS[status_code]
            events.append(
                {
                    "order_no": order_no,
                    "record_key": f"tracking-{index + 1:06d}-01",
                    "event_type": event_type,
                    "detail": detail,
                    "location": f"{warehouse.city} export processing zone",
                    "carrier": ("Northstar Parcel" if index % 3 else "Meridian Freight"),
                    "tracking_no": f"{warehouse.code}T{index + 1:010d}",
                    "occurred_at": created_at + timedelta(minutes=25 + index % 85),
                    "batch_id": SHOWCASE_BATCH_ID,
                }
            )
        elif index < 7_000:
            first_type, first_detail = EVENTS_BY_STATUS[status_code]
            events.extend(
                [
                    {
                        "order_no": order_no,
                        "record_key": f"tracking-{index + 1:06d}-01",
                        "event_type": first_type,
                        "detail": first_detail,
                        "location": f"{warehouse.city} export processing zone",
                        "carrier": ("Northstar Parcel" if index % 3 else "Meridian Freight"),
                        "tracking_no": f"{warehouse.code}T{index + 1:010d}",
                        "occurred_at": created_at + timedelta(minutes=25),
                        "batch_id": SHOWCASE_BATCH_ID,
                    },
                    {
                        "order_no": order_no,
                        "record_key": f"tracking-{index + 1:06d}-02",
                        "event_type": "SORTED_AT_HUB" if status_code in {"SHIPPED", "IN_TRANSIT"} else "PICKING_CONFIRMED",
                        "detail": "Shipment scan recorded at the next handling point",
                        "location": f"{warehouse.city} regional gateway",
                        "carrier": ("Northstar Parcel" if index % 3 else "Meridian Freight"),
                        "tracking_no": f"{warehouse.code}T{index + 1:010d}",
                        "occurred_at": created_at + timedelta(hours=1, minutes=10),
                        "batch_id": SHOWCASE_BATCH_ID,
                    },
                ]
            )
        if index % 20 == 0:
            exception_code, detail = EXCEPTION_CYCLE[(index // 20) % len(EXCEPTION_CYCLE)]
            exceptions.append(
                {
                    "order_no": order_no,
                    "record_key": f"exception-{index + 1:06d}",
                    "code": exception_code,
                    "detail": detail,
                    "active": (index // 20) % 3 != 0,
                    "occurred_at": created_at + timedelta(minutes=45 + index % 90),
                    "batch_id": SHOWCASE_BATCH_ID,
                }
            )
    if len(orders) != ORDER_COUNT or len(items) != ORDER_ITEM_COUNT:
        raise AssertionError("Unexpected generated order or order-item count")
    if len(events) != TRACKING_EVENT_COUNT or len(exceptions) != ORDER_EXCEPTION_COUNT:
        raise AssertionError("Unexpected generated tracking or exception count")
    return orders, items, events, exceptions


def _generate_rows() -> dict[str, list[dict[str, Any]]]:
    """Build the current versioned showcase batch without database access."""
    warehouses = _warehouse_rows()
    skus = _sku_rows()
    locations = _location_rows()
    balances, in_transit = _inventory_rows(skus, locations)
    orders, order_items, tracking_events, order_exceptions = _order_rows(skus)
    rows = {
        "warehouses": warehouses,
        "skus": skus,
        "locations": locations,
        "balances": balances,
        "in_transit": in_transit,
        "orders": orders,
        "order_items": order_items,
        "tracking_events": tracking_events,
        "order_exceptions": order_exceptions,
    }
    if {key: len(value) for key, value in rows.items()} != EXPECTED_COUNTS:
        raise AssertionError("Showcase batch counts differ from the approved plan")
    return rows


# The original generator remains solely as an exact replacement audit oracle.
def _generate_v1_rows() -> dict[str, list[dict[str, Any]]]:
    warehouses = [
        {"code": f"{LEGACY_V1_PREFIX}WH-{index + 1:03d}", "name": f"模拟分拨仓-{index + 1:03d}"}
        for index in range(3)
    ]
    skus = [
        {"code": f"{LEGACY_V1_PREFIX}SKU-{index + 1:04d}", "name": f"模拟商品-{index + 1:04d}"}
        for index in range(1_000)
    ]
    locations = [
        {
            "warehouse_code": f"{LEGACY_V1_PREFIX}WH-{index // 100 + 1:03d}",
            "code": f"{LEGACY_V1_PREFIX}LOC-{index + 1:04d}",
        }
        for index in range(300)
    ]
    balances = []
    for index in range(20_000):
        location_index = index % 300
        sku_index = (location_index * 67 + index // 300) % 1_000
        good_on_hand = 80 + (index * 13) % 920
        allocated = (index * 7) % 35
        frozen = (index * 3) % 12
        balances.append(
            {
                "location_code": f"{LEGACY_V1_PREFIX}LOC-{location_index + 1:04d}",
                "sku_code": f"{LEGACY_V1_PREFIX}SKU-{sku_index + 1:04d}",
                "good_on_hand": good_on_hand,
                "allocated": allocated,
                "frozen": frozen,
            }
        )
    in_transit = [
        {
            "warehouse_code": f"{LEGACY_V1_PREFIX}WH-{warehouse_index + 1:03d}",
            "sku_code": f"{LEGACY_V1_PREFIX}SKU-{sku_index + 1:04d}",
            "quantity": (warehouse_index * 97 + sku_index * 11) % 500,
        }
        for warehouse_index in range(3)
        for sku_index in range(1_000)
    ]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    orders = []
    tracking_events = []
    exceptions = []
    for index in range(10_000):
        created_at = base_time + timedelta(minutes=index * 7)
        status_code, status_text = (
            ("CREATED", "已创建") if index % 5 == 0
            else ("PROCESSING", "处理中") if index % 5 == 1
            else ("PICKING", "拣货中") if index % 5 == 2
            else ("SHIPPED", "已出库") if index % 5 == 3
            else ("IN_TRANSIT", "运输中")
        )
        order_no = f"{LEGACY_V1_PREFIX}ORDER-{index + 1:05d}"
        orders.append(
            {
                "order_no": order_no,
                "status_code": status_code,
                "status_text": status_text,
                "created_at": created_at,
                "status_updated_at": created_at + timedelta(minutes=15 + index % 180),
            }
        )
        event_count = 2 if index < 2_000 else 1
        for event_index in range(event_count):
            tracking_events.append(
                {
                    "order_no": order_no,
                    "record_key": f"{LEGACY_V1_PREFIX}event-{event_index + 1:02d}",
                    "event_type": "ORDER_ACCEPTED" if event_index == 0 else "SORTING_CENTER",
                    "detail": f"{LEGACY_V1_PREFIX}模拟订单已进入仓库处理流程",
                    "location": f"{LEGACY_V1_PREFIX}模拟区域-{index % 20 + 1:02d}",
                    "carrier": f"{LEGACY_V1_PREFIX}示例物流",
                    "tracking_no": f"{LEGACY_V1_PREFIX}TRACK-{index + 1:05d}",
                    "occurred_at": created_at + timedelta(hours=event_index + 1),
                }
            )
        if index % 10 == 0:
            exceptions.append(
                {
                    "order_no": order_no,
                    "record_key": f"{LEGACY_V1_PREFIX}exception-01",
                    "code": "SIMULATED_REVIEW",
                    "detail": f"{LEGACY_V1_PREFIX}模拟地址核验，请勿用于真实履约判断",
                    "active": index % 20 == 0,
                    "occurred_at": created_at + timedelta(minutes=15),
                }
            )
    return {
        "warehouses": warehouses,
        "skus": skus,
        "locations": locations,
        "balances": balances,
        "in_transit": in_transit,
        "orders": orders,
        "tracking_events": tracking_events,
        "order_exceptions": exceptions,
    }


def _bulk_counts(session: Session) -> dict[str, int]:
    batch_id = SHOWCASE_BATCH_ID
    return {
        "warehouses": session.scalar(select(func.count()).select_from(Warehouse).where(Warehouse.batch_id == batch_id)) or 0,
        "skus": session.scalar(select(func.count()).select_from(SKU).where(SKU.batch_id == batch_id)) or 0,
        "locations": session.scalar(select(func.count()).select_from(WarehouseLocation).where(WarehouseLocation.batch_id == batch_id)) or 0,
        "balances": session.scalar(select(func.count()).select_from(InventoryBalance).where(InventoryBalance.batch_id == batch_id)) or 0,
        "in_transit": session.scalar(select(func.count()).select_from(InTransitInventory).where(InTransitInventory.batch_id == batch_id)) or 0,
        "orders": session.scalar(select(func.count()).select_from(Order).where(Order.batch_id == batch_id)) or 0,
        "order_items": session.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.batch_id == batch_id)) or 0,
        "tracking_events": session.scalar(select(func.count()).select_from(OrderTrackingEvent).where(OrderTrackingEvent.batch_id == batch_id)) or 0,
        "order_exceptions": session.scalar(select(func.count()).select_from(OrderException).where(OrderException.batch_id == batch_id)) or 0,
    }


def _has_legacy_prefix(column: Any):
    return func.substr(column, 1, len(LEGACY_V1_PREFIX)) == LEGACY_V1_PREFIX


def _legacy_counts(session: Session) -> dict[str, int]:
    old_warehouses = select(Warehouse.id).where(_has_legacy_prefix(Warehouse.code))
    old_skus = select(SKU.id).where(_has_legacy_prefix(SKU.code))
    old_orders = select(Order.id).where(_has_legacy_prefix(Order.order_no))
    old_locations = select(WarehouseLocation.id).where(
        or_(_has_legacy_prefix(WarehouseLocation.code), WarehouseLocation.warehouse_id.in_(old_warehouses))
    )
    order_item_count = 0
    if "order_items" in inspect(session.get_bind()).get_table_names():
        order_item_count = session.scalar(
            select(func.count()).select_from(OrderItem).where(
                or_(OrderItem.order_id.in_(old_orders), OrderItem.sku_id.in_(old_skus))
            )
        ) or 0
    return {
        "warehouses": session.scalar(select(func.count()).select_from(Warehouse).where(_has_legacy_prefix(Warehouse.code))) or 0,
        "skus": session.scalar(select(func.count()).select_from(SKU).where(_has_legacy_prefix(SKU.code))) or 0,
        "locations": session.scalar(select(func.count()).select_from(WarehouseLocation).where(or_(_has_legacy_prefix(WarehouseLocation.code), WarehouseLocation.warehouse_id.in_(old_warehouses)))) or 0,
        "balances": session.scalar(select(func.count()).select_from(InventoryBalance).where(or_(InventoryBalance.location_id.in_(old_locations), InventoryBalance.sku_id.in_(old_skus)))) or 0,
        "in_transit": session.scalar(select(func.count()).select_from(InTransitInventory).where(or_(InTransitInventory.warehouse_id.in_(old_warehouses), InTransitInventory.sku_id.in_(old_skus)))) or 0,
        "orders": session.scalar(select(func.count()).select_from(Order).where(_has_legacy_prefix(Order.order_no))) or 0,
        "order_items": order_item_count,
        "tracking_events": session.scalar(select(func.count()).select_from(OrderTrackingEvent).where(or_(OrderTrackingEvent.order_id.in_(old_orders), _has_legacy_prefix(OrderTrackingEvent.record_key), _has_legacy_prefix(OrderTrackingEvent.tracking_no)))) or 0,
        "order_exceptions": session.scalar(select(func.count()).select_from(OrderException).where(or_(OrderException.order_id.in_(old_orders), _has_legacy_prefix(OrderException.record_key), _has_legacy_prefix(OrderException.detail)))) or 0,
    }


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _check_exact(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise BulkSeedConflictError(f"Legacy batch {label} differs from its original deterministic contents.")


def _assert_legacy_matches(session: Session) -> dict[str, set[int]]:
    """Validate every old row and collect its exact primary keys before any deletion."""
    expected_rows = _generate_v1_rows()
    counts = _legacy_counts(session)
    if counts != {**LEGACY_COUNTS, "order_items": 0}:
        raise BulkSeedConflictError(f"Legacy batch counts differ; expected {LEGACY_COUNTS} with no order items, found {counts}.")

    expected_wh = {row["code"]: row["name"] for row in expected_rows["warehouses"]}
    actual_wh = dict(session.execute(select(Warehouse.code, Warehouse.name).where(Warehouse.code.like(f"{LEGACY_V1_PREFIX}%"))).all())
    _check_exact(actual_wh, expected_wh, "warehouses")
    warehouse_ids = set(session.scalars(select(Warehouse.id).where(Warehouse.code.like(f"{LEGACY_V1_PREFIX}%"))).all())

    expected_skus = {row["code"]: row["name"] for row in expected_rows["skus"]}
    actual_skus = dict(
        session.execute(
            select(SKU.code, SKU.name).where(SKU.code.like(f"{LEGACY_V1_PREFIX}%"))
        ).all()
    )
    _check_exact(actual_skus, expected_skus, "SKUs")
    sku_ids = set(session.scalars(select(SKU.id).where(SKU.code.like(f"{LEGACY_V1_PREFIX}%"))).all())

    expected_locations = {row["code"]: row["warehouse_code"] for row in expected_rows["locations"]}
    actual_locations = dict(
        session.execute(
            select(WarehouseLocation.code, Warehouse.code)
            .join(Warehouse, WarehouseLocation.warehouse_id == Warehouse.id)
            .where(or_(WarehouseLocation.code.like(f"{LEGACY_V1_PREFIX}%"), WarehouseLocation.warehouse_id.in_(warehouse_ids)))
        ).all()
    )
    _check_exact(actual_locations, expected_locations, "locations")
    location_ids = set(session.scalars(select(WarehouseLocation.id).where(or_(WarehouseLocation.code.like(f"{LEGACY_V1_PREFIX}%"), WarehouseLocation.warehouse_id.in_(warehouse_ids)))).all())

    expected_balances = {(row["location_code"], row["sku_code"]): (row["good_on_hand"], row["allocated"], row["frozen"]) for row in expected_rows["balances"]}
    actual_balances = {
        (loc_code, sku_code): (good, allocated, frozen)
        for loc_code, sku_code, good, allocated, frozen in session.execute(
            select(WarehouseLocation.code, SKU.code, InventoryBalance.good_on_hand, InventoryBalance.allocated, InventoryBalance.frozen)
            .join(WarehouseLocation, InventoryBalance.location_id == WarehouseLocation.id)
            .join(SKU, InventoryBalance.sku_id == SKU.id)
            .where(or_(InventoryBalance.location_id.in_(location_ids), InventoryBalance.sku_id.in_(sku_ids)))
        )
    }
    _check_exact(actual_balances, expected_balances, "inventory balances")
    balance_ids = set(session.scalars(select(InventoryBalance.id).where(or_(InventoryBalance.location_id.in_(location_ids), InventoryBalance.sku_id.in_(sku_ids)))).all())

    expected_transit = {(row["warehouse_code"], row["sku_code"]): row["quantity"] for row in expected_rows["in_transit"]}
    actual_transit = {
        (warehouse_code, sku_code): quantity
        for warehouse_code, sku_code, quantity in session.execute(
            select(Warehouse.code, SKU.code, InTransitInventory.quantity)
            .join(Warehouse, InTransitInventory.warehouse_id == Warehouse.id)
            .join(SKU, InTransitInventory.sku_id == SKU.id)
            .where(or_(InTransitInventory.warehouse_id.in_(warehouse_ids), InTransitInventory.sku_id.in_(sku_ids)))
        )
    }
    _check_exact(actual_transit, expected_transit, "in-transit inventory")
    transit_ids = set(session.scalars(select(InTransitInventory.id).where(or_(InTransitInventory.warehouse_id.in_(warehouse_ids), InTransitInventory.sku_id.in_(sku_ids)))).all())

    expected_orders = {
        row["order_no"]: (row["status_code"], row["status_text"], _normalized_datetime(row["created_at"]), _normalized_datetime(row["status_updated_at"]))
        for row in expected_rows["orders"]
    }
    actual_orders = {
        order_no: (status_code, status_text, _normalized_datetime(created_at), _normalized_datetime(updated_at))
        for order_no, status_code, status_text, created_at, updated_at in session.execute(
            select(Order.order_no, Order.status_code, Order.status_text, Order.created_at, Order.status_updated_at)
            .where(Order.order_no.like(f"{LEGACY_V1_PREFIX}%"))
        )
    }
    _check_exact(actual_orders, expected_orders, "orders")
    order_ids = set(session.scalars(select(Order.id).where(Order.order_no.like(f"{LEGACY_V1_PREFIX}%"))).all())

    expected_events = {
        (row["order_no"], row["record_key"]): (row["event_type"], row["detail"], row["location"], row["carrier"], row["tracking_no"], _normalized_datetime(row["occurred_at"]))
        for row in expected_rows["tracking_events"]
    }
    actual_events = {
        (order_no, record_key): (event_type, detail, location, carrier, tracking_no, _normalized_datetime(occurred_at))
        for order_no, record_key, event_type, detail, location, carrier, tracking_no, occurred_at in session.execute(
            select(Order.order_no, OrderTrackingEvent.record_key, OrderTrackingEvent.event_type, OrderTrackingEvent.detail, OrderTrackingEvent.location, OrderTrackingEvent.carrier, OrderTrackingEvent.tracking_no, OrderTrackingEvent.occurred_at)
            .join(Order, OrderTrackingEvent.order_id == Order.id)
            .where(or_(OrderTrackingEvent.order_id.in_(order_ids), OrderTrackingEvent.record_key.like(f"{LEGACY_V1_PREFIX}%"), OrderTrackingEvent.tracking_no.like(f"{LEGACY_V1_PREFIX}%")))
        )
    }
    _check_exact(actual_events, expected_events, "tracking events")
    event_ids = set(session.scalars(select(OrderTrackingEvent.id).where(or_(OrderTrackingEvent.order_id.in_(order_ids), OrderTrackingEvent.record_key.like(f"{LEGACY_V1_PREFIX}%"), OrderTrackingEvent.tracking_no.like(f"{LEGACY_V1_PREFIX}%")))).all())

    expected_exceptions = {
        (row["order_no"], row["record_key"]): (row["code"], row["detail"], row["active"], _normalized_datetime(row["occurred_at"]))
        for row in expected_rows["order_exceptions"]
    }
    actual_exceptions = {
        (order_no, record_key): (code, detail, active, _normalized_datetime(occurred_at))
        for order_no, record_key, code, detail, active, occurred_at in session.execute(
            select(Order.order_no, OrderException.record_key, OrderException.code, OrderException.detail, OrderException.active, OrderException.occurred_at)
            .join(Order, OrderException.order_id == Order.id)
            .where(or_(OrderException.order_id.in_(order_ids), OrderException.record_key.like(f"{LEGACY_V1_PREFIX}%"), OrderException.detail.like(f"{LEGACY_V1_PREFIX}%")))
        )
    }
    _check_exact(actual_exceptions, expected_exceptions, "order exceptions")
    exception_ids = set(session.scalars(select(OrderException.id).where(or_(OrderException.order_id.in_(order_ids), OrderException.record_key.like(f"{LEGACY_V1_PREFIX}%"), OrderException.detail.like(f"{LEGACY_V1_PREFIX}%")))).all())

    legacy_extension_checks = (
        (Warehouse, warehouse_ids, ("display_id", "name_en", "region", "region_cn", "country", "country_cn", "city", "city_cn", "address", "address_cn", "postal_code", "phone", "latitude", "longitude", "status", "status_cn", "batch_id")),
        (SKU, sku_ids, ("name_en", "category_code", "category_name", "category_name_en", "is_hazmat", "hazmat_class", "un_number", "is_oversized", "length_mm", "width_mm", "height_mm", "weight_g", "batch_id")),
        (WarehouseLocation, location_ids, ("area_code", "storage_type", "batch_id")),
        (Order, order_ids, ("warehouse_id", "batch_id")),
        (InventoryBalance, balance_ids, ("batch_id",)),
        (InTransitInventory, transit_ids, ("batch_id",)),
        (OrderTrackingEvent, event_ids, ("batch_id",)),
        (OrderException, exception_ids, ("batch_id",)),
    )
    for model, ids, fields in legacy_extension_checks:
        for field in fields:
            if ids and session.scalar(
                select(func.count()).select_from(model).where(
                    model.id.in_(ids), getattr(model, field).is_not(None)
                )
            ):
                raise BulkSeedConflictError(
                    f"Legacy {model.__tablename__}.{field} contains unexpected values."
                )
    if session.scalar(select(func.count()).select_from(OrderItem).where(or_(OrderItem.order_id.in_(order_ids), OrderItem.sku_id.in_(sku_ids)))):
        raise BulkSeedConflictError("Unexpected order-item dependencies reference legacy orders or SKUs.")
    return {
        "warehouses": warehouse_ids,
        "skus": sku_ids,
        "locations": location_ids,
        "balances": balance_ids,
        "in_transit": transit_ids,
        "orders": order_ids,
        "tracking_events": event_ids,
        "order_exceptions": exception_ids,
    }


def _assert_no_unrecognized_foreign_keys(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    rows = session.execute(
        text(
            "SELECT source.relname AS source_table, target.relname AS target_table, "
            "array_agg(source_attr.attname ORDER BY key_cols.ordinality) AS source_columns "
            "FROM pg_constraint con "
            "JOIN pg_class source ON source.oid = con.conrelid "
            "JOIN pg_namespace source_ns ON source_ns.oid = source.relnamespace "
            "JOIN pg_class target ON target.oid = con.confrelid "
            "JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS key_cols(attnum, ordinality) ON true "
            "JOIN pg_attribute source_attr ON source_attr.attrelid = source.oid AND source_attr.attnum = key_cols.attnum "
            "WHERE con.contype = 'f' AND source_ns.nspname = current_schema() "
            "AND target.relname IN ('warehouses','skus','warehouse_locations','orders') "
            "GROUP BY source.relname, target.relname"
        )
    ).all()
    expected = {
        ("warehouse_locations", "warehouses", ("warehouse_id",)),
        ("in_transit_inventory", "warehouses", ("warehouse_id",)),
        ("in_transit_inventory", "skus", ("sku_id",)),
        ("inventory_balances", "warehouse_locations", ("location_id",)),
        ("inventory_balances", "skus", ("sku_id",)),
        ("orders", "warehouses", ("warehouse_id",)),
        ("order_items", "orders", ("order_id",)),
        ("order_items", "skus", ("sku_id",)),
        ("order_tracking_events", "orders", ("order_id",)),
        ("order_exceptions", "orders", ("order_id",)),
    }
    actual = {(source, target, tuple(columns)) for source, target, columns in rows}
    if actual != expected:
        raise BulkSeedConflictError(
            f"Foreign-key dependency graph is not the expected application schema: {actual!r}."
        )


def _snapshot_preserved_rows(session: Session, old_ids: dict[str, set[int]]) -> dict[str, str]:
    models = {
        "warehouses": Warehouse,
        "skus": SKU,
        "locations": WarehouseLocation,
        "balances": InventoryBalance,
        "in_transit": InTransitInventory,
        "orders": Order,
        "order_items": OrderItem,
        "tracking_events": OrderTrackingEvent,
        "order_exceptions": OrderException,
    }
    snapshot: dict[str, str] = {}
    for table, model in models.items():
        excluded_ids = old_ids.get(table, set())
        statement = select(model).order_by(model.id)
        if excluded_ids:
            statement = statement.where(model.id.not_in(excluded_ids))
        batch_column = getattr(model, "batch_id", None)
        if batch_column is not None:
            statement = statement.where(
                or_(batch_column.is_(None), batch_column != SHOWCASE_BATCH_ID)
            )
        records = []
        for row in session.scalars(statement):
            record = {}
            for column in model.__table__.columns:
                value = getattr(row, column.key)
                if isinstance(value, datetime):
                    value = _normalized_datetime(value).isoformat()
                elif isinstance(value, Decimal):
                    value = str(value)
                record[column.key] = value
            records.append(record)
        payload = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        snapshot[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return snapshot


def _assert_snapshot_preserved(session: Session, expected: dict[str, str]) -> None:
    empty_ids: dict[str, set[int]] = {}
    actual = _snapshot_preserved_rows(session, empty_ids)
    if actual != expected:
        raise BulkSeedConflictError("Rows outside the verified legacy batch changed; transaction must roll back.")


def _add_in_batches(session: Session, rows: Iterable[Any]) -> None:
    batch: list[Any] = []
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            session.add_all(batch)
            session.flush()
            batch.clear()
    if batch:
        session.add_all(batch)
        session.flush()


def _assert_target_database(session: Session) -> None:
    if (settings.postgres_host, settings.postgres_port, settings.postgres_db) != (EXPECTED_HOST, EXPECTED_PORT, EXPECTED_DATABASE):
        raise BulkSeedTargetError("Bulk data writes are restricted to 127.0.0.1:5433/yuncang.")
    if session.connection().exec_driver_sql("SELECT current_database()").scalar_one() != EXPECTED_DATABASE:
        raise BulkSeedTargetError("Connected database is not the local yuncang database.")
    server_port = session.connection().exec_driver_sql("SELECT inet_server_port()").scalar_one()
    if server_port not in {5432, EXPECTED_PORT}:
        raise BulkSeedTargetError("Connected PostgreSQL server port is not the expected local Compose database port.")


def _assert_showcase_matches(session: Session) -> None:
    rows = _generate_rows()
    if _bulk_counts(session) != EXPECTED_COUNTS:
        raise BulkSeedConflictError("Existing showcase batch has unexpected table counts.")

    def assert_equal(actual: Any, expected: Any, label: str) -> None:
        if actual != expected:
            raise BulkSeedConflictError(f"Existing showcase {label} differ from deterministic contents.")

    actual_warehouses = {
        tuple((key, getattr(obj, key)) for key in rows["warehouses"][0])
        for obj in session.scalars(select(Warehouse).where(Warehouse.batch_id == SHOWCASE_BATCH_ID))
    }
    assert_equal(actual_warehouses, {tuple(row.items()) for row in rows["warehouses"]}, "warehouses")
    actual_skus = {
        tuple((key, getattr(obj, key)) for key in rows["skus"][0])
        for obj in session.scalars(select(SKU).where(SKU.batch_id == SHOWCASE_BATCH_ID))
    }
    assert_equal(actual_skus, {tuple(row.items()) for row in rows["skus"]}, "SKUs")

    actual_locations = {
        (code, warehouse_code, area_code, storage_type, batch_id)
        for code, warehouse_code, area_code, storage_type, batch_id in session.execute(
            select(WarehouseLocation.code, Warehouse.code, WarehouseLocation.area_code,
                   WarehouseLocation.storage_type, WarehouseLocation.batch_id)
            .join(Warehouse, WarehouseLocation.warehouse_id == Warehouse.id)
            .where(WarehouseLocation.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_locations = {
        (row["code"], row["warehouse_code"], row["area_code"], row["storage_type"], row["batch_id"])
        for row in rows["locations"]
    }
    assert_equal(actual_locations, expected_locations, "locations")

    actual_balances = {
        (location_code, sku_code, good, allocated, frozen, batch_id)
        for location_code, sku_code, good, allocated, frozen, batch_id in session.execute(
            select(WarehouseLocation.code, SKU.code, InventoryBalance.good_on_hand,
                   InventoryBalance.allocated, InventoryBalance.frozen, InventoryBalance.batch_id)
            .join(WarehouseLocation, InventoryBalance.location_id == WarehouseLocation.id)
            .join(SKU, InventoryBalance.sku_id == SKU.id)
            .where(InventoryBalance.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_balances = {
        (row["location_code"], row["sku_code"], row["good_on_hand"], row["allocated"], row["frozen"], row["batch_id"])
        for row in rows["balances"]
    }
    assert_equal(actual_balances, expected_balances, "inventory balances")

    actual_transit = {
        (warehouse_code, sku_code, quantity, batch_id)
        for warehouse_code, sku_code, quantity, batch_id in session.execute(
            select(Warehouse.code, SKU.code, InTransitInventory.quantity, InTransitInventory.batch_id)
            .join(Warehouse, InTransitInventory.warehouse_id == Warehouse.id)
            .join(SKU, InTransitInventory.sku_id == SKU.id)
            .where(InTransitInventory.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_transit = {
        (row["warehouse_code"], row["sku_code"], row["quantity"], row["batch_id"])
        for row in rows["in_transit"]
    }
    assert_equal(actual_transit, expected_transit, "in-transit inventory")

    actual_orders = {
        (order_no, status_code, status_text, _normalized_datetime(created),
         _normalized_datetime(updated), warehouse_code, batch_id)
        for order_no, status_code, status_text, created, updated, warehouse_code, batch_id in session.execute(
            select(Order.order_no, Order.status_code, Order.status_text, Order.created_at,
                   Order.status_updated_at, Warehouse.code, Order.batch_id)
            .join(Warehouse, Order.warehouse_id == Warehouse.id)
            .where(Order.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_orders = {
        (row["order_no"], row["status_code"], row["status_text"],
         _normalized_datetime(row["created_at"]), _normalized_datetime(row["status_updated_at"]),
         row["warehouse_code"], row["batch_id"])
        for row in rows["orders"]
    }
    assert_equal(actual_orders, expected_orders, "orders")

    actual_items = {
        (order_no, sku_code, line_no, quantity, Decimal(unit_price), currency, batch_id)
        for order_no, sku_code, line_no, quantity, unit_price, currency, batch_id in session.execute(
            select(Order.order_no, SKU.code, OrderItem.line_no, OrderItem.quantity,
                   OrderItem.unit_price, OrderItem.currency, OrderItem.batch_id)
            .join(Order, OrderItem.order_id == Order.id)
            .join(SKU, OrderItem.sku_id == SKU.id)
            .where(OrderItem.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_items = {
        (row["order_no"], row["sku_code"], row["line_no"], row["quantity"],
         Decimal(row["unit_price"]), row["currency"], row["batch_id"])
        for row in rows["order_items"]
    }
    assert_equal(actual_items, expected_items, "order items")

    actual_events = {
        (order_no, key, event_type, detail, location, carrier, tracking_no,
         _normalized_datetime(occurred_at), batch_id)
        for order_no, key, event_type, detail, location, carrier, tracking_no, occurred_at, batch_id in session.execute(
            select(Order.order_no, OrderTrackingEvent.record_key, OrderTrackingEvent.event_type,
                   OrderTrackingEvent.detail, OrderTrackingEvent.location, OrderTrackingEvent.carrier,
                   OrderTrackingEvent.tracking_no, OrderTrackingEvent.occurred_at, OrderTrackingEvent.batch_id)
            .join(Order, OrderTrackingEvent.order_id == Order.id)
            .where(OrderTrackingEvent.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_events = {
        (row["order_no"], row["record_key"], row["event_type"], row["detail"], row["location"],
         row["carrier"], row["tracking_no"], _normalized_datetime(row["occurred_at"]), row["batch_id"])
        for row in rows["tracking_events"]
    }
    assert_equal(actual_events, expected_events, "tracking events")

    actual_exceptions = {
        (order_no, key, code, detail, active, _normalized_datetime(occurred_at), batch_id)
        for order_no, key, code, detail, active, occurred_at, batch_id in session.execute(
            select(Order.order_no, OrderException.record_key, OrderException.code, OrderException.detail,
                   OrderException.active, OrderException.occurred_at, OrderException.batch_id)
            .join(Order, OrderException.order_id == Order.id)
            .where(OrderException.batch_id == SHOWCASE_BATCH_ID)
        )
    }
    expected_exceptions = {
        (row["order_no"], row["record_key"], row["code"], row["detail"], row["active"],
         _normalized_datetime(row["occurred_at"]), row["batch_id"])
        for row in rows["order_exceptions"]
    }
    assert_equal(actual_exceptions, expected_exceptions, "order exceptions")

    incompatible = session.scalar(
        select(func.count()).select_from(InventoryBalance)
        .join(WarehouseLocation, InventoryBalance.location_id == WarehouseLocation.id)
        .join(SKU, InventoryBalance.sku_id == SKU.id)
        .where(
            InventoryBalance.batch_id == SHOWCASE_BATCH_ID,
            or_(
                (SKU.is_hazmat.is_(True) & (WarehouseLocation.storage_type != "HAZMAT")),
                (SKU.is_oversized.is_(True) & (WarehouseLocation.storage_type != "OVERSIZED")),
                (SKU.is_hazmat.is_(False) & SKU.is_oversized.is_(False) & (WarehouseLocation.storage_type != "STANDARD")),
            ),
        )
    )
    if incompatible:
        raise BulkSeedConflictError("Showcase inventory includes a SKU in an incompatible storage area.")
    old_order_ids = select(Order.id).where(Order.order_no.like(f"{LEGACY_V1_PREFIX}%"))
    old_sku_ids = select(SKU.id).where(SKU.code.like(f"{LEGACY_V1_PREFIX}%"))
    if session.scalar(select(func.count()).select_from(OrderItem).where(or_(OrderItem.order_id.in_(old_order_ids), OrderItem.sku_id.in_(old_sku_ids)))):
        raise BulkSeedConflictError("Unexpected order-item dependencies reference legacy keys.")


def _ensure_new_batch_state(session: Session) -> bool:
    counts = _bulk_counts(session)
    old_counts = _legacy_counts(session)
    if any(old_counts.values()):
        raise BulkSeedConflictError("The old DEMO-BULK-V1 batch is present; use the explicit --replace-v1 path after backup.")
    if all(value == 0 for value in counts.values()):
        return False
    if counts == EXPECTED_COUNTS:
        _assert_showcase_matches(session)
        return True
    raise BulkSeedConflictError(f"Showcase batch is partial or has unexpected counts; found {counts}.")


def _seed_showcase(session: Session) -> None:
    rows = _generate_rows()
    _add_in_batches(session, [Warehouse(**row) for row in rows["warehouses"]])
    _add_in_batches(session, [SKU(**row) for row in rows["skus"]])
    warehouse_ids = dict(session.execute(select(Warehouse.code, Warehouse.id).where(Warehouse.batch_id == SHOWCASE_BATCH_ID)).all())
    sku_ids = dict(session.execute(select(SKU.code, SKU.id).where(SKU.batch_id == SHOWCASE_BATCH_ID)).all())
    _add_in_batches(
        session,
        [WarehouseLocation(warehouse_id=warehouse_ids[row["warehouse_code"]], **{key: value for key, value in row.items() if key not in {"warehouse_code", "warehouse_index", "slot"}}) for row in rows["locations"]],
    )
    location_ids = dict(session.execute(select(WarehouseLocation.code, WarehouseLocation.id).where(WarehouseLocation.batch_id == SHOWCASE_BATCH_ID)).all())
    _add_in_batches(
        session,
        [InventoryBalance(location_id=location_ids[row["location_code"]], sku_id=sku_ids[row["sku_code"]], good_on_hand=row["good_on_hand"], allocated=row["allocated"], frozen=row["frozen"], batch_id=SHOWCASE_BATCH_ID) for row in rows["balances"]],
    )
    _add_in_batches(
        session,
        [InTransitInventory(warehouse_id=warehouse_ids[row["warehouse_code"]], sku_id=sku_ids[row["sku_code"]], quantity=row["quantity"], batch_id=SHOWCASE_BATCH_ID) for row in rows["in_transit"]],
    )
    order_rows = rows["orders"]
    _add_in_batches(
        session,
        [
            Order(
                **{key: value for key, value in row.items() if key != "warehouse_code"},
                warehouse_id=warehouse_ids[row["warehouse_code"]],
            )
            for row in order_rows
        ],
    )
    order_ids = dict(session.execute(select(Order.order_no, Order.id).where(Order.batch_id == SHOWCASE_BATCH_ID)).all())
    _add_in_batches(
        session,
        [OrderItem(order_id=order_ids[row["order_no"]], sku_id=sku_ids[row["sku_code"]], line_no=row["line_no"], quantity=row["quantity"], unit_price=row["unit_price"], currency=row["currency"], batch_id=SHOWCASE_BATCH_ID) for row in rows["order_items"]],
    )
    _add_in_batches(
        session,
        [OrderTrackingEvent(order_id=order_ids[row["order_no"]], **{key: value for key, value in row.items() if key != "order_no"}) for row in rows["tracking_events"]],
    )
    _add_in_batches(
        session,
        [OrderException(order_id=order_ids[row["order_no"]], **{key: value for key, value in row.items() if key != "order_no"}) for row in rows["order_exceptions"]],
    )


def seed_bulk(session: Session) -> bool:
    """Insert the new synthetic showcase batch; no legacy deletion or repair is permitted."""
    if _ensure_new_batch_state(session):
        return False
    _seed_showcase(session)
    _assert_showcase_matches(session)
    return True


def replace_v1_batch(session: Session) -> None:
    """Replace only an exactly verified V1 batch; caller must provide a database backup first."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text(
                "LOCK TABLE warehouses, skus, warehouse_locations, inventory_balances, "
                "in_transit_inventory, orders, order_tracking_events, order_exceptions, order_items "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    old_counts = _legacy_counts(session)
    if not any(old_counts.values()):
        raise BulkSeedConflictError("No legacy DEMO-BULK-V1 batch was found to replace.")
    if any(_bulk_counts(session).values()):
        raise BulkSeedConflictError("A showcase batch already exists; refusing an ambiguous replacement.")
    _assert_no_unrecognized_foreign_keys(session)
    old_ids = _assert_legacy_matches(session)
    preserved_snapshot = _snapshot_preserved_rows(session, old_ids)

    # The dependency graph is deliberately explicit; foreign-key cascades are not used for deletion.
    for table_model, key in (
        (OrderTrackingEvent, "tracking_events"),
        (OrderException, "order_exceptions"),
        (OrderItem, "order_items"),
        (InventoryBalance, "balances"),
        (InTransitInventory, "in_transit"),
        (WarehouseLocation, "locations"),
        (Order, "orders"),
        (SKU, "skus"),
        (Warehouse, "warehouses"),
    ):
        ids = old_ids.get(key, set())
        if ids:
            session.query(table_model).filter(table_model.id.in_(ids)).delete(synchronize_session=False)
    session.flush()
    _assert_snapshot_preserved(session, preserved_snapshot)
    _seed_showcase(session)
    _assert_showcase_matches(session)
    _assert_snapshot_preserved(session, preserved_snapshot)


def _create_verified_backup() -> Path:
    """Stream a local custom-format pg_dump from the Compose database and inspect it."""
    if (settings.postgres_host, settings.postgres_port, settings.postgres_db) != (EXPECTED_HOST, EXPECTED_PORT, EXPECTED_DATABASE):
        raise BulkSeedTargetError("Backup and replacement are restricted to 127.0.0.1:5433/yuncang.")
    docker = shutil.which("docker")
    if not docker:
        raise BackupError("Docker CLI must be available to create and inspect the database backup.")
    with Session(engine) as session:
        _assert_target_database(session)

    backup_dir = Path(__file__).resolve().parents[1] / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"yuncang-before-showcase-{stamp}.dump"
    if destination.exists():
        raise BackupError(f"Backup destination already exists: {destination}")
    fd, temp_name = tempfile.mkstemp(prefix="yuncang-backup-", suffix=".dump", dir=backup_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        dump_command = [
            docker, "compose", "exec", "-T", "db", "pg_dump", "--format=custom", "--no-owner",
            "--username", settings.postgres_user, "--dbname", EXPECTED_DATABASE,
        ]
        with temp_path.open("wb") as backup_file:
            result = subprocess.run(dump_command, stdout=backup_file, stderr=subprocess.PIPE, timeout=300, check=False)
        if result.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise BackupError(f"pg_dump failed before replacement: {message}")

        verify_command = [docker, "compose", "exec", "-T", "db", "pg_restore", "--list"]
        with temp_path.open("rb") as backup_file:
            listing = subprocess.run(verify_command, stdin=backup_file, capture_output=True, timeout=120, check=False)
        listing_text = listing.stdout.decode("utf-8", errors="replace")
        if listing.returncode != 0 or "TABLE DATA" not in listing_text:
            message = listing.stderr.decode("utf-8", errors="replace").strip()
            raise BackupError(f"pg_restore could not inspect the generated backup: {message}")
        expected_tables = {
            "warehouses", "skus", "warehouse_locations", "inventory_balances",
            "in_transit_inventory", "orders", "order_items", "order_tracking_events", "order_exceptions",
        }
        backed_up_tables = {
            line.split()[6]
            for line in listing_text.splitlines()
            if " TABLE DATA public " in line and len(line.split()) > 6
        }
        if not expected_tables.issubset(backed_up_tables):
            raise BackupError(
                f"Backup is missing expected table data entries: {sorted(expected_tables - backed_up_tables)}"
            )
        os.replace(temp_path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        print(f"Backup SHA-256: {digest}")
        return destination
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _main() -> None:
    parser = argparse.ArgumentParser(description="Load fictional warehouse showcase data.")
    parser.add_argument("--replace-v1", action="store_true", help="replace only the fully verified DEMO-BULK-V1 batch")
    args = parser.parse_args()
    backup_path = None
    if args.replace_v1:
        backup_path = _create_verified_backup()
    with Session(engine) as session, session.begin():
        _assert_target_database(session)
        if args.replace_v1:
            replace_v1_batch(session)
            changed = True
        else:
            changed = seed_bulk(session)
    if changed:
        action = f"Replaced V1 with {TOTAL_ROW_COUNT:,} showcase rows" if args.replace_v1 else f"Inserted {TOTAL_ROW_COUNT:,} showcase rows"
        print(f"{action}; batch marker: {SHOWCASE_BATCH_ID}.")
    else:
        print("The complete showcase batch already exists; no rows changed.")
    print(f"Database target: {EXPECTED_HOST}:{EXPECTED_PORT}/{EXPECTED_DATABASE}")
    print(f"Batch counts: {EXPECTED_COUNTS}")
    if backup_path:
        print(f"Verified pre-replacement backup: {backup_path}")


if __name__ == "__main__":
    _main()
