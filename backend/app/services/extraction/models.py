import enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.canonical_resume import Provenance

__all__ = [
    "ExtractionStatus",
    "ExtractionIssue",
    "ExtractionResult",
    "Provenance",
    "ExtractedElement",
    "ExtractedDocument",
]


class ExtractionStatus(enum.StrEnum):
    """Represents the status/completeness of a document text extraction."""

    COMPLETE = "COMPLETE"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"


class ExtractionIssue(BaseModel):
    """Identifies a specific portion of a document that could not be extracted."""

    location_type: str  # e.g., "page", "paragraph", "table", "element"
    location: int  # Numeric index (1-based) of the failed portion
    reason: str  # Concise explanation of the extraction failure


class ExtractionResult(BaseModel):
    """Represents the normalized plain text extraction result from a document."""

    text: str
    character_count: int
    extractor_type: str
    status: ExtractionStatus
    page_count: int | None = None
    paragraph_count: int | None = None
    extraction_issues: list[ExtractionIssue] = Field(default_factory=list)


class ExtractedElement(BaseModel):
    """Represents an atomic extracted structural element (e.g. paragraph, table row, block)."""

    element_id: int  # 1-based sequential element identifier
    page_number: int | None = None  # 1-based page number if available
    order: int  # 1-based document reading order
    element_type: str = "paragraph"  # "paragraph", "table_row", "heading", "block"
    text: str  # Normalized text content of this element
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def provenance(self) -> Provenance:
        """Derive numeric provenance for this extracted element."""
        return Provenance(
            page=self.page_number,
            element=self.element_id,
            order=self.order,
        )


class ExtractedDocument(BaseModel):
    """
    Generic, structured document abstraction produced by extraction and consumed by semantic parsing.
    Completely decoupled from underlying document formats (PDF/DOCX).
    """

    elements: list[ExtractedElement] = Field(default_factory=list)
    full_text: str = ""
    extraction_issues: list[ExtractionIssue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        text: str,
        page_number: int | None = None,
        issues: list[ExtractionIssue] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ExtractedDocument":
        """
        Build an ExtractedDocument from a raw or normalized text string by breaking it
        into paragraph blocks and generating numeric provenance elements.
        """
        from app.services.extraction.normalizer import normalize_text

        normalized_full = normalize_text(text)
        if not normalized_full:
            return cls(
                elements=[],
                full_text="",
                extraction_issues=issues or [],
                metadata=metadata or {},
            )

        # Split on double newlines to form structural elements (paragraphs)
        raw_blocks = [b.strip() for b in normalized_full.split("\n\n") if b.strip()]
        elements: list[ExtractedElement] = []
        for idx, block in enumerate(raw_blocks, start=1):
            elements.append(
                ExtractedElement(
                    element_id=idx,
                    page_number=page_number,
                    order=idx,
                    element_type="paragraph",
                    text=block,
                )
            )

        return cls(
            elements=elements,
            full_text=normalized_full,
            extraction_issues=issues or [],
            metadata=metadata or {},
        )

    @classmethod
    def from_extraction_result(
        cls,
        result: ExtractionResult,
        metadata: dict[str, Any] | None = None,
    ) -> "ExtractedDocument":
        """Build an ExtractedDocument from an ExtractionResult."""
        meta = metadata or {}
        meta["extractor_type"] = result.extractor_type
        meta["status"] = result.status.value
        if result.page_count is not None:
            meta["page_count"] = result.page_count
        if result.paragraph_count is not None:
            meta["paragraph_count"] = result.paragraph_count

        return cls.from_text(
            text=result.text,
            issues=result.extraction_issues,
            metadata=meta,
        )
