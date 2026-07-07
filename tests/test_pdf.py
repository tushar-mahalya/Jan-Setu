import io

from PIL import Image

from jan_setu.pipeline.pdfgen import PdfSummary, build_grievance_pdf


def _summary(**overrides) -> PdfSummary:
    base = dict(
        human_id="JS-000123",
        created_at="2026-07-06T10:00:00+00:00",
        category_label="Roads & Potholes",
        department_name="Public Works Department",
        priority="normal",
        term="long_term",
        address="Shivajinagar, Pune",
        description="Large pothole near the main junction.",
        contact_phone="911234567890",
    )
    base.update(overrides)
    return PdfSummary(**base)


def _tiny_png_bytes() -> bytes:
    image = Image.new("RGB", (1, 1), color=(200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_build_grievance_pdf_without_photo_returns_pdf_bytes():
    pdf_bytes = build_grievance_pdf(_summary())

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")


def test_build_grievance_pdf_with_flags_returns_pdf_bytes():
    pdf_bytes = build_grievance_pdf(_summary(flags=["Duplicate window skipped"]))

    assert pdf_bytes.startswith(b"%PDF")


def test_build_grievance_pdf_with_photo_returns_pdf_bytes():
    pdf_bytes = build_grievance_pdf(_summary(), photo_bytes=_tiny_png_bytes())

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
