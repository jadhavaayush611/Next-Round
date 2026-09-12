from pathlib import Path

import pdfplumber

from app.services.extraction.base import BaseDocumentExtractor
from app.services.extraction.exceptions import DocumentContentError, DocumentReadError
from app.services.extraction.models import (
    ExtractionIssue,
    ExtractionResult,
    ExtractionStatus,
)
from app.services.extraction.normalizer import normalize_text


class PDFExtractor(BaseDocumentExtractor):
    """Local PDF text extractor utilizing pdfplumber."""

    SUPPORTED_MIME_TYPES = {"application/pdf"}
    SUPPORTED_EXTENSIONS = {".pdf"}

    @property
    def extractor_type(self) -> str:
        return "pdf"

    def supports(self, mime_type: str, extension: str | None = None) -> bool:
        norm_mime = (mime_type or "").lower().split(";")[0].strip()
        if norm_mime in self.SUPPORTED_MIME_TYPES:
            return True
        if extension:
            norm_ext = (
                extension.lower()
                if extension.startswith(".")
                else f".{extension.lower()}"
            )
            if norm_ext in self.SUPPORTED_EXTENSIONS:
                return True
        return False

    def extract(self, file_path: Path | str) -> ExtractionResult:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise DocumentReadError(f"PDF document not found at: {path}")

        try:
            with pdfplumber.open(path) as pdf:
                page_texts: list[str] = []
                issues: list[ExtractionIssue] = []
                for idx, page in enumerate(pdf.pages, start=1):
                    try:
                        extracted = page.extract_text()
                        if extracted:
                            page_texts.append(extracted)
                        else:
                            page_texts.append("")
                    except Exception as exc:
                        issues.append(
                            ExtractionIssue(
                                location_type="page",
                                location=idx,
                                reason=f"Failed to extract text from page {idx}: {exc}",
                            )
                        )
                        page_texts.append("")

                raw_text = "\n\n".join(page_texts)
                normalized = normalize_text(raw_text)

                if issues:
                    if normalized:
                        status = ExtractionStatus.PARTIAL
                    else:
                        raise DocumentContentError(
                            "All PDF pages failed to extract content."
                        )
                else:
                    if normalized:
                        status = ExtractionStatus.COMPLETE
                    else:
                        status = ExtractionStatus.EMPTY

                return ExtractionResult(
                    text=normalized,
                    character_count=len(normalized),
                    extractor_type=self.extractor_type,
                    status=status,
                    page_count=len(pdf.pages),
                    extraction_issues=issues,
                )
        except (FileNotFoundError, PermissionError) as exc:
            raise DocumentReadError(f"Failed to access PDF document: {exc}") from None
        except DocumentContentError:
            raise
        except Exception as exc:
            raise DocumentContentError(
                f"Failed to extract text from PDF document: {exc}"
            ) from None
