from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import (
    Base,
    InTransitInventory,
    Order,
    OrderItem,
    SKU,
    Warehouse,
    WarehouseLocation,
)
from app.seed import seed_inventory
from app.seed_bulk import _generate_rows, SHOWCASE_BATCH_ID, _seed_showcase


@pytest.fixture
def api_engine() -> Iterator[Engine]:
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session, session.begin():
        seed_inventory(session)
    yield test_engine
    app.dependency_overrides.clear()
    test_engine.dispose()


@pytest.fixture
def client(api_engine: Engine) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(api_engine) as session:
            yield session
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_inventory_endpoint_returns_warehouse_sku_totals_and_locations(client: TestClient) -> None:
    response = client.get("/data/inventory", params={"warehouse_code": "DEMO-WH-01", "sku_code": "DEMO-SKU-001"})
    assert response.status_code == 200
    assert response.json() == {
        "warehouse": {"code": "DEMO-WH-01", "name": "示例华东仓"},
        "sku": {"code": "DEMO-SKU-001", "name": "模拟收纳箱"},
        "good_on_hand": 55, "allocated": 11, "frozen": 2, "available": 42,
        "in_transit": 12, "has_inventory_record": True,
        "locations": [
            {"code": "A-01-01", "good_on_hand": 40, "allocated": 8, "frozen": 2, "available": 30},
            {"code": "A-01-02", "good_on_hand": 15, "allocated": 3, "frozen": 0, "available": 12},
        ],
    }


def test_inventory_endpoint_returns_404_for_unknown_codes(client: TestClient) -> None:
    assert client.get("/data/inventory", params={"warehouse_code": "MISSING-WH", "sku_code": "DEMO-SKU-001"}).status_code == 404
    assert client.get("/data/inventory", params={"warehouse_code": "DEMO-WH-01", "sku_code": "MISSING-SKU"}).status_code == 404


def test_inventory_endpoint_returns_zero_for_known_entities_without_records(client: TestClient, api_engine: Engine) -> None:
    with Session(api_engine) as session, session.begin():
        session.add_all([Warehouse(code="EMPTY-WH", name="空仓"), SKU(code="EMPTY-SKU", name="无库存商品")])
    payload = client.get("/data/inventory", params={"warehouse_code": "EMPTY-WH", "sku_code": "EMPTY-SKU"}).json()
    assert payload == {
        "warehouse": {"code": "EMPTY-WH", "name": "空仓"},
        "sku": {"code": "EMPTY-SKU", "name": "无库存商品"},
        "good_on_hand": 0, "allocated": 0, "frozen": 0, "available": 0,
        "in_transit": 0, "has_inventory_record": False, "locations": [],
    }


def test_inventory_endpoint_handles_transit_only_records(client: TestClient, api_engine: Engine) -> None:
    with Session(api_engine) as session, session.begin():
        warehouse, sku = Warehouse(code="TRANSIT-WH", name="在途仓"), SKU(code="TRANSIT-SKU", name="在途商品")
        session.add_all([warehouse, sku])
        session.flush()
        session.add(InTransitInventory(warehouse_id=warehouse.id, sku_id=sku.id, quantity=9))
    payload = client.get("/data/inventory", params={"warehouse_code": "TRANSIT-WH", "sku_code": "TRANSIT-SKU"}).json()
    assert payload["in_transit"] == 9
    assert payload["has_inventory_record"] is True
    assert payload["available"] == 0
    assert payload["locations"] == []


def test_warehouse_endpoint_returns_only_complete_bilingual_showcase_rows(client: TestClient, api_engine: Engine) -> None:
    with Session(api_engine) as session, session.begin():
        _seed_showcase(session)
    response = client.get("/data/warehouses")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 50
    assert payload[0]["code"] == "USLAX"
    assert payload[0]["fictional_demo_data"] is True
    assert payload[0]["name"] and payload[0]["name_en"]
    assert payload[0]["country"] == "US"
    assert payload[0]["country_cn"] == "美国"
    assert all(item["phone"].startswith("+999-") for item in payload)


def test_inventory_endpoint_exposes_hazmat_and_oversized_attributes(client: TestClient, api_engine: Engine) -> None:
    with Session(api_engine) as session, session.begin():
        _seed_showcase(session)
    rows = _generate_rows()
    hazmat = next(row for row in rows["skus"] if row["is_hazmat"])
    oversized = next(row for row in rows["skus"] if row["is_oversized"])
    for sku in (hazmat, oversized):
        response = client.get("/data/inventory", params={"warehouse_code": "USLAX", "sku_code": sku["code"]})
        assert response.status_code == 200
        payload = response.json()
        assert payload["sku"]["name_en"]
        assert payload["sku"]["category_code"]
        if sku["is_hazmat"]:
            assert payload["sku"]["hazmat_class"]
            assert payload["sku"]["un_number"]
        if sku["is_oversized"]:
            assert payload["sku"]["is_oversized"] is True
            assert payload["sku"]["length_mm"] > 1_000
