from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Base, Order, OrderException, OrderItem, OrderTrackingEvent
from app.seed import SEED_ORDERS, seed_orders
from app.seed_bulk import _generate_rows, _seed_showcase


@pytest.fixture
def order_engine() -> Iterator[Engine]:
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
        seed_orders(session)
    yield test_engine
    app.dependency_overrides.clear()
    test_engine.dispose()


@pytest.fixture
def order_client(order_engine: Engine) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(order_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_order_endpoint_returns_items_and_warehouse_for_showcase_order(order_client: TestClient, order_engine: Engine) -> None:
    with Session(order_engine) as session, session.begin():
        _seed_showcase(session)
    order_no = _generate_rows()["orders"][0]["order_no"]
    response = order_client.get(f"/data/orders/{order_no}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["warehouse"]["code"] == "USLAX"
    assert payload["items"]
    assert all(item["quantity"] > 0 for item in payload["items"])
    assert all(item["sku_code"] for item in payload["items"])


def test_order_endpoint_keeps_legacy_rows_compatible(order_client: TestClient) -> None:
    response = order_client.get("/data/orders/DEMO-ORDER-1001")
    assert response.status_code == 200
    assert response.json()["warehouse"] is None
    assert response.json()["items"] == []
def test_order_endpoint_returns_status_and_chronological_tracking(
    order_client: TestClient,
) -> None:
    response = order_client.get("/data/orders/DEMO-ORDER-1001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_no"] == "DEMO-ORDER-1001"
    assert payload["status_code"] == "IN_TRANSIT"
    assert payload["status_text"] == "已交承运商"
    assert payload["exceptions"] == []
    assert [event["event_type"] for event in payload["tracking_events"]] == [
        "CARRIER_ACCEPTED",
        "SORTING_CENTER",
    ]
    assert [event["occurred_at"] for event in payload["tracking_events"]] == sorted(
        event["occurred_at"] for event in payload["tracking_events"]
    )
    assert payload["tracking_events"][-1]["location"] == "上海（模拟）"


def test_order_endpoint_returns_recorded_exception_without_inferred_cause(
    order_client: TestClient,
) -> None:
    response = order_client.get("/data/orders/DEMO-ORDER-1002")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_code"] == "PROCESSING"
    assert payload["exceptions"] == [
        {
            "code": "ADDRESS_REVIEW",
            "detail": "收件地址待核对（模拟异常记录）",
            "active": True,
            "occurred_at": "2026-10-09T02:15:00Z",
        }
    ]
    assert payload["tracking_events"] == []
    assert "cause" not in payload
    assert "reason" not in payload


def test_order_endpoint_returns_empty_lists_for_known_order_without_evidence(
    order_client: TestClient,
) -> None:
    response = order_client.get("/data/orders/DEMO-ORDER-1003")

    assert response.status_code == 200
    assert response.json()["exceptions"] == []
    assert response.json()["tracking_events"] == []


def test_order_endpoint_returns_404_for_unknown_order(order_client: TestClient) -> None:
    response = order_client.get("/data/orders/UNKNOWN-ORDER")

    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found."}


def test_order_seed_is_repeatable_and_restores_demo_values(order_engine: Engine) -> None:
    with Session(order_engine) as session, session.begin():
        seed_orders(session)

    with Session(order_engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == len(SEED_ORDERS)
        assert session.scalar(select(func.count()).select_from(OrderException)) == 1
        assert session.scalar(select(func.count()).select_from(OrderTrackingEvent)) == 2

    with Session(order_engine) as session, session.begin():
        order = session.scalar(select(Order).where(Order.order_no == "DEMO-ORDER-1001"))
        assert order is not None
        order.status_text = "changed"

    with Session(order_engine) as session, session.begin():
        seed_orders(session)

    with Session(order_engine) as session:
        order = session.scalar(select(Order).where(Order.order_no == "DEMO-ORDER-1001"))
        assert order is not None
        assert order.status_text == "已交承运商"
        assert session.scalar(select(func.count()).select_from(Order)) == len(SEED_ORDERS)
        assert session.scalar(select(func.count()).select_from(OrderTrackingEvent)) == 2


def test_order_seed_rollback_on_integrity_error(
    order_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.seed as seed_module

    invalid_orders = list(seed_module.SEED_ORDERS)
    invalid_orders[0] = {**invalid_orders[0], "order_no": ""}
    monkeypatch.setattr(seed_module, "SEED_ORDERS", tuple(invalid_orders))

    with pytest.raises(IntegrityError):
        with Session(order_engine) as session, session.begin():
            seed_orders(session)

    with Session(order_engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == len(SEED_ORDERS)
