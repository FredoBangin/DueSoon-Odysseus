from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from src.duesoon.documents.extract import (
    DocumentExtractionError,
    extract_document,
)


def test_extracts_bounded_plain_text_and_html() -> None:
    plain = extract_document(
        b"Exam Friday at 9 AM", filename="exam.txt", content_type="text/plain"
    )
    html = extract_document(
        b"<h1>Midterm</h1><p>Friday at 9 AM</p>",
        filename="midterm.html",
        content_type="text/html",
    )

    assert plain.text == "Exam Friday at 9 AM"
    assert html.text == "Midterm Friday at 9 AM"
    assert plain.format == "text"
    assert html.format == "html"


def test_extracts_docx_paragraphs_without_unbounded_zip_expansion() -> None:
    value = BytesIO()
    with ZipFile(value, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Project due Monday</w:t></w:r></w:p></w:body>
            </w:document>""",
        )

    result = extract_document(
        value.getvalue(),
        filename="syllabus.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    assert result.text == "[DOCX paragraph 1] Project due Monday"
    assert result.format == "docx"


def test_rejects_unsupported_or_oversized_documents() -> None:
    with pytest.raises(DocumentExtractionError, match="unsupported"):
        extract_document(
            b"binary", filename="archive.zip", content_type="application/zip"
        )
    with pytest.raises(DocumentExtractionError, match="size limit"):
        extract_document(
            b"12345", filename="notes.txt", content_type="text/plain", max_bytes=4
        )
