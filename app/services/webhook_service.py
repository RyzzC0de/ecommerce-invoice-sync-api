"""
Webhook dispatch service.

Sends a signed HTTP POST to the configured WEBHOOK_URL after key events
(e.g. invoice.created). The payload is signed with HMAC-SHA256 using
WEBHOOK_SECRET so receivers can verify authenticity.

Failures are logged but never re-raised — a webhook outage must not roll back
the primary business transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class WebhookService:
    """Dispatches HMAC-signed webhook events to the configured endpoint."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _sign(self, body: str) -> str:
        """Compute HMAC-SHA256 hex digest of *body* using WEBHOOK_SECRET."""
        return hmac.new(
            self._settings.WEBHOOK_SECRET.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def dispatch(self, event: str, payload: dict[str, Any]) -> None:
        """
        POST *payload* as JSON to WEBHOOK_URL with HMAC signature headers.

        Headers sent:
            X-Webhook-Event:     event name (e.g. "invoice.created")
            X-Webhook-Signature: hex(HMAC-SHA256(body, WEBHOOK_SECRET))
            Content-Type:        application/json

        When WEBHOOK_MOCK=true or WEBHOOK_URL is empty the call is skipped
        and only a log entry is written.

        Errors are caught, logged at ERROR level, and suppressed — the caller's
        transaction is never reverted due to a webhook failure.

        Args:
            event:   Dot-separated event name, e.g. "invoice.created".
            payload: Arbitrary JSON-serialisable dict to include in the body.
        """
        if self._settings.WEBHOOK_MOCK or not self._settings.WEBHOOK_URL:
            logger.warning(
                "WEBHOOK_MOCK=true or WEBHOOK_URL unset — skipping dispatch of '%s'",
                event,
            )
            return

        body = json.dumps({"event": event, "data": payload}, default=str)
        signature = self._sign(body)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event,
            "X-Webhook-Signature": signature,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self._settings.WEBHOOK_URL,
                    content=body,
                    headers=headers,
                )
                resp.raise_for_status()
                logger.info(
                    "Webhook '%s' dispatched to %s → HTTP %s",
                    event,
                    self._settings.WEBHOOK_URL,
                    resp.status_code,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Webhook '%s' failed (URL=%s): %s",
                event,
                self._settings.WEBHOOK_URL,
                exc,
            )
