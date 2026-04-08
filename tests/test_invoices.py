"""
Tests for the Invoices API  (/api/v1/invoices).

Coverage:
  - POST /api/v1/invoices/create-from-order: success (201), duplicate (409),
    order not found (404), cancelled order (409), order → COMPLETED after invoice
  - GET  /api/v1/invoices: paginated list (200)
  - GET  /api/v1/invoices/{id}: existing (200), non-existent (404)
  - BillingSystemClient.push_invoice is mocked — no real HTTP calls
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

API_KEY_HEADER = {"X-API-Key": "test-api-key"}

DUE_DATE = (date.today() + timedelta(days=30)).isoformat()

# ── Helpers ──────────────────────────────────────────────────────────────────

VALID_ORDER_PAYLOAD = {
    "external_order_id": "INV-TEST-ORDER-001",
    "customer_name": "Acme Corporation",
    "customer_email": "billing@acme.com",
    "customer_tax_id": "ES-B12345678",
    "shipping_address": "Calle Gran Vía 28, 28013 Madrid, Spain",
    "currency": "EUR",
    "notes": "Priority shipment",
    "items": [
        {
            "sku": "WIDGET-BLUE-L",
            "name": "Blue Widget Large",
            "quantity": 3,
            "unit_price": 29.99,
            "tax_rate": 0.21,
        },
        {
            "sku": "GADGET-PRO",
            "name": "Gadget Pro",
            "quantity": 1,
            "unit_price": 149.95,
            "tax_rate": 0.21,
        },
    ],
}


async def _create_order(client: AsyncClient, external_id: str) -> dict:
    """Create an order and return its JSON."""
    payload = {**VALID_ORDER_PAYLOAD, "external_order_id": external_id}
    resp = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_invoice(client: AsyncClient, order_id: str) -> tuple[dict, int]:
    """Create an invoice from an order and return (json, status_code)."""
    resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": order_id, "due_date": DUE_DATE, "notes": "Net 30"},
        headers=API_KEY_HEADER,
    )
    return resp.json(), resp.status_code


# ── Create invoice ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_invoice_from_order(client: AsyncClient):
    """POST /api/v1/invoices/create-from-order → 201 with invoice_number."""
    order = await _create_order(client, "INV-CREATE-001")

    data, status = await _create_invoice(client, order["id"])

    assert status == 201
    assert "invoice_number" in data
    assert data["invoice_number"].startswith("INV-")
    assert data["order_id"] == order["id"]
    assert data["status"] in ("draft", "issued")


@pytest.mark.asyncio
async def test_create_invoice_sets_order_completed(client: AsyncClient):
    """After invoice creation the order status must be 'completed'."""
    order = await _create_order(client, "INV-COMPLETED-001")
    assert order["status"] == "pending"

    data, status = await _create_invoice(client, order["id"])
    assert status == 201

    order_resp = await client.get(
        f"/api/v1/orders/{order['id']}", headers=API_KEY_HEADER
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_create_invoice_duplicate(client: AsyncClient):
    """Invoicing the same order twice → 409 on second call."""
    order = await _create_order(client, "INV-IDEMPOTENT-001")

    data1, status1 = await _create_invoice(client, order["id"])
    assert status1 == 201

    resp2 = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": order["id"], "due_date": DUE_DATE},
        headers=API_KEY_HEADER,
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_invoice_order_not_found(client: AsyncClient):
    """POST create-from-order with non-existent order_id → 404."""
    resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": str(uuid.uuid4()), "due_date": DUE_DATE},
        headers=API_KEY_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_invoice_cancelled_order(client: AsyncClient):
    """POST create-from-order for a cancelled order → 409."""
    order = await _create_order(client, "INV-CANCELLED-001")

    # Cancel the order first
    cancel_resp = await client.patch(
        f"/api/v1/orders/{order['id']}/cancel", headers=API_KEY_HEADER
    )
    assert cancel_resp.status_code == 200

    # Attempting to invoice a cancelled order must be rejected
    resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": order["id"], "due_date": DUE_DATE},
        headers=API_KEY_HEADER,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invoice_financial_totals(client: AsyncClient):
    """grand_total == subtotal + tax_total on the created invoice."""
    order = await _create_order(client, "INV-FINANCIALS-001")
    data, status = await _create_invoice(client, order["id"])

    assert status == 201

    subtotal = Decimal(str(data["subtotal"]))
    tax_total = Decimal(str(data["tax_total"]))
    grand_total = Decimal(str(data["grand_total"]))

    assert grand_total == subtotal + tax_total
    assert subtotal > 0
    assert tax_total > 0


@pytest.mark.asyncio
async def test_create_invoice_billing_error_returns_502(client: AsyncClient):
    """When BillingSystemClient.push_invoice raises, router returns 502."""
    from app.core.exceptions import BillingSystemError
    from app.services.invoice_service import BillingSystemClient

    order = await _create_order(client, "INV-BILLING-ERR-001")

    with patch.object(
        BillingSystemClient,
        "push_invoice",
        new_callable=AsyncMock,
        side_effect=BillingSystemError("upstream timeout"),
    ):
        resp = await client.post(
            "/api/v1/invoices/create-from-order",
            json={"order_id": order["id"], "due_date": DUE_DATE},
            headers=API_KEY_HEADER,
        )

    assert resp.status_code == 502
    assert "billing" in resp.json()["detail"].lower()


# ── List invoices ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_invoices(client: AsyncClient):
    """GET /api/v1/invoices → 200 paginated response."""
    order = await _create_order(client, "INV-LIST-001")
    await _create_invoice(client, order["id"])

    resp = await client.get("/api/v1/invoices", headers=API_KEY_HEADER)
    assert resp.status_code == 200

    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert "page" in data
    assert "page_size" in data
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


# ── Get invoice by ID ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_invoice_by_id(client: AsyncClient):
    """GET /api/v1/invoices/{id} → 200 with correct data."""
    order = await _create_order(client, "INV-GETBYID-001")
    invoice_data, status = await _create_invoice(client, order["id"])
    assert status == 201

    resp = await client.get(
        f"/api/v1/invoices/{invoice_data['id']}", headers=API_KEY_HEADER
    )
    assert resp.status_code == 200

    fetched = resp.json()
    assert fetched["id"] == invoice_data["id"]
    assert fetched["invoice_number"] == invoice_data["invoice_number"]
    assert fetched["order_id"] == order["id"]


@pytest.mark.asyncio
async def test_get_invoice_not_found(client: AsyncClient):
    """GET /api/v1/invoices/{random_uuid} → 404."""
    resp = await client.get(
        f"/api/v1/invoices/{uuid.uuid4()}", headers=API_KEY_HEADER
    )
    assert resp.status_code == 404


# ── Authentication ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_invoice_missing_api_key(client: AsyncClient):
    """POST create-from-order without API key → 403."""
    resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": str(uuid.uuid4()), "due_date": DUE_DATE},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_invoices_missing_api_key(client: AsyncClient):
    """GET /api/v1/invoices without API key → 403."""
    resp = await client.get("/api/v1/invoices")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_invoice_missing_api_key(client: AsyncClient):
    """GET /api/v1/invoices/{id} without API key → 403."""
    resp = await client.get(f"/api/v1/invoices/{uuid.uuid4()}")
    assert resp.status_code == 403
