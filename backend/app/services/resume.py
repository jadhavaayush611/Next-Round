import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.resume import Resume, ResumeStatus
from app.models.user import User
from app.repositories.resume import ResumeRepository
from app.services.storage import (
    BaseStorageService,
    LocalStorageService,
    StorageEmptyFileError,
    StorageLimitExceededError,
)

PDF_SIGNATURE = b"%PDF-"
DOCX_SIGNATURE = b"PK"


class ResumeService:
    def __init__(
        self,
        db: Session,
        storage_service: BaseStorageService | None = None,
    ):
        self.db = db
        self.resume_repo = ResumeRepository(db)
        self.storage_service = storage_service or LocalStorageService()

    def validate_file_metadata(self, file: UploadFile) -> tuple[str, str, str]:
        """
        Validates filename presence, extension whitelist, and allowed MIME types.
        Returns sanitized (original_filename, extension, mime_type).
        """
        if not file.filename or not file.filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is missing.",
            )

        # Extract base filename safely without path traversal artifacts (handling both / and \ separators)
        normalized_filename = file.filename.replace("\\", "/")
        original_filename = Path(normalized_filename).name
        if not original_filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename.",
            )

        ext = Path(original_filename).suffix.lower()
        if ext not in settings.ALLOWED_RESUME_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Only {', '.join(settings.ALLOWED_RESUME_EXTENSIONS)} are supported.",
            )

        mime_type = (file.content_type or "").lower().split(";")[0].strip()
        if mime_type not in settings.ALLOWED_RESUME_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported MIME type '{file.content_type}'. Allowed MIME types: {', '.join(settings.ALLOWED_RESUME_MIME_TYPES)}.",
            )

        # Ensure MIME type matches extension
        if ext == ".pdf" and mime_type != "application/pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MIME type does not match PDF file extension.",
            )
        if (
            ext == ".docx"
            and mime_type
            != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MIME type does not match DOCX file extension.",
            )

        return original_filename, ext, mime_type

    def validate_file_signature(self, file: UploadFile, ext: str) -> None:
        """
        Validates initial magic bytes to prevent MIME spoofing.
        """
        header = file.file.read(8)
        # Always rewind stream so subsequent reads get the full content
        file.file.seek(0)

        if not header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        if ext == ".pdf" and not header.startswith(PDF_SIGNATURE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file signature: Content does not match PDF format.",
            )
        elif ext == ".docx" and not header.startswith(DOCX_SIGNATURE):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file signature: Content does not match DOCX format.",
            )

    def upload_resume(self, user: User, file: UploadFile) -> Resume:
        """
        Validates, stores, and registers a new Resume record for the authenticated user.
        Rolls back database transaction and cleans up stored file on failure.
        """
        # 1. Metadata and extension / MIME validation
        original_filename, ext, mime_type = self.validate_file_metadata(file)

        # 2. Magic signature check
        self.validate_file_signature(file, ext)

        # 3. Determine next version and resume UUID
        latest_version = self.resume_repo.get_latest_version(user.id)
        next_version = latest_version + 1
        resume_id = uuid.uuid4()

        # 4. Generate safe storage key
        storage_key = f"users/{user.id}/resumes/{resume_id}{ext}"

        # 5. Persist file via storage service using chunked writes
        try:
            file_size = self.storage_service.save_file(
                storage_key=storage_key,
                file_obj=file.file,
                max_size_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
            )
        except StorageLimitExceededError:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
            ) from None
        except StorageEmptyFileError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            ) from None
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist uploaded file.",
            ) from exc

        # 6. Create database record
        resume = Resume(
            id=resume_id,
            user_id=user.id,
            original_filename=original_filename,
            storage_key=storage_key,
            mime_type=mime_type,
            file_size=file_size,
            version=next_version,
            status=ResumeStatus.UPLOADED,
        )

        try:
            return self.resume_repo.create_resume(resume)
        except Exception as exc:
            self.db.rollback()
            self.storage_service.delete_file(storage_key)
            raise exc
