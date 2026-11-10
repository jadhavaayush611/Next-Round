import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed_assessments import seed_assessment_catalog
from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.competency import Competency, CompetencyDimension
from app.models.evaluation_rubric import EvaluationMode, EvaluationRubric
from app.models.skill import Skill
from app.repositories.assessment_definition import AssessmentDefinitionRepository
from app.repositories.assessment_task import AssessmentTaskRepository
from app.repositories.competency import CompetencyRepository
from app.schemas.assessment import (
    AssessmentDefinitionCreate,
    AssessmentDefinitionUpdate,
    AssessmentTaskCreate,
    AssessmentTaskUpdate,
    EvaluationRubricCreate,
    RubricCriterionSchema,
)
from app.schemas.competency import CompetencyUpdate
from app.services.assessment_catalog_service import (
    AssessmentCatalogService,
    AssessmentImmutableError,
    AssessmentValidationError,
)
from app.services.competency_service import (
    CompetencyService,
    CompetencyValidationError,
)


def register_user(
    client: TestClient, email: str, name: str = "Assessment Candidate"
) -> tuple[str, dict[str, str]]:
    """Helper to register, login, and obtain authorization headers."""
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return token, headers


@pytest.fixture
def canonical_skill(db: Session) -> Skill:
    """Fixture providing a canonical skill."""
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
def test_competency(db: Session, canonical_skill: Skill) -> Competency:
    """Fixture providing a persistent Competency."""
    comp = Competency(
        skill_id=canonical_skill.id,
        identifier="comp-py-testing",
        name="Python Unit & Integration Testing",
        description="Mastery of pytest, fixtures, mocking, and parameterized tests.",
        dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
        is_active=True,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return comp


# ==============================================================================
# Domain Model & Invariant Tests
# ==============================================================================


def test_assessment_identifier_and_version_uniqueness(db: Session) -> None:
    """Verifies that (identifier, version) must be unique in assessment_definitions."""
    repo = AssessmentDefinitionRepository(db)

    # v1
    def1 = AssessmentDefinition(
        identifier="eval-py-concurrency",
        version=1,
        title="Python Concurrency v1",
        description="First revision.",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.INTERMEDIATE,
        status=AssessmentStatus.DRAFT,
    )
    repo.create(def1)

    # v2 with same identifier is allowed
    def2 = AssessmentDefinition(
        identifier="eval-py-concurrency",
        version=2,
        title="Python Concurrency v2",
        description="Second revision.",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.INTERMEDIATE,
        status=AssessmentStatus.DRAFT,
    )
    repo.create(def2)

    # Duplicate (identifier, version=1) must fail
    with pytest.raises(IntegrityError):
        def_duplicate = AssessmentDefinition(
            identifier="eval-py-concurrency",
            version=1,
            title="Python Concurrency v1 Duplicate",
            description="Duplicate version collision.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            status=AssessmentStatus.DRAFT,
        )
        repo.create(def_duplicate)
    db.rollback()


def test_task_identifier_uniqueness_within_definition(
    db: Session,
) -> None:
    """Verifies task identifier uniqueness within its parent assessment definition."""
    def_repo = AssessmentDefinitionRepository(db)
    task_repo = AssessmentTaskRepository(db)

    definition = def_repo.create(
        AssessmentDefinition(
            identifier="eval-tasks-id-test",
            version=1,
            title="Tasks Uniqueness Test",
            description="Test description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            status=AssessmentStatus.DRAFT,
        )
    )

    task1 = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-1",
        order_index=0,
        task_type=TaskType.CODING,
        title="Task 1",
        prompt="Write a function.",
        payload={"code": "pass"},
        task_metadata={"timeout": 10},
    )
    task_repo.create(task1)

    # Duplicate identifier in same definition fails
    with pytest.raises(IntegrityError):
        task_dup_id = AssessmentTask(
            assessment_definition_id=definition.id,
            identifier="task-1",
            order_index=1,
            task_type=TaskType.CODING,
            title="Task 1 Duplicate ID",
            prompt="Write another function.",
            payload={},
            task_metadata={},
        )
        task_repo.create(task_dup_id)


def test_task_order_uniqueness_within_definition(
    db: Session,
) -> None:
    """Verifies task order index uniqueness within its parent assessment definition."""
    def_repo = AssessmentDefinitionRepository(db)
    task_repo = AssessmentTaskRepository(db)

    definition = def_repo.create(
        AssessmentDefinition(
            identifier="eval-tasks-order-test",
            version=1,
            title="Tasks Order Test",
            description="Test description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            status=AssessmentStatus.DRAFT,
        )
    )

    task1 = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-1",
        order_index=0,
        task_type=TaskType.CODING,
        title="Task 1",
        prompt="Write a function.",
        payload={"code": "pass"},
        task_metadata={"timeout": 10},
    )
    task_repo.create(task1)

    # Duplicate order_index in same definition fails
    with pytest.raises(IntegrityError):
        task_dup_order = AssessmentTask(
            assessment_definition_id=definition.id,
            identifier="task-2",
            order_index=0,
            task_type=TaskType.CODING,
            title="Task 2 Duplicate Order",
            prompt="Write another function.",
            payload={},
            task_metadata={},
        )
        task_repo.create(task_dup_order)


def test_rubric_task_relationship(db: Session) -> None:
    """Verifies 1:1 relationship between AssessmentTask and EvaluationRubric."""
    def_repo = AssessmentDefinitionRepository(db)
    task_repo = AssessmentTaskRepository(db)

    definition = def_repo.create(
        AssessmentDefinition(
            identifier="eval-rubric-test",
            version=1,
            title="Rubric Test Definition",
            description="Test description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            status=AssessmentStatus.DRAFT,
        )
    )
    task = task_repo.create(
        AssessmentTask(
            assessment_definition_id=definition.id,
            identifier="rubric-task",
            order_index=0,
            task_type=TaskType.CODING,
            title="Task with Rubric",
            prompt="Prompt content.",
            payload={},
            task_metadata={},
        )
    )

    rubric = EvaluationRubric(
        task_id=task.id,
        evaluation_mode=EvaluationMode.AUTOMATED,
        criteria=[
            {
                "criterion_id": "c1",
                "name": "Correctness",
                "description": "Passes test cases",
                "eval_type": "CONFORMANCE",
            }
        ],
        rubric_metadata={"hidden_tests": "assert True"},
    )
    db.add(rubric)
    db.commit()
    db.refresh(rubric)

    # Loaded via task
    reloaded_task = task_repo.get_by_id(task.id)
    assert reloaded_task is not None
    assert reloaded_task.rubric is not None
    assert reloaded_task.rubric.evaluation_mode == EvaluationMode.AUTOMATED

    # Cannot have a second rubric on same task
    with pytest.raises(IntegrityError):
        dup_rubric = EvaluationRubric(
            task_id=task.id,
            evaluation_mode=EvaluationMode.RUBRIC_MANUAL,
            criteria=[],
            rubric_metadata={},
        )
        db.add(dup_rubric)
        db.commit()
    db.rollback()


# ==============================================================================
# Immutability & Lifecycle Tests
# ==============================================================================


def test_published_assessment_immutability(
    db: Session, test_competency: Competency
) -> None:
    """Verifies that published assessment definitions, tasks, and rubrics cannot be modified."""
    service = AssessmentCatalogService(db)

    # 1. Create draft with task & rubric
    definition = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="immutable-eval",
            title="Immutable Test v1",
            description="Initial description",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            duration_minutes=30,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-immutable-1",
                    order_index=0,
                    title="Task 1",
                    task_type=TaskType.CODING,
                    prompt="Initial prompt.",
                    payload={"starter": "code"},
                    task_metadata={"lang": "python"},
                    competency_id=test_competency.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="crit-1",
                                name="Criteria 1",
                                description="Description 1",
                            )
                        ],
                        rubric_metadata={"hidden": "secret"},
                    ),
                )
            ],
        )
    )

    # 2. Publish assessment
    service.publish_assessment(definition.id)
    assert definition.status == AssessmentStatus.PUBLISHED

    task_id = definition.tasks[0].id

    # 3. Attempt to update published definition -> raises AssessmentImmutableError
    with pytest.raises(AssessmentImmutableError):
        service.update_draft_definition(
            definition.id, AssessmentDefinitionUpdate(title="Hacked Title")
        )

    # 4. Attempt to add task to published definition -> raises AssessmentImmutableError
    with pytest.raises(AssessmentImmutableError):
        service.add_task_to_draft(
            definition.id,
            AssessmentTaskCreate(
                identifier="task-immutable-2",
                order_index=1,
                title="Task 2",
                task_type=TaskType.CODING,
                prompt="Prompt 2",
            ),
        )

    # 5. Attempt to update task of published definition -> raises AssessmentImmutableError
    with pytest.raises(AssessmentImmutableError):
        service.update_draft_task(
            task_id, AssessmentTaskUpdate(title="Modified Task Title")
        )

    # 6. Attempt to delete task of published definition -> raises AssessmentImmutableError
    with pytest.raises(AssessmentImmutableError):
        service.delete_draft_task(task_id)

    # 7. Attempt to update rubric of published definition -> raises AssessmentImmutableError
    with pytest.raises(AssessmentImmutableError):
        service.set_task_rubric(
            task_id,
            EvaluationRubricCreate(
                evaluation_mode=EvaluationMode.RUBRIC_MANUAL,
                criteria=[],
            ),
        )


def test_revision_workflow_creates_new_draft(
    db: Session, test_competency: Competency
) -> None:
    """Verifies that create_revision clones published assessment into a new draft with incremented version."""
    service = AssessmentCatalogService(db)

    # Create & publish v1
    v1 = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="versioning-eval",
            title="Versioning Assessment",
            description="Version 1 description.",
            assessment_type=AssessmentType.SYSTEM_DESIGN,
            difficulty=AssessmentDifficulty.ADVANCED,
            tasks=[
                AssessmentTaskCreate(
                    identifier="v1-task",
                    order_index=0,
                    title="V1 Task",
                    task_type=TaskType.FREE_RESPONSE,
                    prompt="V1 Prompt.",
                    competency_id=test_competency.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.RUBRIC_MANUAL,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="arch-1",
                                name="Architecture Tradeoff",
                                description="Evaluates tradeoff awareness.",
                            )
                        ],
                    ),
                )
            ],
        )
    )
    service.publish_assessment(v1.id)
    assert v1.version == 1
    assert v1.status == AssessmentStatus.PUBLISHED

    # Create revision
    v2 = service.create_revision(v1.id)
    assert v2.identifier == "versioning-eval"
    assert v2.version == 2
    assert v2.status == AssessmentStatus.DRAFT
    assert len(v2.tasks) == 1
    assert v2.tasks[0].identifier == "v1-task"
    assert v2.tasks[0].id != v1.tasks[0].id  # New cloned task record
    assert v2.tasks[0].rubric is not None
    assert v1.tasks[0].rubric is not None
    assert v2.tasks[0].rubric.id != v1.tasks[0].rubric.id  # New cloned rubric

    # Modify draft v2 without affecting published v1
    service.update_draft_definition(
        v2.id, AssessmentDefinitionUpdate(title="Versioning Assessment Rev 2")
    )
    db.refresh(v1)
    assert v1.title == "Versioning Assessment"
    assert v2.title == "Versioning Assessment Rev 2"

    # Publish v2
    published_v2 = service.publish_assessment(v2.id)
    assert published_v2.status == AssessmentStatus.PUBLISHED


def test_publication_requires_tasks_and_rubrics(db: Session) -> None:
    """Verifies that definitions cannot be published without tasks or rubrics."""
    service = AssessmentCatalogService(db)

    # 1. Draft without tasks cannot be published
    empty_def = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="empty-eval",
            title="Empty Definition",
            description="Has no tasks.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
        )
    )
    with pytest.raises(AssessmentValidationError):
        service.publish_assessment(empty_def.id)

    # 2. Draft with task lacking rubric cannot be published
    task = service.add_task_to_draft(
        empty_def.id,
        AssessmentTaskCreate(
            identifier="unrubriced-task",
            order_index=0,
            title="Task without rubric",
            task_type=TaskType.CODING,
            prompt="Write something.",
            rubric=None,
        ),
    )
    with pytest.raises(AssessmentValidationError):
        service.publish_assessment(empty_def.id)

    # 3. Add rubric and publish succeeds
    service.set_task_rubric(
        task.id,
        EvaluationRubricCreate(
            evaluation_mode=EvaluationMode.AUTOMATED,
            criteria=[
                RubricCriterionSchema(
                    criterion_id="c1",
                    name="Correctness",
                    description="Passes tests",
                )
            ],
        ),
    )
    published = service.publish_assessment(empty_def.id)
    assert published.status == AssessmentStatus.PUBLISHED


# ==============================================================================
# Candidate-Facing API Endpoint Tests
# ==============================================================================


def test_list_assessments_requires_authentication(client: TestClient) -> None:
    """Verifies that GET /api/v1/assessments requires a valid Bearer token."""
    response = client.get("/api/v1/assessments")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_assessment_requires_authentication(client: TestClient) -> None:
    """Verifies that GET /api/v1/assessments/{id} requires a valid Bearer token."""
    response = client.get(f"/api/v1/assessments/{uuid.uuid4()}")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_assessments_excludes_draft_and_deprecated(
    client: TestClient, db: Session, test_competency: Competency
) -> None:
    """Verifies that GET /api/v1/assessments only returns PUBLISHED assessments."""
    _, headers = register_user(client, "catalog_candidate@nextround.in", "Catalog User")
    service = AssessmentCatalogService(db)

    # 1. Create DRAFT definition
    service.create_definition(
        AssessmentDefinitionCreate(
            identifier="draft-only-eval",
            title="Secret Draft Assessment",
            description="Draft description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-draft",
                    order_index=0,
                    title="Draft Task",
                    task_type=TaskType.CODING,
                    prompt="Draft prompt.",
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c",
                                name="N",
                                description="D",
                            )
                        ],
                    ),
                )
            ],
        )
    )

    # 2. Create and DEPRECATE definition
    deprecated_def = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="deprecated-eval",
            title="Deprecated Assessment",
            description="Deprecated description.",
            assessment_type=AssessmentType.CONCEPTUAL_KNOWLEDGE,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-dep",
                    order_index=0,
                    title="Deprecated Task",
                    task_type=TaskType.MULTIPLE_CHOICE,
                    prompt="Deprecated prompt.",
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c",
                                name="N",
                                description="D",
                            )
                        ],
                    ),
                )
            ],
        )
    )
    service.publish_assessment(deprecated_def.id)
    service.deprecate_assessment(deprecated_def.id)

    # 3. Create and PUBLISH definition
    pub_def = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="published-eval",
            title="Live Published Assessment",
            description="Published description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            duration_minutes=45,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-live",
                    order_index=0,
                    title="Live Task",
                    task_type=TaskType.CODING,
                    prompt="Live prompt.",
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c",
                                name="N",
                                description="D",
                            )
                        ],
                    ),
                )
            ],
        )
    )
    service.publish_assessment(pub_def.id)

    # Fetch catalog as candidate
    response = client.get("/api/v1/assessments", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    identifiers = [item["identifier"] for item in data]
    assert "published-eval" in identifiers
    assert "draft-only-eval" not in identifiers
    assert "deprecated-eval" not in identifiers


def test_list_assessments_resolves_to_latest_published_version(
    client: TestClient, db: Session, test_competency: Competency
) -> None:
    """Verifies that multiple published versions of the same assessment do not produce duplicate entries."""
    _, headers = register_user(client, "version_user@nextround.in", "Version User")
    service = AssessmentCatalogService(db)

    # Publish v1
    v1 = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="multi-ver-eval",
            title="Multi Version Eval v1",
            description="Version 1",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-v1",
                    order_index=0,
                    title="Task",
                    task_type=TaskType.CODING,
                    prompt="Prompt",
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c", name="N", description="D"
                            )
                        ],
                    ),
                )
            ],
        )
    )
    service.publish_assessment(v1.id)

    # Create and publish v2
    v2 = service.create_revision(v1.id)
    service.update_draft_definition(
        v2.id, AssessmentDefinitionUpdate(title="Multi Version Eval v2")
    )
    service.publish_assessment(v2.id)

    # Query catalog
    res = client.get("/api/v1/assessments", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    items = res.json()

    matching = [i for i in items if i["identifier"] == "multi-ver-eval"]
    assert len(matching) == 1  # Exactly one entry, no duplicates!
    assert matching[0]["version"] == 2
    assert matching[0]["title"] == "Multi Version Eval v2"


def test_candidate_detail_never_exposes_rubrics_or_hidden_answers(
    client: TestClient, db: Session, test_competency: Competency
) -> None:
    """Verifies that candidate detail endpoints never leak rubrics, hidden tests, or private configurations."""
    _, headers = register_user(
        client, "privacy_candidate@nextround.in", "Privacy Candidate"
    )
    service = AssessmentCatalogService(db)

    definition = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="secure-coding-eval",
            title="Secure Coding Challenge",
            description="Challenge description.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-secure-1",
                    order_index=0,
                    title="Candidate Visible Task",
                    task_type=TaskType.CODING,
                    prompt="Implement safe SQL query builder.",
                    payload={
                        "starter_code": "def build_query(): pass",
                        "correct_answer": "TOP_SECRET_ANSWER_LEAK",
                        "hidden_tests": "TOP_SECRET_HIDDEN_TESTS",
                    },
                    task_metadata={
                        "language": "python",
                        "grading_formula": "secret_percentage_calc",
                    },
                    competency_id=test_competency.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="sql_injection_defense",
                                name="SQL Injection Immunity",
                                description="Evaluates parameter binding compliance.",
                            )
                        ],
                        rubric_metadata={
                            "private_evaluator_script": "import secrets; run_exploit()",
                            "expected_solution": "SELECT * FROM users WHERE id = :id",
                        },
                    ),
                )
            ],
        )
    )
    service.publish_assessment(definition.id)

    # 1. Fetch by UUID
    res_uuid = client.get(f"/api/v1/assessments/{definition.id}", headers=headers)
    assert res_uuid.status_code == status.HTTP_200_OK
    data_uuid = res_uuid.json()

    # 2. Fetch by identifier
    res_ident = client.get("/api/v1/assessments/secure-coding-eval", headers=headers)
    assert res_ident.status_code == status.HTTP_200_OK
    data_ident = res_ident.json()

    for data in [data_uuid, data_ident]:
        assert "tasks" in data
        assert len(data["tasks"]) == 1
        task_data = data["tasks"][0]

        # Candidate-visible fields are present
        assert task_data["identifier"] == "task-secure-1"
        assert task_data["prompt"] == "Implement safe SQL query builder."
        assert task_data["payload"]["starter_code"] == "def build_query(): pass"
        assert task_data["competency"]["name"] == test_competency.name

        # Rubric and evaluator secrets are COMPLETELY absent
        assert "rubric" not in task_data
        assert "criteria" not in task_data
        assert "correct_answer" not in task_data["payload"]
        assert "hidden_tests" not in task_data["payload"]
        assert "grading_formula" not in task_data["task_metadata"]

        raw_json_str = str(data)
        assert "TOP_SECRET" not in raw_json_str
        assert "private_evaluator_script" not in raw_json_str
        assert "expected_solution" not in raw_json_str


def test_candidate_cannot_fetch_draft_or_deprecated_assessment(
    client: TestClient, db: Session
) -> None:
    """Verifies that accessing draft or deprecated assessments via ID returns 404."""
    _, headers = register_user(client, "notfound_user@nextround.in", "NotFound User")
    service = AssessmentCatalogService(db)

    # Draft
    draft_def = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="unauthorized-draft",
            title="Draft Assessment",
            description="Description",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
        )
    )

    # Requesting draft by UUID returns 404
    res = client.get(f"/api/v1/assessments/{draft_def.id}", headers=headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND

    # Requesting draft by identifier returns 404
    res_id = client.get("/api/v1/assessments/unauthorized-draft", headers=headers)
    assert res_id.status_code == status.HTTP_404_NOT_FOUND

    # Non-existent UUID returns 404
    res_rand = client.get(f"/api/v1/assessments/{uuid.uuid4()}", headers=headers)
    assert res_rand.status_code == status.HTTP_404_NOT_FOUND


def test_assessment_catalog_filtering_and_pagination(
    client: TestClient, db: Session, test_competency: Competency
) -> None:
    """Verifies catalog query filters (type, difficulty, search) and pagination (limit, offset)."""
    _, headers = register_user(client, "filter_user@nextround.in", "Filter Candidate")
    service = AssessmentCatalogService(db)

    # Seed 3 distinct published assessments
    for idx, (atype, diff, title) in enumerate(
        [
            (
                AssessmentType.PRACTICAL_CODING,
                AssessmentDifficulty.BEGINNER,
                "Python Algorithms",
            ),
            (
                AssessmentType.SYSTEM_DESIGN,
                AssessmentDifficulty.ADVANCED,
                "Distributed Message Queue",
            ),
            (
                AssessmentType.DEBUGGING_REVIEW,
                AssessmentDifficulty.INTERMEDIATE,
                "Python Memory Leak Triage",
            ),
        ]
    ):
        d = service.create_definition(
            AssessmentDefinitionCreate(
                identifier=f"filter-eval-{idx}",
                title=title,
                description=f"Evaluation description for {title}",
                assessment_type=atype,
                difficulty=diff,
                tasks=[
                    AssessmentTaskCreate(
                        identifier=f"task-{idx}",
                        order_index=0,
                        title=f"Task {idx}",
                        task_type=TaskType.CODING,
                        prompt="Do task",
                        competency_id=test_competency.id if idx == 0 else None,
                        rubric=EvaluationRubricCreate(
                            evaluation_mode=EvaluationMode.AUTOMATED,
                            criteria=[
                                RubricCriterionSchema(
                                    criterion_id="c",
                                    name="N",
                                    description="D",
                                )
                            ],
                        ),
                    )
                ],
            )
        )
        service.publish_assessment(d.id)

    # Filter by assessment_type
    res_type = client.get(
        "/api/v1/assessments?assessment_type=SYSTEM_DESIGN", headers=headers
    )
    assert res_type.status_code == status.HTTP_200_OK
    assert all(i["assessment_type"] == "SYSTEM_DESIGN" for i in res_type.json())
    assert any(i["title"] == "Distributed Message Queue" for i in res_type.json())

    # Filter by difficulty
    res_diff = client.get("/api/v1/assessments?difficulty=ADVANCED", headers=headers)
    assert res_diff.status_code == status.HTTP_200_OK
    assert all(i["difficulty"] == "ADVANCED" for i in res_diff.json())

    # Filter by search string
    res_search = client.get("/api/v1/assessments?search=Memory%20Leak", headers=headers)
    assert res_search.status_code == status.HTTP_200_OK
    assert len(res_search.json()) >= 1
    assert "Python Memory Leak Triage" in [i["title"] for i in res_search.json()]

    # Pagination with limit=1, offset=0
    res_page1 = client.get("/api/v1/assessments?limit=1&offset=0", headers=headers)
    assert res_page1.status_code == status.HTTP_200_OK
    assert len(res_page1.json()) == 1
    assert "X-Total-Count" in res_page1.headers

    # Pagination with limit=1, offset=1
    res_page2 = client.get("/api/v1/assessments?limit=1&offset=1", headers=headers)
    assert res_page2.status_code == status.HTTP_200_OK
    assert len(res_page2.json()) == 1
    assert res_page1.json()[0]["id"] != res_page2.json()[0]["id"]


def test_seed_assessment_catalog_idempotent(db: Session) -> None:
    """Verifies that seed_assessment_catalog runs cleanly and idempotently."""
    seed_assessment_catalog(db)

    comp_repo = CompetencyRepository(db)
    def_repo = AssessmentDefinitionRepository(db)

    assert comp_repo.count() >= 5

    # System design competencies preserved in catalog
    sys_comp = comp_repo.get_by_identifier("comp-sysdesign-cache-invalidation")
    assert sys_comp is not None

    definitions, total = def_repo.list_latest_published()
    assert total >= 2

    # Verified: distributed-systems-tradeoffs is not published
    identifiers = [d.identifier for d in definitions]
    assert "distributed-systems-tradeoffs" not in identifiers
    assert "python-backend-foundations" in identifiers
    assert "sql-database-fundamentals" in identifiers

    # All published assessments are focused on programming / databases / REST
    assert all(
        d.assessment_type == AssessmentType.PRACTICAL_CODING for d in definitions
    )

    # Second execution must not duplicate or crash
    seed_assessment_catalog(db)
    definitions_after, total_after = def_repo.list_latest_published()
    assert total_after == total


def test_create_task_rejects_inactive_competency(
    db: Session, canonical_skill: Skill
) -> None:
    """Verifies that creating a task with an inactive competency raises AssessmentValidationError."""
    service = AssessmentCatalogService(db)

    inactive_comp = Competency(
        skill_id=canonical_skill.id,
        identifier="comp-inactive-test",
        name="Inactive Competency Test",
        description="Testing inactive rejection.",
        dimension=CompetencyDimension.KNOWLEDGE,
        is_active=False,
    )
    db.add(inactive_comp)
    db.commit()
    db.refresh(inactive_comp)

    # 1. Path A: create_definition with inactive competency
    with pytest.raises(
        AssessmentValidationError, match="is inactive and cannot be assigned"
    ):
        service.create_definition(
            AssessmentDefinitionCreate(
                identifier="eval-inactive-comp-test",
                title="Inactive Comp Test",
                description="Desc",
                assessment_type=AssessmentType.PRACTICAL_CODING,
                difficulty=AssessmentDifficulty.BEGINNER,
                tasks=[
                    AssessmentTaskCreate(
                        identifier="task-inactive",
                        order_index=0,
                        title="Task 1",
                        task_type=TaskType.CODING,
                        prompt="Solve problem",
                        competency_id=inactive_comp.id,
                    )
                ],
            )
        )

    # 2. Path B: add_task_to_draft with inactive competency
    draft = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-draft-add-inactive",
            title="Draft Assessment",
            description="Desc",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[],
        )
    )

    with pytest.raises(
        AssessmentValidationError, match="is inactive and cannot be assigned"
    ):
        service.add_task_to_draft(
            draft.id,
            AssessmentTaskCreate(
                identifier="task-added-inactive",
                order_index=0,
                title="Task Added",
                task_type=TaskType.CODING,
                prompt="Prompt",
                competency_id=inactive_comp.id,
            ),
        )


def test_update_task_rejects_inactive_competency(
    db: Session, canonical_skill: Skill, test_competency: Competency
) -> None:
    """Verifies that updating a draft task with an inactive competency raises AssessmentValidationError."""
    service = AssessmentCatalogService(db)

    inactive_comp = Competency(
        skill_id=canonical_skill.id,
        identifier="comp-inactive-update-test",
        name="Inactive Update Test",
        description="Testing inactive rejection on update.",
        dimension=CompetencyDimension.KNOWLEDGE,
        is_active=False,
    )
    db.add(inactive_comp)
    db.commit()
    db.refresh(inactive_comp)

    draft = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-update-inactive-comp",
            title="Draft for Update",
            description="Desc",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-active-initially",
                    order_index=0,
                    title="Task Initial",
                    task_type=TaskType.CODING,
                    prompt="Initial prompt",
                    competency_id=test_competency.id,
                )
            ],
        )
    )
    task_id = draft.tasks[0].id

    with pytest.raises(
        AssessmentValidationError, match="is inactive and cannot be assigned"
    ):
        service.update_draft_task(
            task_id,
            AssessmentTaskUpdate(competency_id=inactive_comp.id),
        )


def test_candidate_task_payload_scrubs_nested_and_unexpected_fields(
    db: Session, client: TestClient, test_competency: Competency
) -> None:
    """
    Verifies that candidate detail responses strictly prune:
    - Unexpected top-level payload keys.
    - Nested evaluator configurations and unexpected fields inside public test cases.
    - Multiple choice answer keys and correct choice flags.
    - Unexpected authoring metadata from task_metadata.
    - Full rubric objects (isolated from candidate).
    """
    _, headers = register_user(
        client, "security_cand@nextround.in", "Security Candidate"
    )
    service = AssessmentCatalogService(db)

    # Construct an assessment with malicious / unexpected fields embedded in payload & metadata
    draft = service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-payload-security-test",
            title="Payload Security Assessment",
            description="Testing candidate payload stripping and allowlisting.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            tasks=[
                # Task 1: CODING with unexpected top-level and nested keys
                AssessmentTaskCreate(
                    identifier="task-coding-security",
                    order_index=0,
                    title="Coding Security Task",
                    task_type=TaskType.CODING,
                    prompt="Write function",
                    payload={
                        "language": "python",
                        "starter_code": "def solve(): pass",
                        # Unexpected top-level keys:
                        "hidden_tests": ["assert solve() == 42"],
                        "solution_code": "def solve(): return 42",
                        "author_notes": "Do not leak this!",
                        # Nested evaluator config in public_test_cases:
                        "public_test_cases": [
                            {
                                "description": "Public sample 1",
                                "input": 1,
                                "expected_output": 2,
                                "hidden_grader_key": "secret_salt",
                                "nested_evaluator_config": {"tolerance": 0.001},
                            }
                        ],
                    },
                    task_metadata={
                        "estimated_time_minutes": 25,
                        "target_language": "python",
                        # Unexpected metadata:
                        "evaluator_script": "grade_submission.py",
                        "internal_benchmark_score": 95,
                    },
                    competency_id=test_competency.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="crit-1",
                                name="Crit 1",
                                description="Desc 1",
                            )
                        ],
                        rubric_metadata={"hidden_suite": "secret_tests.py"},
                    ),
                ),
                # Task 2: MULTIPLE_CHOICE with answer keys in options
                AssessmentTaskCreate(
                    identifier="task-mcq-security",
                    order_index=1,
                    title="MCQ Security Task",
                    task_type=TaskType.MULTIPLE_CHOICE,
                    prompt="Select option",
                    payload={
                        "question": "What is the GIL?",
                        "multi_select": False,
                        # Options with unexpected/sensitive fields
                        "choices": [
                            {
                                "id": "A",
                                "text": "Global Interpreter Lock",
                                "is_correct": True,
                                "answer_explanation": "secret explanation",
                            },
                            {
                                "id": "B",
                                "text": "General Interface Layer",
                                "is_correct": False,
                            },
                        ],
                        # Top-level secret keys:
                        "correct_choice": "A",
                        "answer_key": "A",
                    },
                    task_metadata={
                        "estimated_time_minutes": 5,
                        "reviewer_notes": "Author confidential",
                    },
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="crit-2",
                                name="Crit 2",
                                description="Desc 2",
                            )
                        ],
                    ),
                ),
            ],
        )
    )
    published = service.publish_assessment(draft.id)

    # Retrieve candidate-facing view via API
    res = client.get(f"/api/v1/assessments/{published.identifier}", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    detail = res.json()

    # 1. Verify Task 1 (CODING)
    task1 = detail["tasks"][0]
    payload1 = task1["payload"]
    metadata1 = task1["task_metadata"]

    # Allowed fields present
    assert payload1["language"] == "python"
    assert payload1["starter_code"] == "def solve(): pass"
    assert len(payload1["public_test_cases"]) == 1
    tc = payload1["public_test_cases"][0]
    assert tc["description"] == "Public sample 1"
    assert tc["input"] == 1
    assert tc["expected_output"] == 2

    # Unexpected top-level fields pruned
    assert "hidden_tests" not in payload1
    assert "solution_code" not in payload1
    assert "author_notes" not in payload1

    # Unexpected nested fields pruned
    assert "hidden_grader_key" not in tc
    assert "nested_evaluator_config" not in tc

    # Metadata pruned
    assert metadata1["estimated_time_minutes"] == 25
    assert metadata1["target_language"] == "python"
    assert "evaluator_script" not in metadata1
    assert "internal_benchmark_score" not in metadata1

    # 2. Verify Task 2 (MULTIPLE_CHOICE)
    task2 = detail["tasks"][1]
    payload2 = task2["payload"]
    metadata2 = task2["task_metadata"]

    assert payload2["question"] == "What is the GIL?"
    assert payload2["multi_select"] is False
    assert len(payload2["choices"]) == 2
    assert payload2["choices"][0]["id"] == "A"
    assert payload2["choices"][0]["text"] == "Global Interpreter Lock"

    # Answer keys pruned from choices
    assert "is_correct" not in payload2["choices"][0]
    assert "answer_explanation" not in payload2["choices"][0]
    assert "is_correct" not in payload2["choices"][1]

    # Top-level answer keys pruned
    assert "correct_choice" not in payload2
    assert "answer_key" not in payload2

    # Metadata pruned
    assert metadata2["estimated_time_minutes"] == 5
    assert "reviewer_notes" not in metadata2

    # 3. Verify Rubric completely absent
    for t in detail["tasks"]:
        assert "rubric" not in t
        assert "criteria" not in t


def test_deactivating_competency_referenced_by_published_assessment_rejected(
    db: Session, test_competency: Competency
) -> None:
    """
    Verifies that deactivating a competency referenced by a PUBLISHED assessment
    is rejected with CompetencyValidationError, but succeeds once deprecated.
    """
    assessment_service = AssessmentCatalogService(db)
    comp_service = CompetencyService(db)

    # 1. Create and publish an assessment referencing test_competency
    draft = assessment_service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-comp-lifecycle-published",
            title="Competency Lifecycle Assessment",
            description="Testing competency lifecycle locks against published assessments.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.INTERMEDIATE,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-comp-lock",
                    order_index=0,
                    title="Task referencing active competency",
                    task_type=TaskType.CODING,
                    prompt="Implement solution",
                    competency_id=test_competency.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c1",
                                name="Conformance",
                                description="Check conformance",
                            )
                        ],
                    ),
                )
            ],
        )
    )
    published = assessment_service.publish_assessment(draft.id)
    assert published.status == AssessmentStatus.PUBLISHED

    # 2. Attempting to deactivate competency referenced by published assessment must fail
    with pytest.raises(
        CompetencyValidationError,
        match="referenced by active published assessment",
    ):
        comp_service.update_competency(
            test_competency.id, CompetencyUpdate(is_active=False)
        )

    # 3. Deprecate the assessment
    deprecated = assessment_service.deprecate_assessment(published.id)
    assert deprecated.status == AssessmentStatus.DEPRECATED

    # 4. Now deactivation must succeed because there are no PUBLISHED assessments referencing it
    retired = comp_service.update_competency(
        test_competency.id, CompetencyUpdate(is_active=False)
    )
    assert retired.is_active is False


def test_publishing_draft_after_competency_deactivated_rejected(
    db: Session, canonical_skill: Skill
) -> None:
    """
    Verifies that if an assigned competency is deactivated after task creation,
    assessment publication is rejected with AssessmentValidationError.
    """
    assessment_service = AssessmentCatalogService(db)
    comp_service = CompetencyService(db)

    # 1. Create an active competency
    active_comp = Competency(
        skill_id=canonical_skill.id,
        identifier="comp-to-deactivate-before-pub",
        name="Competency To Deactivate Before Publish",
        description="Will be deactivated before draft publication.",
        dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
        is_active=True,
    )
    db.add(active_comp)
    db.commit()
    db.refresh(active_comp)

    # 2. Create draft assessment referencing active competency
    draft = assessment_service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-deactivated-before-publish",
            title="Draft with Competency Deactivated Prior to Publish",
            description="Testing publication failure on deactivated competency.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-deactivated-comp",
                    order_index=0,
                    title="Task with Competency",
                    task_type=TaskType.CODING,
                    prompt="Solve problem",
                    competency_id=active_comp.id,
                    rubric=EvaluationRubricCreate(
                        evaluation_mode=EvaluationMode.AUTOMATED,
                        criteria=[
                            RubricCriterionSchema(
                                criterion_id="c1",
                                name="Criteria",
                                description="Criteria description",
                            )
                        ],
                    ),
                )
            ],
        )
    )

    # 3. Deactivate the competency while assessment is still DRAFT (allowed)
    deactivated = comp_service.update_competency(
        active_comp.id, CompetencyUpdate(is_active=False)
    )
    assert deactivated.is_active is False

    # 4. Attempt to publish the draft assessment; must be rejected
    with pytest.raises(
        AssessmentValidationError,
        match="references inactive competency",
    ):
        assessment_service.publish_assessment(draft.id)


def test_deactivating_competency_not_referenced_by_published_assessment_succeeds(
    db: Session, canonical_skill: Skill
) -> None:
    """
    Verifies that a competency referenced only by a DRAFT assessment (or unreferenced)
    can be deactivated successfully.
    """
    assessment_service = AssessmentCatalogService(db)
    comp_service = CompetencyService(db)

    # 1. Create an active competency
    comp = Competency(
        skill_id=canonical_skill.id,
        identifier="comp-draft-only-reference",
        name="Draft Only Referenced Competency",
        description="Only referenced by a draft assessment.",
        dimension=CompetencyDimension.KNOWLEDGE,
        is_active=True,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)

    # 2. Create a draft assessment referencing this competency
    assessment_service.create_definition(
        AssessmentDefinitionCreate(
            identifier="eval-draft-only-ref",
            title="Draft Only Ref",
            description="Draft referencing competency.",
            assessment_type=AssessmentType.PRACTICAL_CODING,
            difficulty=AssessmentDifficulty.BEGINNER,
            tasks=[
                AssessmentTaskCreate(
                    identifier="task-draft-ref",
                    order_index=0,
                    title="Draft task",
                    task_type=TaskType.CODING,
                    prompt="Draft prompt",
                    competency_id=comp.id,
                )
            ],
        )
    )

    # 3. Deactivation succeeds because no PUBLISHED assessment references it
    updated = comp_service.update_competency(comp.id, CompetencyUpdate(is_active=False))
    assert updated.is_active is False
