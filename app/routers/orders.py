"""
Orders router: POST /orders, GET /orders, GET /orders/{id}, PATCH /orders/{id}/cancel.
All business logic is delegated to OrderService.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.security import require_api_key
from app.db.database import get_db
from app.models.order import OrderStatus
from app.schemas.order_schema import OrderCreate, OrderListResponse, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


# ── Dependency helpers ────────────────────────────────────────────────────────
def get_order_service(db: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(db)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
    description=(
        "Accepts an ecommerce order payload and persists it to the database. "
        "Returns the created order with computed financial totals."
    ),
)
@limiter.limit("10/minute")
async def create_order(
    request: Request,
    payload: OrderCreate,
    svc: OrderService = Depends(get_order_service),
    _: str = Depends(require_api_key),
) -> OrderResponse:
    try:
        return await svc.create_order(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "",
    response_model=OrderListResponse,
    summary="List orders",
    description="Returns a paginated list of orders, optionally filtered by status.",
)
async def list_orders(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
    order_status: Annotated[
        OrderStatus | None,
        Query(alias="status", description="Filter by order status"),
    ] = None,
    svc: OrderService = Depends(get_order_service),
    _: str = Depends(require_api_key),
) -> OrderListResponse:
    return await svc.list_orders(page=page, page_size=page_size, status=order_status)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get a single order",
)
async def get_order(
    order_id: uuid.UUID,
    svc: OrderService = Depends(get_order_service),
    _: str = Depends(require_api_key),
) -> OrderResponse:
    try:
        order = await svc.get_order(order_id)
        return OrderResponse.model_validate(order)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an order",
    description=(
        "Sets the order status to CANCELLED. "
        "Returns 409 if the order is already completed or cancelled."
    ),
)
async def cancel_order(
    order_id: uuid.UUID,
    svc: OrderService = Depends(get_order_service),
    _: str = Depends(require_api_key),
) -> OrderResponse:
    try:
        order = await svc.cancel_order(order_id)
        return OrderResponse.model_validate(order)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
