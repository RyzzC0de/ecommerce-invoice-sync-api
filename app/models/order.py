"""
Order ORM model and Pydantic schemas.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import List

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────
class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ── ORM models ────────────────────────────────────────────────────────────────
class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.21")
    )

    # Back-reference
    order: Mapped["Order"] = relationship(back_populates="items")

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def tax_amount(self) -> Decimal:
        return self.subtotal * self.tax_rate

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax_amount


class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        UniqueConstraint("external_order_id", name="uq_external_order_id"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    status: Mapped[OrderStatus] = mapped_column(
        String(20), nullable=False, default=OrderStatus.PENDING
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    invoices: Mapped[List["Invoice"]] = relationship(  # type: ignore[name-defined]
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def subtotal(self) -> Decimal:
        return sum(i.subtotal for i in self.items)

    @property
    def tax_total(self) -> Decimal:
        return sum(i.tax_amount for i in self.items)

    @property
    def grand_total(self) -> Decimal:
        return sum(i.total for i in self.items)
