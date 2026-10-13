from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, InventoryBalance, InTransitInventory, SKU, Warehouse, WarehouseLocation
from app.seed import SEED_WAREHOUSE, seed_inventory


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


def test_seed_inserts_expected_inventory_and_is_repeatable(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        seed_inventory(session)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Warehouse)) == 1
        assert session.scalar(select(func.count()).select_from(SKU)) == 2
        assert session.scalar(select(func.count()).select_from(WarehouseLocation)) == 2
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 3
        assert session.scalar(select(func.count()).select_from(InTransitInventory)) == 2

        sku = session.scalar(select(SKU).where(SKU.code == "DEMO-SKU-001"))
        assert sku is not None
        balances = session.scalars(
            select(InventoryBalance)
            .where(InventoryBalance.sku_id == sku.id)
            .order_by(InventoryBalance.id)
        ).all()
        assert [(row.good_on_hand, row.allocated, row.frozen) for row in balances] == [
            (40, 8, 2),
            (15, 3, 0),
        ]
        assert sum(row.good_on_hand - row.allocated - row.frozen for row in balances) == 42

    with Session(engine) as session, session.begin():
        seed_inventory(session)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Warehouse)) == 1
        assert session.scalar(select(func.count()).select_from(SKU)) == 2
        assert session.scalar(select(func.count()).select_from(WarehouseLocation)) == 2
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 3
        assert session.scalar(select(func.count()).select_from(InTransitInventory)) == 2


def test_seed_restores_canonical_values_and_preserves_unrelated_rows(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        unrelated_warehouse = Warehouse(code="OTHER-WH", name="Unrelated")
        unrelated_sku = SKU(code="OTHER-SKU", name="Unrelated item")
        session.add_all([unrelated_warehouse, unrelated_sku])

    with Session(engine) as session, session.begin():
        seed_inventory(session)

    with Session(engine) as session, session.begin():
        balance = session.scalar(select(InventoryBalance).limit(1))
        assert balance is not None
        balance.good_on_hand = 11

    with Session(engine) as session, session.begin():
        seed_inventory(session)

    with Session(engine) as session:
        warehouse = session.scalar(select(Warehouse).where(Warehouse.code == SEED_WAREHOUSE["code"]))
        assert warehouse is not None
        assert session.scalar(select(Warehouse).where(Warehouse.code == "OTHER-WH")) is not None
        assert session.scalar(select(SKU).where(SKU.code == "OTHER-SKU")) is not None
        assert session.scalar(select(func.count()).select_from(Warehouse)) == 2
        assert session.scalar(select(func.count()).select_from(SKU)) == 3
        balances = session.scalars(select(InventoryBalance)).all()
        assert all(row.good_on_hand != 11 for row in balances)


def test_seed_transaction_rolls_back_when_constraint_fails(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.seed as seed_module

    monkeypatch.setattr(seed_module, "SEED_IN_TRANSIT", {"DEMO-SKU-001": -1})

    with pytest.raises(IntegrityError):
        with Session(engine) as session, session.begin():
            seed_inventory(session)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Warehouse)) == 0
        assert session.scalar(select(func.count()).select_from(SKU)) == 0
        assert session.scalar(select(func.count()).select_from(WarehouseLocation)) == 0
        assert session.scalar(select(func.count()).select_from(InventoryBalance)) == 0
        assert session.scalar(select(func.count()).select_from(InTransitInventory)) == 0
