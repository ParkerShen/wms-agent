from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
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
from app.seed import SEED_ORDERS
from app.seed_bulk import (
    EXPECTED_COUNTS,
    LEGACY_COUNTS,
    SHOWCASE_BATCH_ID,
    TOTAL_ROW_COUNT,
    BulkSeedConflictError,
    _generate_rows,
    _generate_v1_rows,
    _legacy_counts,
    _seed_showcase,
    replace_v1_batch,
    seed_bulk,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    test_engine = create_engine("sqlite://")

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


def test_generator_has_expected_counts_and_quality() -> None:
    rows = _generate_rows()
    assert rows == _generate_rows()
    assert {key: len(value) for key, value in rows.items()} == EXPECTED_COUNTS
    assert sum(map(len, rows.values())) == TOTAL_ROW_COUNT == 48_050
    assert len({row["code"] for row in rows["warehouses"]}) == 50
    assert len({row["code"] for row in rows["skus"]}) == 2_000
    assert len({row["name"] for row in rows["skus"]}) == 2_000
    assert len({row["category_code"] for row in rows["skus"]}) >= 20
    assert any(row["is_hazmat"] and row["un_number"] for row in rows["skus"])
    assert any(row["is_oversized"] for row in rows["skus"])
    assert all(row["name_en"] and row["name"] for row in rows["warehouses"])
    assert all(row["phone"].startswith("+999-555-") for row in rows["warehouses"])
    assert all(row["good_on_hand"] >= row["allocated"] + row["frozen"] >= 0 for row in rows["balances"])
    assert all(row["quantity"] > 0 for row in rows["order_items"])
    assert all(row["order_no"].startswith(row["warehouse_code"] + "-") for row in rows["orders"])
    assert all("DEMO" not in row["order_no"] for row in rows["orders"])
    assert all("模拟商品" not in row["name"] for row in rows["skus"])


def _seed_existing_demo_rows(session: Session) -> None:
    warehouse = Warehouse(code="DEMO-WH-01", name="Existing demo warehouse")
    sku = SKU(code="DEMO-SKU-001", name="Existing demo sku")
    session.add_all([warehouse, sku])
    session.flush()
    location = WarehouseLocation(warehouse_id=warehouse.id, code="A-01-01")
    order = Order(
        order_no="DEMO-ORDER-1001",
        status_code="BEFORE",
        status_text="Existing value",
        created_at=SEED_ORDERS[0]["created_at"],
        status_updated_at=SEED_ORDERS[0]["status_updated_at"],
    )
    session.add_all([location, order])
    session.flush()
    session.add_all(
        [
            InventoryBalance(location_id=location.id, sku_id=sku.id, good_on_hand=41, allocated=7, frozen=2),
            InTransitInventory(warehouse_id=warehouse.id, sku_id=sku.id, quantity=13),
            OrderTrackingEvent(
                order_id=order.id,
                record_key="existing-event",
                event_type="EXISTING",
                detail="Keep this row unchanged",
                location="Existing location",
                carrier="Existing carrier",
                tracking_no="EXISTING-TRACK",
                occurred_at=SEED_ORDERS[0]["created_at"],
            ),
            OrderException(
                order_id=order.id,
                record_key="existing-exception",
                code="EXISTING",
                detail="Keep this exception unchanged",
                active=True,
                occurred_at=SEED_ORDERS[0]["created_at"],
            ),
        ]
    )


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_seed_is_idempotent_and_does_not_modify_existing_records(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        _seed_existing_demo_rows(session)
    with Session(engine) as session, session.begin():
        assert seed_bulk(session) is True
    with Session(engine) as session, session.begin():
        assert seed_bulk(session) is False
    with Session(engine) as session:
        assert _count(session, Warehouse) == EXPECTED_COUNTS["warehouses"] + 1
        assert _count(session, SKU) == EXPECTED_COUNTS["skus"] + 1
        assert _count(session, Order) == EXPECTED_COUNTS["orders"] + 1
        assert _count(session, OrderItem) == EXPECTED_COUNTS["order_items"]
        assert session.scalar(select(Warehouse.name).where(Warehouse.code == "DEMO-WH-01")) == "Existing demo warehouse"
        assert session.scalar(select(SKU.name).where(SKU.code == "DEMO-SKU-001")) == "Existing demo sku"
        assert session.scalar(select(Order.status_text).where(Order.order_no == "DEMO-ORDER-1001")) == "Existing value"


def test_partial_showcase_batch_is_rejected_without_changes(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(Warehouse(code="PARTIAL", name="Partial", batch_id=SHOWCASE_BATCH_ID))
    with Session(engine) as session, session.begin():
        with pytest.raises(BulkSeedConflictError):
            seed_bulk(session)
    with Session(engine) as session:
        assert _count(session, Warehouse) == 1
        assert _count(session, SKU) == 0


def test_modified_showcase_batch_is_rejected(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        _seed_showcase(session)
    with Session(engine) as session, session.begin():
        warehouse = session.scalar(select(Warehouse).where(Warehouse.batch_id == SHOWCASE_BATCH_ID))
        assert warehouse is not None
        warehouse.name = "Changed outside loader"
    with Session(engine) as session, session.begin():
        with pytest.raises(BulkSeedConflictError):
            seed_bulk(session)


def _load_legacy_batch(session: Session) -> None:
    rows = _generate_v1_rows()
    warehouses = {row["code"]: Warehouse(**row) for row in rows["warehouses"]}
    skus = {row["code"]: SKU(**row) for row in rows["skus"]}
    session.add_all([*warehouses.values(), *skus.values()])
    session.flush()
    locations = {row["code"]: WarehouseLocation(warehouse_id=warehouses[row["warehouse_code"]].id, code=row["code"]) for row in rows["locations"]}
    session.add_all(locations.values())
    session.flush()
    session.add_all([
        InventoryBalance(
            location_id=locations[row["location_code"]].id,
            sku_id=skus[row["sku_code"]].id,
            good_on_hand=row["good_on_hand"],
            allocated=row["allocated"],
            frozen=row["frozen"],
        )
        for row in rows["balances"]
    ])
    session.add_all([
        InTransitInventory(warehouse_id=warehouses[row["warehouse_code"]].id, sku_id=skus[row["sku_code"]].id, quantity=row["quantity"])
        for row in rows["in_transit"]
    ])
    orders = {row["order_no"]: Order(**row) for row in rows["orders"]}
    session.add_all(orders.values())
    session.flush()
    session.add_all([
        OrderTrackingEvent(order_id=orders[row["order_no"]].id, **{key: value for key, value in row.items() if key != "order_no"})
        for row in rows["tracking_events"]
    ])
    session.add_all([
        OrderException(order_id=orders[row["order_no"]].id, **{key: value for key, value in row.items() if key != "order_no"})
        for row in rows["order_exceptions"]
    ])


def test_regular_seed_refuses_to_replace_legacy_batch(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(Warehouse(code="DEMO-BULK-V1-extra", name="legacy marker"))
    with Session(engine) as session, session.begin():
        with pytest.raises(BulkSeedConflictError):
            seed_bulk(session)
    with Session(engine) as session:
        assert _count(session, Warehouse) == 1


def test_replace_rejects_modified_legacy_batch_without_deleting_rows(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        _load_legacy_batch(session)
    with Session(engine) as session, session.begin():
        warehouse = session.scalar(select(Warehouse).where(Warehouse.code == "DEMO-BULK-V1-WH-001"))
        assert warehouse is not None
        warehouse.name = "modified"
    with Session(engine) as session:
        before = _count(session, Warehouse)
    with Session(engine) as session, session.begin():
        with pytest.raises(BulkSeedConflictError):
            replace_v1_batch(session)
    with Session(engine) as session:
        assert _count(session, Warehouse) == before
        assert _legacy_counts(session) == {**LEGACY_COUNTS, "order_items": 0}


def test_replace_refuses_order_item_dependency(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        _load_legacy_batch(session)
    with Session(engine) as session, session.begin():
        old_order = session.scalar(select(Order).where(Order.order_no == "DEMO-BULK-V1-ORDER-00001"))
        old_sku = session.scalar(select(SKU).where(SKU.code == "DEMO-BULK-V1-SKU-0001"))
        assert old_order is not None and old_sku is not None
        session.add(OrderItem(order_id=old_order.id, sku_id=old_sku.id, line_no=1, quantity=1, unit_price=1, currency="USD"))
    with Session(engine) as session, session.begin():
        with pytest.raises(BulkSeedConflictError):
            replace_v1_batch(session)
    with Session(engine) as session:
        assert _count(session, Warehouse) == LEGACY_COUNTS["warehouses"]


def test_replace_requires_exact_legacy_set_and_preserves_non_batch_rows(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        _seed_existing_demo_rows(session)
        _load_legacy_batch(session)
    with Session(engine) as session, session.begin():
        replace_v1_batch(session)
    with Session(engine) as session:
        assert _legacy_counts(session) == {key: 0 for key in EXPECTED_COUNTS}
        assert _count(session, Warehouse) == EXPECTED_COUNTS["warehouses"] + 1
        assert _count(session, SKU) == EXPECTED_COUNTS["skus"] + 1
        assert _count(session, OrderItem) == EXPECTED_COUNTS["order_items"]
        assert session.scalar(select(Warehouse.name).where(Warehouse.code == "DEMO-WH-01")) == "Existing demo warehouse"
        assert session.scalar(select(SKU.name).where(SKU.code == "DEMO-SKU-001")) == "Existing demo sku"
        assert session.scalar(select(Order.status_text).where(Order.order_no == "DEMO-ORDER-1001")) == "Existing value"
        assert _count(session, WarehouseLocation) == EXPECTED_COUNTS["locations"] + 1


def test_preserved_rows_are_rechecked_after_showcase_insert(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.seed_bulk as module

    with Session(engine) as session, session.begin():
        _seed_existing_demo_rows(session)
        _load_legacy_batch(session)

    original_seed_showcase = module._seed_showcase

    def mutate_preserved_row(session: Session) -> None:
        original_seed_showcase(session)
        warehouse = session.scalar(select(Warehouse).where(Warehouse.code == "DEMO-WH-01"))
        assert warehouse is not None
        warehouse.name = "unexpected change during replacement"

    monkeypatch.setattr(module, "_seed_showcase", mutate_preserved_row)
    with pytest.raises(BulkSeedConflictError, match="Rows outside the verified legacy batch changed"):
        with Session(engine) as session, session.begin():
            replace_v1_batch(session)

    with Session(engine) as session:
        assert _legacy_counts(session) == {**LEGACY_COUNTS, "order_items": 0}
        assert session.scalar(select(Warehouse.name).where(Warehouse.code == "DEMO-WH-01")) == "Existing demo warehouse"


def test_failed_new_write_rolls_back_replacement(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.seed_bulk as module

    with Session(engine) as session, session.begin():
        _load_legacy_batch(session)
    original = module._seed_showcase
    def fail(session: Session) -> None:
        original(session)
        raise RuntimeError("forced failure")
    monkeypatch.setattr(module, "_seed_showcase", fail)
    with pytest.raises(RuntimeError, match="forced failure"):
        with Session(engine) as session, session.begin():
            replace_v1_batch(session)
    with Session(engine) as session:
        assert _legacy_counts(session) == {**LEGACY_COUNTS, "order_items": 0}
        assert _count(session, Warehouse) == LEGACY_COUNTS["warehouses"]
