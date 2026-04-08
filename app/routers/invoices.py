"""
Invoices router: POST /invoices/create-from-order, GET /invoices, GET /invoices/{id}.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BillingSystemError
from app.core.limiter import limiter
from app.core.security import require_api_key
from app.db.database import get_db
from app.models.invoice import InvoiceStatus
from app.schemas.invoice_schema import (
    InvoiceCreateFromOrder,
    InvoiceListResponse,
    InvoiceResponse,
)
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/invoices", tags=["Invoices"])


def get_invoice_service(db: AsyncSession = Depends(get_db)) -> InvoiceService:
    return InvoiceService(db)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post(
    "/create-from-order",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create invoice from an existing order",
    description=(
        "Generates an invoice from a previously created order, snapshots all "
        "financial data, and syncs the invoice to the external billing system. "
        "Idempotent: calling this endpoint twice for the same order returns a 409."
    ),
)
@limiter.limit("10/minute")
async def create_invoice_from_order(
    request: Request,
    payload: InvoiceCreateFromOrder,
    svc: InvoiceService = Depends(get_invoice_service),
    _: str = Depends(require_api_key),
) -> InvoiceResponse:
    try:
        return await svc.create_from_order(payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except BillingSystemError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External billing system error: {exc.message}",
        ) from exc


@router.get(
    "",
    response_model=InvoiceListResponse,
    summary="List invoices",
)
async def list_invoices(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    invoice_status: Annotated[
        InvoiceStatus | None, Query(alias="status")
    ] = None,
    svc: InvoiceService = Depends(get_invoice_service),
    _: str = Depends(require_api_key),
) -> InvoiceListResponse:
    return await svc.list_invoices(
        page=page, page_size=page_size, status=invoice_status
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get a single invoice",
)
async def get_invoice(
    invoice_id: uuid.UUID,
    svc: InvoiceService = Depends(get_invoice_service),
    _: str = Depends(require_api_key),
) -> InvoiceResponse:
    try:
        return await svc.get_invoice(invoice_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/{invoice_id}/pdf",
    summary="Download invoice as PDF",
    description=(
        "Renders the invoice as a PDF using WeasyPrint and streams it as a "
        "file download. Requires a valid API key."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF file attachment",
        },
        404: {"description": "Invoice not found"},
    },
)
async def download_invoice_pdf(
    invoice_id: uuid.UUID,
    svc: InvoiceService = Depends(get_invoice_service),
    _: str = Depends(require_api_key),
) -> Response:
    try:
        pdf_bytes, invoice_number = await svc.get_invoice_pdf(invoice_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    filename = f"{invoice_number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
