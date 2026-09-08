# Changelog

All notable changes to the NextRound platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-25

### Added
- **User Persistence**: Core PostgreSQL data models with SQLAlchemy 2.0 declarative mappings and Alembic migrations.
- **Authentication**: Secure registration and OAuth2 password flow login with Bcrypt password hashing.
- **JWT Authorization**: Token generation and validation via Bearer scheme with configurable expiration and secure subject claim handling.
- **User Profile Management**: Authenticated `GET /api/v1/users/me` and `PATCH /api/v1/users/me` endpoints for viewing and updating profile details (`name`, `full_name`, `username`).
- **Validation**: Strict Pydantic schemas enforcing username format constraints, non-empty update payloads, and rejection of immutable fields (`email`, `password_hash`, `role`, `is_active`, `created_at`).
- **Soft Deletion & Account Safety**: Support for soft-deleted accounts (`is_active=False`) with immediate rejection across authentication and protected routes.
- **CI & Testing Infrastructure**: Pytest test suite with SQLite in-memory test isolation, coverage for auth, permissions, persistence, and validation, plus unified monorepo verification scripts (`scripts/check_all.py`, `Makefile`, and `npm` scripts).
