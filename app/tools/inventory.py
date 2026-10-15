from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.catalog_repository import (
    MAX_PAGE_SIZE,
    find_warehouses_for_product,
    list_products_at_warehouse,
    list_showcase_warehouses,
)
from app.inventory_repository import query_inventory


class QueryInventoryInput(BaseModel):
    """Strict model-call input for a single warehouse and SKU query."""

    model_config = ConfigDict(extra="forbid", strict=True)

    warehouse_code: str = Field(
        min_length=1,
        max_length=50,
        description="Exact warehouse business code, such as DEMO-WH-01.",
    )
    sku_code: str = Field(
        min_length=1,
        max_length=80,
        description="Exact SKU business code, such as DEMO-SKU-001.",
    )


class ListWarehousesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    offset: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=10, ge=1, le=10)


class ListWarehouseProductsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    warehouse_query: str = Field(
        min_length=1,
        max_length=120,
        description="Warehouse code, Chinese or English name, or city name.",
    )
    offset: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)


class FindProductWarehousesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product_query: str = Field(
        min_length=1,
        max_length=160,
        description="SKU code or Chinese or English product name.",
    )
    offset: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)


QUERY_INVENTORY_TOOL_NAME = "query_inventory"
QUERY_INVENTORY_TOOL_DESCRIPTION = (
    "Read inventory totals, bilingual product handling attributes, and storage locations for one warehouse and SKU."
)
QUERY_INVENTORY_TOOL_SCHEMA = QueryInventoryInput.model_json_schema()
QUERY_INVENTORY_TOOL = {
    "name": QUERY_INVENTORY_TOOL_NAME,
    "description": QUERY_INVENTORY_TOOL_DESCRIPTION,
    "input_schema": QUERY_INVENTORY_TOOL_SCHEMA,
}

LIST_WAREHOUSES_TOOL = {
    "name": "list_warehouses",
    "description": "List the fictional showcase warehouses. Use this for questions asking which warehouses exist.",
    "input_schema": ListWarehousesInput.model_json_schema(),
}
LIST_WAREHOUSE_PRODUCTS_TOOL = {
    "name": "list_warehouse_products",
    "description": "List products with on-hand or in-transit records at one warehouse. Resolve its Chinese/English name, city, or code.",
    "input_schema": ListWarehouseProductsInput.model_json_schema(),
}
FIND_PRODUCT_WAREHOUSES_TOOL = {
    "name": "find_product_warehouses",
    "description": "Find warehouses with on-hand or in-transit records for a product matched by Chinese/English name or SKU code.",
    "input_schema": FindProductWarehousesInput.model_json_schema(),
}
DISCOVERY_TOOLS = (
    LIST_WAREHOUSES_TOOL,
    LIST_WAREHOUSE_PRODUCTS_TOOL,
    FIND_PRODUCT_WAREHOUSES_TOOL,
)


def execute_query_inventory(session: Session, arguments: Mapping[str, object]) -> dict:
    """Validate model-supplied arguments and delegate to the read-only repository."""
    validated = QueryInventoryInput.model_validate(arguments)
    return query_inventory(
        session,
        warehouse_code=validated.warehouse_code,
        sku_code=validated.sku_code,
    )


def execute_list_warehouses(session: Session, arguments: Mapping[str, object]) -> dict:
    validated = ListWarehousesInput.model_validate(arguments)
    return list_showcase_warehouses(session, validated.offset, validated.limit)


def execute_list_warehouse_products(session: Session, arguments: Mapping[str, object]) -> dict:
    validated = ListWarehouseProductsInput.model_validate(arguments)
    return list_products_at_warehouse(
        session, validated.warehouse_query, validated.offset, validated.limit
    )


def execute_find_product_warehouses(session: Session, arguments: Mapping[str, object]) -> dict:
    validated = FindProductWarehousesInput.model_validate(arguments)
    return find_warehouses_for_product(
        session, validated.product_query, validated.offset, validated.limit
    )


def registered_inventory_tools() -> tuple[dict, ...]:
    """Return the fixed read-only inventory and catalog discovery allowlist."""
    return (QUERY_INVENTORY_TOOL, *DISCOVERY_TOOLS)


def execute_inventory_tool(
    name: str, session: Session, arguments: Mapping[str, object]
) -> dict:
    """Dispatch only to an explicitly registered read-only inventory Tool."""
    executors = {
        QUERY_INVENTORY_TOOL_NAME: execute_query_inventory,
        LIST_WAREHOUSES_TOOL["name"]: execute_list_warehouses,
        LIST_WAREHOUSE_PRODUCTS_TOOL["name"]: execute_list_warehouse_products,
        FIND_PRODUCT_WAREHOUSES_TOOL["name"]: execute_find_product_warehouses,
    }
    executor = executors.get(name)
    if executor is None:
        raise KeyError(name)
    return executor(session, arguments)
