"""DocumentReader: PDF text layers and page renders, image normalisation."""

import base64
import io
import logging
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.services import document_reader
from app.services.document_reader import MAX_IMAGE_SIDE, DocumentReader
from tests.helpers import SAMPLES_DIR, text_pdf


@pytest.fixture
def reader() -> DocumentReader:
    return DocumentReader(render_dpi=72, max_pdf_pages=2)


def decoded(part) -> Image.Image:
    assert part.media_type == "image/jpeg"
    image = Image.open(io.BytesIO(base64.b64decode(part.data_b64)))
    assert image.format == "JPEG"
    return image


def save(tmp_path: Path, name: str, image: Image.Image, **params) -> Path:
    path = tmp_path / name
    image.save(path, **params)
    return path


class TestPdf:
    def test_sample_pdf_yields_text_a_page_render_and_the_original_bytes(self, reader):
        path = SAMPLES_DIR / "apollo_pharmacy_bill.pdf"
        content = reader.read(path, "application/pdf")

        assert content.kind == "pdf" and content.page_count == 1
        assert content.text.splitlines()[0] == "Apollo Pharmacy"
        assert "Total Amount Rs. 284.00" in content.text
        assert base64.b64decode(content.pdf_b64) == path.read_bytes()
        (page,) = content.images
        assert decoded(page).size == (595, 842)  # A4 at 72 dpi

    def test_render_resolution_follows_the_configured_dpi(self):
        content = DocumentReader(render_dpi=144, max_pdf_pages=1).read(SAMPLES_DIR / "uber_ride.pdf", "application/pdf")
        assert decoded(content.images[0]).size == (1131, 1600)  # 1190x1684 render, downscaled to 1600 max

    @pytest.mark.parametrize(("name", "mime"), [("receipt.pdf", "application/octet-stream"), ("receipt.bin", "application/pdf")])
    def test_pdfs_are_recognised_by_extension_or_mime_type(self, reader, tmp_path, name, mime):
        path = tmp_path / name
        path.write_bytes(text_pdf(["Cafe Mocha", "Total 120.00"]))
        content = reader.read(path, mime)
        assert content.kind == "pdf" and content.text == "Cafe Mocha\nTotal 120.00"

    def test_only_the_first_pages_are_read_but_all_are_counted(self, reader, tmp_path):
        writer = PdfWriter()
        for number in (1, 2, 3):
            writer.append(PdfReader(io.BytesIO(text_pdf([f"Page {number} heading", f"Line on page {number}"]))))
        path = tmp_path / "three-pages.pdf"
        with path.open("wb") as fh:
            writer.write(fh)

        content = reader.read(path, "application/pdf")

        assert content.page_count == 3 and len(content.images) == 2
        assert "Page 2 heading" in content.text and "Page 3" not in content.text

    def test_a_render_failure_still_returns_the_text_layer(self, reader, monkeypatch, caplog):
        def broken(_raw):
            raise pdfium.PdfiumError("cannot render")

        monkeypatch.setattr(document_reader.pdfium, "PdfDocument", broken)
        with caplog.at_level(logging.ERROR, logger="app.services.document_reader"):
            content = reader.read(SAMPLES_DIR / "starbucks_coffee.pdf", "application/pdf")
        assert content.images == [] and content.text.startswith("Starbucks Coffee")
        assert "Could not render PDF pages" in caplog.text


class TestImages:
    def test_photo_is_reencoded_as_a_single_jpeg(self, reader):
        content = reader.read(SAMPLES_DIR / "chai_point_photo.png", "image/png")
        assert (content.kind, content.text, content.pdf_b64, content.page_count) == ("image", "", None, 1)
        (image,) = content.images
        assert decoded(image).mode == "RGB"

    def test_large_images_are_downscaled_keeping_the_aspect_ratio(self, reader, tmp_path):
        path = save(tmp_path, "big.png", Image.new("RGB", (4000, 3000), "white"))
        assert decoded(reader.read(path, "image/png").images[0]).size == (MAX_IMAGE_SIDE, 1200)

    def test_small_images_are_not_upscaled(self, reader, tmp_path):
        path = save(tmp_path, "small.webp", Image.new("RGB", (320, 240), "white"))
        assert decoded(reader.read(path, "image/webp").images[0]).size == (320, 240)

    @pytest.mark.parametrize("mode", ["RGBA", "P", "L"])
    def test_any_colour_mode_becomes_rgb(self, reader, tmp_path, mode):
        path = save(tmp_path, f"{mode}.png", Image.new(mode, (50, 40)))
        assert decoded(reader.read(path, "image/png").images[0]).mode == "RGB"

    def test_exif_orientation_is_applied(self, reader, tmp_path):
        exif = Image.Exif()
        exif[0x0112] = 6  # "rotate 90 CW": phones store portrait shots like this
        path = save(tmp_path, "phone.jpg", Image.new("RGB", (300, 100), "white"), exif=exif.tobytes())
        assert decoded(reader.read(path, "image/jpeg").images[0]).size == (100, 300)

    def test_unreadable_bytes_raise_an_os_error(self, reader, tmp_path):
        path = tmp_path / "broken.png"
        path.write_bytes(b"definitely not an image")
        with pytest.raises(OSError):
            reader.read(path, "image/png")
