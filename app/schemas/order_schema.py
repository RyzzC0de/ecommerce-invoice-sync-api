"""
Pydantic schemas for Order requests and responses.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.order import OrderStatus


# ── Item schemas ──────────────────────────────────────────────────────────────
class OrderItemCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100, examples=["SKU-001"])
    name: str = Field(..., min_length=1, max_length=255, examples=["Blue Widget"])
    quantity: int = Field(..., ge=1, examples=[2])
    unit_price: Decimal = Field(..., gt=0, decimal_places=2, examples=[29.99])
    tax_rate: Decimal = Field(
        default=Decimal("0.21"),
        ge=0,
        le=1,
        decimal_places=4,
        description="Tax rate as a decimal (e.g. 0.21 for 21% VAT)",
        examples=[0.21],
    )


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    tax_rate: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal

    model_config = {"from_attributes": True}


# ── Order schemas ─────────────────────────────────────────────────────────────
class OrderCreate(BaseModel):
    external_order_id: str = Field(
        ..., min_length=1, max_length=100, examples=["SHOP-20240101-0001"]
    )
    customer_name: str = Field(..., min_length=1, max_length=255, examples=["Acme Corp"])
    customer_email: EmailStr = Field(..., examples=["billing@acme.com"])
    customer_tax_id: str | None = Field(
        default=None, max_length=50, examples=["ES-B12345678"]
    )
    shipping_address: str = Field(
        ..., min_length=5, examples=["Calle Mayor 1, 28001 Madrid, Spain"]
    )
    currency: str = Field(
        default="EUR", min_length=3, max_length=3, examples=["EUR"]
    )
    notes: str | None = Field(default=None, max_length=1000)
    items: List[OrderItemCreate] = Field(..., min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()


class OrderResponse(BaseModel):
    id: uuid.UUID
    external_order_id: str
    customer_name: str
    customer_email: str
    customer_tax_id: str | None
    shipping_address: str
    currency: str
    status: OrderStatus
    notes: str | None
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[OrderResponse]
