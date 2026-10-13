from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderException, OrderItem, OrderTrackingEvent, SKU, Warehouse


def _as_utc(value):
    """Treat naive fixture timestamps as UTC and normalize aware timestamps."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class OrderNotFoundError(Exception):
    """Raised when the requested synthetic order number is not present."""


def query_order(session: Session, order_no: str) -> dict:
    """Return a read-only order snapshot with ordered items and recorded evidence.

    Exception and tracking rows are ordered by timestamp then ID; item rows are
    ordered by line number. All timestamps are normalized to UTC. The repository
    reports stored status, exceptions, and events without inferring a root cause.
    """
    order = session.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise OrderNotFoundError("Order not found.")

    warehouse = session.get(Warehouse, order.warehouse_id) if order.warehouse_id is not None else None
    exceptions = session.scalars(
        select(OrderException)
        .where(OrderException.order_id == order.id)
        .order_by(OrderException.occurred_at, OrderException.id)
    ).all()
    events = session.scalars(
        select(OrderTrackingEvent)
        .where(OrderTrackingEvent.order_id == order.id)
        .order_by(OrderTrackingEvent.occurred_at, OrderTrackingEvent.id)
    ).all()
    items = session.execute(
        select(OrderItem, SKU)
        .join(SKU, OrderItem.sku_id == SKU.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.line_no)
    ).all()

    return {
        "order_no": order.order_no,
        "status_code": order.status_code,
        "status_text": order.status_text,
        "created_at": _as_utc(order.created_at),
        "status_updated_at": _as_utc(order.status_updated_at),
        "warehouse": None if warehouse is None else {
            "code": warehouse.code,
            "name": warehouse.name,
            "name_en": warehouse.name_en,
            "region": warehouse.region,
            "region_cn": warehouse.region_cn,
            "country": warehouse.country,
            "country_cn": warehouse.country_cn,
            "city": warehouse.city,
            "city_cn": warehouse.city_cn,
        },
        "items": [
            {
                "line_no": item.line_no,
                "sku_code": sku.code,
                "sku_name": sku.name,
                "sku_name_en": sku.name_en,
                "category_code": sku.category_code,
                "category_name": sku.category_name,
                "category_name_en": sku.category_name_en,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "currency": item.currency,
                "is_hazmat": sku.is_hazmat,
                "hazmat_class": sku.hazmat_class,
                "un_number": sku.un_number,
                "is_oversized": sku.is_oversized,
            }
            for item, sku in items
        ],
        "exceptions": [
            {
                "code": exception.code,
                "detail": exception.detail,
                "active": exception.active,
                "occurred_at": _as_utc(exception.occurred_at),
            }
            for exception in exceptions
        ],
        "tracking_events": [
            {
                "event_type": event.event_type,
                "detail": event.detail,
                "location": event.location,
                "carrier": event.carrier,
                "tracking_no": event.tracking_no,
                "occurred_at": _as_utc(event.occurred_at),
            }
            for event in events
        ],
    }
