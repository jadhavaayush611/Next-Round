import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.candidate_target import CandidateTarget
from app.repositories.base import BaseRepository


class CandidateTargetRepository(BaseRepository[CandidateTarget]):
    """Repository for managing CandidateTarget records and active/historical transitions."""

    def __init__(self, db: Session):
        super().__init__(CandidateTarget, db)

    def get_by_id(self, target_id: uuid.UUID) -> CandidateTarget | None:
        """Fetch candidate target by its primary key."""
        return self.get(target_id)

    def get_active_target(self, profile_id: uuid.UUID) -> CandidateTarget | None:
        """Fetch the currently active target for a given candidate profile."""
        query = select(self.model).where(
            self.model.candidate_profile_id == profile_id,
            self.model.is_active.is_(True),
        )
        return self.db.execute(query).scalars().first()

    def list_by_profile(
        self, profile_id: uuid.UUID, active_only: bool = False
    ) -> Sequence[CandidateTarget]:
        """List all targets belonging to a profile, ordered by creation time descending."""
        query = select(self.model).where(self.model.candidate_profile_id == profile_id)
        if active_only:
            query = query.where(self.model.is_active.is_(True))
        query = query.order_by(self.model.created_at.desc())
        return self.db.execute(query).scalars().all()

    def deactivate_all_for_profile(self, profile_id: uuid.UUID) -> int:
        """
        Deactivate any active target for the specified candidate profile.
        Returns the number of rows modified.
        """
        stmt = (
            update(self.model)
            .where(
                self.model.candidate_profile_id == profile_id,
                self.model.is_active.is_(True),
            )
            .values(is_active=False)
        )
        result = self.db.execute(stmt)
        count = getattr(result, "rowcount", 0)
        return int(count) if count is not None else 0
