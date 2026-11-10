import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.competency import Competency, CompetencyDimension
from app.repositories.competency import CompetencyRepository
from app.repositories.skill import SkillRepository
from app.schemas.competency import (
    CompetencyCreate,
    CompetencyResponse,
    CompetencyUpdate,
)
from app.utils.skill_normalization import normalize_skill_name


class CompetencyServiceError(Exception):
    """Base exception for competency service errors."""

    pass


class CompetencyNotFoundError(CompetencyServiceError):
    """Raised when a requested competency does not exist."""

    pass


class CompetencyAlreadyExistsError(CompetencyServiceError):
    """Raised when creating a competency with an already registered identifier."""

    pass


class SkillNotFoundError(CompetencyServiceError):
    """Raised when linking a competency to a non-existent canonical skill."""

    pass


class SkillNameCollisionError(CompetencyServiceError):
    """Raised when a competency name or identifier merely duplicates a canonical skill name or alias."""

    pass


class CompetencyValidationError(CompetencyServiceError):
    """Raised when a competency lifecycle or state modification violates domain rules."""

    pass


class CompetencyService:
    """
    Internal domain service for managing the technical Competency catalog.
    Enforces grounding against canonical Skills, identifier uniqueness,
    and clear semantic separation from skill synonyms.
    """

    def __init__(self, db: Session):
        self.db = db
        self.competency_repo = CompetencyRepository(db)
        self.skill_repo = SkillRepository(db)

    def create_competency(self, competency_in: CompetencyCreate) -> CompetencyResponse:
        """
        Create and persist a new technical competency.

        Validations:
        - Referenced canonical Skill must exist.
        - Identifier must be globally unique (case-insensitive).
        - Competency name/identifier must not duplicate canonical skill name or aliases.
        """
        # 1. Validate canonical skill exists
        skill = self.skill_repo.get_by_id(competency_in.skill_id)
        if not skill:
            raise SkillNotFoundError(
                f"Canonical skill with id '{competency_in.skill_id}' does not exist."
            )

        # 2. Check identifier uniqueness
        existing = self.competency_repo.get_by_identifier(competency_in.identifier)
        if existing:
            raise CompetencyAlreadyExistsError(
                f"Competency with identifier '{competency_in.identifier}' already exists."
            )

        # 3. Ensure competency does not simply duplicate skill name or aliases
        norm_comp_id = normalize_skill_name(competency_in.identifier)
        norm_comp_name = normalize_skill_name(competency_in.name)
        norm_skill_canonical = normalize_skill_name(skill.canonical_name)
        skill_aliases = [normalize_skill_name(a) for a in (skill.aliases or [])]

        if norm_comp_id in [norm_skill_canonical, *skill_aliases]:
            raise SkillNameCollisionError(
                f"Competency identifier '{competency_in.identifier}' duplicates canonical skill name or alias."
            )
        if norm_comp_name in [norm_skill_canonical, *skill_aliases]:
            raise SkillNameCollisionError(
                f"Competency name '{competency_in.name}' duplicates canonical skill name or alias."
            )

        # 4. Persist competency
        db_obj = Competency(
            skill_id=competency_in.skill_id,
            identifier=competency_in.identifier,
            name=competency_in.name,
            description=competency_in.description,
            dimension=competency_in.dimension,
            is_active=competency_in.is_active,
        )
        try:
            created = self.competency_repo.create(db_obj)
        except IntegrityError as exc:
            self.db.rollback()
            raise CompetencyAlreadyExistsError(
                f"Competency with identifier '{competency_in.identifier}' already exists."
            ) from exc

        return self._to_response(created)

    def get_competency(self, competency_id: uuid.UUID) -> CompetencyResponse:
        """Fetch competency by primary key ID."""
        competency = self.competency_repo.get_by_id(competency_id)
        if not competency:
            raise CompetencyNotFoundError(
                f"Competency with id '{competency_id}' not found."
            )
        return self._to_response(competency)

    def get_by_identifier(self, identifier: str) -> CompetencyResponse:
        """Fetch competency by unique identifier string."""
        competency = self.competency_repo.get_by_identifier(identifier)
        if not competency:
            raise CompetencyNotFoundError(
                f"Competency with identifier '{identifier}' not found."
            )
        return self._to_response(competency)

    def list_competencies(
        self,
        skill_id: uuid.UUID | None = None,
        dimension: CompetencyDimension | None = None,
        is_active: bool | None = None,
    ) -> list[CompetencyResponse]:
        """List competencies with optional skill, dimension, and active state filters."""
        records: Sequence[Competency] = self.competency_repo.list_all(
            skill_id=skill_id, dimension=dimension, is_active=is_active
        )
        return [self._to_response(c) for c in records]

    def update_competency(
        self, competency_id: uuid.UUID, update_in: CompetencyUpdate
    ) -> CompetencyResponse:
        """Update fields of an existing competency."""
        competency = self.competency_repo.get_by_id(competency_id)
        if not competency:
            raise CompetencyNotFoundError(
                f"Competency with id '{competency_id}' not found."
            )

        update_dict: dict[str, Any] = {}
        if update_in.name is not None:
            # Check collision with skill
            norm_name = normalize_skill_name(update_in.name)
            skill = competency.skill
            if skill:
                norm_skill = normalize_skill_name(skill.canonical_name)
                skill_aliases = [normalize_skill_name(a) for a in (skill.aliases or [])]
                if norm_name in [norm_skill, *skill_aliases]:
                    raise SkillNameCollisionError(
                        f"Competency name '{update_in.name}' duplicates canonical skill name or alias."
                    )
            update_dict["name"] = update_in.name

        if update_in.description is not None:
            update_dict["description"] = update_in.description
        if update_in.dimension is not None:
            update_dict["dimension"] = update_in.dimension
        if update_in.is_active is not None:
            if update_in.is_active is False:
                published_refs = (
                    self.competency_repo.get_published_assessment_references(
                        competency_id
                    )
                )
                if published_refs:
                    refs_str = ", ".join(sorted(published_refs))
                    raise CompetencyValidationError(
                        f"Cannot deactivate competency '{competency.identifier}' because it is referenced by active published assessment(s): {refs_str}. Deprecate dependent assessments before retiring this competency."
                    )
            update_dict["is_active"] = update_in.is_active

        updated = self.competency_repo.update(competency, update_dict)
        return self._to_response(updated)

    def _to_response(self, competency: Competency) -> CompetencyResponse:
        """Map ORM Competency to validated schema response."""
        skill_name = competency.skill.canonical_name if competency.skill else None
        return CompetencyResponse(
            id=competency.id,
            skill_id=competency.skill_id,
            identifier=competency.identifier,
            name=competency.name,
            description=competency.description,
            dimension=competency.dimension,
            is_active=competency.is_active,
            created_at=competency.created_at,
            updated_at=competency.updated_at,
            skill_canonical_name=skill_name,
        )
