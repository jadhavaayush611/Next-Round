import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.competency import Competency, CompetencyDimension
from app.models.skill import Skill
from app.repositories.competency import CompetencyRepository
from app.schemas.competency import (
    CompetencyCreate,
    CompetencyUpdate,
)
from app.services.competency_service import (
    CompetencyAlreadyExistsError,
    CompetencyNotFoundError,
    CompetencyService,
    SkillNameCollisionError,
    SkillNotFoundError,
)


@pytest.fixture
def test_skill(db: Session) -> Skill:
    """Fixture providing a persistent canonical Skill."""
    skill = Skill(
        canonical_name="Python",
        category="Programming Language",
        aliases=["py", "python3"],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@pytest.fixture
def second_skill(db: Session) -> Skill:
    """Fixture providing a second canonical Skill."""
    skill = Skill(
        canonical_name="PostgreSQL",
        category="Database",
        aliases=["postgres", "psql"],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def test_create_competency_success(db: Session, test_skill: Skill) -> None:
    """Verifies successful registration of a Competency linked to a canonical Skill."""
    service = CompetencyService(db)
    payload = CompetencyCreate(
        skill_id=test_skill.id,
        identifier="py-memory-gil-internals",
        name="Python Memory and GIL Internals",
        description="Detailed comprehension of reference counting, cyclic GC, and GIL constraints.",
        dimension=CompetencyDimension.KNOWLEDGE,
        is_active=True,
    )

    comp = service.create_competency(payload)
    assert comp.identifier == "py-memory-gil-internals"
    assert comp.name == "Python Memory and GIL Internals"
    assert comp.dimension == CompetencyDimension.KNOWLEDGE
    assert comp.skill_id == test_skill.id
    assert comp.skill_canonical_name == "Python"
    assert comp.is_active is True
    assert comp.id is not None
    assert comp.created_at is not None


def test_create_competency_missing_skill_fails(db: Session) -> None:
    """Verifies that referencing a non-existent canonical skill raises SkillNotFoundError."""
    service = CompetencyService(db)
    payload = CompetencyCreate(
        skill_id=uuid.uuid4(),
        identifier="missing-skill-comp",
        name="Unanchored Competency",
        description="Valid description for test.",
        dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
    )
    with pytest.raises(SkillNotFoundError):
        service.create_competency(payload)


def test_create_competency_duplicate_identifier_rejected(
    db: Session, test_skill: Skill
) -> None:
    """Verifies that duplicate identifiers (case-insensitive) are rejected."""
    service = CompetencyService(db)
    payload1 = CompetencyCreate(
        skill_id=test_skill.id,
        identifier="py-code-comprehension",
        name="Python Code Comprehension 1",
        description="First description.",
        dimension=CompetencyDimension.DEBUGGING_CODE_COMPREHENSION,
    )
    service.create_competency(payload1)

    # Attempt second with case difference
    payload2 = CompetencyCreate(
        skill_id=test_skill.id,
        identifier="PY-CODE-COMPREHENSION",
        name="Python Code Comprehension 2",
        description="Second description.",
        dimension=CompetencyDimension.DEBUGGING_CODE_COMPREHENSION,
    )
    with pytest.raises(CompetencyAlreadyExistsError):
        service.create_competency(payload2)


def test_competency_rejects_canonical_skill_name_duplication(
    db: Session, test_skill: Skill
) -> None:
    """Verifies that competencies cannot merely duplicate canonical skill names or aliases."""
    service = CompetencyService(db)

    # Duplicating canonical name
    payload1 = CompetencyCreate(
        skill_id=test_skill.id,
        identifier="python",
        name="Python Proficiency",
        description="Valid description.",
        dimension=CompetencyDimension.KNOWLEDGE,
    )
    with pytest.raises(SkillNameCollisionError):
        service.create_competency(payload1)

    # Duplicating skill alias
    payload2 = CompetencyCreate(
        skill_id=test_skill.id,
        identifier="py-knowledge",
        name="py",
        description="Valid description.",
        dimension=CompetencyDimension.KNOWLEDGE,
    )
    with pytest.raises(SkillNameCollisionError):
        service.create_competency(payload2)


def test_all_five_competency_dimensions_supported(
    db: Session, test_skill: Skill
) -> None:
    """Verifies creation and retrieval across all 5 initial competency dimensions."""
    service = CompetencyService(db)
    dimensions = [
        CompetencyDimension.KNOWLEDGE,
        CompetencyDimension.PRACTICAL_IMPLEMENTATION,
        CompetencyDimension.DEBUGGING_CODE_COMPREHENSION,
        CompetencyDimension.SYSTEM_DESIGN_TRADEOFFS,
        CompetencyDimension.TECHNICAL_COMMUNICATION,
    ]

    for dim in dimensions:
        comp = service.create_competency(
            CompetencyCreate(
                skill_id=test_skill.id,
                identifier=f"py-dimension-{dim.lower()}",
                name=f"Python Capability in {dim}",
                description=f"Detailed evaluation criteria for {dim}.",
                dimension=dim,
            )
        )
        assert comp.dimension == dim

    all_comps = service.list_competencies(skill_id=test_skill.id)
    assert len(all_comps) == 5


def test_filter_competencies_by_skill_dimension_and_active(
    db: Session, test_skill: Skill, second_skill: Skill
) -> None:
    """Verifies filtering competencies by skill, dimension, and active status."""
    service = CompetencyService(db)

    # Active competency for Python
    service.create_competency(
        CompetencyCreate(
            skill_id=test_skill.id,
            identifier="py-active-impl",
            name="Python Async Implementation",
            description="Practical async programming.",
            dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
            is_active=True,
        )
    )

    # Inactive competency for Python
    service.create_competency(
        CompetencyCreate(
            skill_id=test_skill.id,
            identifier="py-inactive-legacy",
            name="Python 2 to 3 Migration",
            description="Legacy migration patterns.",
            dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
            is_active=False,
        )
    )

    # Active competency for PostgreSQL
    service.create_competency(
        CompetencyCreate(
            skill_id=second_skill.id,
            identifier="pg-index-tradeoffs",
            name="PostgreSQL Index Design",
            description="B-tree vs GIN tradeoffs.",
            dimension=CompetencyDimension.SYSTEM_DESIGN_TRADEOFFS,
            is_active=True,
        )
    )

    # Filter by skill
    py_comps = service.list_competencies(skill_id=test_skill.id)
    assert len(py_comps) == 2

    # Filter by active only
    active_py = service.list_competencies(skill_id=test_skill.id, is_active=True)
    assert len(active_py) == 1
    assert active_py[0].identifier == "py-active-impl"

    # Filter by dimension
    sys_comps = service.list_competencies(
        dimension=CompetencyDimension.SYSTEM_DESIGN_TRADEOFFS
    )
    assert len(sys_comps) == 1
    assert sys_comps[0].identifier == "pg-index-tradeoffs"


def test_update_competency(db: Session, test_skill: Skill) -> None:
    """Verifies updating competency description, active status, and name."""
    service = CompetencyService(db)
    comp = service.create_competency(
        CompetencyCreate(
            skill_id=test_skill.id,
            identifier="py-update-target",
            name="Original Name",
            description="Original description.",
            dimension=CompetencyDimension.KNOWLEDGE,
            is_active=True,
        )
    )

    updated = service.update_competency(
        comp.id,
        CompetencyUpdate(
            name="Updated Name",
            description="Updated description.",
            is_active=False,
        ),
    )
    assert updated.name == "Updated Name"
    assert updated.description == "Updated description."
    assert updated.is_active is False

    # Check collision on update
    with pytest.raises(SkillNameCollisionError):
        service.update_competency(comp.id, CompetencyUpdate(name="Python"))


def test_get_competency_not_found(db: Session) -> None:
    """Verifies that requesting a non-existent competency raises CompetencyNotFoundError."""
    service = CompetencyService(db)
    with pytest.raises(CompetencyNotFoundError):
        service.get_competency(uuid.uuid4())
    with pytest.raises(CompetencyNotFoundError):
        service.get_by_identifier("non-existent-comp")


def test_db_check_constraints_competency(db: Session, test_skill: Skill) -> None:
    """Verifies DB check constraints prevent empty identifier, name, or description."""
    repo = CompetencyRepository(db)

    # Empty identifier
    with pytest.raises(IntegrityError):
        comp = Competency(
            skill_id=test_skill.id,
            identifier="   ",
            name="Valid Name",
            description="Valid Description",
            dimension=CompetencyDimension.KNOWLEDGE,
        )
        repo.create(comp)
    db.rollback()
