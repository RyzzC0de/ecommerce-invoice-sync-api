# Ecommerce Invoice Sync API

**Production-ready async REST API that ingests ecommerce orders, generates VAT-compliant invoices, syncs them to an external billing system, delivers PDF invoices by email, and emits signed webhook events.**

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
- **Renders PDF invoices** using WeasyPrint (Linux/Docker) or ReportLab as a pure-Python fallback (Windows), returned via a dedicated download endpoint
- **Delivers invoices by email** via the Resend API, with the PDF attached
- **Emits signed webhook events** (`invoice.created`) with HMAC-SHA256 signatures so receivers can verify authenticity
- **Syncs invoices** to an external billing system via HTTP, surfacing failures as `502 Bad Gateway` instead of silently swallowing them
- **Enforces idempotency** — duplicate orders or double-invoiced orders are rejected with `409 Conflict`
- **Guards every endpoint** behind a static API key (`X-API-Key`) designed for B2B machine-to-machine integrations
- **Throttles abusive clients** with per-IP rate limiting (60 req/min global, 10 req/min on write endpoints)

The codebase is structured for long-term maintainability: a strict service layer separates business logic from HTTP concerns, Alembic manages schema migrations, and a 64-test suite exercises every endpoint and edge case against an in-memory SQLite database — no external services required to run tests.

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
| PDF (primary) | [WeasyPrint](https://weasyprint.org) | 62.3 |
| PDF (fallback) | [ReportLab](https://www.reportlab.com) | 4.2.5 |
| Template engine | [Jinja2](https://jinja.palletsprojects.com) | 3.1.4 |
| Email delivery | [Resend Python SDK](https://resend.com/docs/send-with-python) | 2.4.0 |
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
│                     │  GET  /api/v1/invoices/{id}/pdf (60/min)   │  │
│                     │  GET  /health                  (no auth)   │  │
│                     └───────────────────┬────────────────────────┘  │
│                                         │  Depends(get_db)          │
│                     ┌───────────────────▼────────────────────────┐  │
│                     │            Service Layer                    │  │
│                     │  OrderService    │   InvoiceService         │  │
│                     │  · create_order │   · create_from_order    │  │
│                     │  · list_orders  │   · list_invoices        │  │
│                     │  · get_order    │   · get_invoice          │  │
│                     │  · cancel_order │   · get_invoice_pdf      │  │
│                     │  · update_status│                          │  │
│                     └────────┬────────┴──────────┬───────────────┘  │
│                              │                   │                  │
│              ┌───────────────┘     ┌─────────────┼──────────────┐  │
│              │ AsyncSession        │  BillingSystemClient (httpx)│  │
│              │                    │  PDFService (WeasyPrint/RL)  │  │
│              │                    │  EmailService (Resend SDK)   │  │
│              │                    │  WebhookService (HMAC POST)  │  │
└──────────────┼────────────────────┴──────────────────────────────┘  │
               ▼                                                        
┌─────────────────────┐   ┌─────────────────┐   ┌──────────────────┐
│  PostgreSQL (prod)  │   │  Billing System │   │  Webhook receiver│
│  orders             │   │  (Stripe/Holded)│   │  (your endpoint) │
│  order_items        │   └─────────────────┘   └──────────────────┘
│  invoices           │   ┌─────────────────┐
└─────────────────────┘   │  Resend API     │
                          │  (email + PDF)  │
                          └─────────────────┘
```

**Invoice creation lifecycle:**
1. Validate order exists and is not cancelled
2. Idempotency check — reject if invoice already exists
3. Persist invoice in `DRAFT` status
4. Push to external billing system → `502` on failure (transaction rolled back)
5. Generate PDF (WeasyPrint on Linux, ReportLab on Windows)
6. Send email with PDF attachment via Resend
7. Dispatch signed `invoice.created` webhook (failure is logged, never propagated)
8. Update order status → `COMPLETED`

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
│   │   ├── invoice_service.py    # Invoice workflow + BillingSystemClient HTTP wrapper
│   │   ├── pdf_service.py        # PDF generation: WeasyPrint (Linux) / ReportLab (Windows)
│   │   ├── email_service.py      # Email delivery via Resend SDK (PDF attachment)
│   │   └── webhook_service.py    # HMAC-SHA256 signed webhook dispatch
│   │
│   ├── templates/
│   │   └── invoice.html          # Jinja2 invoice template (WeasyPrint path)
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
│   ├── test_orders.py            # 18 tests — all order endpoints + auth
│   ├── test_invoices.py          # 14 tests — all invoice endpoints + 502 mock
│   ├── test_health.py            # 1 test  — health check
│   ├── test_security.py          # 8 tests  — password hashing and JWT
│   └── test_pdf_email_webhook.py # 23 tests — PDF template, email, webhook, PDF endpoint
│
├── conftest.py                   # Async test client, SQLite override, autouse service mocks
├── alembic.ini                   # Alembic configuration
├── pytest.ini                    # asyncio_mode=auto, testpaths=tests
├── requirements.txt              # All pinned dependencies
├── Dockerfile                    # Multi-stage production Docker image
├── docker-compose.yml            # PostgreSQL + API with healthcheck
├── .env.example                  # Template for all environment variables
└── .gitignore
```

---

## Getting Started

### Docker (recommended)

The fastest path to a running system. No local Python or PostgreSQL setup required.

**Prerequisites:** Docker Engine 24+ and Docker Compose v2.

```bash
git clone <your-repo-url>
cd ecommerce-invoice-sync-api

cp .env.example .env
```

Edit `.env` — minimum values to change for local development:

```env
SECRET_KEY=your-random-32-char-secret      # openssl rand -hex 32
API_KEY=your-strong-api-key                # openssl rand -hex 24
BILLING_SYSTEM_MOCK=true
EMAIL_MOCK=true
WEBHOOK_MOCK=true
```

```bash
# Build and start PostgreSQL + API
docker-compose up --build

# Apply migrations (first run only)
docker-compose exec api alembic upgrade head
```

| URL | Description |
|---|---|
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8000/health` | Health check |

> **Note:** WeasyPrint (the primary PDF engine) works out of the box in Docker because the image includes the required GTK/Cairo/Pango system libraries. On Windows, the API automatically falls back to ReportLab.

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
SECRET_KEY=your-random-32-char-secret        # openssl rand -hex 32
API_KEY=your-strong-api-key
BILLING_SYSTEM_MOCK=true                     # skip real billing calls in dev
EMAIL_MOCK=true                              # skip real email delivery in dev
WEBHOOK_MOCK=true                            # skip real webhook dispatch in dev
```

#### 3. Create the database and run migrations

```bash
psql -U postgres -c "CREATE DATABASE invoice_sync;"
alembic upgrade head
```

> **Why Alembic and not `create_all`?** See [Design Decisions](#alembic-over-create_all-on-startup).

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
  "items": [...]
}
```

| Status | Condition |
|---|---|
| `403 Forbidden` | Missing or invalid `X-API-Key` |
| `409 Conflict` | `external_order_id` already exists |
| `422 Unprocessable Entity` | Validation failure (bad email, missing field, quantity < 1) |
| `429 Too Many Requests` | Rate limit exceeded |

---

#### `GET /api/v1/orders` — List orders

**Query parameters:** `page` (default 1), `page_size` (default 20, max 100), `status` filter.

```bash
GET /api/v1/orders?page=2&page_size=10&status=pending
```

**Response `200 OK`:** `{ total, page, page_size, items: [...] }`

---

#### `GET /api/v1/orders/{order_id}` — Get a single order

**Response `200 OK`:** Full order object. `404` if not found.

---

#### `PATCH /api/v1/orders/{order_id}/cancel` — Cancel an order

Transitions an order to `cancelled` status. Safe to call on any `pending` or `processing` order.

**Response `200 OK`:** Updated order object with `"status": "cancelled"`.

| Status | Condition |
|---|---|
| `404 Not Found` | Order UUID does not exist |
| `409 Conflict` | Order is already `completed` or `cancelled` |

---

### Invoices

#### `POST /api/v1/invoices/create-from-order` — Create invoice from order

Rate limit: **10 requests/minute per IP**

Executes the full invoice workflow:
1. Validates order exists and is not cancelled
2. Idempotency check (unique constraint per order)
3. Persists invoice in `DRAFT` status
4. Pushes to external billing system → `502` on failure
5. Generates PDF (WeasyPrint/ReportLab)
6. Sends email with PDF attachment via Resend
7. Dispatches signed `invoice.created` webhook
8. Updates order status → `completed`

**Request body:**

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

| Status | Condition |
|---|---|
| `403 Forbidden` | Missing or invalid `X-API-Key` |
| `404 Not Found` | `order_id` does not exist |
| `409 Conflict` | Invoice already exists for this order, or order is cancelled |
| `429 Too Many Requests` | Rate limit exceeded |
| `502 Bad Gateway` | External billing system returned an error or timed out |

---

#### `GET /api/v1/invoices` — List invoices

**Query parameters:** `page`, `page_size`, `status` (draft, issued, sent, paid, void, overdue).

**Response `200 OK`:** `{ total, page, page_size, items: [...] }`

---

#### `GET /api/v1/invoices/{invoice_id}` — Get a single invoice

**Response `200 OK`:** Full invoice object. `404` if not found.

---

#### `GET /api/v1/invoices/{invoice_id}/pdf` — Download invoice PDF

Returns the invoice rendered as a PDF file download. The PDF engine is selected automatically at runtime: WeasyPrint on Linux/Docker (requires system GTK libraries), ReportLab on Windows or any environment without GTK.

```bash
curl http://localhost:8000/api/v1/invoices/7e9e4567-e89b-12d3-a456-426614174000/pdf \
  -H "X-API-Key: your-api-key" \
  --output invoice.pdf
```

**Response `200 OK`:**

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="INV-20240515-A3F72C91.pdf"
```

| Status | Condition |
|---|---|
| `403 Forbidden` | Missing or invalid `X-API-Key` |
| `404 Not Found` | Invoice UUID does not exist |

---

### System

#### `GET /health` — Health check

No authentication required. Designed for load balancer liveness probes.

**Response `200 OK`:**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected"
}
```

`status` becomes `"degraded"` and `database` becomes `"unreachable"` if PostgreSQL is unavailable. The HTTP status code remains `200` so orchestrators can distinguish application startup from a complete crash.

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
{ "detail": "Invalid or missing API key." }
```

> In production, set `API_KEY` to a minimum 32-character random string: `openssl rand -hex 24`.

---

## Rate Limiting

Rate limiting is implemented with [slowapi](https://github.com/laurents/slowapi) (Starlette/FastAPI port of Flask-Limiter) using in-process memory storage.

| Scope | Limit | Applies to |
|---|---|---|
| Global default | 60 requests / minute / IP | All endpoints |
| Write endpoints | 10 requests / minute / IP | `POST /orders`, `POST /invoices/create-from-order` |

**Exceeded limit → `429 Too Many Requests`:**

```json
{ "error": "Rate limit exceeded: 10 per 1 minute" }
```

The response includes a `Retry-After` header indicating when the window resets.

> For multi-instance deployments, swap the in-memory storage for a Redis backend by setting `storage_uri="redis://..."` on the `Limiter` in `app/core/limiter.py`.

---

## Running Tests

Tests run entirely against an **in-memory SQLite database** via `aiosqlite`. No PostgreSQL, no external services, no network calls required. PDF generation, email delivery, and webhook dispatch are all mocked globally via autouse fixtures in `conftest.py`.

```bash
# Run all 64 tests
pytest -v

# Run a specific file
pytest tests/test_orders.py -v
pytest tests/test_pdf_email_webhook.py -v

# Run a single test
pytest tests/test_invoices.py::test_create_invoice_billing_error_returns_502 -v

# With coverage
pytest --cov=app --cov-report=term-missing
```

**Expected output:**

```
tests/test_health.py::test_health_check                                            PASSED
tests/test_invoices.py::test_create_invoice_from_order                             PASSED
tests/test_invoices.py::test_create_invoice_sets_order_completed                   PASSED
tests/test_invoices.py::test_create_invoice_duplicate                              PASSED
tests/test_invoices.py::test_create_invoice_order_not_found                        PASSED
tests/test_invoices.py::test_create_invoice_cancelled_order                        PASSED
tests/test_invoices.py::test_invoice_financial_totals                              PASSED
tests/test_invoices.py::test_create_invoice_billing_error_returns_502              PASSED
tests/test_invoices.py::test_list_invoices                                         PASSED
tests/test_invoices.py::test_get_invoice_by_id                                     PASSED
tests/test_invoices.py::test_get_invoice_not_found                                 PASSED
tests/test_invoices.py::test_create_invoice_missing_api_key                        PASSED
tests/test_invoices.py::test_list_invoices_missing_api_key                         PASSED
tests/test_invoices.py::test_get_invoice_missing_api_key                           PASSED
tests/test_orders.py::test_create_order_success                                    PASSED
...
tests/test_pdf_email_webhook.py::TestPDFServiceTemplate::test_template_renders_invoice_number   PASSED
tests/test_pdf_email_webhook.py::TestPDFServiceTemplate::test_template_renders_customer_name    PASSED
tests/test_pdf_email_webhook.py::TestEmailService::test_send_invoice_mock_mode_skips_resend     PASSED
tests/test_pdf_email_webhook.py::TestEmailService::test_send_invoice_non_mock_calls_resend      PASSED
tests/test_pdf_email_webhook.py::TestWebhookService::test_dispatch_mock_mode_skips_http         PASSED
tests/test_pdf_email_webhook.py::TestWebhookService::test_hmac_signature_is_verifiable          PASSED
tests/test_pdf_email_webhook.py::test_download_invoice_pdf_returns_pdf                          PASSED
...

======================== 64 passed in ~11s ============================
```

**How the test infrastructure works:**

- `conftest.py` overrides `DATABASE_URL` → `sqlite+aiosqlite:///./test.db`, `BILLING_SYSTEM_MOCK=true`, `EMAIL_MOCK=true`, `WEBHOOK_MOCK=true` *before* any app code is imported
- A PostgreSQL `UUID` column type is monkey-patched to fall back to `CHAR(32)` on SQLite so the same ORM models work across both dialects
- Each test gets a fresh database: tables are created before each test and dropped after, providing full isolation
- Three `autouse=True` fixtures globally mock `PDFService.generate_invoice_pdf`, `EmailService.send_invoice`, and `WebhookService.dispatch` — no PDF rendering, email calls, or HTTP webhook POSTs ever leave the process
- Unit tests for those three services bypass the autouse patches by capturing the original function objects at module import time (before fixtures run)

---

## Environment Variables

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_sync` | Yes | Async PostgreSQL DSN |
| `SECRET_KEY` | `change-me-in-production` | Yes | Min 32 chars — used to sign JWTs |
| `API_KEY` | `change-me-strong-api-key` | Yes | Static B2B API key for `X-API-Key` header |
| `ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | No | JWT expiry window |
| `BILLING_SYSTEM_URL` | `https://billing.example.com/api/v1` | Yes | External billing endpoint |
| `BILLING_SYSTEM_API_KEY` | `external-billing-key` | Yes | Bearer token for billing system |
| `BILLING_SYSTEM_TIMEOUT` | `10` | No | HTTP timeout in seconds |
| `BILLING_SYSTEM_MOCK` | `false` | No | `true` returns a simulated ID, skips real HTTP call |
| `RESEND_API_KEY` | `re_your_api_key_here` | Yes | Resend API key for email delivery |
| `EMAIL_FROM` | `facturas@tudominio.com` | Yes | Sender address for invoice emails |
| `EMAIL_MOCK` | `true` | No | `true` logs intent but skips real email delivery |
| `WEBHOOK_URL` | _(empty)_ | No | POST target for webhook events; empty = disabled |
| `WEBHOOK_SECRET` | `change-me-webhook-secret` | Yes (if URL set) | HMAC-SHA256 signing key |
| `WEBHOOK_MOCK` | `true` | No | `true` logs intent but skips real webhook dispatch |
| `DB_POOL_SIZE` | `10` | No | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | No | Extra connections above pool size |
| `DB_POOL_TIMEOUT` | `30` | No | Seconds to wait for a pool connection |
| `LOG_LEVEL` | `INFO` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_JSON` | `false` | No | `true` for structured JSON logs (Datadog, Loki) |
| `DEBUG` | `false` | No | Enables SQLAlchemy query echo |
| `ALLOWED_HOSTS` | `["*"]` | No | CORS allowed origins |

---

## Design Decisions

### Async SQLAlchemy over sync SQLAlchemy

FastAPI is built on Starlette's async core. Using a synchronous ORM forces every database operation into `run_in_executor`, burning a thread-pool slot and adding latency. SQLAlchemy 2.0's `AsyncSession` with `asyncpg` lets the event loop handle I/O natively — one process can handle hundreds of concurrent requests while waiting on PostgreSQL.

The tradeoff is more boilerplate (`await`, `async with`) and a narrower ecosystem. For an API whose primary bottleneck is I/O, it is the correct trade.

---

### Alembic over `create_all` on startup

`Base.metadata.create_all()` is fine for prototyping, unsuitable for production:

1. **It cannot alter existing tables.** Adding a column requires either data loss or raw SQL.
2. **It is not transactional.** A failed deployment can leave the schema in a partially-applied state with no rollback path.

Alembic generates versioned migration scripts that are reviewable in code review, applied atomically, and rolled back with `alembic downgrade -1`. Every schema change becomes a documented, auditable event in version control.

---

### Service layer pattern

No business logic lives in routers. Routers translate HTTP ↔ service calls. Services own the business rules. This means:

- **Testability** — services can be unit-tested without an HTTP server
- **Reusability** — `OrderService.update_status` is called by both `InvoiceService.create_from_order` and the cancel endpoint, with no code duplication
- **Clarity** — the full invoice creation workflow is readable in one method (`InvoiceService.create_from_order`) without parsing FastAPI decorators or dependency injection chains

---

### Idempotency on invoice creation

A `UNIQUE(order_id)` constraint on the `invoices` table, enforced at both the application layer (pre-check) and database layer (constraint), means calling `POST /invoices/create-from-order` twice for the same order is safe. The second call returns `409 Conflict` rather than creating a duplicate invoice or double-charging the customer.

This matters in practice: webhooks are retried, network timeouts cause clients to retry, batch jobs process the same record twice. Idempotency makes the system correct under all of those conditions without requiring the caller to track state.

---

### Billing system errors return `502 Bad Gateway`, not silent fallback

The original implementation caught billing errors and returned a simulated external ID as if the push had succeeded. This is a production bug: the invoice would be marked `issued` with a fake ID, no record of the failure would exist, and the billing system would be out of sync.

The corrected behavior raises `BillingSystemError` on any HTTP or network failure, which the router converts to `502 Bad Gateway`. The database transaction is rolled back — no half-created invoice is persisted. The caller knows exactly what happened and can retry, alert, or queue for manual processing.

The simulated fallback is preserved behind `BILLING_SYSTEM_MOCK=true`, explicitly scoped to development and test environments.

---

### PDF generation: dual-engine strategy (WeasyPrint + ReportLab fallback)

WeasyPrint produces higher-fidelity PDFs from the same HTML/CSS template used for the email — single source of truth for the invoice layout. However, it requires system-level GTK/Cairo/Pango libraries that are unavailable on Windows without GTK4 Runtime.

Rather than requiring all developers to install native dependencies or use WSL, the service detects WeasyPrint availability once at import time via a `try/except OSError`. On Windows (or any environment without GTK), it falls back to ReportLab, a pure-Python PDF library with no native dependencies. Both engines produce a valid, complete invoice PDF with identical information.

In Docker (the production/CI environment), WeasyPrint is always available and is always used.

---

### Webhook failures are logged, never propagated

A webhook outage (receiver down, DNS failure, HTTP 5xx) must not roll back a successfully created invoice. The invoice was persisted, the billing system was notified, and the PDF was emailed. Failing the entire request because a secondary notification failed is the wrong trade-off.

`WebhookService.dispatch` catches all exceptions, logs them at `ERROR` level (triggering any log-based alerting), and returns silently. The transaction is never affected. If guaranteed delivery is needed, the correct solution is a persistent message queue (Celery + Redis, SQS), not exception propagation.

---

## Production Checklist

- [ ] Generate a strong `SECRET_KEY`: `openssl rand -hex 32`
- [ ] Generate a strong `API_KEY`: `openssl rand -hex 24`
- [ ] Generate a strong `WEBHOOK_SECRET`: `openssl rand -hex 32`
- [ ] Set `DEBUG=false` and `LOG_JSON=true`
- [ ] Set `BILLING_SYSTEM_MOCK=false` and configure `BILLING_SYSTEM_URL` + `BILLING_SYSTEM_API_KEY`
- [ ] Set `EMAIL_MOCK=false` and configure `RESEND_API_KEY` + `EMAIL_FROM`
- [ ] Set `WEBHOOK_MOCK=false` and configure `WEBHOOK_URL` + `WEBHOOK_SECRET` (if using webhooks)
- [ ] Set `ALLOWED_HOSTS` to your specific domain(s) — not `["*"]`
- [ ] Apply migrations before deploying: `alembic upgrade head`
- [ ] Deploy behind a TLS-terminating reverse proxy (nginx, Traefik, AWS ALB)
- [ ] Size `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` based on your database instance limits
- [ ] Wire `/health` to your load balancer's health check
- [ ] Set up log aggregation (Datadog, Grafana Loki, AWS CloudWatch) to consume JSON logs
- [ ] Configure alerting on `502` responses from `POST /invoices/create-from-order`
- [ ] For multi-instance deployments, configure a Redis backend for slowapi rate limiting
- [ ] Verify webhook receiver validates `X-Webhook-Signature` before processing events

---

## License

MIT © 2024
