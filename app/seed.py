from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    InventoryBalance,
    InTransitInventory,
    Order,
    OrderException,
    OrderTrackingEvent,
    SKU,
    Warehouse,
    WarehouseLocation,
)


SEED_WAREHOUSE = {
    "code": "DEMO-WH-01",
    "name": "示例华东仓",
}

SEED_SKUS = (
    {"code": "DEMO-SKU-001", "name": "模拟收纳箱"},
    {"code": "DEMO-SKU-002", "name": "模拟保温杯"},
)

SEED_LOCATIONS = (
    {"code": "A-01-01", "balances": {"DEMO-SKU-001": (40, 8, 2)}},
    {"code": "A-01-02", "balances": {"DEMO-SKU-001": (15, 3, 0), "DEMO-SKU-002": (20, 4, 1)}},
)

SEED_IN_TRANSIT = {
    "DEMO-SKU-001": 12,
    "DEMO-SKU-002": 5,
}

SEED_ORDERS = (
    {
        "order_no": "DEMO-ORDER-1001",
        "status_code": "IN_TRANSIT",
        "status_text": "已交承运商",
        "created_at": datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc),
        "status_updated_at": datetime(2026, 10, 9, 3, 30, tzinfo=timezone.utc),
        "exceptions": (),
        "events": (
            {
                "record_key": "carrier-accepted",
                "event_type": "CARRIER_ACCEPTED",
                "detail": "包裹已由承运商揽收（模拟记录）",
                "location": "杭州（模拟）",
                "carrier": "示例物流",
                "tracking_no": "DEMO-TRACK-1001",
                "occurred_at": datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc),
            },
            {
                "record_key": "sorting-center",
                "event_type": "SORTING_CENTER",
                "detail": "包裹到达分拨中心（模拟记录）",
                "location": "上海（模拟）",
                "carrier": "示例物流",
                "tracking_no": "DEMO-TRACK-1001",
                "occurred_at": datetime(2026, 10, 9, 3, 30, tzinfo=timezone.utc),
            },
        ),
    },
    {
        "order_no": "DEMO-ORDER-1002",
        "status_code": "PROCESSING",
        "status_text": "处理中",
        "created_at": datetime(2026, 10, 9, 2, 0, tzinfo=timezone.utc),
        "status_updated_at": datetime(2026, 10, 9, 2, 15, tzinfo=timezone.utc),
        "exceptions": (
            {
                "record_key": "address-review",
                "code": "ADDRESS_REVIEW",
                "detail": "收件地址待核对（模拟异常记录）",
                "active": True,
                "occurred_at": datetime(2026, 10, 9, 2, 15, tzinfo=timezone.utc),
            },
        ),
        "events": (),
    },
    {
        "order_no": "DEMO-ORDER-1003",
        "status_code": "CREATED",
        "status_text": "已创建",
        "created_at": datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc),
        "status_updated_at": datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc),
        "exceptions": (),
        "events": (),
    },
)


def seed_inventory(session: Session) -> None:
    warehouse = session.scalar(
        select(Warehouse).where(Warehouse.code == SEED_WAREHOUSE["code"])
    )
    if warehouse is None:
        warehouse = Warehouse(**SEED_WAREHOUSE)
        session.add(warehouse)
    else:
        warehouse.name = SEED_WAREHOUSE["name"]
    session.flush()

    skus: dict[str, SKU] = {}
    for sku_data in SEED_SKUS:
        sku = session.scalar(select(SKU).where(SKU.code == sku_data["code"]))
        if sku is None:
            sku = SKU(**sku_data)
            session.add(sku)
        else:
            sku.name = sku_data["name"]
        skus[sku.code] = sku
    session.flush()

    locations: dict[str, WarehouseLocation] = {}
    for location_data in SEED_LOCATIONS:
        location = session.scalar(
            select(WarehouseLocation).where(
                WarehouseLocation.warehouse_id == warehouse.id,
                WarehouseLocation.code == location_data["code"],
            )
        )
        if location is None:
            location = WarehouseLocation(
                warehouse_id=warehouse.id,
                code=location_data["code"],
            )
            session.add(location)
        locations[location.code] = location
    session.flush()

    for location_data in SEED_LOCATIONS:
        location = locations[location_data["code"]]
        for sku_code, (good_on_hand, allocated, frozen) in location_data["balances"].items():
            balance = session.scalar(
                select(InventoryBalance).where(
                    InventoryBalance.location_id == location.id,
                    InventoryBalance.sku_id == skus[sku_code].id,
                )
            )
            if balance is None:
                balance = InventoryBalance(
                    location_id=location.id,
                    sku_id=skus[sku_code].id,
                    good_on_hand=good_on_hand,
                    allocated=allocated,
                    frozen=frozen,
                )
                session.add(balance)
            else:
                balance.good_on_hand = good_on_hand
                balance.allocated = allocated
                balance.frozen = frozen

    for sku_code, quantity in SEED_IN_TRANSIT.items():
        transit = session.scalar(
            select(InTransitInventory).where(
                InTransitInventory.warehouse_id == warehouse.id,
                InTransitInventory.sku_id == skus[sku_code].id,
            )
        )
        if transit is None:
            transit = InTransitInventory(
                warehouse_id=warehouse.id,
                sku_id=skus[sku_code].id,
                quantity=quantity,
            )
            session.add(transit)
        else:
            transit.quantity = quantity


def seed_orders(session: Session) -> None:
    for order_data in SEED_ORDERS:
        order = session.scalar(select(Order).where(Order.order_no == order_data["order_no"]))
        order_fields = {
            "status_code": order_data["status_code"],
            "status_text": order_data["status_text"],
            "created_at": order_data["created_at"],
            "status_updated_at": order_data["status_updated_at"],
        }
        if order is None:
            order = Order(order_no=order_data["order_no"], **order_fields)
            session.add(order)
        else:
            for field, value in order_fields.items():
                setattr(order, field, value)
        session.flush()

        for exception_data in order_data["exceptions"]:
            exception = session.scalar(
                select(OrderException).where(
                    OrderException.order_id == order.id,
                    OrderException.record_key == exception_data["record_key"],
                )
            )
            if exception is None:
                session.add(OrderException(order_id=order.id, **exception_data))
            else:
                for field, value in exception_data.items():
                    if field != "record_key":
                        setattr(exception, field, value)

        for event_data in order_data["events"]:
            event = session.scalar(
                select(OrderTrackingEvent).where(
                    OrderTrackingEvent.order_id == order.id,
                    OrderTrackingEvent.record_key == event_data["record_key"],
                )
            )
            if event is None:
                session.add(OrderTrackingEvent(order_id=order.id, **event_data))
            else:
                for field, value in event_data.items():
                    if field != "record_key":
                        setattr(event, field, value)


def main() -> None:
    from app.database import engine

    with Session(engine) as session, session.begin():
        seed_inventory(session)
        seed_orders(session)
    print("Synthetic inventory and order seed completed.")


if __name__ == "__main__":
    main()
