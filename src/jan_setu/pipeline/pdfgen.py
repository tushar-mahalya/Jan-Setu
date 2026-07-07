"""Generates the complaint-summary PDF the citizen reviews before confirming —
sent as a WhatsApp document on that channel, and offered as a download on the
web. fpdf2 is the only new dependency: a pure-Python PDF writer, no system
libs, versus hand-rolling PDF syntax.
"""

import io
from dataclasses import dataclass, field

from fpdf import FPDF

PDF_THUMBNAIL_MAX_PX = 800


@dataclass(frozen=True)
class PdfSummary:
    human_id: str
    created_at: str
    category_label: str
    department_name: str
    priority: str
    term: str
    address: str | None
    description: str
    contact_phone: str
    flags: list[str] = field(default_factory=list)


def _thumbnail_jpeg(photo_bytes: bytes) -> bytes | None:
    """Downscale the photo so the PDF stays well under WhatsApp document
    limits. Returns None if the bytes cannot be decoded as an image."""
    try:
        from PIL import Image
    except ImportError:
        return photo_bytes

    try:
        image = Image.open(io.BytesIO(photo_bytes))
        image.thumbnail((PDF_THUMBNAIL_MAX_PX, PDF_THUMBNAIL_MAX_PX))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=80)
        return buffer.getvalue()
    except Exception:
        return None


def build_grievance_pdf(summary: PdfSummary, photo_bytes: bytes | None = None) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Jan Setu - Complaint Summary", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    rows = [
        ("Ticket ID", summary.human_id),
        ("Filed at", summary.created_at),
        ("Contact", summary.contact_phone),
        ("Category", summary.category_label),
        ("Department", summary.department_name),
        ("Priority", summary.priority),
        ("Type of fix", summary.term.replace("_", " ")),
        ("Location", summary.address or "Not resolved"),
    ]
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(45, 8, f"{label}:")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 8, value, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Description", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, summary.description or "(no description provided)")

    if summary.flags:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 6, "Notes: " + "; ".join(summary.flags))

    if photo_bytes:
        thumbnail = _thumbnail_jpeg(photo_bytes)
        if thumbnail is not None:
            pdf.ln(4)
            pdf.image(io.BytesIO(thumbnail), w=100)

    return bytes(pdf.output())
