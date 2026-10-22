import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed_skills import SEED_SKILLS
from app.models.skill import Skill
from app.repositories.skill import SkillRepository
from app.schemas.skill import SkillCreate, SkillResponse, SkillUpdate
from app.utils.skill_normalization import clean_aliases, normalize_skill_name


class SkillAlreadyExistsError(Exception):
    """Raised when attempting to create a skill with an existing canonical name."""

    pass


class AliasCollisionError(Exception):
    """Raised when an alias collides with an existing canonical name or another skill's alias."""

    pass


class AmbiguousSkillError(Exception):
    """Raised when resolving a skill query that matches multiple conflicting skills."""

    pass


class SkillService:
    """
    Internal domain service for managing the shared Skill catalog.
    Provides deterministic name and alias normalization, collision prevention,
    and repeatable, non-destructive catalog seeding.
    """

    def __init__(self, db: Session):
        self.db = db
        self.skill_repo = SkillRepository(db)

    def create_skill(self, skill_in: SkillCreate) -> SkillResponse:
        """
        Create and persist a new canonical skill in the catalog.

        Validations:
        - Canonical name must not exist case-insensitively.
        - Canonical name must not collide with an existing skill's alias.
        - Proposed aliases must not collide with any existing canonical name or alias.
        """
        # 1. Check canonical name existence
        existing = self.skill_repo.get_by_canonical_name(skill_in.canonical_name)
        if existing:
            raise SkillAlreadyExistsError(
                f"Skill with canonical name '{skill_in.canonical_name}' already exists."
            )

        # 2. Check canonical name vs existing aliases
        alias_holder = self.skill_repo.find_by_alias(skill_in.canonical_name)
        if alias_holder:
            raise AliasCollisionError(
                f"Canonical name '{skill_in.canonical_name}' collides with alias "
                f"of existing skill '{alias_holder[0].canonical_name}'."
            )

        # 3. Check proposed aliases for collisions
        cleaned = clean_aliases(skill_in.aliases, skill_in.canonical_name)
        for alias in cleaned:
            # Check collision with existing canonical names
            canonical_holder = self.skill_repo.get_by_canonical_name(alias)
            if canonical_holder:
                raise AliasCollisionError(
                    f"Alias '{alias}' collides with canonical name of "
                    f"existing skill '{canonical_holder.canonical_name}'."
                )
            # Check collision with existing aliases
            existing_with_alias = self.skill_repo.find_by_alias(alias)
            if existing_with_alias:
                raise AliasCollisionError(
                    f"Alias '{alias}' collides with alias of "
                    f"existing skill '{existing_with_alias[0].canonical_name}'."
                )

        db_skill = Skill(
            canonical_name=skill_in.canonical_name,
            category=skill_in.category,
            aliases=cleaned,
        )
        try:
            created = self.skill_repo.create(db_skill)
        except IntegrityError as exc:
            self.db.rollback()
            raise SkillAlreadyExistsError(
                f"Skill with canonical name '{skill_in.canonical_name}' already exists."
            ) from exc
        return SkillResponse.model_validate(created)

    def get_skill(self, skill_id: uuid.UUID) -> SkillResponse:
        """Retrieve a skill by its UUID primary key."""
        skill = self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill not found in catalog.",
            )
        return SkillResponse.model_validate(skill)

    def get_by_canonical_name(self, name: str) -> SkillResponse | None:
        """Fetch a skill by its exact canonical name case-insensitively."""
        skill = self.skill_repo.get_by_canonical_name(name)
        if not skill:
            return None
        return SkillResponse.model_validate(skill)

    def resolve_skill(self, query: str) -> SkillResponse | None:
        """
        Deterministically resolve a raw user, resume, or requirement skill mention
        to its canonical Skill entity.

        Resolution order & ambiguity invariants:
        1. Query is normalized (whitespace collapsed, case-folded).
        2. If query matches both a canonical skill and an alias of another skill -> raise AmbiguousSkillError.
        3. If query matches aliases of multiple distinct skills -> raise AmbiguousSkillError.
        4. If query matches a canonical skill -> return it.
        5. If query matches exactly one skill via alias -> return it.
        6. Otherwise -> return None.
        """
        norm = normalize_skill_name(query)
        if not norm:
            return None

        canonical_match = self.skill_repo.get_by_canonical_name(query)
        alias_matches = self.skill_repo.find_by_alias(query)

        # Collision detection: canonical vs alias
        if canonical_match and alias_matches:
            for a_match in alias_matches:
                if a_match.id != canonical_match.id:
                    raise AmbiguousSkillError(
                        f"Ambiguous skill identifier '{query}': matches canonical skill "
                        f"'{canonical_match.canonical_name}' and alias of '{a_match.canonical_name}'."
                    )

        # Ambiguity detection: multiple alias matches for distinct skills
        if not canonical_match and len(alias_matches) > 1:
            distinct_ids = {s.id for s in alias_matches}
            if len(distinct_ids) > 1:
                names = sorted([s.canonical_name for s in alias_matches])
                raise AmbiguousSkillError(
                    f"Ambiguous skill query '{query}': matches multiple skills: {', '.join(names)}."
                )

        if canonical_match:
            return SkillResponse.model_validate(canonical_match)

        if alias_matches:
            return SkillResponse.model_validate(alias_matches[0])

        return None

    def list_skills(self, category: str | None = None) -> list[SkillResponse]:
        """List all canonical skills, optionally filtered by category."""
        skills = self.skill_repo.list_all(category=category)
        return [SkillResponse.model_validate(s) for s in skills]

    def list_categories(self) -> list[str]:
        """List all unique skill categories in the catalog."""
        return list(self.skill_repo.list_categories())

    def update_skill(
        self, skill_id: uuid.UUID, skill_update: SkillUpdate
    ) -> SkillResponse:
        """Update an existing skill's attributes while preserving uniqueness and collision safety."""
        skill = self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill not found in catalog.",
            )

        update_dict: dict[str, Any] = {}
        if skill_update.canonical_name is not None:
            existing = self.skill_repo.get_by_canonical_name(
                skill_update.canonical_name
            )
            if existing and existing.id != skill.id:
                raise SkillAlreadyExistsError(
                    f"Skill with canonical name '{skill_update.canonical_name}' already exists."
                )
            update_dict["canonical_name"] = skill_update.canonical_name

        if skill_update.category is not None:
            update_dict["category"] = skill_update.category

        if skill_update.aliases is not None:
            eff_canonical = skill_update.canonical_name or skill.canonical_name
            cleaned = clean_aliases(skill_update.aliases, eff_canonical)
            for a in cleaned:
                # Check collision with other skills' canonical names
                c = self.skill_repo.get_by_canonical_name(a)
                if c and c.id != skill.id:
                    raise AliasCollisionError(
                        f"Alias '{a}' collides with canonical name of '{c.canonical_name}'."
                    )
                # Check collision with other skills' aliases
                others = self.skill_repo.find_by_alias(a)
                for other in others:
                    if other.id != skill.id:
                        raise AliasCollisionError(
                            f"Alias '{a}' collides with alias of '{other.canonical_name}'."
                        )
            update_dict["aliases"] = cleaned

        try:
            updated = self.skill_repo.update(skill, update_dict)
        except IntegrityError as exc:
            self.db.rollback()
            raise SkillAlreadyExistsError(
                f"Skill with canonical name '{skill_update.canonical_name}' already exists."
            ) from exc
        return SkillResponse.model_validate(updated)

    def seed_catalog(self) -> list[SkillResponse]:
        """
        Populate the catalog with curated backend / software engineering skills.

        Invariants:
        - Repeatable and idempotent.
        - Never duplicates or overwrites existing entries.
        - If a skill already exists with that canonical name, it is preserved intact.
        """
        for entry in SEED_SKILLS:
            existing = self.skill_repo.get_by_canonical_name(entry["canonical_name"])
            if existing is None:
                db_skill = Skill(
                    canonical_name=entry["canonical_name"],
                    category=entry["category"],
                    aliases=clean_aliases(entry["aliases"], entry["canonical_name"]),
                )
                self.db.add(db_skill)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
        return self.list_skills()
