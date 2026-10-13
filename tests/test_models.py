from app.models import Base, OrderItem


def test_inventory_constraint_names_are_unique() -> None:
    for table in Base.metadata.tables.values():
        names = [constraint.name for constraint in table.constraints if constraint.name]
        assert len(names) == len(set(names))


def test_schema_contains_showcase_catalog_and_order_lines() -> None:
    assert set(Base.metadata.tables) == {
        "warehouses",
        "skus",
        "warehouse_locations",
        "inventory_balances",
        "in_transit_inventory",
        "orders",
        "order_exceptions",
        "order_tracking_events",
        "order_items",
    }
    assert {"display_id", "name_en", "region", "country", "city", "address", "latitude", "longitude", "batch_id"}.issubset(
        Base.metadata.tables["warehouses"].columns.keys()
    )
    assert {"category_code", "name_en", "is_hazmat", "hazmat_class", "un_number", "is_oversized", "length_mm", "weight_g"}.issubset(
        Base.metadata.tables["skus"].columns.keys()
    )
    assert "warehouse_id" in Base.metadata.tables["orders"].columns
    assert {"order_id", "sku_id", "line_no", "quantity", "unit_price", "currency"}.issubset(
        Base.metadata.tables["order_items"].columns.keys()
    )


def test_inventory_quantities_have_nonnegative_constraints() -> None:
    balance_constraints = {
        constraint.name for constraint in Base.metadata.tables["inventory_balances"].constraints
    }
    in_transit_constraints = {
        constraint.name for constraint in Base.metadata.tables["in_transit_inventory"].constraints
    }

    assert "ck_inventory_balances_good_on_hand_nonnegative" in balance_constraints
    assert "ck_inventory_balances_allocated_nonnegative" in balance_constraints
    assert "ck_inventory_balances_frozen_nonnegative" in balance_constraints
    assert "ck_inventory_balances_allocated_frozen_within_good_on_hand" in balance_constraints
    assert "ck_in_transit_inventory_quantity_nonnegative" in in_transit_constraints


def test_order_item_has_positive_quantity_and_line_constraints() -> None:
    constraints = {constraint.name for constraint in OrderItem.__table__.constraints}
    assert "ck_order_items_quantity_positive" in constraints
    assert "ck_order_items_line_no_positive" in constraints
    assert "uq_order_items_order_line" in constraints


def test_available_quantity_is_not_stored() -> None:
    columns = Base.metadata.tables["inventory_balances"].columns

    assert "available" not in columns
    assert {"good_on_hand", "allocated", "frozen"}.issubset(columns.keys())
