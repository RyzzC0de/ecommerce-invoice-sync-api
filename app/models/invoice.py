"""
Invoice ORM model.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Date,
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


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    SENT = "sent"
    PAID = "paid"
    VOID = "void"
    OVERDUE = "overdue"


class Invoice(Base):
    __tablename__ = "invoices"

    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_invoice_number"),
        UniqueConstraint("order_id", name="uq_invoice_order_id"),  # 1 invoice per order
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_due_date", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── Billing details snapshot (denormalised intentionally) ─────────────────
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_address: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # ── Financials ────────────────────────────────────────────────────────────
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # ── Dates ─────────────────────────────────────────────────────────────────
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # ── External billing system reference ─────────────────────────────────────
    external_invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(
        String(20), nullable=False, default=InvoiceStatus.DRAFT
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Audit ─────────────────────────────────────────────────────────────────
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

    # ── Relationships ──────────────────────────────────────────────────────────
    order: Mapped["Order"] = relationship(back_populates="invoices")  # type: ignore[name-defined]
