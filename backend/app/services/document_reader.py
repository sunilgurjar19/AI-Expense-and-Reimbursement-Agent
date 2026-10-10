"""Turns an uploaded file into text and/or images an LLM can read."""

import base64
import io
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader

from app.services.llm import ImagePart

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 1600

# pdfium is not thread-safe; all PDF parsing/rendering goes through this lock.
_PDF_LOCK = threading.Lock()


@dataclass
class DocumentContent:
    kind: str  # "pdf" | "image"
    text: str = ""
    images: list[ImagePart] = field(default_factory=list)
    pdf_b64: str | None = None
    page_count: int = 1


class DocumentReader:
    def __init__(self, render_dpi: int, max_pdf_pages: int) -> None:
        self._render_scale = render_dpi / 72
        self._max_pages = max_pdf_pages

    def read(self, path: Path, mime_type: str) -> DocumentContent:
        raw = path.read_bytes()
        if mime_type == "application/pdf" or path.suffix.lower() == ".pdf":
            with _PDF_LOCK:
                return self._read_pdf(raw)
        return DocumentContent(kind="image", images=[self._normalise_image(Image.open(io.BytesIO(raw)))])

    def _read_pdf(self, raw: bytes) -> DocumentContent:
        reader = PdfReader(io.BytesIO(raw))
        pages = reader.pages[: self._max_pages]
        text = "\n".join((page.extract_text() or "") for page in pages).strip()

        images: list[ImagePart] = []
        try:
            pdf = pdfium.PdfDocument(raw)
            for index in range(min(len(pdf), self._max_pages)):
                bitmap = pdf[index].render(scale=self._render_scale)
                images.append(self._normalise_image(bitmap.to_pil()))
        except pdfium.PdfiumError:
            logger.exception("Could not render PDF pages")

        return DocumentContent(
            kind="pdf",
            text=text,
            images=images,
            pdf_b64=base64.b64encode(raw).decode(),
            page_count=len(reader.pages),
        )

    @staticmethod
    def _normalise_image(image: Image.Image) -> ImagePart:
        """Fix orientation, downscale and re-encode as JPEG to keep payloads small."""
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return ImagePart(media_type="image/jpeg", data_b64=base64.b64encode(buffer.getvalue()).decode())
