import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.skill import Skill
from app.repositories.base import BaseRepository
from app.utils.skill_normalization import normalize_skill_name


class SkillRepository(BaseRepository[Skill]):
    """Repository for querying, indexing, and persisting canonical skills and aliases."""

    def __init__(self, db: Session):
        super().__init__(Skill, db)

    def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        """Fetch skill by primary key UUID."""
        return self.get(skill_id)

    def get_by_canonical_name(self, name: str) -> Skill | None:
        """
        Fetch skill by canonical name using deterministic case-insensitive matching.
        """
        normalized = normalize_skill_name(name)
        if not normalized:
            return None
        stmt = select(self.model).where(
            func.lower(self.model.canonical_name) == normalized
        )
        return self.db.execute(stmt).scalars().first()

    def list_all(self, category: str | None = None) -> Sequence[Skill]:
        """List all canonical skills ordered alphabetically, optionally filtered by category."""
        stmt = select(self.model)
        if category is not None:
            norm_cat = normalize_skill_name(category)
            stmt = stmt.where(func.lower(self.model.category) == norm_cat)
        stmt = stmt.order_by(self.model.canonical_name.asc())
        return self.db.execute(stmt).scalars().all()

    def list_categories(self) -> Sequence[str]:
        """List all distinct skill categories ordered alphabetically."""
        stmt = (
            select(self.model.category).distinct().order_by(self.model.category.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def find_by_alias(self, alias: str) -> list[Skill]:
        """
        Find all skills in the catalog that contain the given alias (case-insensitively).
        Deterministic across both SQLite and PostgreSQL.
        """
        norm_alias = normalize_skill_name(alias)
        if not norm_alias:
            return []

        all_skills = self.db.execute(select(self.model)).scalars().all()
        matched: list[Skill] = []
        for skill in all_skills:
            aliases = skill.aliases or []
            for a in aliases:
                if normalize_skill_name(a) == norm_alias:
                    matched.append(skill)
                    break
        return matched

    def count(self) -> int:
        """Count total registered skills in the catalog."""
        stmt = select(func.count(self.model.id))
        result = self.db.execute(stmt).scalar_one_or_none()
        return result or 0
