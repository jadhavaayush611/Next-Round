import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed_skills import SEED_SKILLS
from app.models.skill import Skill
from app.repositories.skill import SkillRepository
from app.schemas.skill import SkillCreate, SkillUpdate
from app.services.skill_service import (
    AliasCollisionError,
    AmbiguousSkillError,
    SkillAlreadyExistsError,
    SkillService,
)
from app.utils.skill_normalization import clean_aliases, normalize_skill_name

# =========================================================================
# 1. Normalization Utility Tests
# =========================================================================


def test_normalize_skill_name_casing_and_whitespace() -> None:
    """Verifies deterministic whitespace collapse, trimming, and lowercasing."""
    assert normalize_skill_name("  PostgreSQL  ") == "postgresql"
    assert normalize_skill_name("Python") == "python"
    assert normalize_skill_name("   Ruby    on    Rails   ") == "ruby on rails"
    assert normalize_skill_name("FASTAPI") == "fastapi"
    assert normalize_skill_name("") == ""
    assert normalize_skill_name("   ") == ""
    assert normalize_skill_name(None) == ""


def test_normalize_skill_name_preserves_technical_symbols() -> None:
    """Verifies that technical symbols (+, #, ., -, /) are strictly preserved."""
    assert normalize_skill_name("C++") == "c++"
    assert normalize_skill_name("C#") == "c#"
    assert normalize_skill_name(".NET") == ".net"
    assert normalize_skill_name("Node.js") == "node.js"
    assert normalize_skill_name("CI/CD") == "ci/cd"
    assert normalize_skill_name("TCP/IP") == "tcp/ip"


def test_clean_aliases_deduplication_and_canonical_filtering() -> None:
    """Verifies cleaning, whitespace collapse, deduplication, and exclusion of canonical name."""
    raw_aliases = [" postgres ", "PGSQL", "postgres", "  psql  ", "PostgreSQL", ""]
    cleaned = clean_aliases(raw_aliases, canonical_name="PostgreSQL")
    # 'PostgreSQL' matches canonical name so it must be omitted.
    # 'postgres' and 'postgres' are deduplicated.
    assert cleaned == ["postgres", "PGSQL", "psql"]


# =========================================================================
# 2. Model Constraints and Database Integrity
# =========================================================================


def test_skill_model_creation_and_defaults(db: Session) -> None:
    """Verifies persisting a Skill model with UUID, default empty aliases, and timestamps."""
    skill = Skill(
        canonical_name="Rust",
        category="Programming Language",
        aliases=["rustlang"],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)

    assert isinstance(skill.id, uuid.UUID)
    assert skill.canonical_name == "Rust"
    assert skill.category == "Programming Language"
    assert skill.aliases == ["rustlang"]
    assert skill.created_at is not None
    assert skill.updated_at is not None


def test_skill_model_rejects_empty_canonical_name(db: Session) -> None:
    """Verifies check constraint ck_skills_canonical_name_not_empty."""
    skill = Skill(
        canonical_name="   ",
        category="Database",
    )
    db.add(skill)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()


def test_skill_model_rejects_empty_category(db: Session) -> None:
    """Verifies check constraint ck_skills_category_not_empty."""
    skill = Skill(
        canonical_name="Redis",
        category="   ",
    )
    db.add(skill)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()


def test_skill_model_rejects_duplicate_canonical_name_exact(db: Session) -> None:
    """Verifies unique constraint uq_skills_canonical_name on exact duplicate."""
    s1 = Skill(canonical_name="Docker", category="DevOps")
    db.add(s1)
    db.commit()

    s2 = Skill(canonical_name="Docker", category="Containers")
    db.add(s2)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()


def test_skill_model_rejects_duplicate_canonical_name_case_insensitive(
    db: Session,
) -> None:
    """Verifies unique index uq_skills_canonical_name_lower rejects case-variant duplicate."""
    s1 = Skill(canonical_name="Kubernetes", category="DevOps")
    db.add(s1)
    db.commit()

    s2 = Skill(canonical_name="kubernetes", category="DevOps")
    db.add(s2)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()


# =========================================================================
# 3. Repository Operations
# =========================================================================


def test_skill_repository_operations(db: Session) -> None:
    """Verifies repository get, list, search by canonical name, category, and alias."""
    repo = SkillRepository(db)
    skill_py = Skill(
        canonical_name="Python",
        category="Programming Language",
        aliases=["py", "python3"],
    )
    skill_pg = Skill(
        canonical_name="PostgreSQL",
        category="Database",
        aliases=["postgres", "psql"],
    )
    repo.create(skill_py)
    repo.create(skill_pg)

    # get_by_id
    assert repo.get_by_id(skill_py.id) is not None

    # get_by_canonical_name (case-insensitive & whitespace-tolerant)
    found_py = repo.get_by_canonical_name("  python  ")
    assert found_py is not None
    assert found_py.id == skill_py.id

    found_pg = repo.get_by_canonical_name("POSTGRESQL")
    assert found_pg is not None
    assert found_pg.id == skill_pg.id

    # find_by_alias
    by_alias = repo.find_by_alias("  PSQL  ")
    assert len(by_alias) == 1
    assert by_alias[0].id == skill_pg.id

    # list_all
    all_skills = repo.list_all()
    assert len(all_skills) == 2

    # list_all with category filter
    db_skills = repo.list_all(category="database")
    assert len(db_skills) == 1
    assert db_skills[0].id == skill_pg.id

    # list_categories
    cats = repo.list_categories()
    assert sorted(cats) == ["Database", "Programming Language"]

    # count
    assert repo.count() == 2


# =========================================================================
# 4. Service Operations: Creation, Validation & Collision Rejection
# =========================================================================


def test_service_create_skill_success(db: Session) -> None:
    """Verifies creating a skill via service with cleaned aliases and response validation."""
    service = SkillService(db)
    payload = SkillCreate(
        canonical_name="TypeScript",
        category="Programming Language",
        aliases=["ts", "TypeScript", "  ts  "],
    )
    res = service.create_skill(payload)
    assert res.canonical_name == "TypeScript"
    assert res.category == "Programming Language"
    # Deduplicated, whitespace stripped, and canonical name removed from aliases
    assert res.aliases == ["ts"]


def test_service_create_skill_rejects_duplicate_canonical_name(
    db: Session,
) -> None:
    """Verifies that creating a skill with an existing canonical name raises SkillAlreadyExistsError."""
    service = SkillService(db)
    service.create_skill(
        SkillCreate(canonical_name="Go", category="Programming Language")
    )

    with pytest.raises(SkillAlreadyExistsError) as exc_info:
        service.create_skill(SkillCreate(canonical_name="  go  ", category="Languages"))
    assert "already exists" in str(exc_info.value)


def test_service_create_skill_rejects_canonical_colliding_with_existing_alias(
    db: Session,
) -> None:
    """Verifies that a new skill's canonical name cannot collide with an existing skill's alias."""
    service = SkillService(db)
    service.create_skill(
        SkillCreate(
            canonical_name="PostgreSQL",
            category="Database",
            aliases=["postgres"],
        )
    )

    # Attempting to register a new skill named 'Postgres' must be rejected
    with pytest.raises(AliasCollisionError) as exc_info:
        service.create_skill(
            SkillCreate(canonical_name="Postgres", category="Database")
        )
    assert "collides with alias of existing skill 'PostgreSQL'" in str(exc_info.value)


def test_service_create_skill_rejects_alias_colliding_with_existing_canonical(
    db: Session,
) -> None:
    """Verifies that a proposed alias cannot collide with an existing skill's canonical name."""
    service = SkillService(db)
    service.create_skill(
        SkillCreate(canonical_name="Java", category="Programming Language")
    )

    # Attempting to add skill 'JVM' with alias 'Java' must be rejected
    with pytest.raises(AliasCollisionError) as exc_info:
        service.create_skill(
            SkillCreate(
                canonical_name="JVM Platform",
                category="Runtime",
                aliases=["java"],
            )
        )
    assert "collides with canonical name of existing skill 'Java'" in str(
        exc_info.value
    )


def test_service_create_skill_rejects_alias_colliding_with_existing_alias(
    db: Session,
) -> None:
    """Verifies that an alias cannot collide with an alias already claimed by another skill."""
    service = SkillService(db)
    service.create_skill(
        SkillCreate(
            canonical_name="JavaScript",
            category="Programming Language",
            aliases=["js"],
        )
    )

    # Attempting to claim 'js' for another skill must be rejected
    with pytest.raises(AliasCollisionError) as exc_info:
        service.create_skill(
            SkillCreate(
                canonical_name="JSON",
                category="Data Format",
                aliases=["js"],
            )
        )
    assert "collides with alias of existing skill 'JavaScript'" in str(exc_info.value)


# =========================================================================
# 5. Deterministic Resolution and Ambiguity Handling
# =========================================================================


def test_service_resolve_skill_canonical_and_alias(db: Session) -> None:
    """Verifies deterministic resolution to canonical entity for both exact names and aliases."""
    service = SkillService(db)
    service.create_skill(
        SkillCreate(
            canonical_name="PostgreSQL",
            category="Database",
            aliases=["postgres", "psql"],
        )
    )
    service.create_skill(
        SkillCreate(
            canonical_name="Python",
            category="Programming Language",
            aliases=["py"],
        )
    )
    service.create_skill(
        SkillCreate(
            canonical_name="FastAPI",
            category="Framework",
            aliases=["fast-api"],
        )
    )

    # 1. Canonical lookup (case-insensitive & whitespace tolerant)
    res_py = service.resolve_skill("  python  ")
    assert res_py is not None
    assert res_py.canonical_name == "Python"

    # 2. Alias lookup
    res_pg = service.resolve_skill("postgres")
    assert res_pg is not None
    assert res_pg.canonical_name == "PostgreSQL"

    res_pg2 = service.resolve_skill("  PSQL  ")
    assert res_pg2 is not None
    assert res_pg2.canonical_name == "PostgreSQL"

    # 3. Distinct technologies: FastAPI vs Python
    res_fa = service.resolve_skill("fastapi")
    assert res_fa is not None
    assert res_fa.canonical_name == "FastAPI"
    assert res_fa.id != res_py.id

    # 4. Unknown query returns None
    assert service.resolve_skill("UnknownTech123") is None
    assert service.resolve_skill("") is None
    assert service.resolve_skill("   ") is None


def test_service_resolve_skill_rejects_ambiguous_alias_collision(
    db: Session,
) -> None:
    """
    Verifies that if an alias collides across multiple skills (e.g. from direct DB inserts
    or historical data), resolve_skill raises AmbiguousSkillError rather than guessing.
    """
    # Force two skills in DB with overlapping alias 'jvm'
    s1 = Skill(
        canonical_name="Java",
        category="Programming Language",
        aliases=["jvm"],
    )
    s2 = Skill(
        canonical_name="Scala",
        category="Programming Language",
        aliases=["jvm"],
    )
    db.add_all([s1, s2])
    db.commit()

    service = SkillService(db)
    with pytest.raises(AmbiguousSkillError) as exc_info:
        service.resolve_skill("jvm")

    assert "matches multiple skills" in str(exc_info.value)
    assert "Java" in str(exc_info.value)
    assert "Scala" in str(exc_info.value)


def test_service_resolve_skill_rejects_canonical_vs_alias_collision(
    db: Session,
) -> None:
    """
    Verifies that if a query matches one skill's canonical name and another skill's alias,
    resolve_skill raises AmbiguousSkillError rather than guessing.
    """
    s1 = Skill(
        canonical_name="Go",
        category="Programming Language",
        aliases=["golang"],
    )
    s2 = Skill(
        canonical_name="Board Game Go",
        category="Game",
        aliases=["go"],
    )
    db.add_all([s1, s2])
    db.commit()

    service = SkillService(db)
    with pytest.raises(AmbiguousSkillError) as exc_info:
        service.resolve_skill("go")

    assert "matches canonical skill 'Go'" in str(exc_info.value)
    assert "Board Game Go" in str(exc_info.value)


# =========================================================================
# 6. Idempotent & Repeatable Seeding
# =========================================================================


def test_seed_catalog_is_repeatable_and_preserves_existing_data(
    db: Session,
) -> None:
    """
    Verifies that seed_catalog():
    1. Populates all curated backend skills.
    2. Repeated calls are idempotent and do not duplicate records.
    3. Existing user-customized skills are preserved and never overwritten.
    """
    service = SkillService(db)

    # 1. First run on empty DB
    seeded = service.seed_catalog()
    assert len(seeded) == len(SEED_SKILLS)
    total_count = len(seeded)

    # Verify key contract entries
    pg_skill = service.get_by_canonical_name("PostgreSQL")
    assert pg_skill is not None
    assert "postgres" in pg_skill.aliases

    fa_skill = service.get_by_canonical_name("FastAPI")
    assert fa_skill is not None
    py_skill = service.get_by_canonical_name("Python")
    assert py_skill is not None
    assert fa_skill.id != py_skill.id

    # 2. Modify an existing skill to test non-overwriting behavior
    service.update_skill(
        pg_skill.id,
        SkillUpdate(
            category="Relational Database",
            aliases=["postgres", "psql", "custom_alias"],
        ),
    )
    modified_pg = service.get_skill(pg_skill.id)
    assert modified_pg.category == "Relational Database"
    assert "custom_alias" in modified_pg.aliases

    # 3. Second run must be idempotent: does not duplicate or overwrite modified skill
    second_run = service.seed_catalog()
    assert len(second_run) == total_count

    check_pg = service.get_skill(pg_skill.id)
    assert check_pg.category == "Relational Database"
    assert "custom_alias" in check_pg.aliases

    # 4. Third run to ensure total count stability
    third_run = service.seed_catalog()
    assert len(third_run) == total_count


# =========================================================================
# 7. Absence of Public Write Endpoints
# =========================================================================


def test_no_public_skill_write_endpoints_exposed(client: TestClient) -> None:
    """
    Verifies the architectural constraint that no public write endpoints exist
    for creating, updating, or deleting Skill catalog entries.
    """
    dummy_payload = {
        "canonical_name": "InjectedSkill",
        "category": "Arbitrary",
    }
    random_id = uuid.uuid4()

    # POST /api/v1/skills must not exist
    assert client.post("/api/v1/skills", json=dummy_payload).status_code in [404, 405]

    # PUT /api/v1/skills/{id} must not exist
    assert client.put(
        f"/api/v1/skills/{random_id}", json=dummy_payload
    ).status_code in [404, 405]

    # DELETE /api/v1/skills/{id} must not exist
    assert client.delete(f"/api/v1/skills/{random_id}").status_code in [404, 405]


# =========================================================================
# 8. Seed Catalog Integrity & Concurrency Race Handling
# =========================================================================


def test_seed_catalog_has_no_internal_collisions() -> None:
    """
    Verifies that the initial SEED_SKILLS catalog has zero internal collisions:
    - No duplicate canonical names.
    - No alias collisions with any canonical name.
    - No alias collisions between different skills.
    """
    canonical_names: set[str] = set()
    alias_to_skill: dict[str, str] = {}

    for entry in SEED_SKILLS:
        canon_norm = normalize_skill_name(entry["canonical_name"])
        assert (
            canon_norm not in canonical_names
        ), f"Duplicate canonical name in SEED_SKILLS: {entry['canonical_name']}"
        canonical_names.add(canon_norm)

    for entry in SEED_SKILLS:
        canon = entry["canonical_name"]
        canon_norm = normalize_skill_name(canon)
        for alias in entry["aliases"]:
            alias_norm = normalize_skill_name(alias)
            assert (
                alias_norm != canon_norm
            ), f"Alias '{alias}' in skill '{canon}' matches its own canonical name."
            assert (
                alias_norm not in canonical_names
            ), f"Alias '{alias}' in skill '{canon}' collides with another skill's canonical name."
            assert (
                alias_norm not in alias_to_skill
            ), f"Alias '{alias}' in skill '{canon}' collides with alias in skill '{alias_to_skill[alias_norm]}'."
            alias_to_skill[alias_norm] = canon


def test_create_skill_handles_concurrent_race_integrity_error(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Simulates a race condition where two workers attempt to insert the same skill
    at the same time. Even if both pass application-level duplicate checks,
    the second worker's database commit raises IntegrityError.
    The service must catch IntegrityError, rollback, and raise SkillAlreadyExistsError.
    """
    service = SkillService(db)

    def mock_create(self_repo: SkillRepository, skill: Skill) -> Skill:
        raise IntegrityError("mock statement", {}, Exception("unique violation"))

    monkeypatch.setattr(SkillRepository, "create", mock_create)

    with pytest.raises(SkillAlreadyExistsError) as exc_info:
        service.create_skill(
            SkillCreate(canonical_name="ConcurrentSkill", category="Tools")
        )

    assert "already exists" in str(exc_info.value)


def test_seed_catalog_handles_concurrent_race_integrity_error(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Simulates a race condition where two workers run seed_catalog() concurrently.
    The second worker's commit encounters IntegrityError due to the unique index.
    The service must catch IntegrityError, rollback, and return without crashing.
    """
    service = SkillService(db)
    rollback_called = False

    def mock_commit() -> None:
        raise IntegrityError("mock statement", {}, Exception("unique violation"))

    original_rollback = db.rollback

    def mock_rollback() -> None:
        nonlocal rollback_called
        rollback_called = True
        original_rollback()

    monkeypatch.setattr(db, "commit", mock_commit)
    monkeypatch.setattr(db, "rollback", mock_rollback)

    # Must catch IntegrityError, rollback, and return list of skills without crashing
    skills = service.seed_catalog()
    assert rollback_called is True
    assert isinstance(skills, list)
