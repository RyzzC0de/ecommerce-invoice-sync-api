"""
Order service: encapsulates all business logic related to orders.
Routers never touch the DB directly — they delegate to this service.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order_schema import OrderCreate, OrderListResponse, OrderResponse

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────
    async def create_order(self, payload: OrderCreate) -> OrderResponse:
        """
        Persist a new order with its items.
        Raises ValueError if external_order_id already exists.
        """
        logger.info(
            "Creating order external_id=%s customer=%s",
            payload.external_order_id,
            payload.customer_email,
        )

        order = Order(
            external_order_id=payload.external_order_id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_tax_id=payload.customer_tax_id,
            shipping_address=payload.shipping_address,
            currency=payload.currency,
            notes=payload.notes,
            status=OrderStatus.PENDING,
        )

        for item_data in payload.items:
            order.items.append(
                OrderItem(
                    sku=item_data.sku,
                    name=item_data.name,
                    quantity=item_data.quantity,
                    unit_price=item_data.unit_price,
                    tax_rate=item_data.tax_rate,
                )
            )

        self._db.add(order)
        try:
            await self._db.flush()  # get generated ID before commit
        except IntegrityError:
            await self._db.rollback()
            raise ValueError(
                f"Order with external_order_id='{payload.external_order_id}' already exists."
            )

        await self._db.refresh(order)
        logger.info("Order created id=%s", order.id)
        return OrderResponse.model_validate(order)

    # ── List ──────────────────────────────────────────────────────────────────
    async def list_orders(
        self,
        page: int = 1,
        page_size: int = 20,
        status: OrderStatus | None = None,
    ) -> OrderListResponse:
        """
        Return a paginated list of orders, optionally filtered by status.
        """
        offset = (page - 1) * page_size

        # Build base query
        base_q = select(Order)
        count_q = select(func.count()).select_from(Order)
        if status:
            base_q = base_q.where(Order.status == status)
            count_q = count_q.where(Order.status == status)

        count_result = await self._db.execute(count_q)
        total: int = count_result.scalar_one()

        result = await self._db.execute(
            base_q.order_by(Order.created_at.desc()).offset(offset).limit(page_size)
        )
        orders = result.scalars().all()

        return OrderListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[OrderResponse.model_validate(o) for o in orders],
        )

    # ── Get by ID ─────────────────────────────────────────────────────────────
    async def get_order(self, order_id: uuid.UUID) -> Order:
        """
        Fetch a single order by PK.
        Raises LookupError if not found.
        """
        result = await self._db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            raise LookupError(f"Order '{order_id}' not found.")
        return order

    # ── Update status ─────────────────────────────────────────────────────────
    async def update_status(self, order_id: uuid.UUID, new_status: OrderStatus) -> Order:
        order = await self.get_order(order_id)
        order.status = new_status
        await self._db.flush()
        # Commit is handled by the get_db dependency on request completion.
        await self._db.refresh(order)
        logger.info("Order %s status → %s", order_id, new_status)
        return order

    # ── Cancel ────────────────────────────────────────────────────────────────
    async def cancel_order(self, order_id: uuid.UUID) -> Order:
        """
        Set order status to CANCELLED.
        Raises ValueError if already completed or cancelled.
        Raises LookupError if the order does not exist.
        """
        order = await self.get_order(order_id)
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise ValueError(
                f"Cannot cancel order '{order_id}': current status is '{order.status}'."
            )
        return await self.update_status(order_id, OrderStatus.CANCELLED)
