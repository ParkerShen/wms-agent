from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, InTransitInventory, InventoryBalance, SKU, Warehouse, WarehouseLocation
from app.seed import seed_inventory
from app.tools.inventory import (
    QUERY_INVENTORY_TOOL,
    QUERY_INVENTORY_TOOL_NAME,
    QUERY_INVENTORY_TOOL_SCHEMA,
    QueryInventoryInput,
    execute_query_inventory,
)
from app.seed_bulk import _generate_rows, _seed_showcase
from app.inventory_repository import InventoryNotFoundError


@pytest.fixture
def tool_engine() -> Iterator[Engine]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session, session.begin():
        seed_inventory(session)
    yield test_engine
    test_engine.dispose()


def test_inventory_tool_contract_has_only_bounded_inputs() -> None:
    assert QUERY_INVENTORY_TOOL_NAME == "query_inventory"
    assert QUERY_INVENTORY_TOOL["name"] == QUERY_INVENTORY_TOOL_NAME
    assert QUERY_INVENTORY_TOOL["input_schema"] == QUERY_INVENTORY_TOOL_SCHEMA
    assert QUERY_INVENTORY_TOOL_SCHEMA["additionalProperties"] is False
    assert set(QUERY_INVENTORY_TOOL_SCHEMA["properties"]) == {
        "warehouse_code",
        "sku_code",
    }

    with pytest.raises(ValidationError):
        QueryInventoryInput.model_validate(
            {"warehouse_code": "DEMO-WH-01", "sku_code": "DEMO-SKU-001", "sql": "..."}
        )
    with pytest.raises(ValidationError):
        QueryInventoryInput.model_validate({"warehouse_code": "", "sku_code": "DEMO-SKU-001"})


def test_inventory_tool_returns_repository_result(tool_engine: Engine) -> None:
    with Session(tool_engine) as session:
        result = execute_query_inventory(
            session,
            {"warehouse_code": "DEMO-WH-01", "sku_code": "DEMO-SKU-001"},
        )

    assert result == {
        "warehouse": {"code": "DEMO-WH-01", "name": "示例华东仓"},
        "sku": {"code": "DEMO-SKU-001", "name": "模拟收纳箱"},
        "good_on_hand": 55,
        "allocated": 11,
        "frozen": 2,
        "available": 42,
        "in_transit": 12,
        "has_inventory_record": True,
        "locations": [
            {"code": "A-01-01", "good_on_hand": 40, "allocated": 8, "frozen": 2, "available": 30},
            {"code": "A-01-02", "good_on_hand": 15, "allocated": 3, "frozen": 0, "available": 12},
        ],
    }


def test_inventory_tool_preserves_unknown_entity_errors(tool_engine: Engine) -> None:
    with Session(tool_engine) as session:
        with pytest.raises(InventoryNotFoundError, match="Warehouse not found"):
            execute_query_inventory(
                session,
                {"warehouse_code": "MISSING-WH", "sku_code": "DEMO-SKU-001"},
            )
        with pytest.raises(InventoryNotFoundError, match="SKU not found"):
            execute_query_inventory(
                session,
                {"warehouse_code": "DEMO-WH-01", "sku_code": "MISSING-SKU"},
            )


def test_inventory_tool_returns_known_empty_and_transit_only_results(
    tool_engine: Engine,
) -> None:
    with Session(tool_engine) as session, session.begin():
        empty_warehouse = Warehouse(code="EMPTY-WH", name="空仓")
        empty_sku = SKU(code="EMPTY-SKU", name="无库存商品")
        transit_warehouse = Warehouse(code="TRANSIT-WH", name="在途仓")
        transit_sku = SKU(code="TRANSIT-SKU", name="在途商品")
        session.add_all([empty_warehouse, empty_sku, transit_warehouse, transit_sku])
        session.flush()
        session.add(
            InTransitInventory(
                warehouse_id=transit_warehouse.id,
                sku_id=transit_sku.id,
                quantity=9,
            )
        )

    with Session(tool_engine) as session:
        empty_result = execute_query_inventory(
            session,
            {"warehouse_code": "EMPTY-WH", "sku_code": "EMPTY-SKU"},
        )
        transit_result = execute_query_inventory(
            session,
            {"warehouse_code": "TRANSIT-WH", "sku_code": "TRANSIT-SKU"},
        )

    assert empty_result["available"] == 0
    assert empty_result["has_inventory_record"] is False
    assert empty_result["locations"] == []
    assert transit_result["in_transit"] == 9
    assert transit_result["has_inventory_record"] is True
    assert transit_result["available"] == 0
    assert transit_result["locations"] == []


def test_inventory_tool_result_can_be_json_serialized(tool_engine: Engine) -> None:
    import json

    with Session(tool_engine) as session:
        result = execute_query_inventory(
            session,
            {"warehouse_code": "DEMO-WH-01", "sku_code": "DEMO-SKU-001"},
        )

    encoded = json.dumps(result, ensure_ascii=False)
    assert json.loads(encoded) == result


def test_inventory_tool_does_not_write_to_database(tool_engine: Engine) -> None:
    with Session(tool_engine) as session:
        before = (
            session.scalar(select(func.count()).select_from(Warehouse)),
            session.scalar(select(func.count()).select_from(SKU)),
            session.scalar(select(func.count()).select_from(WarehouseLocation)),
            session.scalar(select(func.count()).select_from(InventoryBalance)),
            session.scalar(select(func.count()).select_from(InTransitInventory)),
        )
        execute_query_inventory(
            session,
            {"warehouse_code": "DEMO-WH-01", "sku_code": "DEMO-SKU-001"},
        )
        session.rollback()

    with Session(tool_engine) as session:
        after = (
            session.scalar(select(func.count()).select_from(Warehouse)),
            session.scalar(select(func.count()).select_from(SKU)),
            session.scalar(select(func.count()).select_from(WarehouseLocation)),
            session.scalar(select(func.count()).select_from(InventoryBalance)),
            session.scalar(select(func.count()).select_from(InTransitInventory)),
        )

    assert after == before
