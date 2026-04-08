"""
Pydantic schemas for Invoice requests and responses.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.invoice import InvoiceStatus


class InvoiceCreateFromOrder(BaseModel):
    order_id: uuid.UUID = Field(..., description="UUID of the order to invoice.")
    due_date: date = Field(..., description="Payment due date for the invoice.")
    notes: str | None = Field(default=None, max_length=1000)


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    invoice_number: str
    customer_name: str
    customer_email: str
    customer_tax_id: str | None
    billing_address: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    issue_date: date
    due_date: date
    status: InvoiceStatus
    external_invoice_id: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[InvoiceResponse]
