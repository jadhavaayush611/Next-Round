import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.resume import Resume, ResumeStatus
from app.repositories.base import BaseRepository


class ResumeRepository(BaseRepository[Resume]):
    def __init__(self, db: Session):
        super().__init__(Resume, db)

    def create_resume(self, resume: Resume) -> Resume:
        """Persist a new Resume entity."""
        return self.create(resume)

    def get_by_id(self, resume_id: uuid.UUID) -> Resume | None:
        """Fetch a resume by its primary key ID."""
        return self.get(resume_id)

    def get_user_resume(
        self, resume_id: uuid.UUID, user_id: uuid.UUID
    ) -> Resume | None:
        """Fetch a specific resume belonging to the specified user."""
        query = select(self.model).where(
            self.model.id == resume_id, self.model.user_id == user_id
        )
        return self.db.execute(query).scalar_one_or_none()

    def list_user_resumes(
        self, user_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> Sequence[Resume]:
        """List all resumes belonging to a specific user, ordered by version descending."""
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.version.desc())
            .offset(skip)
            .limit(limit)
        )
        return self.db.execute(query).scalars().all()

    def get_latest_version(self, user_id: uuid.UUID) -> int:
        """Return the highest version number for a user's resumes, or 0 if none exist."""
        query = select(func.coalesce(func.max(self.model.version), 0)).where(
            self.model.user_id == user_id
        )
        result = self.db.execute(query).scalar_one()
        return int(result)

    def archive_resume(self, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume | None:
        """Archive a resume for a given user by updating status to ARCHIVED."""
        resume = self.get_user_resume(resume_id, user_id)
        if resume is None:
            return None
        resume.status = ResumeStatus.ARCHIVED
        resume.updated_at = datetime.now(UTC)
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume
