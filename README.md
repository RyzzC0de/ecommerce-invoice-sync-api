  # Ecommerce Invoice Sync API

  > **Production-ready FastAPI service that receives ecommerce orders and transforms them into invoices, syncing with an external billing system.**

  ---

  ## What it does

  | Capability | Detail |
  |---|---|
  | **Order ingestion** | Accepts structured order payloads from any ecommerce platform |
  | **Invoice generation** | Automatically builds numbered invoices with full VAT breakdown |
  | **External billing sync** | Pushes invoices to a configurable external billing system via HTTP |
  | **Idempotency** | Duplicate orders or invoices are rejected with a clear `409 Conflict` |
  | **Security** | All endpoints are protected by an API Key (`X-API-Key` header) |
  | **Observability** | Structured request logging with method, path, status code, and latency |
  | **Health check** | `/health` endpoint for load balancer / container orchestration probes |

  ---

  ## Architecture

  ```
  app/
  ├── main.py              # FastAPI app, middleware, lifespan, routers registration
  ├── core/
  │   ├── config.py        # Pydantic-settings: all env vars in one place
  │   └── security.py      # API Key + JWT utilities
  ├── db/
  │   └── database.py      # Async SQLAlchemy engine, session factory, Base
  ├── models/
  │   ├── order.py         # Order + OrderItem ORM models
  │   └── invoice.py       # Invoice ORM model
  ├── schemas/
  │   ├── order_schema.py  # Pydantic request/response schemas for orders
  │   └── invoice_schema.py
  ├── services/
  │   ├── order_service.py   # Business logic: create, list, get, update status
  │   └── invoice_service.py # Orchestrates invoice creation + billing push
  └── routers/
      ├── orders.py          # POST /orders, GET /orders, GET /orders/{id}
      └── invoices.py        # POST /invoices/create-from-order, GET /invoices, GET /invoices/{id}
  ```

  ---

  ## Prerequisites

  - Python **3.12+**
  - PostgreSQL **14+** (running locally or via Docker)
  - `pip` or a virtual-environment manager

  ---

  ## Quick start

  ### 1 — Clone and set up the environment

  ```bash
  git clone https://github.com/RyzzC0de/ecommerce-invoice-sync-api.git
  cd ecommerce-invoice-sync-api

  python -m venv .venv
  # Windows
  .venv\Scripts\activate
  # macOS / Linux
  source .venv/bin/activate

  pip install -r requirements.txt
  ```

  ### 2 — Configure environment variables

  ```bash
  cp .env.example .env
  # Edit .env with your database URL, secret key, and API key
  ```

  Minimum required values in `.env`:

  ```env
  DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/invoice_sync
  SECRET_KEY=your-random-32-char-secret
  API_KEY=your-strong-api-key
  ```

  ### 3 — Create the database

  ```bash
  # Using psql
  psql -U postgres -c "CREATE DATABASE invoice_sync;"
  ```

  > Tables are created automatically on first startup via `Base.metadata.create_all`.

  ### 4 — Run the server

  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```

  Interactive API docs: **http://localhost:8000/docs**

  ---

  ## Docker (one command)

  ```bash
  docker-compose up --build
  ```

  This starts both **PostgreSQL** and the **API** automatically. No manual database setup required — tables are created on first startup.

  The API will be available at **http://localhost:8000** and docs at **http://localhost:8000/docs**.

  ---

  ## API Reference

  All endpoints require the header:
  ```
  X-API-Key: <your-api-key>
  ```

  ### Orders

  #### `POST /api/v1/orders` — Create an order

  ```bash
  curl -X POST http://localhost:8000/api/v1/orders \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-api-key" \
    -d '{
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
    }'
  ```

  **Response `201 Created`:**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "external_order_id": "SHOP-20240101-0001",
    "status": "pending",
    "grand_total": "268.75",
    "tax_total": "46.75",
    "subtotal": "222.00",
    ...
  }
  ```

  ---

  #### `GET /api/v1/orders` — List orders

  ```bash
  curl "http://localhost:8000/api/v1/orders?page=1&page_size=20&status=pending" \
    -H "X-API-Key: your-api-key"
  ```

  ---

  #### `GET /api/v1/orders/{order_id}` — Get a single order

  ```bash
  curl "http://localhost:8000/api/v1/orders/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
    -H "X-API-Key: your-api-key"
  ```

  ---

  ### Invoices

  #### `POST /api/v1/invoices/create-from-order` — Create invoice from order

  ```bash
  curl -X POST http://localhost:8000/api/v1/invoices/create-from-order \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-api-key" \
    -d '{
      "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "due_date": "2024-02-01",
      "notes": "Net 30"
    }'
  ```

  **Response `201 Created`:**
  ```json
  {
    "id": "7e9e4567-e89b-12d3-a456-426614174000",
    "invoice_number": "INV-20240101-A1B2C3D4",
    "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "status": "issued",
    "external_invoice_id": "EXT-AB1234567890",
    "grand_total": "268.75",
    ...
  }
  ```

  ---

  #### `GET /api/v1/invoices` — List invoices

  ```bash
  curl "http://localhost:8000/api/v1/invoices?page=1&page_size=20&status=issued" \
    -H "X-API-Key: your-api-key"
  ```

  ---

  #### `GET /api/v1/invoices/{invoice_id}` — Get a single invoice

  ```bash
  curl "http://localhost:8000/api/v1/invoices/7e9e4567-e89b-12d3-a456-426614174000" \
    -H "X-API-Key: your-api-key"
  ```

  ---

  ### System

  #### `GET /health` — Health check (no auth required)

  ```bash
  curl http://localhost:8000/health
  ```

  ```json
  {
    "status": "healthy",
    "version": "1.0.0",
    "database": "connected"
  }
  ```

  ---

  ## Running tests

  Tests use an **in-memory SQLite database** — no PostgreSQL required.

  ```bash
  pytest -v
  ```

  All tests should pass. ✅

  ---

  ## Environment variables reference

  | Variable | Default | Description |
  |---|---|---|
  | `DATABASE_URL` | *(required)* | Async PostgreSQL DSN |
  | `SECRET_KEY` | *(required)* | Min 32 chars, used for JWT signing |
  | `API_KEY` | *(required)* | Static B2B API key |
  | `BILLING_SYSTEM_URL` | `https://billing.example.com/api/v1` | External billing endpoint |
  | `BILLING_SYSTEM_API_KEY` | *(required)* | Auth key for billing system |
  | `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
  | `LOG_JSON` | `false` | Set `true` for structured JSON logs |
  | `DEBUG` | `false` | Enables SQLAlchemy query logging |
  | `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size |

  ---

  ## Production checklist

  - [ ] Set strong `SECRET_KEY` (`openssl rand -hex 32`)
  - [ ] Set strong `API_KEY` (min 32 chars random string)
  - [ ] Set `DEBUG=false`
  - [ ] Set `LOG_JSON=true` for log aggregators (Datadog, ELK, CloudWatch)
  - [ ] Deploy behind a reverse proxy (nginx / traefik) with TLS termination
  - [ ] Set `ALLOWED_HOSTS` to your specific domain(s)
  - [ ] Run database migrations with Alembic before deploying
  - [ ] Configure connection pool sizes based on your DB instance limits
  - [ ] Replace BILLING_SYSTEM_URL with a real billing provider (Stripe, Holded, Facturae, etc.)

  ---

  ## License

  MIT © 2026
