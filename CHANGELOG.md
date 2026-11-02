# Changelog

All notable changes to the NextRound platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-07-27

### Added
- **Document Extraction Layer**: Modular, YAGNI-first text extraction system (`BaseDocumentExtractor`, `PDFExtractor`, `DOCXExtractor`) utilizing `pdfplumber` and `python-docx`.
- **Deterministic Extractor Registry**: Registry mapping `application/pdf` and OpenXML DOCX MIME types deterministically with strict `UnsupportedDocumentError` reporting.
- **Robust Text Normalizer**: Unified text normalization engine implementing Unicode NFKC normalization, whitespace sanitization, CRLF/CR unification, and paragraph structure preservation while protecting technical tokens (`C++`, `C#`, `.NET`, `Node.js`, `SQL`, URLs, emails).
- **Controlled Exception Model**: Domain-level exceptions (`DocumentExtractionError`, `UnsupportedDocumentError`, `DocumentReadError`, `DocumentContentError`) preventing raw library internals from escaping.
- **Storage-Bound DocumentExtractionService**: Trusted path resolution guaranteeing extraction uses internal storage keys rather than client filenames.
- **Extraction Test Suite**: 20 comprehensive unit and integration tests covering single/multi-page PDFs, scanned empty documents, paragraphs, tables in reading order, Unicode normalization, corrupt document recovery, and path traversal defense.

## [0.2.0] - 2026-07-26

### Added
- **Secure File Storage Abstraction**: Abstract `BaseStorageService` and `LocalStorageService` for decoupled, path-traversal resistant binary persistence outside application source code.
- **Resume Upload API**: Authenticated `POST /api/v1/resumes` accepting PDF and DOCX documents with automatic versioning (`latest_version + 1`) and `UPLOADED` initial status.
- **Strict Security & Signature Validation**: Lightweight magic-byte verification (`%PDF-` and `PK`), extension whitelist, MIME compatibility, non-empty checks, and streaming 5 MB upload size enforcement.
- **Transaction Rollback & Storage Cleanup**: Automatic database rollback and stored file deletion upon database persistence or commit failures.
- **Docker Persistence**: Persistent named volumes (`resume_uploads`, `resume_uploads_prod`) configured for local development and production container environments.
- **Security & Storage Test Suite**: 19 new unit and integration tests covering magic byte verification, MIME spoofing prevention, path traversal rejection, version incrementing, ownership isolation, and failure recovery.

## [0.1.0] - 2026-07-25

### Added
- **User Persistence**: Core PostgreSQL data models with SQLAlchemy 2.0 declarative mappings and Alembic migrations.
- **Authentication**: Secure registration and OAuth2 password flow login with Bcrypt password hashing.
- **JWT Authorization**: Token generation and validation via Bearer scheme with configurable expiration and secure subject claim handling.
- **User Profile Management**: Authenticated `GET /api/v1/users/me` and `PATCH /api/v1/users/me` endpoints for viewing and updating profile details (`name`, `full_name`, `username`).
- **Validation**: Strict Pydantic schemas enforcing username format constraints, non-empty update payloads, and rejection of immutable fields (`email`, `password_hash`, `role`, `is_active`, `created_at`).
- **Soft Deletion & Account Safety**: Support for soft-deleted accounts (`is_active=False`) with immediate rejection across authentication and protected routes.
- **CI & Testing Infrastructure**: Pytest test suite with SQLite in-memory test isolation, coverage for auth, permissions, persistence, and validation, plus unified monorepo verification scripts (`scripts/check_all.py`, `Makefile`, and `npm` scripts).
