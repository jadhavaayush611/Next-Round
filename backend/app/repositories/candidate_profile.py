import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.candidate_profile import CandidateProfile
from app.repositories.base import BaseRepository


class CandidateProfileRepository(BaseRepository[CandidateProfile]):
    """Repository for managing CandidateProfile persistence operations."""

    def __init__(self, db: Session):
        super().__init__(CandidateProfile, db)

    def get_by_user_id(
        self, user_id: uuid.UUID, load_targets: bool = False
    ) -> CandidateProfile | None:
        """Fetch candidate profile by the owner's user_id."""
        query = select(self.model).where(self.model.user_id == user_id)
        if load_targets:
            query = query.options(selectinload(self.model.targets))
        return self.db.execute(query).scalars().first()

    def get_by_id(
        self, profile_id: uuid.UUID, load_targets: bool = False
    ) -> CandidateProfile | None:
        """Fetch candidate profile by primary key."""
        if not load_targets:
            return self.get(profile_id)
        query = (
            select(self.model)
            .where(self.model.id == profile_id)
            .options(selectinload(self.model.targets))
        )
        return self.db.execute(query).scalars().first()
