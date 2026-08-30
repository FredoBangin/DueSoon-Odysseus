"""Bounded, non-executing text extraction for supported academic documents."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
SUPPORTED_CONTENT_TYPES = frozenset(
    {"application/pdf", DOCX_CONTENT_TYPE, "text/html", "text/plain"}
)
DEFAULT_MAX_BYTES = 8_000_000
DEFAULT_MAX_CHARS = 12_000
MAX_PDF_PAGES = 100
MAX_DOCX_XML_BYTES = 16_000_000
MAX_ZIP_RATIO = 100


class DocumentExtractionError(RuntimeError):
    """Safe document rejection without source content in the message."""


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    format: str
    locator_scheme: str
    truncated: bool


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def extract_document(
    data: bytes,
    *,
    filename: str,
    content_type: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ExtractedDocument:
    """Extract inert text from a supported bounded document."""

    if not data:
        raise DocumentExtractionError("document is empty")
    if len(data) > max_bytes:
        raise DocumentExtractionError("document exceeds size limit")
    normalized_type = content_type.split(";", 1)[0].strip().casefold()
    if normalized_type not in SUPPORTED_CONTENT_TYPES:
        raise DocumentExtractionError("unsupported document type")

    if normalized_type == "application/pdf":
        text, locator = _pdf_text(data), "pdf_page"
        format_name = "pdf"
    elif normalized_type == DOCX_CONTENT_TYPE:
        text, locator = _docx_text(data), "docx_paragraph"
        format_name = "docx"
    elif normalized_type == "text/html":
        text, locator = _html_text(data), "document_text"
        format_name = "html"
    else:
        text, locator = _decode_text(data), "document_text"
        format_name = "text"

    normalized = re.sub(r"[ \t\f\v]+", " ", text)
    normalized = re.sub(r" *\n+ *", "\n", normalized).strip()
    if not normalized:
        raise DocumentExtractionError("document contains no extractable text")
    truncated = len(normalized) > max_chars
    return ExtractedDocument(
        text=normalized[:max_chars],
        format=format_name,
        locator_scheme=locator,
        truncated=truncated,
    )


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _html_text(data: bytes) -> str:
    parser = _HTMLText()
    try:
        parser.feed(_decode_text(data))
    except Exception as exc:
        raise DocumentExtractionError("invalid HTML document") from exc
    return " ".join(parser.parts)


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentExtractionError("encrypted PDF is unsupported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentExtractionError("PDF exceeds page limit")
        parts = []
        for number, page in enumerate(reader.pages, start=1):
            value = page.extract_text() or ""
            if value.strip():
                parts.append(f"[PDF page {number}] {value.strip()}")
        return "\n".join(parts)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("invalid PDF document") from exc


def _docx_text(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.flag_bits & 0x1:
                raise DocumentExtractionError("encrypted DOCX is unsupported")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise DocumentExtractionError("DOCX content exceeds size limit")
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / info.compress_size > MAX_ZIP_RATIO
            ):
                raise DocumentExtractionError("DOCX compression ratio is unsafe")
            document_xml = archive.read(info)
    except DocumentExtractionError:
        raise
    except (BadZipFile, KeyError, OSError) as exc:
        raise DocumentExtractionError("invalid DOCX document") from exc

    paragraphs: list[str] = []
    for block in re.findall(rb"<w:p(?:\s[^>]*)?>(.*?)</w:p>", document_xml, re.DOTALL):
        runs = re.findall(rb"<w:t(?:\s[^>]*)?>(.*?)</w:t>", block, re.DOTALL)
        text = "".join(html.unescape(_decode_text(item)) for item in runs).strip()
        if text:
            paragraphs.append(f"[DOCX paragraph {len(paragraphs) + 1}] {text}")
    return "\n".join(paragraphs)
