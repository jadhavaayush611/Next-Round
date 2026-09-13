from abc import ABC, abstractmethod
from pathlib import Path

from app.services.extraction.models import ExtractedDocument, ExtractionResult


class BaseDocumentExtractor(ABC):
    """Abstract base contract for document extractors."""

    @property
    @abstractmethod
    def extractor_type(self) -> str:
        """Identifier for the extractor engine (e.g. 'pdf', 'docx')."""
        pass

    @abstractmethod
    def supports(self, mime_type: str, extension: str | None = None) -> bool:
        """Return True if this extractor can process the given MIME type or file extension."""
        pass

    @abstractmethod
    def extract(self, file_path: Path | str) -> ExtractionResult:
        """
        Extract plain text from the specified document path.
        Must raise DocumentReadError or DocumentContentError on failure.
        """
        pass

    def extract_document(self, file_path: Path | str) -> ExtractedDocument:
        """
        Extract structured ExtractedDocument with elements and numeric provenance.
        Extractors can override this for granular native structure extraction.
        """
        result = self.extract(file_path)
        return ExtractedDocument.from_extraction_result(result)
