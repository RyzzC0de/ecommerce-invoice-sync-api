"""
Invoice service: orchestrates invoice creation from an order
and simulates sync with an external billing system.
"""

import logging
import uuid
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import BillingSystemError
from app.models.invoice import Invoice, InvoiceStatus
from app.models.order import Order, OrderStatus
from app.schemas.invoice_schema import (
    InvoiceCreateFromOrder,
    InvoiceListResponse,
    InvoiceResponse,
)
from app.services.email_service import EmailService
from app.services.order_service import OrderService
from app.services.pdf_service import PDFService
from app.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)
settings = get_settings()


def _generate_invoice_number() -> str:
    """
    Generate a sequential-style invoice number.
    Format: INV-YYYYMMDD-{8-char UUID segment}
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    uid = uuid.uuid4().hex[:8].upper()
    return f"INV-{today}-{uid}"


class BillingSystemClient:
    """
    Thin async HTTP client wrapping the external billing system API.
    Isolated so it can be replaced with a real integration or mocked in tests.
    """

    def __init__(self) -> None:
        self._base_url = settings.BILLING_SYSTEM_URL
        self._headers = {
            "Authorization": f"Bearer {settings.BILLING_SYSTEM_API_KEY}",
            "Content-Type": "application/json",
        }
        self._timeout = settings.BILLING_SYSTEM_TIMEOUT

    async def push_invoice(self, invoice: Invoice) -> str:
        """
        Push invoice to the external billing system.

        Returns the external invoice ID on success.

        Raises:
            BillingSystemError: if the HTTP call fails and BILLING_SYSTEM_MOCK
                is False. When BILLING_SYSTEM_MOCK=true a simulated ID is
                returned instead so development/test environments never need a
                live billing endpoint.
        """
        if settings.BILLING_SYSTEM_MOCK:
            simulated_id = f"EXT-{uuid.uuid4().hex[:12].upper()}"
            logger.warning(
                "BILLING_SYSTEM_MOCK=true — returning simulated ID %s for invoice %s",
                simulated_id,
                invoice.invoice_number,
            )
            return simulated_id

        payload = {
            "reference": invoice.invoice_number,
            "customer_name": invoice.customer_name,
            "customer_email": invoice.customer_email,
            "customer_tax_id": invoice.customer_tax_id,
            "address": invoice.billing_address,
            "currency": invoice.currency,
            "subtotal": str(invoice.subtotal),
            "tax_total": str(invoice.tax_total),
            "grand_total": str(invoice.grand_total),
            "issue_date": invoice.issue_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/invoices",
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                external_id: str = data.get("id", "")
                logger.info(
                    "Invoice %s pushed to billing system → external_id=%s",
                    invoice.invoice_number,
                    external_id,
                )
                return external_id
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Billing system returned HTTP %s for invoice %s: %s",
                exc.response.status_code,
                invoice.invoice_number,
                exc.response.text,
            )
            raise BillingSystemError(
                f"Billing system returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Network error pushing invoice %s: %s",
                invoice.invoice_number,
                exc,
            )
            raise BillingSystemError(
                f"Network error contacting billing system: {exc}"
            ) from exc


class InvoiceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._order_svc = OrderService(db)
        self._billing = BillingSystemClient()
        self._pdf = PDFService()
        self._email = EmailService()
        self._webhook = WebhookService()

    # ── Create from order ─────────────────────────────────────────────────────
    async def create_from_order(
        self, payload: InvoiceCreateFromOrder
    ) -> InvoiceResponse:
        """
        Full invoice creation workflow:
          1. Validate order exists and is in a valid state.
          2. Build and persist the invoice.
          3. Push to external billing system.
          4. Update order status → COMPLETED.
        """
        order: Order = await self._order_svc.get_order(payload.order_id)

        if order.status == OrderStatus.CANCELLED:
            raise ValueError("Cannot create an invoice for a cancelled order.")

        # Idempotency: check if invoice already exists for this order
        existing = await self._db.execute(
            select(Invoice).where(Invoice.order_id == order.id)
        )
        if existing.scalar_one_or_none():
            raise ValueError(
                f"An invoice already exists for order '{order.id}'."
            )

        invoice = Invoice(
            order_id=order.id,
            invoice_number=_generate_invoice_number(),
            customer_name=order.customer_name,
            customer_email=order.customer_email,
            customer_tax_id=order.customer_tax_id,
            billing_address=order.shipping_address,
            currency=order.currency,
            subtotal=order.subtotal,
            tax_total=order.tax_total,
            grand_total=order.grand_total,
            issue_date=date.today(),
            due_date=payload.due_date,
            notes=payload.notes,
            status=InvoiceStatus.DRAFT,
        )

        self._db.add(invoice)
        try:
            await self._db.flush()
        except IntegrityError:
            await self._db.rollback()
            raise ValueError("Invoice creation failed due to a constraint violation.")

        # ── Push to external billing system ───────────────────────────────────
        # BillingSystemError propagates to the router → HTTP 502
        external_id = await self._billing.push_invoice(invoice)
        invoice.external_invoice_id = external_id
        invoice.status = InvoiceStatus.ISSUED

        # ── Generate PDF ──────────────────────────────────────────────────────
        pdf_bytes = self._pdf.generate_invoice_pdf(invoice, order)

        # ── Send email with PDF attachment ────────────────────────────────────
        await self._email.send_invoice(invoice, pdf_bytes)

        # ── Dispatch webhook (fire-and-forget — errors are only logged) ───────
        await self._webhook.dispatch(
            "invoice.created",
            {
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "order_id": str(order.id),
                "external_invoice_id": external_id,
                "grand_total": str(invoice.grand_total),
                "currency": invoice.currency,
                "customer_email": invoice.customer_email,
            },
        )

        # ── Update order status ───────────────────────────────────────────────
        await self._order_svc.update_status(order.id, OrderStatus.COMPLETED)

        await self._db.refresh(invoice)
        logger.info(
            "Invoice %s created (external=%s) for order %s",
            invoice.invoice_number,
            external_id,
            order.id,
        )
        return InvoiceResponse.model_validate(invoice)

    # ── List ──────────────────────────────────────────────────────────────────
    async def list_invoices(
        self,
        page: int = 1,
        page_size: int = 20,
        status: InvoiceStatus | None = None,
    ) -> InvoiceListResponse:
        offset = (page - 1) * page_size

        base_q = select(Invoice)
        count_q = select(func.count()).select_from(Invoice)
        if status:
            base_q = base_q.where(Invoice.status == status)
            count_q = count_q.where(Invoice.status == status)

        total = (await self._db.execute(count_q)).scalar_one()
        result = await self._db.execute(
            base_q.order_by(Invoice.created_at.desc()).offset(offset).limit(page_size)
        )
        invoices = result.scalars().all()

        return InvoiceListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[InvoiceResponse.model_validate(i) for i in invoices],
        )

    # ── Get by ID ─────────────────────────────────────────────────────────────
    async def get_invoice(self, invoice_id: uuid.UUID) -> InvoiceResponse:
        result = await self._db.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise LookupError(f"Invoice '{invoice_id}' not found.")
        return InvoiceResponse.model_validate(invoice)

    # ── Get PDF ───────────────────────────────────────────────────────────────
    async def get_invoice_pdf(self, invoice_id: uuid.UUID) -> tuple[bytes, str]:
        """
        Render the invoice as a PDF and return (pdf_bytes, invoice_number).

        Raises LookupError if the invoice or its parent order is not found.
        """
        from sqlalchemy.orm import selectinload

        result = await self._db.execute(
            select(Invoice)
            .options(selectinload(Invoice.order))
            .where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise LookupError(f"Invoice '{invoice_id}' not found.")

        order = invoice.order
        if order is None:
            raise LookupError(f"Parent order for invoice '{invoice_id}' not found.")

        pdf_bytes = self._pdf.generate_invoice_pdf(invoice, order)
        return pdf_bytes, invoice.invoice_number
