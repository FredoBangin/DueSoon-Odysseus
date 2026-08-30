"""Bounded document extraction for academic evidence."""

from .extract import DocumentExtractionError, ExtractedDocument, extract_document

__all__ = ["DocumentExtractionError", "ExtractedDocument", "extract_document"]
