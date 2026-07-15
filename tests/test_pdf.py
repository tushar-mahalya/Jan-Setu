import io
from importlib.resources import files

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


def test_build_grievance_pdf_supports_mixed_hindi_and_english():
    pdf_bytes = build_grievance_pdf(
        _summary(
            category_label="सड़क एवं गड्ढे / Roads & Potholes",
            department_name="लोक निर्माण विभाग",
            address="राजीव चौक, नई दिल्ली",
            description="मुख्य सड़क पर बड़ा गड्ढा है। कृपया जल्द मरम्मत करें।",
            flags=["स्थान नागरिक द्वारा सत्यापित", "Priority review"],
        )
    )

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1_000


def test_build_grievance_pdf_supports_hindi_with_photo():
    pdf_bytes = build_grievance_pdf(
        _summary(description="सड़क पर पानी भरा हुआ है।"),
        photo_bytes=_tiny_png_bytes(),
    )

    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_font_assets_are_packaged():
    font_root = files("jan_setu.assets.fonts")
    required = {
        "NotoSans-Regular.ttf",
        "NotoSans-Bold.ttf",
        "NotoSansDevanagari-Regular.ttf",
        "NotoSansDevanagari-Bold.ttf",
        "OFL-NotoSans.txt",
        "OFL-NotoSansDevanagari.txt",
    }

    assert all(font_root.joinpath(filename).is_file() for filename in required)
