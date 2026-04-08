# Invoice automation backend for ecommerce platforms (Shopify / WooCommerce ready)

Automates invoice generation, VAT calculation, PDF creation, email delivery and billing system synchronization for ecommerce businesses.

---

## Who is this for?

- **Shopify / WooCommerce store owners** who need automated invoicing without manual work
- **SaaS companies** building billing backends that handle orders, invoices and payments
- **Businesses integrating with ERP or accounting systems** (Holded, Stripe, Xero, Odoo)
- **Developers** who need a production-ready invoicing API to plug into their platform in days, not months

---

## Business Use Cases

- **Automatic invoice generation** on every order — one API call, everything handled
- **VAT-compliant invoices** sent by email to customers automatically, with PDF attached
- **PDF invoice download** from a simple API call — no extra tooling needed
- **Real-time sync** to external billing or accounting systems (Holded, Stripe, custom ERP)
- **Webhook notifications** to Shopify or any platform the moment an invoice is created
- **Order cancellation** — cancel any pending order with a single request
- **Duplicate protection** — calling the same invoice twice never creates duplicates or double charges

---

## Live Demo

**Swagger UI:** `https://your-deploy-url/docs`

Try it — copy this request directly into Swagger or curl:

```json
{
  "external_order_id": "DEMO-001",
  "customer_name": "Acme Corp",
  "customer_email": "billing@acme.com",
  "customer_tax_id": "ES-B12345678",
  "shipping_address": "Calle Gran Vía 1, Madrid",
  "currency": "EUR",
  "items": [
    {
      "sku": "PLAN-PRO",
      "name": "Pro Plan",
      "quantity": 1,
      "unit_price": 49.99,
      "tax_rate": 0.21
    }
  ]
}
```

Send that to `POST /api/v1/orders` with `X-API-Key: your-key`, then call `POST /api/v1/invoices/create-from-order` with the returned `id`. In one round-trip: invoice persisted, PDF generated, email sent, billing system notified, webhook fired.

---

## Table of Contents

1. [Getting Started](#getting-started)
   - [Docker (recommended)](#docker-recommended)
   - [Local Setup](#local-setup)
2. [API Reference](#api-reference)
3. [Authentication](#authentication)
4. [Running Tests](#running-tests)
5. [Environment Variables](#environment-variables)
6. [Production Checklist](#production-checklist)
7. [Architecture Notes](#architecture-notes)

---

## Getting Started

### Docker (recommended)

No local Python or PostgreSQL setup required.

**Prerequisites:** Docker Engine 24+ and Docker Compose v2.

```bash
git clone <your-repo-url>
cd ecommerce-invoice-sync-api

cp .env.example .env
```

Edit `.env` — minimum values to change:

```env
SECRET_KEY=your-random-32-char-secret      # openssl rand -hex 32
API_KEY=your-strong-api-key                # openssl rand -hex 24
BILLING_SYSTEM_MOCK=true
EMAIL_MOCK=true
WEBHOOK_MOCK=true
```

```bash
docker-compose up --build
docker-compose exec api alembic upgrade head
```

| URL | Description |
|---|---|
| `http://localhost:8000/docs` | Swagger UI — try every endpoint interactively |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8000/health` | Health check |

> WeasyPrint (primary PDF engine) works out of the box in Docker. On Windows the API falls back to ReportLab automatically — no configuration needed.

---

### Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL 14+

```bash
git clone <your-repo-url>
cd ecommerce-invoice-sync-api

python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
cp .env.example .env
```

Minimum `.env` values for local development:

```env
DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/invoice_sync
SECRET_KEY=your-random-32-char-secret
API_KEY=your-strong-api-key
BILLING_SYSTEM_MOCK=true
EMAIL_MOCK=true
WEBHOOK_MOCK=true
```

```bash
psql -U postgres -c "CREATE DATABASE invoice_sync;"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API live at **http://localhost:8000** — docs at **/docs**.

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

Rate limit: **10 req/min per IP**

```json
{
  "external_order_id": "SHOP-20240515-0042",
  "customer_name": "Acme Corporation",
  "customer_email": "billing@acme.com",
  "customer_tax_id": "ES-B12345678",
  "shipping_address": "Calle Gran Vía 28, 28013 Madrid, Spain",
  "currency": "EUR",
  "notes": "Priority shipment",
  "items": [
    { "sku": "WIDGET-L", "name": "Blue Widget Large", "quantity": 3, "unit_price": 29.99, "tax_rate": 0.21 },
    { "sku": "GADGET-PRO", "name": "Gadget Pro", "quantity": 1, "unit_price": 149.95, "tax_rate": 0.21 }
  ]
}
```

**Response `201`:** Full order with computed `subtotal`, `tax_total`, `grand_total`.

| Status | Condition |
|---|---|
| `409` | `external_order_id` already exists |
| `422` | Validation error (bad email, quantity < 1, missing field) |

---

#### `GET /api/v1/orders` — List orders

Query params: `page`, `page_size` (max 100), `status` (`pending` / `processing` / `completed` / `cancelled` / `failed`).

#### `GET /api/v1/orders/{order_id}` — Get single order

#### `PATCH /api/v1/orders/{order_id}/cancel` — Cancel an order

| Status | Condition |
|---|---|
| `409` | Already `completed` or `cancelled` |

---

### Invoices

#### `POST /api/v1/invoices/create-from-order` — Create invoice

Rate limit: **10 req/min per IP**

One call triggers the full workflow: invoice persisted → billing system notified → PDF generated → email sent → webhook dispatched → order marked completed.

```json
{
  "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "due_date": "2024-06-15",
  "notes": "Net 30 — wire transfer only"
}
```

**Response `201`:**

```json
{
  "id": "7e9e4567-e89b-12d3-a456-426614174000",
  "invoice_number": "INV-20240515-A3F72C91",
  "status": "issued",
  "external_invoice_id": "EXT-AB1C2D3E4F56",
  "subtotal": "239.92",
  "tax_total": "50.38",
  "grand_total": "290.30",
  "issue_date": "2024-05-15",
  "due_date": "2024-06-15"
}
```

| Status | Condition |
|---|---|
| `404` | Order not found |
| `409` | Invoice already exists for this order, or order is cancelled |
| `502` | External billing system error or timeout |

---

#### `GET /api/v1/invoices` — List invoices

Query params: `page`, `page_size`, `status` (`draft` / `issued` / `sent` / `paid` / `void` / `overdue`).

#### `GET /api/v1/invoices/{invoice_id}` — Get single invoice

#### `GET /api/v1/invoices/{invoice_id}/pdf` — Download PDF

Returns the invoice as an `application/pdf` file attachment. Engine selected automatically (WeasyPrint on Linux, ReportLab on Windows).

```bash
curl https://your-api/api/v1/invoices/{id}/pdf \
  -H "X-API-Key: your-key" \
  --output invoice.pdf
```

---

### System

#### `GET /health` — Health check (no auth)

```json
{ "status": "healthy", "version": "1.0.0", "database": "connected" }
```

---

## Authentication

Static API key via `X-API-Key` header — designed for B2B machine-to-machine integrations.

```bash
curl https://your-api/api/v1/orders -H "X-API-Key: your-api-key"
```

The codebase also includes a full JWT Bearer token implementation ready to activate for user-level auth.

> Generate a production key: `openssl rand -hex 24`

---

## Running Tests

64 tests. No PostgreSQL, no external services, no network calls required — everything runs against an in-memory SQLite database.

```bash
pytest -v

# Specific file
pytest tests/test_orders.py -v
pytest tests/test_pdf_email_webhook.py -v

# With coverage
pytest --cov=app --cov-report=term-missing
```

**Expected:** `64 passed in ~11s`

---

## Environment Variables

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Yes | Async PostgreSQL connection string |
| `SECRET_KEY` | `change-me` | Yes | Min 32 chars — signs JWTs |
| `API_KEY` | `change-me` | Yes | Static key for `X-API-Key` header |
| `BILLING_SYSTEM_URL` | `https://billing.example.com/api/v1` | Yes | External billing endpoint |
| `BILLING_SYSTEM_API_KEY` | `external-billing-key` | Yes | Auth token for billing system |
| `BILLING_SYSTEM_MOCK` | `false` | No | `true` skips real billing calls (dev/test) |
| `RESEND_API_KEY` | `re_your_key` | Yes | Resend API key for email delivery |
| `EMAIL_FROM` | `facturas@tudominio.com` | Yes | Sender address for invoice emails |
| `EMAIL_MOCK` | `true` | No | `true` skips real email delivery |
| `WEBHOOK_URL` | _(empty)_ | No | POST target for events; empty = disabled |
| `WEBHOOK_SECRET` | `change-me` | Yes (if URL set) | HMAC-SHA256 signing key |
| `WEBHOOK_MOCK` | `true` | No | `true` skips real webhook dispatch |
| `LOG_LEVEL` | `INFO` | No | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_JSON` | `false` | No | `true` for structured JSON logs in production |
| `DB_POOL_SIZE` | `10` | No | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | No | Extra connections above pool size |

Full reference: see `.env.example`.

---

## Production Checklist

- [ ] `SECRET_KEY`: `openssl rand -hex 32`
- [ ] `API_KEY`: `openssl rand -hex 24`
- [ ] `WEBHOOK_SECRET`: `openssl rand -hex 32`
- [ ] `DEBUG=false`, `LOG_JSON=true`
- [ ] `BILLING_SYSTEM_MOCK=false` + configure `BILLING_SYSTEM_URL` and `BILLING_SYSTEM_API_KEY`
- [ ] `EMAIL_MOCK=false` + configure `RESEND_API_KEY` and `EMAIL_FROM`
- [ ] `WEBHOOK_MOCK=false` + configure `WEBHOOK_URL` (if using webhooks)
- [ ] `ALLOWED_HOSTS` set to your domain(s) — not `["*"]`
- [ ] Run `alembic upgrade head` before deploying
- [ ] Deploy behind TLS-terminating proxy (nginx, Traefik, AWS ALB)
- [ ] Wire `/health` to load balancer health check
- [ ] Set up log aggregation (Datadog, Grafana Loki, CloudWatch)
- [ ] Alert on `502` responses from `POST /invoices/create-from-order`
- [ ] Redis backend for slowapi if running multiple instances

---

## Architecture Notes

<details>
<summary>Tech stack, system diagram, design decisions, and project structure</summary>

### Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com) | 0.115.6 |
| ASGI server | [Uvicorn](https://www.uvicorn.org) | 0.32.1 |
| ORM | [SQLAlchemy async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) | 2.0.36 |
| DB driver (prod) | [asyncpg](https://github.com/MagicStack/asyncpg) | 0.30.0 |
| DB driver (tests) | [aiosqlite](https://github.com/omnilib/aiosqlite) | 0.20.0 |
| Migrations | [Alembic](https://alembic.sqlalchemy.org) | 1.14.0 |
| Validation | [Pydantic v2](https://docs.pydantic.dev) | 2.10.3 |
| JWT | [python-jose](https://github.com/mpdavis/python-jose) | 3.3.0 |
| HTTP client | [httpx](https://www.python-httpx.org) | 0.27.2 |
| Rate limiting | [slowapi](https://github.com/laurents/slowapi) | 0.1.9 |
| PDF (primary) | [WeasyPrint](https://weasyprint.org) | 62.3 |
| PDF (fallback) | [ReportLab](https://www.reportlab.com) | 4.2.5 |
| Template engine | [Jinja2](https://jinja.palletsprojects.com) | 3.1.4 |
| Email delivery | [Resend Python SDK](https://resend.com/docs/send-with-python) | 2.4.0 |
| Testing | pytest-asyncio + httpx | 0.24.0 |
| Database (prod) | PostgreSQL | 14+ |

---

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         External Clients                            │
│           (Ecommerce platform, B2B partner, curl, Postman)          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  HTTPS  +  X-API-Key header
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                            │
│  ┌──────────────┐   ┌────────────────────────────────────────────┐  │
│  │  Middleware  │   │               Routers                      │  │
│  │ CORS        │   │  POST /api/v1/orders           (10/min)    │  │
│  │ Rate limit  │   │  GET  /api/v1/orders           (60/min)    │  │
│  │ Request log │   │  PATCH /api/v1/orders/{id}/cancel          │  │
│  └──────────────┘   │  POST /api/v1/invoices/create-from-order  │  │
│                     │  GET  /api/v1/invoices/{id}/pdf            │  │
│                     │  GET  /health                  (no auth)   │  │
│                     └───────────────────┬────────────────────────┘  │
│                     ┌───────────────────▼────────────────────────┐  │
│                     │            Service Layer                    │  │
│                     │  OrderService  │  InvoiceService           │  │
│                     │               │  BillingSystemClient       │  │
│                     │               │  PDFService (WP / RL)      │  │
│                     │               │  EmailService (Resend)     │  │
│                     │               │  WebhookService (HMAC)     │  │
│                     └───────────────┴────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
         │                   │                  │               │
         ▼                   ▼                  ▼               ▼
  PostgreSQL          Billing System       Resend API    Webhook receiver
```

**Invoice creation lifecycle (8 steps):**
1. Validate order exists and is not cancelled
2. Idempotency check — reject if invoice already exists
3. Persist invoice in `DRAFT` status
4. Push to external billing system → `502` on failure (transaction rolled back)
5. Generate PDF (WeasyPrint on Linux, ReportLab on Windows)
6. Send email with PDF attachment via Resend
7. Dispatch signed `invoice.created` webhook (failure is logged, never propagated)
8. Update order status → `COMPLETED`

---

### Project Structure

```
ecommerce-invoice-sync-api/
├── app/
│   ├── main.py                   # App factory, middleware, lifespan, routers
│   ├── core/
│   │   ├── config.py             # Settings via pydantic-settings
│   │   ├── security.py           # API key + JWT
│   │   ├── limiter.py            # slowapi singleton
│   │   └── exceptions.py         # BillingSystemError
│   ├── db/database.py            # Async engine, session, Base, get_db
│   ├── models/                   # SQLAlchemy ORM models
│   ├── schemas/                  # Pydantic v2 request/response schemas
│   ├── services/
│   │   ├── order_service.py
│   │   ├── invoice_service.py    # Orchestrates the full invoice workflow
│   │   ├── pdf_service.py        # WeasyPrint (Linux) / ReportLab (Windows)
│   │   ├── email_service.py      # Resend SDK
│   │   └── webhook_service.py    # HMAC-SHA256 signed POST
│   ├── templates/invoice.html    # Jinja2 invoice template (WeasyPrint path)
│   └── routers/                  # HTTP layer — delegates to services
├── alembic/versions/             # Versioned DB migrations
├── tests/
│   ├── test_orders.py            # 18 tests
│   ├── test_invoices.py          # 14 tests
│   ├── test_health.py            # 1 test
│   ├── test_security.py          # 8 tests
│   └── test_pdf_email_webhook.py # 23 tests
├── conftest.py                   # SQLite override, autouse service mocks
├── Dockerfile                    # Multi-stage, non-root, GTK libraries included
├── docker-compose.yml            # PostgreSQL + API with healthcheck
└── .env.example
```

---

### Rate Limiting

| Scope | Limit | Endpoints |
|---|---|---|
| Global default | 60 req / min / IP | All |
| Write endpoints | 10 req / min / IP | `POST /orders`, `POST /invoices/create-from-order` |

Exceeded → `429 Too Many Requests` with `Retry-After` header.

For multi-instance deployments, configure a Redis backend: `storage_uri="redis://..."` in `app/core/limiter.py`.

---

### Design Decisions

**Async SQLAlchemy** — FastAPI's async core means sync DB operations block the event loop. `AsyncSession` + `asyncpg` lets one process serve hundreds of concurrent requests.

**Alembic over `create_all`** — `create_all` cannot alter existing tables and is not transactional. Alembic migrations are versioned, reviewable, and rollbackable (`alembic downgrade -1`).

**Service layer** — no business logic in routers. Routers translate HTTP ↔ service calls. Services own the rules. Result: fully testable without an HTTP server, zero code duplication.

**Idempotency** — `UNIQUE(order_id)` on `invoices` enforced at both application and database layers. Calling create-from-order twice is always safe.

**502 on billing errors** — silently returning a fake ID on billing failure leaves the system in an inconsistent state with no observable signal. Raising `BillingSystemError` rolls back the transaction and returns `502` so the caller knows exactly what happened.

**Dual-engine PDF** — WeasyPrint gives higher-fidelity HTML/CSS rendering but requires GTK system libraries (unavailable on Windows). The service detects availability at import time and falls back to ReportLab (pure Python, no native deps) automatically.

**Webhook failures are not propagated** — a webhook outage must not roll back a valid invoice. Errors are caught, logged at `ERROR` level, and swallowed. For guaranteed delivery, replace with a persistent queue (Celery + Redis, SQS).

</details>

---

## License

MIT © 2024
