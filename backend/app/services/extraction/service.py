from pathlib import Path

from app.models.resume import Resume
from app.services.extraction.exceptions import DocumentReadError
from app.services.extraction.models import ExtractionResult
from app.services.extraction.registry import (
    ExtractorRegistry,
    default_extractor_registry,
)
from app.services.storage import BaseStorageService, LocalStorageService


class DocumentExtractionService:
    """Service to coordinate resolving trusted storage paths and extracting plain text."""

    def __init__(
        self,
        storage_service: BaseStorageService | None = None,
        registry: ExtractorRegistry | None = None,
    ):
        self.storage_service = storage_service or LocalStorageService()
        self.registry = registry or default_extractor_registry

    def extract_from_resume(self, resume: Resume) -> ExtractionResult:
        """
        Extract plain text from a stored Resume entity using trusted storage key resolution.
        Never uses user-provided original filenames for filesystem access.
        """
        resolved_path = self.storage_service.resolve_path(resume.storage_key)
        if not resolved_path.is_file():
            raise DocumentReadError(
                f"Resume file not found in storage for key: '{resume.storage_key}'"
            )

        ext = Path(resume.storage_key).suffix
        extractor = self.registry.get_extractor(
            mime_type=resume.mime_type,
            extension=ext,
        )

        return extractor.extract(resolved_path)

    def extract_from_storage_key(
        self, storage_key: str, mime_type: str
    ) -> ExtractionResult:
        """
        Extract plain text from a trusted storage key and MIME type.
        """
        resolved_path = self.storage_service.resolve_path(storage_key)
        if not resolved_path.is_file():
            raise DocumentReadError(
                f"Document file not found in storage for key: '{storage_key}'"
            )

        ext = Path(storage_key).suffix
        extractor = self.registry.get_extractor(
            mime_type=mime_type,
            extension=ext,
        )

        return extractor.extract(resolved_path)
