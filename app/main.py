from pathlib import Path
from datetime import datetime
from collections.abc import AsyncIterator
import asyncio
import json

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.inventory_agent import (
    AgentLoopError,
    CompletionModel,
    run_inventory_agent,
    stream_inventory_agent,
)
from app.database import check_database_connection, get_session
from app.inventory_repository import InventoryNotFoundError, query_inventory, query_warehouses
from app.llm.deepseek import (
    DeepSeekClient,
    DeepSeekClientError,
    DeepSeekConfigurationError,
)
from app.order_repository import OrderNotFoundError, query_order

app = FastAPI(
    title="YunCang Copilot API",
    description="云仓运营助手的本地模拟数据 API",
    version="0.1.0",
)
CHAT_PAGE = Path(__file__).parent / "static" / "index.html"


class InventoryIdentity(BaseModel):
    """Stable warehouse or SKU identity included in read-only data responses."""

    code: str = Field(description="Synthetic business code used in queries.")
    name: str = Field(description="Display name; demo records may be bilingual.")


class InventoryWarehouseIdentity(InventoryIdentity):
    name_en: str | None = None
    region: str | None = None
    region_cn: str | None = None
    country: str | None = None
    country_cn: str | None = None
    city: str | None = None
    city_cn: str | None = None


class InventorySKUIdentity(InventoryIdentity):
    name_en: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    category_name_en: str | None = None
    is_hazmat: bool | None = None
    hazmat_class: str | None = None
    un_number: str | None = None
    is_oversized: bool | None = None
    length_mm: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    weight_g: int | None = None


class InventoryLocationResponse(BaseModel):
    """Inventory quantities at one warehouse location (all values are units)."""

    code: str = Field(description="Synthetic location code.")
    area_code: str | None = Field(default=None, description="Area within the warehouse, when known.")
    storage_type: str | None = Field(default=None, description="Synthetic storage category, when present.")
    good_on_hand: int = Field(description="Recorded good quantity physically on hand.")
    allocated: int = Field(description="Quantity assigned to existing work.")
    frozen: int = Field(description="Quantity unavailable due to a recorded hold.")
    available: int = Field(description="Project-defined good_on_hand minus allocated minus frozen.")


class InventoryResponse(BaseModel):
    """Read-only stock totals, product attributes, and storage locations."""

    warehouse: InventoryWarehouseIdentity = Field(description="Warehouse matched by exact code.")
    sku: InventorySKUIdentity = Field(description="SKU matched by exact code.")
    good_on_hand: int = Field(description="Sum of good stock across warehouse locations.")
    allocated: int = Field(description="Sum of allocated stock across warehouse locations.")
    frozen: int = Field(description="Sum of frozen stock across warehouse locations.")
    available: int = Field(description="good_on_hand - allocated - frozen; an MVP assumption.")
    in_transit: int = Field(description="Recorded inbound quantity, separate from available stock.")
    has_inventory_record: bool = Field(description="Whether a balance or in-transit record exists.")
    locations: list[InventoryLocationResponse] = Field(description="Matching location-level stock rows.")


class WarehouseResponse(BaseModel):
    """Public fields for a fictional showcase warehouse."""

    id: int
    code: str
    region: str
    region_cn: str
    country: str
    country_cn: str
    city: str
    city_cn: str
    name: str
    name_en: str
    address: str
    address_cn: str
    postal_code: str
    phone: str
    latitude: float
    longitude: float
    status: str
    status_cn: str
    fictional_demo_data: bool


class OrderWarehouseResponse(InventoryWarehouseIdentity):
    pass


class OrderItemResponse(BaseModel):
    """One stored order line with synthetic product classification fields."""

    line_no: int
    sku_code: str
    sku_name: str
    sku_name_en: str | None
    category_code: str | None
    category_name: str | None
    category_name_en: str | None
    quantity: int
    unit_price: float
    currency: str
    is_hazmat: bool | None
    hazmat_class: str | None
    un_number: str | None
    is_oversized: bool | None


class OrderExceptionResponse(BaseModel):
    """A recorded order exception; ``active`` reflects the stored record."""

    code: str
    detail: str
    active: bool
    occurred_at: datetime


class OrderTrackingEventResponse(BaseModel):
    """One stored tracking event; this record alone is not a root-cause inference."""

    event_type: str
    detail: str
    location: str | None
    carrier: str | None
    tracking_no: str | None
    occurred_at: datetime


class OrderResponse(BaseModel):
    """Read-only order snapshot; lists contain stored evidence, not inferred causes."""

    order_no: str
    status_code: str
    status_text: str
    created_at: datetime
    status_updated_at: datetime
    warehouse: OrderWarehouseResponse | None = None
    items: list[OrderItemResponse] = Field(default_factory=list)
    exceptions: list[OrderExceptionResponse]
    tracking_events: list[OrderTrackingEventResponse]


class ChatRequest(BaseModel):
    """Single user turn sent to either chat completion endpoint."""

    message: str = Field(
        min_length=1,
        max_length=2000,
        description="Natural-language question; current Agent scope is read-only inventory.",
    )


class ChatResponse(BaseModel):
    """Final, non-streaming answer returned by POST /chat."""

    answer: str = Field(description="Assistant answer based on the read-only inventory Tool.")


async def get_completion_model() -> AsyncIterator[CompletionModel]:
    """Provide a request-scoped completion model client.

    FastAPI runs this dependency as an async generator; its teardown must await
    ``aclose`` because the streaming endpoint may have created an async transport.
    Sync-only injected test models continue to work through the ``close`` fallback.
    """
    model = DeepSeekClient()
    try:
        yield model
    finally:
        aclose = getattr(model, "aclose", None)
        if aclose is not None:
            await aclose()
        else:
            close = getattr(model, "close", None)
            if close is not None:
                close()


@app.get("/", include_in_schema=False)
def chat_page() -> FileResponse:
    """Serve the legacy single-file chat while the Next.js UI is being adopted."""
    return FileResponse(CHAT_PAGE, media_type="text/html")


@app.get("/health", tags=["health"], summary="Check API process health")
def health_check() -> dict[str, str]:
    """Return liveness only; use /health/ready to check database connectivity."""
    return {"status": "ok"}


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Answer a read-only inventory question",
    description=(
        "Runs the bounded inventory Agent and returns one JSON answer. "
        "The current Tool allowlist contains only query_inventory; it does not modify data."
    ),
    responses={
        502: {"description": "Provider or Agent failed; internal details are not returned."},
        503: {"description": "DeepSeek is not configured on the API server."},
        422: {"description": "The message is empty or longer than 2000 characters."},
    },
)
def chat(
    request: ChatRequest,
    session: Session = Depends(get_session),
    model: CompletionModel = Depends(get_completion_model),
) -> ChatResponse:
    try:
        answer = run_inventory_agent(request.message, session, model)
    except DeepSeekConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service is not configured.",
        ) from error
    except (DeepSeekClientError, AgentLoopError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chat service could not complete the request.",
        ) from error
    return ChatResponse(answer=answer)


@app.post(
    "/chat/stream",
    tags=["chat"],
    summary="Stream a read-only inventory answer",
    description=(
        "Returns Server-Sent Events using data-only JSON frames: "
        "{type: delta, text: ...}, then {type: done}; failures after streaming "
        "starts use a safe {type: error, message: ...} event. Tool-call data is not exposed."
    ),
    responses={
        200: {"description": "text/event-stream containing delta and one terminal event."},
        502: {"description": "Provider or Agent failed before the stream began."},
        503: {"description": "DeepSeek is not configured on the API server."},
        422: {"description": "The message is empty or longer than 2000 characters."},
    },
)
async def chat_stream(
    request: ChatRequest,
    session: Session = Depends(get_session),
    model: CompletionModel = Depends(get_completion_model),
) -> StreamingResponse:
    """Return POST-based SSE because requests carry a JSON message body.

    Configuration failures are returned as HTTP errors before headers are sent;
    once streaming begins, failures use a fixed safe ``error`` event instead.
    """
    try:
        ensure_configured = getattr(model, "ensure_configured", None)
        if ensure_configured is not None:
            ensure_configured()
    except DeepSeekConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service is not configured.",
        ) from error
    except DeepSeekClientError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chat service could not complete the request.",
        ) from error

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async for text_delta in stream_inventory_agent(request.message, session, model):
                yield _sse_event({"type": "delta", "text": text_delta})
            yield _sse_event({"type": "done"})
        except (DeepSeekConfigurationError, DeepSeekClientError, AgentLoopError):
            # HTTP headers are already committed here, so report only a fixed safe event.
            yield _sse_event({"type": "error", "message": "Chat service could not complete the request."})
        except asyncio.CancelledError:
            raise
        except Exception:
            yield _sse_event({"type": "error", "message": "Chat service could not complete the request."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_event(payload: dict[str, str]) -> bytes:
    """Encode one JSON SSE data frame, terminated by the required blank line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@app.get(
    "/data/warehouses",
    response_model=list[WarehouseResponse],
    tags=["warehouses"],
    summary="List fictional showcase warehouses",
    description="Returns read-only warehouse records from the current synthetic showcase batch.",
)
def get_warehouses(session: Session = Depends(get_session)) -> list[WarehouseResponse]:
    """List the project's fictional demo warehouses in display order."""
    return [WarehouseResponse(**row) for row in query_warehouses(session)]


@app.get(
    "/data/inventory",
    response_model=InventoryResponse,
    response_model_exclude_none=True,
    tags=["inventory"],
    summary="Query stock for one warehouse and SKU",
    description=(
        "Read-only lookup. Unknown warehouse or SKU codes return 404. Known codes "
        "without balance/in-transit rows return zero quantities and no locations. "
        "Available = good_on_hand - allocated - frozen; in_transit is separate."
    ),
    responses={404: {"description": "Warehouse code or SKU code was not found."}},
)
def get_inventory(
    warehouse_code: str = Query(
        min_length=1,
        max_length=50,
        description="Exact synthetic warehouse code, such as DEMO-WH-01.",
    ),
    sku_code: str = Query(
        min_length=1,
        max_length=80,
        description="Exact synthetic SKU code, such as DEMO-SKU-001.",
    ),
    session: Session = Depends(get_session),
) -> InventoryResponse:
    """Return one warehouse/SKU stock summary and its recorded location rows."""
    try:
        result = query_inventory(session, warehouse_code, sku_code)
    except InventoryNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return InventoryResponse(**result)


@app.get(
    "/data/orders/{order_no}",
    response_model=OrderResponse,
    tags=["orders"],
    summary="Read one synthetic order and its recorded evidence",
    description=(
        "Returns stored status, line items, exceptions, and tracking events. "
        "Timestamps are UTC; missing evidence is not used to infer a root cause."
    ),
    responses={404: {"description": "The order number was not found."}},
)
def get_order(
    order_no: str = PathParameter(..., description="Synthetic business order number."),
    session: Session = Depends(get_session),
) -> OrderResponse:
    """Return a stored order snapshot without interpreting its workflow state."""
    try:
        result = query_order(session, order_no)
    except OrderNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return OrderResponse(**result)


@app.get(
    "/health/ready",
    tags=["health"],
    summary="Check database readiness",
    responses={503: {"description": "The database health query failed."}},
)
def readiness_check() -> JSONResponse:
    """Check database connectivity using a non-mutating SELECT 1."""
    try:
        check_database_connection()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable"},
        )
    return JSONResponse(content={"status": "ready"})
