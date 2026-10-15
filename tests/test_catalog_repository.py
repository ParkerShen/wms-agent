from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.catalog_repository import SHOWCASE_BATCH_ID, find_warehouses_for_product, list_products_at_warehouse, list_showcase_warehouses
from app.models import Base, InTransitInventory, InventoryBalance, SKU, Warehouse, WarehouseLocation


@pytest.fixture
def catalog_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        la = Warehouse(display_id=1, code="USLAX", name="洛杉矶国际物流中心", name_en="Los Angeles Regional Fulfillment Center", city="Los Angeles", city_cn="洛杉矶", country_cn="美国", batch_id=SHOWCASE_BATCH_ID)
        london = Warehouse(display_id=2, code="GBLON", name="伦敦国际物流中心", name_en="London Regional Fulfillment Center", city="London", city_cn="伦敦", country_cn="英国", batch_id=SHOWCASE_BATCH_ID)
        old = Warehouse(code="OLD-WH", name="旧样例仓", batch_id="OLD-BATCH")
        product = SKU(code="YC-TEST-001", name="蓝牙降噪耳机（曜石黑）", name_en="Bluetooth noise-isolating headset, onyx black", category_name="消费电子", batch_id=SHOWCASE_BATCH_ID)
        similar = SKU(code="YC-TEST-002", name="蓝牙降噪耳机（海军蓝）", name_en="Bluetooth noise-isolating headset, navy blue", category_name="消费电子", batch_id=SHOWCASE_BATCH_ID)
        transit_only = SKU(code="YC-TEST-003", name="仅在途商品", name_en="Transit-only product", batch_id=SHOWCASE_BATCH_ID)
        old_sku = SKU(code="OLD-SKU", name="旧批次商品", batch_id="OLD-BATCH")
        session.add_all([la, london, old, product, similar, transit_only, old_sku])
        session.flush()
        locations = [WarehouseLocation(warehouse_id=la.id, code="USLAX-01", batch_id=SHOWCASE_BATCH_ID), WarehouseLocation(warehouse_id=la.id, code="USLAX-02", batch_id=SHOWCASE_BATCH_ID), WarehouseLocation(warehouse_id=london.id, code="GBLON-01", batch_id=SHOWCASE_BATCH_ID), WarehouseLocation(warehouse_id=old.id, code="OLD-LOC", batch_id="OLD-BATCH")]
        session.add_all(locations)
        session.flush()
        session.add_all([
            InventoryBalance(location_id=locations[0].id, sku_id=product.id, good_on_hand=10, allocated=3, frozen=1, batch_id=SHOWCASE_BATCH_ID),
            InventoryBalance(location_id=locations[1].id, sku_id=product.id, good_on_hand=5, allocated=1, frozen=1, batch_id=SHOWCASE_BATCH_ID),
            InventoryBalance(location_id=locations[2].id, sku_id=similar.id, good_on_hand=8, allocated=2, frozen=0, batch_id=SHOWCASE_BATCH_ID),
            InventoryBalance(location_id=locations[3].id, sku_id=old_sku.id, good_on_hand=99, allocated=0, frozen=0, batch_id="OLD-BATCH"),
            InTransitInventory(warehouse_id=la.id, sku_id=product.id, quantity=4, batch_id=SHOWCASE_BATCH_ID),
            InTransitInventory(warehouse_id=london.id, sku_id=transit_only.id, quantity=7, batch_id=SHOWCASE_BATCH_ID),
        ])
    yield engine
    engine.dispose()


def test_warehouse_listing_is_paged_and_batch_scoped(catalog_engine: Engine) -> None:
    with Session(catalog_engine) as session:
        first = list_showcase_warehouses(session, offset=0, limit=1)
        second = list_showcase_warehouses(session, offset=1, limit=10)
    assert first["total"] == 2 and first["items"][0]["code"] == "USLAX"
    assert first["has_more"] and first["next_offset"] == 1
    assert [row["code"] for row in second["items"]] == ["GBLON"]
    assert not second["has_more"]


def test_products_at_warehouse_match_chinese_and_aggregate(catalog_engine: Engine) -> None:
    with Session(catalog_engine) as session:
        result = list_products_at_warehouse(session, "洛杉矶仓库")
    assert result["status"] == "ok" and result["warehouse"]["code"] == "USLAX"
    assert result["total"] == 1
    item = next(row for row in result["items"] if row["code"] == "YC-TEST-001")
    assert (item["good_on_hand"], item["available"], item["in_transit"], item["location_count"]) == (15, 9, 4, 2)


def test_matching_ambiguity_missing_and_transit_only(catalog_engine: Engine) -> None:
    with Session(catalog_engine) as session:
        transit = list_products_at_warehouse(session, "London")
        ambiguous_wh = list_products_at_warehouse(session, "Regional Fulfillment Center")
        missing_wh = list_products_at_warehouse(session, "不存在的仓库")
        located = find_warehouses_for_product(session, "YC-TEST-001")
        transit_located = find_warehouses_for_product(session, "仅在途商品")
        ambiguous_sku = find_warehouses_for_product(session, "蓝牙降噪耳机")
        missing_sku = find_warehouses_for_product(session, "不存在的商品")
    assert transit["status"] == "ok"
    transit_item = next(row for row in transit["items"] if row["code"] == "YC-TEST-003")
    assert transit_item["in_transit"] == 7 and transit_item["good_on_hand"] == 0
    assert ambiguous_wh["status"] == "ambiguous" and len(ambiguous_wh["candidates"]) == 2
    assert missing_wh["status"] == "not_found"
    assert located["items"][0]["code"] == "USLAX"
    assert located["items"][0]["good_on_hand"] == 15 and located["items"][0]["in_transit"] == 4
    assert transit_located["items"][0]["code"] == "GBLON"
    assert transit_located["items"][0]["good_on_hand"] == 0 and transit_located["items"][0]["in_transit"] == 7
    assert ambiguous_sku["status"] == "ambiguous" and missing_sku["status"] == "not_found"


def test_product_listing_is_paged(catalog_engine: Engine) -> None:
    with Session(catalog_engine) as session, session.begin():
        warehouse = session.scalar(select(Warehouse).where(Warehouse.code == "USLAX"))
        location = session.scalar(select(WarehouseLocation).where(WarehouseLocation.code == "USLAX-01"))
        assert warehouse is not None and location is not None
        for index in range(11):
            sku = SKU(
                code=f"YC-PAGE-{index:02d}",
                name=f"分页商品{index:02d}",
                batch_id=SHOWCASE_BATCH_ID,
            )
            session.add(sku)
            session.flush()
            session.add(
                InventoryBalance(
                    location_id=location.id,
                    sku_id=sku.id,
                    good_on_hand=1,
                    allocated=0,
                    frozen=0,
                    batch_id=SHOWCASE_BATCH_ID,
                )
            )

    with Session(catalog_engine) as session:
        first = list_products_at_warehouse(session, "USLAX", offset=0, limit=10)
        second = list_products_at_warehouse(session, "USLAX", offset=10, limit=10)
    assert first["total"] == 12 and len(first["items"]) == 5
    assert first["has_more"] and first["next_offset"] == 5
    assert len(second["items"]) == 5 and second["has_more"]


def test_discovery_queries_do_not_write(catalog_engine: Engine) -> None:
    with Session(catalog_engine) as session:
        before = tuple(session.scalar(select(func.count()).select_from(model)) for model in (Warehouse, SKU, WarehouseLocation, InventoryBalance, InTransitInventory))
        list_showcase_warehouses(session)
        list_products_at_warehouse(session, "洛杉矶")
        find_warehouses_for_product(session, "蓝牙降噪耳机（曜石黑）")
        session.rollback()
    with Session(catalog_engine) as session:
        after = tuple(session.scalar(select(func.count()).select_from(model)) for model in (Warehouse, SKU, WarehouseLocation, InventoryBalance, InTransitInventory))
    assert after == before
