import enum

from pydantic import BaseModel


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
    extraction_issues: list[ExtractionIssue] = []
