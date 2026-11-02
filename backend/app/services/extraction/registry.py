from app.services.extraction.base import BaseDocumentExtractor
from app.services.extraction.docx import DOCXExtractor
from app.services.extraction.exceptions import UnsupportedDocumentError
from app.services.extraction.pdf import PDFExtractor


class ExtractorRegistry:
    """Deterministic registry for selecting document extractors."""

    def __init__(self, extractors: list[BaseDocumentExtractor] | None = None):
        self._extractors: list[BaseDocumentExtractor] = extractors or [
            PDFExtractor(),
            DOCXExtractor(),
        ]

    def register(self, extractor: BaseDocumentExtractor) -> None:
        """Register a new extractor."""
        self._extractors.append(extractor)

    def get_extractor(
        self, mime_type: str, extension: str | None = None
    ) -> BaseDocumentExtractor:
        """
        Deterministically selects an extractor matching the MIME type or extension.
        Raises UnsupportedDocumentError if no matching extractor is found.
        """
        for extractor in self._extractors:
            if extractor.supports(mime_type, extension):
                return extractor

        raise UnsupportedDocumentError(
            f"Unsupported document format with MIME type '{mime_type}' and extension '{extension}'."
        )


default_extractor_registry = ExtractorRegistry()
