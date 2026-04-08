"""
Email delivery service.

Uses the official Resend Python SDK to send invoice PDFs to customers.
When EMAIL_MOCK=true (default in dev/test) no real email is sent — the call is
only logged, so tests never need a live Resend API key.
"""

from __future__ import annotations

import logging

import resend

from app.core.config import get_settings
from app.models.invoice import Invoice

logger = logging.getLogger(__name__)


class EmailService:
    """Sends invoice emails via Resend."""

    def __init__(self) -> None:
        self._settings = get_settings()
        resend.api_key = self._settings.RESEND_API_KEY

    async def send_invoice(self, invoice: Invoice, pdf_bytes: bytes) -> None:
        """
        Send the invoice PDF to the customer's email address.

        When EMAIL_MOCK=true the method logs the intent and returns immediately
        without making any network call.

        Args:
            invoice:   The Invoice ORM object (provides recipient and number).
            pdf_bytes: Raw PDF bytes to attach.
        """
        if self._settings.EMAIL_MOCK:
            logger.warning(
                "EMAIL_MOCK=true — skipping real delivery of invoice %s to %s",
                invoice.invoice_number,
                invoice.customer_email,
            )
            return

        filename = f"{invoice.invoice_number}.pdf"

        params: resend.Emails.SendParams = {
            "from": self._settings.EMAIL_FROM,
            "to": [invoice.customer_email],
            "subject": f"Tu factura {invoice.invoice_number}",
            "html": (
                f"<p>Estimado/a <strong>{invoice.customer_name}</strong>,</p>"
                f"<p>Adjuntamos la factura <strong>{invoice.invoice_number}</strong> "
                f"correspondiente a tu pedido. El importe total es "
                f"<strong>{invoice.grand_total} {invoice.currency}</strong>.</p>"
                f"<p>Gracias por tu confianza.</p>"
            ),
            "attachments": [
                {
                    "filename": filename,
                    "content": list(pdf_bytes),
                }
            ],
        }

        email = resend.Emails.send(params)
        logger.info(
            "Invoice %s emailed to %s — Resend message id=%s",
            invoice.invoice_number,
            invoice.customer_email,
            email.get("id"),
        )
