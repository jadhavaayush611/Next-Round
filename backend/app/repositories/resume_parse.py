import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resume_parse import ParseStatus, ResumeParse
from app.repositories.base import BaseRepository


class ResumeParseRepository(BaseRepository[ResumeParse]):
    """Repository for managing ResumeParse persistence and query operations."""

    def __init__(self, db: Session):
        super().__init__(ResumeParse, db)

    def create_parse(self, parse: ResumeParse) -> ResumeParse:
        """Persist a new ResumeParse record."""
        return self.create(parse)

    def get_by_id(self, parse_id: uuid.UUID) -> ResumeParse | None:
        """Fetch a parse record by its primary key ID."""
        return self.get(parse_id)

    def get_successful_snapshot(
        self,
        resume_id: uuid.UUID,
        resume_version: int,
        parser_version: str,
        schema_version: str,
    ) -> ResumeParse | None:
        """
        Fetch an existing successful (READY) parse snapshot matching the exact version dimensions.
        Used to ensure idempotent parsing without creating duplicate snapshots.
        """
        query = (
            select(self.model)
            .where(
                self.model.resume_id == resume_id,
                self.model.resume_version == resume_version,
                self.model.parser_version == parser_version,
                self.model.schema_version == schema_version,
                self.model.status == ParseStatus.READY,
            )
            .order_by(self.model.created_at.desc())
        )
        return self.db.execute(query).scalars().first()

    def get_latest_successful_parse(self, resume_id: uuid.UUID) -> ResumeParse | None:
        """
        Retrieve the latest successful (READY) parse snapshot for a resume.
        Ordered deterministically by snapshot creation timestamp descending.
        """
        query = (
            select(self.model)
            .where(
                self.model.resume_id == resume_id,
                self.model.status == ParseStatus.READY,
            )
            .order_by(self.model.created_at.desc())
        )
        return self.db.execute(query).scalars().first()

    def list_by_resume(self, resume_id: uuid.UUID) -> Sequence[ResumeParse]:
        """List all parse records (historical, failed, ready) for a given resume."""
        query = (
            select(self.model)
            .where(self.model.resume_id == resume_id)
            .order_by(self.model.created_at.desc())
        )
        return self.db.execute(query).scalars().all()
