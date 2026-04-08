"""
PDF generation service.

Primary engine: WeasyPrint (Linux/Docker — requires system Cairo/Pango/GTK).
Fallback engine: ReportLab (Windows and any environment without GTK libraries).

Detection is done once at import time via a try/except on the WeasyPrint import.
Both engines produce a byte string containing a valid PDF document.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.invoice import Invoice
from app.models.order import Order

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _strftime_filter(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


_jinja_env.filters["strftime"] = _strftime_filter

# ── Engine detection (done once at import time) ───────────────────────────────

try:
    from weasyprint import HTML as _WeasyHTML  # type: ignore[import-untyped]
    _WEASYPRINT_AVAILABLE = True
    logger.debug("PDF engine: WeasyPrint")
except OSError:
    _WEASYPRINT_AVAILABLE = False
    logger.warning(
        "WeasyPrint unavailable (missing GTK/Cairo system libraries) — "
        "falling back to ReportLab for PDF generation."
    )


# ── ReportLab helper ──────────────────────────────────────────────────────────

def _build_pdf_reportlab(invoice: Invoice, order: Order) -> bytes:
    """
    Generate an invoice PDF using ReportLab (pure-Python, no native deps).

    Produces a clean, professional document with the same information as the
    WeasyPrint/HTML path: header, client block, line-items table, totals, footer.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # ── Custom styles ─────────────────────────────────────────────────────────
    h1 = ParagraphStyle(
        "InvH1",
        parent=styles["Normal"],
        fontSize=22,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#16213e"),
        spaceAfter=2,
    )
    h3 = ParagraphStyle(
        "InvH3",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#94a3b8"),
        spaceAfter=4,
    )
    normal = ParagraphStyle(
        "InvNormal",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.HexColor("#374151"),
        leading=13,
    )
    bold9 = ParagraphStyle(
        "InvBold9",
        parent=normal,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e293b"),
    )
    small_gray = ParagraphStyle(
        "InvSmallGray",
        parent=normal,
        fontSize=7.5,
        textColor=colors.HexColor("#94a3b8"),
    )
    grand_total_style = ParagraphStyle(
        "InvGrandTotal",
        parent=styles["Normal"],
        fontSize=12,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f3460"),
    )

    W = A4[0] - 36 * mm  # usable width
    story = []

    # ── Header row ────────────────────────────────────────────────────────────
    issue = _strftime_filter(invoice.issue_date)
    due   = _strftime_filter(invoice.due_date)
    status_upper = str(invoice.status).upper()

    header_data = [
        [
            Paragraph("FACTURA", h1),
            Paragraph(
                f'<font size="14" color="#0f3460"><b>{invoice.invoice_number}</b></font><br/>'
                f'<font size="8" color="#6b7280">Emisión: {issue} &nbsp;&nbsp; Vencimiento: {due}</font><br/>'
                f'<font size="8" color="#6b7280">Moneda: {invoice.currency} &nbsp;&nbsp; Estado: {status_upper}</font>',
                normal,
            ),
        ]
    ]
    header_table = Table(header_data, colWidths=[W * 0.5, W * 0.5])
    header_table.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("ALIGN",        (1, 0), (1, 0),   "RIGHT"),
        ("LINEBELOW",    (0, 0), (-1, 0),  1.5, colors.HexColor("#16213e")),
        ("BOTTOMPADDING",(0, 0), (-1, 0),  10),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10 * mm))

    # ── Parties block ─────────────────────────────────────────────────────────
    tax_line = (
        f'<font size="7.5" color="#94a3b8">NIF/CIF:</font> {invoice.customer_tax_id}<br/>'
        if invoice.customer_tax_id else ""
    )
    ext_ref_lines = (
        f'<font size="7.5" color="#94a3b8">Ref. externa:</font><br/>'
        f'<font size="7.5">{invoice.external_invoice_id}</font><br/>'
        if invoice.external_invoice_id else ""
    )
    notes_line = (
        f'<font size="7.5" color="#94a3b8">Notas:</font> {invoice.notes}'
        if invoice.notes else ""
    )

    parties_data = [
        [
            [
                Paragraph("FACTURADO A", h3),
                Paragraph(f"<b>{invoice.customer_name}</b>", bold9),
                Paragraph(
                    f"{tax_line}"
                    f'<font size="7.5" color="#94a3b8">Email:</font> {invoice.customer_email}<br/>'
                    f'<font color="#4b5563">{invoice.billing_address}</font>',
                    normal,
                ),
            ],
            [
                Paragraph("REFERENCIA DE PEDIDO", h3),
                Paragraph(
                    f"{ext_ref_lines}"
                    f'<font size="7.5" color="#94a3b8">ID de pedido:</font><br/>'
                    f'<font size="7.5" color="#6b7280">{invoice.order_id}</font><br/>'
                    f"{notes_line}",
                    normal,
                ),
            ],
        ]
    ]
    parties_table = Table(parties_data, colWidths=[W * 0.5 - 3 * mm, W * 0.5 - 3 * mm])
    parties_table.setStyle(TableStyle([
        ("VALIGN",          (0, 0), (-1, -1), "TOP"),
        ("BOX",             (0, 0), (0, 0),   0.5, colors.HexColor("#e2e8f0")),
        ("BOX",             (1, 0), (1, 0),   0.5, colors.HexColor("#e2e8f0")),
        ("BACKGROUND",      (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING",     (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",    (0, 0), (-1, -1), 8),
        ("TOPPADDING",      (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",   (0, 0), (-1, -1), 8),
        ("COLPADDING",      (0, 0), (-1, -1), 3),
    ]))
    story.append(parties_table)
    story.append(Spacer(1, 8 * mm))

    # ── Line items table ──────────────────────────────────────────────────────
    story.append(Paragraph("DETALLE DE LÍNEAS", h3))

    col_widths = [W * 0.30, W * 0.07, W * 0.13, W * 0.08, W * 0.13, W * 0.13, W * 0.14]
    items_data = [
        [
            Paragraph("<b>Descripción / SKU</b>", small_gray),
            Paragraph("<b>Cant.</b>", small_gray),
            Paragraph("<b>Precio unit.</b>", small_gray),
            Paragraph("<b>IVA %</b>", small_gray),
            Paragraph("<b>Base impon.</b>", small_gray),
            Paragraph("<b>Cuota IVA</b>", small_gray),
            Paragraph("<b>Total línea</b>", small_gray),
        ]
    ]

    for item in order.items:
        tax_pct = f"{float(item.tax_rate) * 100:.0f}%"
        items_data.append([
            Paragraph(
                f"<b>{item.name}</b><br/>"
                f'<font size="7.5" color="#94a3b8">{item.sku}</font>',
                normal,
            ),
            Paragraph(str(item.quantity), normal),
            Paragraph(f"{float(item.unit_price):.2f}", normal),
            Paragraph(tax_pct, normal),
            Paragraph(f"{float(item.subtotal):.2f}", normal),
            Paragraph(f"{float(item.tax_amount):.2f}", normal),
            Paragraph(f"<b>{float(item.total):.2f}</b>", bold9),
        ])

    items_table = Table(items_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#16213e")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("TOPPADDING",    (0, 0), (-1, 0),  6),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        # Data rows
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 6 * mm))

    # ── Totals ────────────────────────────────────────────────────────────────
    cur = invoice.currency
    totals_data = [
        [
            "",
            Paragraph("Base imponible", normal),
            Paragraph(f"{float(invoice.subtotal):.2f} {cur}", normal),
        ],
        [
            "",
            Paragraph("IVA (cuota total)", normal),
            Paragraph(f"{float(invoice.tax_total):.2f} {cur}", normal),
        ],
        [
            "",
            Paragraph("<b>TOTAL</b>", grand_total_style),
            Paragraph(f"<b>{float(invoice.grand_total):.2f} {cur}</b>", grand_total_style),
        ],
    ]
    totals_table = Table(
        totals_data,
        colWidths=[W * 0.55, W * 0.25, W * 0.20],
    )
    totals_table.setStyle(TableStyle([
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("TEXTCOLOR",     (1, 0), (1, 1),   colors.HexColor("#6b7280")),
        ("LINEABOVE",     (1, 2), (-1, 2),  1.5, colors.HexColor("#16213e")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)

    # ── Notes ─────────────────────────────────────────────────────────────────
    if invoice.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("OBSERVACIONES", h3))
        story.append(Paragraph(invoice.notes, normal))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    footer_parts = ["Documento generado electrónicamente — válido sin firma manuscrita"]
    if invoice.external_invoice_id:
        footer_parts.append(f"EXT: {invoice.external_invoice_id}")
    story.append(Paragraph(
        ' &nbsp;&nbsp;|&nbsp;&nbsp; '.join(footer_parts),
        small_gray,
    ))

    doc.build(story)
    return buf.getvalue()


# ── Public service class ──────────────────────────────────────────────────────

class PDFService:
    """
    Renders an Invoice ORM object to a PDF byte string.

    Engine selection:
      - WeasyPrint: used when available (Linux/Docker with GTK system libraries).
      - ReportLab:  fallback on Windows or any environment without GTK.
    """

    def generate_invoice_pdf(self, invoice: Invoice, order: Order) -> bytes:
        """
        Generate a PDF for the given invoice and return it as raw bytes.

        Args:
            invoice: The Invoice ORM object (must have all fields populated).
            order:   The parent Order ORM object (provides the line items).

        Returns:
            PDF file content as bytes.
        """
        logger.debug(
            "Rendering PDF for invoice %s (%d line items) — engine=%s",
            invoice.invoice_number,
            len(order.items),
            "weasyprint" if _WEASYPRINT_AVAILABLE else "reportlab",
        )

        if _WEASYPRINT_AVAILABLE:
            template = _jinja_env.get_template("invoice.html")
            html_content = template.render(invoice=invoice, items=order.items)
            pdf_bytes: bytes = _WeasyHTML(string=html_content).write_pdf()
        else:
            pdf_bytes = _build_pdf_reportlab(invoice, order)

        logger.info(
            "PDF generated for invoice %s — %d bytes",
            invoice.invoice_number,
            len(pdf_bytes),
        )
        return pdf_bytes
