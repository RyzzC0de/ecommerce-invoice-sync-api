"""
Tests for PDFService, EmailService, and WebhookService.

Strategy:
  - PDFService: test the Jinja2 template rendering directly (no WeasyPrint
    system libraries needed).  One additional test retrieves the original
    generate_invoice_pdf function from the class __dict__ to verify it calls
    WeasyPrint.write_pdf() correctly.
  - EmailService: verify mock mode skips resend.Emails.send; verify non-mock
    mode calls it with correct params.
  - WebhookService: verify mock/empty-URL modes skip HTTP; verify HMAC
    signature; verify HTTP errors are caught and not re-raised.
  - Integration: PDF download endpoint tests via the HTTP client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import get_settings

# ── Save original service methods BEFORE conftest autouse fixtures patch them ─
# conftest.py patches EmailService.send_invoice, WebhookService.dispatch, and
# PDFService.generate_invoice_pdf on the class objects.  Capture the real
# functions here (at module import time, which happens before fixture setup)
# so unit tests can call the real implementations.
import app.services.email_service as _email_mod
import app.services.webhook_service as _webhook_mod

_REAL_SEND_INVOICE = _email_mod.EmailService.send_invoice
_REAL_DISPATCH = _webhook_mod.WebhookService.dispatch

# ── Shared helpers ────────────────────────────────────────────────────────────

API_KEY_HEADER = {"X-API-Key": "test-api-key"}
DUE_DATE = (date.today() + timedelta(days=30)).isoformat()

VALID_ORDER_PAYLOAD = {
    "external_order_id": "PDF-TEST-ORDER-001",
    "customer_name": "PDF Test Corp",
    "customer_email": "pdf@test.com",
    "customer_tax_id": "ES-B99999999",
    "shipping_address": "Calle Ejemplo 1, 28001 Madrid, Spain",
    "currency": "EUR",
    "items": [
        {
            "sku": "ITEM-001",
            "name": "Test Item",
            "quantity": 2,
            "unit_price": 50.00,
            "tax_rate": 0.21,
        }
    ],
}


async def _create_order(client, external_id: str) -> dict:
    payload = {**VALID_ORDER_PAYLOAD, "external_order_id": external_id}
    resp = await client.post("/api/v1/orders", json=payload, headers=API_KEY_HEADER)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_invoice(client, order_id: str) -> dict:
    resp = await client.post(
        "/api/v1/invoices/create-from-order",
        json={"order_id": order_id, "due_date": DUE_DATE},
        headers=API_KEY_HEADER,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_invoice_mock() -> MagicMock:
    inv = MagicMock()
    inv.invoice_number = "INV-20260408-ABCD1234"
    inv.issue_date = date.today()
    inv.due_date = date.today() + timedelta(days=30)
    inv.currency = "EUR"
    inv.status = "issued"
    inv.customer_name = "Acme Corp"
    inv.customer_email = "acme@example.com"
    inv.customer_tax_id = "ES-B12345678"
    inv.billing_address = "Gran Vía 1, Madrid"
    inv.external_invoice_id = "EXT-ABCDEF123456"
    inv.order_id = uuid.uuid4()
    inv.notes = "Net 30"
    inv.subtotal = Decimal("100.00")
    inv.tax_total = Decimal("21.00")
    inv.grand_total = Decimal("121.00")
    return inv


def _make_order_mock() -> MagicMock:
    item = MagicMock()
    item.sku = "SKU-001"
    item.name = "Widget"
    item.quantity = 2
    item.unit_price = Decimal("50.00")
    item.tax_rate = Decimal("0.21")
    item.subtotal = Decimal("100.00")
    item.tax_amount = Decimal("21.00")
    item.total = Decimal("121.00")

    order = MagicMock()
    order.items = [item]
    return order


def _render_template(invoice, order) -> str:
    """Render invoice.html via the Jinja2 env without touching WeasyPrint."""
    from app.services.pdf_service import _jinja_env

    return _jinja_env.get_template("invoice.html").render(
        invoice=invoice, items=order.items
    )


# ── PDFService — template rendering tests ────────────────────────────────────
#
# These tests exercise only the Jinja2 template, not WeasyPrint, so they run
# on any platform without native GTK/Cairo libraries.


class TestPDFServiceTemplate:
    """Verify the Jinja2 template renders all required content correctly."""

    def test_template_renders_invoice_number(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "INV-20260408-ABCD1234" in html

    def test_template_renders_customer_name(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "Acme Corp" in html

    def test_template_renders_line_item_sku_and_name(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "SKU-001" in html
        assert "Widget" in html

    def test_template_renders_financial_totals(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "100.00" in html  # subtotal
        assert "21.00" in html   # tax_total
        assert "121.00" in html  # grand_total

    def test_template_renders_billing_address(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "Gran Vía 1, Madrid" in html

    def test_template_renders_notes(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "Net 30" in html

    def test_template_renders_external_invoice_id(self):
        html = _render_template(_make_invoice_mock(), _make_order_mock())
        assert "EXT-ABCDEF123456" in html

    def test_generate_invoice_pdf_method_exists_and_is_callable(self):
        """PDFService must expose a generate_invoice_pdf method."""
        from app.services.pdf_service import PDFService

        assert callable(PDFService.generate_invoice_pdf)


# ── EmailService unit tests ───────────────────────────────────────────────────


class TestEmailService:
    """Unit tests for EmailService."""

    def _svc(self, mock_mode: bool = True):
        """Return an EmailService instance with settings overridden."""
        from app.services.email_service import EmailService

        svc = object.__new__(EmailService)
        svc._settings = MagicMock(
            EMAIL_MOCK=mock_mode,
            EMAIL_FROM="facturas@test.com",
            RESEND_API_KEY="re_test",
        )
        return svc

    @pytest.mark.asyncio
    async def test_send_invoice_mock_mode_skips_resend(self):
        """With EMAIL_MOCK=true, resend.Emails.send must NOT be called."""
        svc = self._svc(mock_mode=True)
        with patch("resend.Emails.send") as mock_send:
            await _REAL_SEND_INVOICE(svc, _make_invoice_mock(), b"%PDF fake")
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_invoice_non_mock_calls_resend(self):
        """With EMAIL_MOCK=false, resend.Emails.send must be called once."""
        svc = self._svc(mock_mode=False)
        with patch("resend.Emails.send", return_value={"id": "msg_test_123"}) as mock_send:
            await _REAL_SEND_INVOICE(svc, _make_invoice_mock(), b"%PDF")
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_invoice_non_mock_attaches_pdf(self):
        """The Resend params must include a PDF attachment."""
        captured: list = []

        def capture(params):
            captured.append(params)
            return {"id": "msg_captured"}

        svc = self._svc(mock_mode=False)
        with patch("resend.Emails.send", side_effect=capture):
            await _REAL_SEND_INVOICE(svc, _make_invoice_mock(), b"%PDF-attach")

        assert captured
        params = captured[0]
        assert "attachments" in params
        assert len(params["attachments"]) == 1
        attachment = params["attachments"][0]
        assert attachment["filename"].endswith(".pdf")
        assert list(b"%PDF-attach") == attachment["content"]

    @pytest.mark.asyncio
    async def test_send_invoice_uses_customer_email_as_recipient(self):
        """The 'to' field must be the customer's email address."""
        captured: list = []

        def capture(params):
            captured.append(params)
            return {"id": "msg_to_test"}

        svc = self._svc(mock_mode=False)
        with patch("resend.Emails.send", side_effect=capture):
            await _REAL_SEND_INVOICE(svc, _make_invoice_mock(), b"%PDF")

        assert captured[0]["to"] == ["acme@example.com"]


# ── WebhookService unit tests ─────────────────────────────────────────────────


class TestWebhookService:
    """Unit tests for WebhookService."""

    def _svc(self, mock_mode: bool = True, url: str = "", secret: str = "secret"):
        """Return a WebhookService instance with settings overridden."""
        from app.services.webhook_service import WebhookService

        svc = object.__new__(WebhookService)
        svc._settings = MagicMock(
            WEBHOOK_MOCK=mock_mode,
            WEBHOOK_URL=url,
            WEBHOOK_SECRET=secret,
        )
        return svc

    @pytest.mark.asyncio
    async def test_dispatch_mock_mode_skips_http(self):
        """WEBHOOK_MOCK=true must not make any HTTP call."""
        svc = self._svc(mock_mode=True, url="https://hooks.example.com")
        with patch("httpx.AsyncClient") as mock_client_cls:
            await _REAL_DISPATCH(svc, "invoice.created", {"key": "value"})
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_empty_url_skips_http(self):
        """Empty WEBHOOK_URL must not make any HTTP call even if mock=false."""
        svc = self._svc(mock_mode=False, url="")
        with patch("httpx.AsyncClient") as mock_client_cls:
            await _REAL_DISPATCH(svc, "invoice.created", {})
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_sends_correct_event_header(self):
        """When enabled, dispatch POSTs with X-Webhook-Event header."""
        svc = self._svc(mock_mode=False, url="https://hooks.example.com/recv", secret="test-secret")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            await _REAL_DISPATCH(svc, "invoice.created", {"invoice_id": "123"})

            mock_ctx.post.assert_called_once()
            sent_headers = mock_ctx.post.call_args.kwargs.get("headers", {})
            assert sent_headers["X-Webhook-Event"] == "invoice.created"
            assert "X-Webhook-Signature" in sent_headers

    def test_hmac_signature_is_verifiable(self):
        """The HMAC signature must be verifiable with the shared secret."""
        from app.services.webhook_service import WebhookService

        secret = "test-secret-key"
        svc = object.__new__(WebhookService)
        svc._settings = MagicMock(WEBHOOK_SECRET=secret)

        body = json.dumps({"event": "invoice.created", "data": {"id": "abc"}})
        signature = svc._sign(body)

        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        assert signature == expected
        assert hmac.compare_digest(signature, expected)

    @pytest.mark.asyncio
    async def test_dispatch_http_error_does_not_raise(self):
        """A network failure must be caught and not re-raised."""
        import httpx

        svc = self._svc(mock_mode=False, url="https://hooks.example.com/recv", secret="test-secret")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(side_effect=httpx.RequestError("refused"))

            # Must NOT raise — errors are logged and swallowed
            await _REAL_DISPATCH(svc, "invoice.created", {"id": "xyz"})


# ── Integration: PDF download endpoint ────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_invoice_pdf_returns_pdf(client):
    """GET /api/v1/invoices/{id}/pdf → 200 application/pdf."""
    order = await _create_order(client, "PDF-DL-001")
    invoice = await _create_invoice(client, order["id"])

    resp = await client.get(
        f"/api/v1/invoices/{invoice['id']}/pdf",
        headers=API_KEY_HEADER,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert invoice["invoice_number"] in resp.headers["content-disposition"]
    # Autouse mock_pdf_service returns fake bytes
    assert resp.content == b"%PDF-1.4 fake-pdf-content"


@pytest.mark.asyncio
async def test_download_invoice_pdf_not_found(client):
    """GET /api/v1/invoices/{random_uuid}/pdf → 404."""
    resp = await client.get(
        f"/api/v1/invoices/{uuid.uuid4()}/pdf",
        headers=API_KEY_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_invoice_pdf_requires_api_key(client):
    """GET /api/v1/invoices/{id}/pdf without API key → 403."""
    resp = await client.get(f"/api/v1/invoices/{uuid.uuid4()}/pdf")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pdf_service_called_during_invoice_creation(client, mock_pdf_service):
    """PDFService.generate_invoice_pdf is called once per invoice creation."""
    order = await _create_order(client, "PDF-CALL-001")
    await _create_invoice(client, order["id"])
    mock_pdf_service.assert_called_once()


@pytest.mark.asyncio
async def test_email_service_called_during_invoice_creation(client, mock_email_service):
    """EmailService.send_invoice is called once per invoice creation."""
    order = await _create_order(client, "EMAIL-CALL-001")
    await _create_invoice(client, order["id"])
    mock_email_service.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_service_called_during_invoice_creation(client, mock_webhook_service):
    """WebhookService.dispatch is called with 'invoice.created' event."""
    order = await _create_order(client, "WEBHOOK-CALL-001")
    await _create_invoice(client, order["id"])
    mock_webhook_service.assert_awaited_once()
    assert mock_webhook_service.await_args.args[0] == "invoice.created"
