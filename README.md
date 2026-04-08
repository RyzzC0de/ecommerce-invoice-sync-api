<div align="center">

# Ecommerce Invoice Sync API

**Production-ready async REST API that ingests ecommerce orders, generates VAT-compliant invoices, and syncs them to an external billing system.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20async-D71F00?style=flat-square)](https://www.sqlalchemy.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Alembic](https://img.shields.io/badge/Alembic-1.14-6BA81E?style=flat-square)](https://alembic.sqlalchemy.org)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square)](https://docs.pydantic.dev)
[![Tests](https://img.shields.io/badge/tests-41%20passed-brightgreen?style=flat-square&logo=pytest)](./tests)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](./LICENSE)

</div>

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [Getting Started](#getting-started)
   - [Docker (recommended)](#docker-recommended)
   - [Local Setup](#local-setup)
6. [API Reference](#api-reference)
7. [Authentication](#authentication)
8. [Rate Limiting](#rate-limiting)
9. [Running Tests](#running-tests)
10. [Environment Variables](#environment-variables)
11. [Design Decisions](#design-decisions)
12. [Production Checklist](#production-checklist)

---

## Project Overview

This API serves as the integration layer between an ecommerce platform (Shopify, WooCommerce, a custom storefront) and an external billing/invoicing system. It exposes a clean HTTP interface that:

- **Ingests orders** from any upstream platform with full item-level VAT breakdown
- **Generates sequential invoices** (`INV-YYYYMMDD-XXXXXXXX`) snapshotting all financial data at the moment of issue
- **Syncs invoices** to an external billing system via HTTP, surfacing failures as `502 Bad Gateway` instead of silently swallowing them
- **Enforces idempotency** — duplicate orders or double-invoiced orders are rejected with `409 Conflict`
- **Guards every endpoint** behind a static API key (`X-API-Key`) designed for B2B machine-to-machine integrations
- **Throttles abusive clients** with per-IP rate limiting (60 req/min global, 10 req/min on write endpoints)

The codebase is structured for long-term maintainability: a strict service layer separates business logic from HTTP concerns, Alembic manages schema migrations, and a 41-test suite exercises every endpoint and edge case against an in-memory SQLite database — no external services required to run tests.

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com) | 0.115.6 |
| ASGI server | [Uvicorn](https://www.uvicorn.org) | 0.32.1 |
| ORM | [SQLAlchemy async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) | 2.0.36 |
| DB driver (prod) | [asyncpg](https://github.com/MagicStack/asyncpg) | 0.30.0 |
| DB driver (tests) | [aiosqlite](https://github.com/omnilib/aiosqlite) | 0.20.0 |
| Migrations | [Alembic](https://alembic.sqlalchemy.org) | 1.14.0 |
| Validation | [Pydantic v2](https://docs.pydantic.dev) | 2.10.3 |
| Settings | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | 2.6.1 |
| JWT | [python-jose](https://github.com/mpdavis/python-jose) | 3.3.0 |
| Password hashing | [passlib + bcrypt](https://passlib.readthedocs.io) | 1.7.4 |
| HTTP client | [httpx](https://www.python-httpx.org) | 0.27.2 |
| Rate limiting | [slowapi](https://github.com/laurents/slowapi) | 0.1.9 |
| Testing | [pytest-asyncio](https://pytest-asyncio.readthedocs.io) + [httpx](https://www.python-httpx.org) | 0.24.0 |
| Database (prod) | PostgreSQL | 14+ |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         External Clients                            │
│           (Ecommerce platform, B2B partner, curl, Postman)          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  HTTPS  +  X-API-Key header
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                            │
│                                                                     │
│  ┌──────────────┐   ┌────────────────────────────────────────────┐  │
│  │  Middleware  │   │               Routers                      │  │
│  │─────────────│   │  POST /api/v1/orders           (10/min)    │  │
│  │ CORS        │   │  GET  /api/v1/orders           (60/min)    │  │
│  │ Rate limit  │   │  GET  /api/v1/orders/{id}      (60/min)    │  │
│  │ Request log │   │  PATCH /api/v1/orders/{id}/cancel          │  │
│  └──────────────┘   │  POST /api/v1/invoices/create-from-order  │  │
│                     │  GET  /api/v1/invoices         (60/min)    │  │
│                     │  GET  /api/v1/invoices/{id}    (60/min)    │  │
│                     │  GET  /health                  (no auth)   │  │
│                     └───────────────────┬────────────────────────┘  │
│                                         │  Depends(get_db)          │
│                     ┌───────────────────▼────────────────────────┐  │
│                     │            Service Layer                    │  │
│                     │  OrderService    │   InvoiceService         │  │
│                     │  · create_order │   · create_from_order    │  │
│                     │  · list_orders  │   · list_invoices        │  │
│                     │  · get_order    │   · get_invoice          │  │
│                     │  · cancel_order │                          │  │
│                     │  · update_status│   BillingSystemClient    │  │
│                     └────────┬────────┴──────────┬───────────────┘  │
└──────────────────────────────┼───────────────────┼─────────────────┘
                               │  AsyncSession      │  httpx
                               ▼                    ▼
              ┌─────────────────────────┐  ┌─────────────────────────┐
              │   PostgreSQL Database   │  │  External Billing System │
              │  ┌─────────────────┐   │  │  (Stripe / Holded / etc) │
              │  │    orders       │   │  └─────────────────────────┘
              │  │    order_items  │   │
              │  │    invoices     │   │
              │  └─────────────────┘   │
              └─────────────────────────┘
```

**Request lifecycle:** Client → SlowAPI rate check → API Key validation → Router → Service → SQLAlchemy async session → PostgreSQL. On invoice creation the service additionally calls the external billing HTTP endpoint before committing.

---

## Project Structure

```
ecommerce-invoice-sync-api/
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # App factory, middleware, lifespan, routers
│   │
│   ├── core/
│   │   ├── config.py             # All settings via pydantic-settings (env vars)
│   │   ├── security.py           # API key + JWT utilities, FastAPI dependencies
│   │   ├── limiter.py            # slowapi Limiter singleton (avoids circular imports)
│   │   └── exceptions.py         # Custom exceptions (BillingSystemError)
│   │
│   ├── db/
│   │   └── database.py           # Async engine, session factory, Base, get_db dep
│   │
│   ├── models/
│   │   ├── order.py              # Order + OrderItem ORM models, OrderStatus enum
│   │   └── invoice.py            # Invoice ORM model, InvoiceStatus enum
│   │
│   ├── schemas/
│   │   ├── order_schema.py       # Pydantic v2 request/response schemas for orders
│   │   └── invoice_schema.py     # Pydantic v2 schemas for invoices
│   │
│   ├── services/
│   │   ├── order_service.py      # Order business logic: create, list, get, cancel
│   │   └── invoice_service.py    # Invoice workflow + BillingSystemClient HTTP wrapper
│   │
│   └── routers/
│       ├── orders.py             # Order endpoints (delegates entirely to OrderService)
│       └── invoices.py           # Invoice endpoints (delegates to InvoiceService)
│
├── alembic/
│   ├── env.py                    # Async Alembic env, pulls DATABASE_URL from config
│   ├── script.py.mako            # Migration file template
│   └── versions/
│       └── 0001_initial_schema.py  # Initial migration: orders, order_items, invoices
│
├── tests/
│   ├── __init__.py
│   ├── test_orders.py            # 18 tests covering all order endpoints + auth
│   ├── test_invoices.py          # 14 tests covering all invoice endpoints + 502 mock
│   ├── test_health.py            # Health check endpoint
│   └── test_security.py          # Password hashing and JWT unit tests
│
├── conftest.py                   # Async test client, SQLite engine override, fixtures
├── alembic.ini                   # Alembic configuration
├── pytest.ini                    # pytest: asyncio_mode=auto, testpaths=tests
├── requirements.txt              # All pinned dependencies
├── Dockerfile                    # Multi-stage production Docker image
├── docker-compose.yml            # PostgreSQL + API with healthcheck
└── .env.example                  # Template for environment variables
```

---

## Getting Started

### Docker (recommended)

The fastest path to a running system. No local Python or PostgreSQL setup required.

**Prerequisites:** Docker Engine 24+ and Docker Compose v2.

```bash
git clone <your-repo-url>
cd ecommerce-invoice-sync-api

# Copy and edit the environment file
cp .env.example .env
```

Edit `.env` — the only values you must change for local development:

```env
SECRET_KEY=your-random-32-char-secret-here
API_KEY=your-strong-api-key-here
```

```bash
# Start PostgreSQL + API (builds image on first run)
docker-compose up --build

# Run in background
docker-compose up --build -d
```

Once up, apply migrations and you're ready:

```bash
docker-compose exec api alembic upgrade head
```

| URL | Description |
|---|---|
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8000/health` | Health check |

---

### Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL 14+

#### 1. Clone and create virtual environment

```bash
git clone <your-repo-url>
cd ecommerce-invoice-sync-api

python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

#### 2. Configure environment

```bash
cp .env.example .env
```

Minimum required values:

```env
DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/invoice_sync
SECRET_KEY=your-random-32-char-secret          # openssl rand -hex 32
API_KEY=your-strong-api-key
BILLING_SYSTEM_MOCK=true                        # skip real billing calls in dev
```

#### 3. Create the database and run migrations

```bash
# Create the database (psql or your preferred tool)
psql -U postgres -c "CREATE DATABASE invoice_sync;"

# Apply all migrations
alembic upgrade head
```

> **Why Alembic and not `create_all`?** See [Design Decisions](#design-decisions).

#### 4. Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is live at **http://localhost:8000** — docs at **/docs**.

---

## API Reference

All endpoints except `/health` require:

```
X-API-Key: <your-api-key>
```

Missing or invalid key → `403 Forbidden`.

---

### Orders

#### `POST /api/v1/orders` — Create an order

Rate limit: **10 requests/minute per IP**

**Request body:**

```json
{
  "external_order_id": "SHOP-20240515-0042",
  "customer_name": "Acme Corporation",
  "customer_email": "billing@acme.com",
  "customer_tax_id": "ES-B12345678",
  "shipping_address": "Calle Gran Vía 28, 28013 Madrid, Spain",
  "currency": "EUR",
  "notes": "Priority shipment — deliver before Friday",
  "items": [
    {
      "sku": "WIDGET-BLUE-L",
      "name": "Blue Widget Large",
      "quantity": 3,
      "unit_price": 29.99,
      "tax_rate": 0.21
    },
    {
      "sku": "GADGET-PRO",
      "name": "Gadget Pro",
      "quantity": 1,
      "unit_price": 149.95,
      "tax_rate": 0.21
    }
  ]
}
```

**Field rules:**
- `external_order_id` — unique across all orders; duplicate → `409 Conflict`
- `customer_email` — validated as a proper email address
- `items` — at least one item required; `quantity` ≥ 1; `unit_price` > 0
- `tax_rate` — decimal between 0 and 1 (e.g. `0.21` = 21% VAT)
- `currency` — ISO 4217, 3 characters, auto-uppercased

**Response `201 Created`:**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "external_order_id": "SHOP-20240515-0042",
  "customer_name": "Acme Corporation",
  "customer_email": "billing@acme.com",
  "customer_tax_id": "ES-B12345678",
  "shipping_address": "Calle Gran Vía 28, 28013 Madrid, Spain",
  "currency": "EUR",
  "status": "pending",
  "notes": "Priority shipment — deliver before Friday",
  "subtotal": "239.92",
  "tax_total": "50.38",
  "grand_total": "290.30",
  "created_at": "2024-05-15T10:23:41.123456+00:00",
  "updated_at": "2024-05-15T10:23:41.123456+00:00",
  "items": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "sku": "WIDGET-BLUE-L",
      "name": "Blue Widget Large",
      "quantity": 3,
      "unit_price": "29.99",
      "tax_rate": "0.2100",
      "subtotal": "89.97",
      "tax_amount": "18.89",
      "total": "108.86"
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "sku": "GADGET-PRO",
      "name": "Gadget Pro",
      "quantity": 1,
      "unit_price": "149.95",
      "tax_rate": "0.2100",
      "subtotal": "149.95",
      "tax_amount": "31.49",
      "total": "181.44"
    }
  ]
}
```

**Error responses:**

| Status | Condition |
|---|---|
| `403 Forbidden` | Missing or invalid `X-API-Key` |
| `409 Conflict` | `external_order_id` already exists |
| `422 Unprocessable Entity` | Validation failure (bad email, missing field, quantity < 1) |
| `429 Too Many Requests` | Rate limit exceeded |

---

#### `GET /api/v1/orders` — List orders

Rate limit: **60 requests/minute per IP**

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer ≥ 1 | `1` | Page number |
| `page_size` | integer 1–100 | `20` | Items per page |
| `status` | string | — | Filter: `pending`, `processing`, `completed`, `cancelled`, `failed` |

```bash
# All orders, page 2
GET /api/v1/orders?page=2&page_size=10

# Only pending orders
GET /api/v1/orders?status=pending
```

**Response `200 OK`:**

```json
{
  "total": 84,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "external_order_id": "SHOP-20240515-0042",
      "customer_name": "Acme Corporation",
      "customer_email": "billing@acme.com",
      "status": "pending",
      "grand_total": "290.30",
      "created_at": "2024-05-15T10:23:41.123456+00:00",
      "..."
    }
  ]
}
```

---

#### `GET /api/v1/orders/{order_id}` — Get a single order

```bash
GET /api/v1/orders/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

**Response `200 OK`:** Full order object (same schema as create response).

**Error responses:**

| Status | Condition |
|---|---|
| `404 Not Found` | Order UUID does not exist |

---

#### `PATCH /api/v1/orders/{order_id}/cancel` — Cancel an order

Transitions an order to `cancelled` status. Safe to call on any `pending` or `processing` order.

```bash
PATCH /api/v1/orders/3fa85f64-5717-4562-b3fc-2c963f66afa6/cancel
```

**Response `200 OK`:**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "cancelled",
  "updated_at": "2024-05-15T11:05:22.456789+00:00",
  "..."
}
```

**Error responses:**

| Status | Condition |
|---|---|
| `404 Not Found` | Order UUID does not exist |
| `409 Conflict` | Order is already `completed` or `cancelled` |

---

### Invoices

#### `POST /api/v1/invoices/create-from-order` — Create invoice from order

Rate limit: **10 requests/minute per IP**

Executes the full invoice workflow atomically:
1. Validates the order exists and is not cancelled
2. Checks no invoice already exists for this order (idempotency)
3. Builds and persists the invoice with a snapshotted financial breakdown
4. Pushes the invoice to the external billing system
5. Updates the order status to `completed`

```json
{
  "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "due_date": "2024-06-15",
  "notes": "Net 30 — wire transfer only"
}
```

**Response `201 Created`:**

```json
{
  "id": "7e9e4567-e89b-12d3-a456-426614174000",
  "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "invoice_number": "INV-20240515-A3F72C91",
  "customer_name": "Acme Corporation",
  "customer_email": "billing@acme.com",
  "customer_tax_id": "ES-B12345678",
  "billing_address": "Calle Gran Vía 28, 28013 Madrid, Spain",
  "currency": "EUR",
  "subtotal": "239.92",
  "tax_total": "50.38",
  "grand_total": "290.30",
  "issue_date": "2024-05-15",
  "due_date": "2024-06-15",
  "status": "issued",
  "external_invoice_id": "EXT-AB1C2D3E4F56",
  "notes": "Net 30 — wire transfer only",
  "created_at": "2024-05-15T10:25:03.789012+00:00",
  "updated_at": "2024-05-15T10:25:03.789012+00:00"
}
```

**Error responses:**

| Status | Condition |
|---|---|
| `403 Forbidden` | Missing or invalid `X-API-Key` |
| `404 Not Found` | `order_id` does not exist |
| `409 Conflict` | Invoice already exists for this order, or order is cancelled |
| `429 Too Many Requests` | Rate limit exceeded |
| `502 Bad Gateway` | External billing system returned an error or timed out |

---

#### `GET /api/v1/invoices` — List invoices

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer ≥ 1 | `1` | Page number |
| `page_size` | integer 1–100 | `20` | Items per page |
| `status` | string | — | Filter: `draft`, `issued`, `sent`, `paid`, `void`, `overdue` |

**Response `200 OK`:**

```json
{
  "total": 31,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "7e9e4567-e89b-12d3-a456-426614174000",
      "invoice_number": "INV-20240515-A3F72C91",
      "status": "issued",
      "grand_total": "290.30",
      "issue_date": "2024-05-15",
      "due_date": "2024-06-15",
      "..."
    }
  ]
}
```

---

#### `GET /api/v1/invoices/{invoice_id}` — Get a single invoice

```bash
GET /api/v1/invoices/7e9e4567-e89b-12d3-a456-426614174000
```

**Response `200 OK`:** Full invoice object (same schema as create response).

---

### System

#### `GET /health` — Health check

No authentication required. Designed for load balancer liveness probes and container orchestration readiness checks.

**Response `200 OK`:**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected"
}
```

`status` is `"degraded"` and `database` is `"unreachable"` if PostgreSQL is unavailable. The HTTP status code remains `200` so orchestrators can distinguish application startup from a complete crash.

---

## Authentication

The API uses a **static API key** sent via the `X-API-Key` header, designed for B2B machine-to-machine integrations where a shared secret is rotated out-of-band.

```bash
curl http://localhost:8000/api/v1/orders \
  -H "X-API-Key: your-api-key"
```

The codebase also includes a full **JWT Bearer token** implementation (`create_access_token`, `decode_access_token`, `require_jwt` dependency) ready to activate on endpoints that need user-level auth rather than service-level auth.

**Missing or wrong key → `403 Forbidden`:**

```json
{
  "detail": "Invalid or missing API key."
}
```

> In production, set `API_KEY` to a minimum 32-character random string: `openssl rand -hex 32`.

---

## Rate Limiting

Rate limiting is implemented with [slowapi](https://github.com/laurents/slowapi) (Starlette/FastAPI port of Flask-Limiter) using in-process memory storage.

| Scope | Limit | Applies to |
|---|---|---|
| Global default | 60 requests / minute / IP | All endpoints |
| Write endpoints | 10 requests / minute / IP | `POST /orders`, `POST /invoices/create-from-order` |

**Exceeded limit → `429 Too Many Requests`:**

```json
{
  "error": "Rate limit exceeded: 10 per 1 minute"
}
```

The response includes a `Retry-After` header indicating when the window resets.

> For multi-instance deployments, swap the in-memory storage for a Redis backend by setting `storage_uri="redis://..."` on the `Limiter` in `app/core/limiter.py`.

---

## Running Tests

Tests run entirely against an **in-memory SQLite database** via `aiosqlite`. No PostgreSQL, no external billing service, no network calls required.

```bash
# Run all 41 tests with verbose output
pytest -v

# Run a specific test file
pytest tests/test_orders.py -v

# Run a single test
pytest tests/test_invoices.py::test_create_invoice_billing_error_returns_502 -v

# Run with coverage (requires pytest-cov)
pytest --cov=app --cov-report=term-missing
```

**Expected output:**

```
tests/test_health.py::test_health_check                                  PASSED
tests/test_invoices.py::test_create_invoice_from_order                   PASSED
tests/test_invoices.py::test_create_invoice_sets_order_completed         PASSED
tests/test_invoices.py::test_create_invoice_duplicate                    PASSED
tests/test_invoices.py::test_create_invoice_order_not_found              PASSED
tests/test_invoices.py::test_create_invoice_cancelled_order              PASSED
tests/test_invoices.py::test_invoice_financial_totals                    PASSED
tests/test_invoices.py::test_create_invoice_billing_error_returns_502    PASSED
tests/test_invoices.py::test_list_invoices                               PASSED
tests/test_invoices.py::test_get_invoice_by_id                           PASSED
tests/test_invoices.py::test_get_invoice_not_found                       PASSED
tests/test_invoices.py::test_create_invoice_missing_api_key              PASSED
tests/test_invoices.py::test_list_invoices_missing_api_key               PASSED
tests/test_invoices.py::test_get_invoice_missing_api_key                 PASSED
tests/test_orders.py::test_create_order_success                          PASSED
tests/test_orders.py::test_create_order_duplicate_external_id            PASSED
tests/test_orders.py::test_create_order_missing_fields                   PASSED
tests/test_orders.py::test_create_order_bad_email                        PASSED
tests/test_orders.py::test_create_order_quantity_less_than_1             PASSED
tests/test_orders.py::test_list_orders                                   PASSED
tests/test_orders.py::test_list_orders_filtered_by_status                PASSED
tests/test_orders.py::test_get_order_by_id                               PASSED
tests/test_orders.py::test_get_order_not_found                           PASSED
tests/test_orders.py::test_cancel_order_success                          PASSED
tests/test_orders.py::test_cancel_already_cancelled_order                PASSED
tests/test_orders.py::test_cancel_completed_order                        PASSED
tests/test_orders.py::test_cancel_nonexistent_order                      PASSED
tests/test_orders.py::test_create_order_missing_api_key                  PASSED
tests/test_orders.py::test_create_order_wrong_api_key                    PASSED
tests/test_orders.py::test_list_orders_missing_api_key                   PASSED
tests/test_orders.py::test_get_order_missing_api_key                     PASSED
tests/test_orders.py::test_cancel_order_missing_api_key                  PASSED
tests/test_security.py::test_hash_password_returns_non_empty_string      PASSED
tests/test_security.py::test_hash_password_is_not_plaintext              PASSED
tests/test_security.py::test_verify_password_correct                     PASSED
tests/test_security.py::test_verify_password_wrong                       PASSED
tests/test_security.py::test_hash_same_password_produces_different_hashes PASSED
tests/test_security.py::test_create_access_token_returns_string          PASSED
tests/test_security.py::test_decode_access_token_valid                   PASSED
tests/test_security.py::test_decode_access_token_invalid_raises_http_exception PASSED
tests/test_security.py::test_decode_access_token_tampered_raises_http_exception PASSED

======================== 41 passed in 4.96s ============================
```

**How the test infrastructure works:**

- `conftest.py` overrides `DATABASE_URL` to `sqlite+aiosqlite:///./test.db` and `BILLING_SYSTEM_MOCK=true` *before* any app code is imported, ensuring the app never touches PostgreSQL during testing
- A PostgreSQL `UUID` column type is monkey-patched to fall back to `CHAR(32)` on SQLite, so the same ORM models work across both dialects without modification
- Each test gets a fresh database: tables are created in `setup_database` and dropped after, providing full isolation
- `BillingSystemClient.push_invoice` is mocked with `unittest.mock.AsyncMock` in billing-related tests — no HTTP calls ever leave the process

---

## Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_sync` | Yes | Async PostgreSQL DSN |
| `SECRET_KEY` | `change-me-in-production` | Yes | Min 32 chars — used to sign JWTs |
| `API_KEY` | `ryzzAPIT3st` | Yes | Static B2B API key for `X-API-Key` header |
| `ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | No | JWT expiry window |
| `BILLING_SYSTEM_URL` | `https://billing.example.com/api/v1` | No | External billing endpoint |
| `BILLING_SYSTEM_API_KEY` | `external-billing-key` | No | Bearer token for billing system |
| `BILLING_SYSTEM_TIMEOUT` | `10` | No | HTTP timeout in seconds |
| `BILLING_SYSTEM_MOCK` | `false` | No | Set `true` to skip real billing calls (returns simulated ID) |
| `DB_POOL_SIZE` | `10` | No | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | No | Extra connections above pool size |
| `DB_POOL_TIMEOUT` | `30` | No | Seconds to wait for a pool connection |
| `LOG_LEVEL` | `INFO` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_JSON` | `false` | No | `true` for structured JSON logs (production) |
| `DEBUG` | `false` | No | Enables SQLAlchemy query echo |
| `ALLOWED_HOSTS` | `["*"]` | No | CORS allowed origins |

---

## Design Decisions

### Async SQLAlchemy over sync SQLAlchemy

FastAPI is built on Starlette's async core. Using a synchronous ORM with an async framework forces every database operation to be wrapped in `run_in_executor`, which burns a thread-pool slot and adds overhead. SQLAlchemy 2.0's `AsyncSession` with `asyncpg` allows the event loop to handle I/O wait natively — the same single-threaded process can serve hundreds of concurrent requests while waiting for PostgreSQL to respond.

The tradeoff is slightly more boilerplate (explicit `await`, `async with`) and a narrower ecosystem of tooling, but for an API whose primary bottleneck is I/O, it is the correct choice.

---

### Alembic over `create_all` on startup

`Base.metadata.create_all()` is convenient for prototyping but unsuitable for production for two reasons:

1. **It cannot alter existing tables.** Adding a column, changing a type, or adding an index requires either dropping and recreating the table (data loss) or writing raw SQL by hand.
2. **It is not transactional.** A failed deployment can leave the schema in a partially-applied state with no rollback path.

Alembic generates versioned migration scripts that can be reviewed in code review, applied atomically, and rolled back with `alembic downgrade -1`. Every schema change becomes a documented, auditable event in version control.

---

### Service layer pattern

No business logic lives in routers. Routers handle one thing: translating HTTP requests into service calls and HTTP responses. Services handle one thing: business logic. This separation means:

- **Testability** — services can be unit-tested without spinning up an HTTP server
- **Reusability** — `OrderService.update_status` is called by both `InvoiceService` and the cancel endpoint without code duplication
- **Clarity** — a reader can understand the full invoice creation workflow by reading `InvoiceService.create_from_order` without parsing FastAPI decorators, dependency injection chains, or Pydantic validators

---

### Idempotency on invoice creation

The constraint `UNIQUE(order_id)` on the `invoices` table, enforced at both the application layer (pre-check) and the database layer (unique constraint), ensures that calling `POST /invoices/create-from-order` twice for the same order is safe. The second call returns `409 Conflict` with a clear message rather than creating a duplicate invoice, charging the customer twice, or producing conflicting records in the billing system.

This matters in practice: webhooks are retried, network timeouts cause clients to retry, and batch jobs sometimes process the same record twice. Idempotency makes the system correct under all of those conditions without requiring the caller to track state.

---

### Billing system errors return `502 Bad Gateway`, not silent fallback

The original implementation caught `httpx.HTTPStatusError` and `httpx.RequestError`, logged a warning, and returned a simulated external ID as if the push had succeeded. This is a critical production bug: the invoice would be marked `issued` with a fake ID, the customer would receive a confirmation, and there would be no record of the billing system failure to act on.

The corrected behavior raises `BillingSystemError` on any HTTP or network failure, which the router converts to `502 Bad Gateway`. The database transaction is rolled back — no half-created invoice is persisted. The caller knows the operation failed and can retry, alert, or queue for manual processing.

The simulated fallback is preserved behind `BILLING_SYSTEM_MOCK=true`, explicitly scoped to development and testing environments where a real billing endpoint is unavailable.

---

## Production Checklist

- [ ] Generate a strong `SECRET_KEY`: `openssl rand -hex 32`
- [ ] Generate a strong `API_KEY`: `openssl rand -hex 24`
- [ ] Set `DEBUG=false` and `LOG_JSON=true`
- [ ] Set `BILLING_SYSTEM_MOCK=false` and configure `BILLING_SYSTEM_URL` + `BILLING_SYSTEM_API_KEY`
- [ ] Set `ALLOWED_HOSTS` to your specific domain(s) — not `["*"]`
- [ ] Apply migrations before deploying: `alembic upgrade head`
- [ ] Deploy behind a TLS-terminating reverse proxy (nginx, Traefik, AWS ALB)
- [ ] Size `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` based on your database instance limits
- [ ] Wire `/health` to your load balancer's health check
- [ ] Set up log aggregation (Datadog, Grafana Loki, AWS CloudWatch) to capture JSON logs
- [ ] Configure alerting on `502` responses from `POST /invoices/create-from-order`
- [ ] For multi-instance deployments, configure a Redis backend for slowapi rate limiting

---

## License

MIT © 2024
