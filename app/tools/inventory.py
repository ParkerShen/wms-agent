from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

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


def execute_query_inventory(
    session: Session,
    arguments: Mapping[str, object],
) -> dict:
    """Validate model-supplied arguments and delegate to the read-only repository.

    Extra fields and coercions are rejected by QueryInventoryInput; repository
    lookup errors are allowed to propagate for the Agent to sanitize.
    """
    validated = QueryInventoryInput.model_validate(arguments)
    return query_inventory(
        session,
        warehouse_code=validated.warehouse_code,
        sku_code=validated.sku_code,
    )
