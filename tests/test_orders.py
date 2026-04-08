"""
Tests for the Orders API  (/api/v1/orders).

Coverage:
  - POST /api/v1/orders: success (201), duplicate external_order_id (409),
    invalid payload (422)
  - GET  /api/v1/orders: paginated list (200), filtered by status
  - GET  /api/v1/orders/{id}: existing (200), non-existent (404)
  - PATCH /api/v1/orders/{id}/cancel: success, already completed/cancelled (409)
  - All authenticated endpoints: 403 on missing / wrong API key
"""

import uuid

import pytest
from httpx import AsyncClient

API_KEY_HEADER = {"X-API-Key": "test-api-key"}
BAD_KEY_HEADER = {"X-API-Key": "wrong-key"}

# ── Helpers ──────────────────────────────────────────────────────────────────

VALID_ORDER_PAYLOAD = {
    "external_order_id": "SHOP-20240101-0001",
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


def _make_order_payload(**overrides) -> dict:
    """Return a deep copy of the valid payload with optional field overrides."""
    payload = {**VALID_ORDER_PAYLOAD, **overrides}
    return payload


# ── Create order ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_order_success(client: AsyncClient):
    """POST /api/v1/orders → 201 with correct financial totals."""
    resp = await client.post(
        "/api/v1/orders",
        json=VALID_ORDER_PAYLOAD,
        headers=API_KEY_HEADER,
    )

    assert resp.status_code == 201
    data = resp.json()

    assert data["external_order_id"] == "SHOP-20240101-0001"
    assert data["status"] == "pending"
    assert "id" in data

    from decimal import Decimal

    subtotal = Decimal(str(data["subtotal"]))
    tax_total = Decimal(str(data["tax_total"]))
    grand_total = Decimal(str(data["grand_total"]))

    assert grand_total == subtotal + tax_total
    assert subtotal > 0
    assert tax_total > 0


@pytest.mark.asyncio
async def test_create_order_duplicate_external_id(client: AsyncClient):
    """POST /api/v1/orders with duplicate external_order_id → 409."""
    payload = _make_order_payload(external_order_id="DUPLICATE-001")
    resp1 = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_order_missing_fields(client: AsyncClient):
    """POST /api/v1/orders with empty body → 422."""
    resp = await client.post("/api/v1/orders", json={}, headers=API_KEY_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_order_bad_email(client: AsyncClient):
    """POST /api/v1/orders with invalid email → 422."""
    payload = _make_order_payload(
        external_order_id="BAD-EMAIL-001", customer_email="not-an-email"
    )
    resp = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_order_quantity_less_than_1(client: AsyncClient):
    """POST /api/v1/orders with item quantity=0 → 422."""
    payload = _make_order_payload(external_order_id="BAD-QTY-001")
    payload["items"] = [
        {
            "sku": "BAD-ITEM",
            "name": "Bad Item",
            "quantity": 0,  # invalid
            "unit_price": 9.99,
            "tax_rate": 0.21,
        }
    ]
    resp = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp.status_code == 422


# ── List orders ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_orders(client: AsyncClient):
    """GET /api/v1/orders → paginated response with expected fields."""
    await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="LIST-001"),
        headers=API_KEY_HEADER,
    )
    await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="LIST-002"),
        headers=API_KEY_HEADER,
    )

    resp = await client.get("/api/v1/orders", headers=API_KEY_HEADER)
    assert resp.status_code == 200

    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert "page" in data
    assert "page_size" in data
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


@pytest.mark.asyncio
async def test_list_orders_filtered_by_status(client: AsyncClient):
    """GET /api/v1/orders?status=pending → only pending orders returned."""
    await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="FILTER-001"),
        headers=API_KEY_HEADER,
    )

    resp = await client.get(
        "/api/v1/orders?status=pending", headers=API_KEY_HEADER
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for item in data["items"]:
        assert item["status"] == "pending"


# ── Get order by ID ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_order_by_id(client: AsyncClient):
    """Create order → GET /api/v1/orders/{id} returns same data."""
    create_resp = await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="GET-BY-ID-001"),
        headers=API_KEY_HEADER,
    )
    assert create_resp.status_code == 201
    created = create_resp.json()

    get_resp = await client.get(
        f"/api/v1/orders/{created['id']}", headers=API_KEY_HEADER
    )
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    assert fetched["id"] == created["id"]
    assert fetched["external_order_id"] == created["external_order_id"]
    assert fetched["grand_total"] == created["grand_total"]


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient):
    """GET /api/v1/orders/{random_uuid} → 404."""
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/orders/{random_id}", headers=API_KEY_HEADER)
    assert resp.status_code == 404


# ── Cancel order ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_order_success(client: AsyncClient):
    """PATCH /api/v1/orders/{id}/cancel → 200, status becomes cancelled."""
    create_resp = await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="CANCEL-001"),
        headers=API_KEY_HEADER,
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    cancel_resp = await client.patch(
        f"/api/v1/orders/{order_id}/cancel", headers=API_KEY_HEADER
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_order(client: AsyncClient):
    """Cancelling an already-cancelled order → 409."""
    create_resp = await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="CANCEL-TWICE-001"),
        headers=API_KEY_HEADER,
    )
    order_id = create_resp.json()["id"]

    await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=API_KEY_HEADER)

    resp = await client.patch(
        f"/api/v1/orders/{order_id}/cancel", headers=API_KEY_HEADER
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_completed_order(client: AsyncClient):
    """Cancelling a completed order → 409."""
    from datetime import date, timedelta

    create_resp = await client.post(
        "/api/v1/orders",
        json=_make_order_payload(external_order_id="CANCEL-COMPLETED-001"),
        headers=API_KEY_HEADER,
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    # Create invoice to move order to COMPLETED
    due_date = (date.today() + timedelta(days=30)).isoformat()
    inv_resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": order_id, "due_date": due_date},
        headers=API_KEY_HEADER,
    )
    assert inv_resp.status_code == 201

    cancel_resp = await client.patch(
        f"/api/v1/orders/{order_id}/cancel", headers=API_KEY_HEADER
    )
    assert cancel_resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_nonexistent_order(client: AsyncClient):
    """PATCH /api/v1/orders/{random_uuid}/cancel → 404."""
    resp = await client.patch(
        f"/api/v1/orders/{uuid.uuid4()}/cancel", headers=API_KEY_HEADER
    )
    assert resp.status_code == 404


# ── Authentication ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_order_missing_api_key(client: AsyncClient):
    """POST /api/v1/orders without X-API-Key → 403."""
    resp = await client.post("/api/v1/orders", json=VALID_ORDER_PAYLOAD)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_order_wrong_api_key(client: AsyncClient):
    """POST /api/v1/orders with wrong X-API-Key → 403."""
    resp = await client.post(
        "/api/v1/orders", json=VALID_ORDER_PAYLOAD, headers=BAD_KEY_HEADER
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_orders_missing_api_key(client: AsyncClient):
    """GET /api/v1/orders without X-API-Key → 403."""
    resp = await client.get("/api/v1/orders")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_order_missing_api_key(client: AsyncClient):
    """GET /api/v1/orders/{id} without X-API-Key → 403."""
    resp = await client.get(f"/api/v1/orders/{uuid.uuid4()}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_order_missing_api_key(client: AsyncClient):
    """PATCH /api/v1/orders/{id}/cancel without X-API-Key → 403."""
    resp = await client.patch(f"/api/v1/orders/{uuid.uuid4()}/cancel")
    assert resp.status_code == 403
