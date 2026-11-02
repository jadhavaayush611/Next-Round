class DocumentExtractionError(Exception):
    """Base exception for all document extraction errors."""

    pass


class UnsupportedDocumentError(DocumentExtractionError):
    """Raised when the document MIME type or extension is unsupported."""

    pass


class DocumentReadError(DocumentExtractionError):
    """Raised when the document file cannot be found, accessed, or read from storage."""

    pass


class DocumentContentError(DocumentExtractionError):
    """Raised when document content is corrupted, malformed, or unparseable."""

    pass
