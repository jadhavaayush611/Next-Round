import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.resume_parse import ParseStatus, ResumeParse
from app.models.user import User
from app.repositories.resume import ResumeRepository
from app.repositories.resume_parse import ResumeParseRepository
from app.schemas.canonical_resume import CanonicalResume
from app.schemas.resume_parse import CanonicalResumeResponse
from app.services.extraction.exceptions import (
    DocumentContentError,
    DocumentExtractionError,
    DocumentReadError,
    UnsupportedDocumentError,
)
from app.services.extraction.service import DocumentExtractionService
from app.services.parser.constants import (
    PARSER_VERSION,
    SCHEMA_VERSION,
)
from app.services.parser.parser import SemanticResumeParser
from app.services.storage import BaseStorageService, LocalStorageService

logger = logging.getLogger(__name__)


class ResumeParseService:
    """
    Coordinates synchronous resume semantic parsing, immutable snapshot persistence,
    idempotent re-parsing, and latest-successful canonical representation retrieval.
    """

    def __init__(
        self,
        db: Session,
        storage_service: BaseStorageService | None = None,
        extraction_service: DocumentExtractionService | None = None,
        parser: SemanticResumeParser | None = None,
    ):
        self.db = db
        self.resume_repo = ResumeRepository(db)
        self.parse_repo = ResumeParseRepository(db)
        self.storage_service = storage_service or LocalStorageService()
        self.extraction_service = extraction_service or DocumentExtractionService(
            storage_service=self.storage_service
        )
        self.parser = parser or SemanticResumeParser()

    def parse_resume(
        self,
        user: User,
        resume_id: uuid.UUID,
        parser_version: str = PARSER_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> ResumeParse:
        """
        Synchronously parses a candidate resume, validates the canonical representation,
        and persists an immutable parse snapshot.
        Enforces strict user ownership, idempotency for identical version dimensions,
        and safe error handling.
        """
        # 1. Verify resume existence and user ownership
        resume = self.resume_repo.get_user_resume(resume_id, user.id)
        if resume is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found.",
            )

        # 2. Check for an existing successful snapshot (Idempotency)
        existing_snapshot = self.parse_repo.get_successful_snapshot(
            resume_id=resume.id,
            resume_version=resume.version,
            parser_version=parser_version,
            schema_version=schema_version,
        )
        if existing_snapshot is not None:
            logger.info(
                "Reusing existing successful parse snapshot %s for resume %s (v%d)",
                existing_snapshot.id,
                resume.id,
                resume.version,
            )
            return existing_snapshot

        # 3. Extract structured document and perform semantic parsing
        try:
            extracted_doc = self.extraction_service.extract_document_from_resume(resume)
            canonical = self.parser.parse(extracted_doc)

            # 4. Validate canonical data via Pydantic model serialization
            canonical_dict = canonical.model_dump(mode="json")
            extraction_metadata: dict[str, Any] = {
                "extractor_type": extracted_doc.metadata.get(
                    "extractor_type", "document_extractor"
                ),
                "status": extracted_doc.metadata.get("status", "COMPLETE"),
                "character_count": len(extracted_doc.full_text),
                "element_count": len(extracted_doc.elements),
                "page_count": extracted_doc.metadata.get("page_count"),
                "paragraph_count": extracted_doc.metadata.get("paragraph_count"),
            }

            # 5. Persist successful immutable parse snapshot
            parse_snapshot = ResumeParse(
                resume_id=resume.id,
                resume_version=resume.version,
                parser_version=parser_version,
                schema_version=schema_version,
                status=ParseStatus.READY,
                canonical_data=canonical_dict,
                extraction_metadata=extraction_metadata,
                error_message=None,
            )
            return self.parse_repo.create_parse(parse_snapshot)

        except (
            DocumentExtractionError,
            DocumentReadError,
            DocumentContentError,
            UnsupportedDocumentError,
        ) as exc:
            sanitized_err = exc.message if hasattr(exc, "message") else str(exc)
            logger.warning(
                "Document extraction failure for resume %s: %s",
                resume.id,
                sanitized_err,
            )
            self._record_failed_parse(
                resume_id=resume.id,
                resume_version=resume.version,
                parser_version=parser_version,
                schema_version=schema_version,
                error_message=sanitized_err,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document extraction failed: {sanitized_err}",
            ) from None

        except Exception as exc:
            sanitized_err = (
                "An unexpected error occurred during resume semantic parsing."
            )
            logger.exception(
                "Unexpected semantic parsing failure for resume %s",
                resume.id,
            )
            self._record_failed_parse(
                resume_id=resume.id,
                resume_version=resume.version,
                parser_version=parser_version,
                schema_version=schema_version,
                error_message=str(exc)[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=sanitized_err,
            ) from None

    def get_latest_canonical(
        self, user: User, resume_id: uuid.UUID
    ) -> CanonicalResumeResponse:
        """
        Retrieves the latest successful canonical resume representation for the authenticated user.
        Validates JSONB snapshot through Pydantic CanonicalResume schema.
        """
        # 1. Verify resume existence and user ownership
        resume = self.resume_repo.get_user_resume(resume_id, user.id)
        if resume is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found.",
            )

        # 2. Retrieve latest successful snapshot
        latest_snapshot = self.parse_repo.get_latest_successful_parse(resume.id)
        if latest_snapshot is None or latest_snapshot.canonical_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No successful canonical parse snapshot found for this resume.",
            )

        # 3. Validate stored JSONB through Pydantic CanonicalResume model
        try:
            canonical_resume = CanonicalResume.model_validate(
                latest_snapshot.canonical_data
            )
        except Exception:
            logger.error(
                "Stored canonical JSONB failed schema validation for snapshot %s",
                latest_snapshot.id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stored canonical resume snapshot is corrupted or invalid.",
            ) from None

        return CanonicalResumeResponse(
            resume_id=resume.id,
            resume_version=latest_snapshot.resume_version,
            parser_version=latest_snapshot.parser_version,
            schema_version=latest_snapshot.schema_version,
            created_at=latest_snapshot.created_at,
            canonical_resume=canonical_resume,
        )

    def _record_failed_parse(
        self,
        resume_id: uuid.UUID,
        resume_version: int,
        parser_version: str,
        schema_version: str,
        error_message: str,
    ) -> ResumeParse:
        """Records a failed parse attempt in the database so failures remain audited and retryable."""
        try:
            failed_snapshot = ResumeParse(
                resume_id=resume_id,
                resume_version=resume_version,
                parser_version=parser_version,
                schema_version=schema_version,
                status=ParseStatus.FAILED,
                canonical_data=None,
                extraction_metadata=None,
                error_message=error_message[:1000],
            )
            return self.parse_repo.create_parse(failed_snapshot)
        except Exception:
            logger.exception("Failed to record failed parse snapshot in database")
            self.db.rollback()
            raise
