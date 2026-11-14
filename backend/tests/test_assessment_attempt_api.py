import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.assessment_attempt import AssessmentAttempt
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

# ==============================================================================
# Test Fixtures & Helpers
# ==============================================================================


def register_user(
    client: TestClient, email: str, name: str = "Test Candidate"
) -> tuple[str, dict[str, str], uuid.UUID]:
    """Registers and logs in a test candidate, returning token, headers, and user id."""
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    reg_res = client.post("/api/v1/auth/register", json=user_data)
    assert reg_res.status_code == status.HTTP_201_CREATED, reg_res.text
    user_id = uuid.UUID(reg_res.json()["id"])

    login_data = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    assert res.status_code == status.HTTP_200_OK, res.text
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return token, headers, user_id


@pytest.fixture
def published_assessment(db: Session) -> AssessmentDefinition:
    """Creates a published multi-task assessment with coding and MCQ tasks and rubrics."""
    skill = Skill(
        canonical_name=f"Python-{uuid.uuid4().hex[:6]}",
        category="Programming Language",
        aliases=["py"],
    )
    db.add(skill)
    db.flush()

    competency = Competency(
        skill_id=skill.id,
        identifier=f"comp-{uuid.uuid4().hex[:6]}",
        name="Data Structures and Algorithms",
        description="Comprehensive evaluation of candidate algorithmic skill.",
        dimension=CompetencyDimension.PRACTICAL_IMPLEMENTATION,
    )
    db.add(competency)
    db.flush()

    definition = AssessmentDefinition(
        identifier=f"assess-{uuid.uuid4().hex[:6]}",
        version=1,
        title="Python Data Structures Assessment",
        description="Comprehensive evaluation of candidate algorithmic skill.",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.INTERMEDIATE,
        status=AssessmentStatus.PUBLISHED,
        duration_minutes=60,
    )
    db.add(definition)
    db.flush()

    # Task 1: CODING
    task1 = AssessmentTask(
        assessment_definition_id=definition.id,
        competency_id=competency.id,
        identifier="task-binary-search",
        order_index=1,
        title="Binary Search Implementation",
        task_type=TaskType.CODING,
        prompt="Implement an efficient binary search algorithm in Python.",
        payload={
            "initial_code": "def binary_search(arr, target):\n    pass\n",
            "language": "python",
            "test_cases": [
                {"input": "[1, 2, 3, 4, 5], 3", "expected": "2", "hidden": False},
                {"input": "[1, 2, 3, 4, 5], 6", "expected": "-1", "hidden": True},
            ],
        },
        task_metadata={"target_language": "python", "estimated_time_minutes": 25},
    )
    db.add(task1)
    db.flush()

    rubric1 = EvaluationRubric(
        task_id=task1.id,
        evaluation_mode=EvaluationMode.AUTOMATED,
        criteria=[
            {
                "criterion_id": "c1",
                "name": "Correctness",
                "description": "Solves O(log n)",
            }
        ],
        rubric_metadata={"secret_grading_key": "hidden_eval_rubric_secret_xyz"},
    )
    db.add(rubric1)

    # Task 2: MULTIPLE_CHOICE
    task2 = AssessmentTask(
        assessment_definition_id=definition.id,
        competency_id=competency.id,
        identifier="task-algo-complexity",
        order_index=2,
        title="Time Complexity of Hash Tables",
        task_type=TaskType.MULTIPLE_CHOICE,
        prompt="What is the average time complexity of lookup in a hash table?",
        payload={
            "choices": [
                {"id": "opt-1", "label": "O(1)", "text": "Constant time"},
                {"id": "opt-2", "label": "O(log n)", "text": "Logarithmic time"},
                {"id": "opt-3", "label": "O(n)", "text": "Linear time"},
            ],
            "multi_select": False,
        },
        task_metadata={"estimated_time_minutes": 5},
    )
    db.add(task2)
    db.flush()

    rubric2 = EvaluationRubric(
        task_id=task2.id,
        evaluation_mode=EvaluationMode.AUTOMATED,
        criteria=[
            {
                "criterion_id": "c2",
                "name": "MCQ Correctness",
                "description": "Option 1 is correct",
            }
        ],
        rubric_metadata={"correct_choice_id": "opt-1"},
    )
    db.add(rubric2)

    db.commit()
    db.refresh(definition)
    return definition


# ==============================================================================
# 1. Authentication Enforcement (401 Unauthorized)
# ==============================================================================


def test_authentication_enforcement(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that unauthenticated requests to all attempt endpoints return 401."""
    random_uuid = uuid.uuid4()

    # POST /{assessment_id}/attempts
    res = client.post(f"/api/v1/assessments/{published_assessment.id}/attempts")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # GET /attempts
    res = client.get("/api/v1/assessments/attempts")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # GET /attempts/{attempt_id}
    res = client.get(f"/api/v1/assessments/attempts/{random_uuid}")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # POST /attempts/{attempt_id}/start
    res = client.post(f"/api/v1/assessments/attempts/{random_uuid}/start")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # PUT /attempts/{attempt_id}/tasks/{task_id}/submission
    res = client.put(
        f"/api/v1/assessments/attempts/{random_uuid}/tasks/{random_uuid}/submission",
        json={"expected_revision": 1, "submission_payload": {}},
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # POST /attempts/{attempt_id}/submit
    res = client.post(f"/api/v1/assessments/attempts/{random_uuid}/submit")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # POST /attempts/{attempt_id}/abandon
    res = client.post(f"/api/v1/assessments/attempts/{random_uuid}/abandon")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ==============================================================================
# 2. Candidate Isolation & Confidentiality (404 Not Found)
# ==============================================================================


def test_cross_candidate_isolation(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that candidate B cannot access, read, or modify candidate A's attempt (returns 404)."""
    _, headers_a, _ = register_user(client, "candidate_a@example.com")
    _, headers_b, _ = register_user(client, "candidate_b@example.com")

    # Candidate A creates attempt
    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers_a,
    )
    assert init_res.status_code == status.HTTP_201_CREATED
    attempt_a_id = init_res.json()["id"]
    task_id = init_res.json()["submissions"][0]["task_id"]

    # Candidate B tries to read Candidate A's attempt detail -> 404
    get_res = client.get(
        f"/api/v1/assessments/attempts/{attempt_a_id}",
        headers=headers_b,
    )
    assert get_res.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B tries to start Candidate A's attempt -> 404
    start_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_a_id}/start",
        headers=headers_b,
    )
    assert start_res.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B tries to save autosave on Candidate A's attempt -> 404
    save_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_a_id}/tasks/{task_id}/submission",
        headers=headers_b,
        json={
            "expected_revision": 1,
            "submission_payload": {
                "code": "def binary_search(): pass",
                "language": "python",
            },
        },
    )
    assert save_res.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B tries to submit Candidate A's attempt -> 404
    sub_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_a_id}/submit",
        headers=headers_b,
    )
    assert sub_res.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B tries to abandon Candidate A's attempt -> 404
    ab_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_a_id}/abandon",
        headers=headers_b,
    )
    assert ab_res.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B's history does not contain Candidate A's attempt
    history_res = client.get("/api/v1/assessments/attempts", headers=headers_b)
    assert history_res.status_code == status.HTTP_200_OK
    assert history_res.json()["total"] == 0
    assert len(history_res.json()["items"]) == 0


# ==============================================================================
# 3. Initialization (201 Created vs 200 OK Idempotency & Slug Resolution)
# ==============================================================================


def test_initialization_by_uuid_and_idempotent_status_code(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that initial creation returns 201 Created, while subsequent call returns 200 OK."""
    _, headers, _ = register_user(client, "init_candidate@example.com")

    # 1. First call: creates new attempt -> 201
    res1 = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    assert res1.status_code == status.HTTP_201_CREATED
    data1 = res1.json()
    assert data1["status"] == "INITIALIZED"
    assert data1["attempt_number"] == 1
    assert data1["assessment_identifier"] == published_assessment.identifier
    assert data1["assessment_version"] == 1
    assert data1["assessment_title"] == published_assessment.title
    assert len(data1["submissions"]) == 2
    assert len(data1["tasks"]) == 2

    # 2. Second call: idempotent recovery of active attempt -> 200
    res2 = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()
    assert data2["id"] == data1["id"]
    assert data2["status"] == "INITIALIZED"
    assert data2["attempt_number"] == 1


def test_initialization_by_slug_resolves_to_latest_published(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that passing a slug identifier resolves to the latest published version."""
    _, headers, _ = register_user(client, "slug_candidate@example.com")

    res = client.post(
        f"/api/v1/assessments/{published_assessment.identifier}/attempts",
        headers=headers,
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["assessment_definition_id"] == str(published_assessment.id)
    assert data["assessment_identifier"] == published_assessment.identifier


def test_initialization_non_existent_and_invalid_state(
    client: TestClient, db: Session
) -> None:
    """Verifies that non-existent, draft, and deprecated assessments return proper error codes."""
    _, headers, _ = register_user(client, "status_check_user@example.com")

    # Non-existent UUID
    fake_uuid = uuid.uuid4()
    res = client.post(f"/api/v1/assessments/{fake_uuid}/attempts", headers=headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND

    # Non-existent slug
    res_slug = client.post(
        "/api/v1/assessments/non-existent-slug-xyz/attempts", headers=headers
    )
    assert res_slug.status_code == status.HTTP_404_NOT_FOUND

    # Draft assessment
    draft_def = AssessmentDefinition(
        identifier=f"draft-{uuid.uuid4().hex[:6]}",
        version=1,
        title="Draft Assessment",
        description="Not published yet",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.BEGINNER,
        status=AssessmentStatus.DRAFT,
    )
    db.add(draft_def)
    db.commit()
    db.refresh(draft_def)

    res_draft = client.post(
        f"/api/v1/assessments/{draft_def.id}/attempts", headers=headers
    )
    assert res_draft.status_code == status.HTTP_400_BAD_REQUEST
    assert "DRAFT" in res_draft.text

    # Deprecated assessment
    dep_def = AssessmentDefinition(
        identifier=f"dep-{uuid.uuid4().hex[:6]}",
        version=1,
        title="Deprecated Assessment",
        description="Deprecated old version",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.BEGINNER,
        status=AssessmentStatus.DEPRECATED,
    )
    db.add(dep_def)
    db.commit()
    db.refresh(dep_def)

    res_dep = client.post(f"/api/v1/assessments/{dep_def.id}/attempts", headers=headers)
    assert res_dep.status_code == status.HTTP_400_BAD_REQUEST
    assert "DEPRECATED" in res_dep.text


# ==============================================================================
# 4. Attempt History & Pagination Envelope
# ==============================================================================


def test_attempt_history_pagination_and_filters(
    client: TestClient, published_assessment: AssessmentDefinition, db: Session
) -> None:
    """Verifies pagination envelope {items, total, limit, offset}, X-Total-Count, and status filters."""
    _, headers, user_id = register_user(client, "history_candidate@example.com")

    # Create two attempts by creating, abandoning, and initializing again
    init_1 = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts", headers=headers
    )
    att_1_id = init_1.json()["id"]
    client.post(f"/api/v1/assessments/attempts/{att_1_id}/abandon", headers=headers)

    init_2 = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts", headers=headers
    )
    att_2_id = init_2.json()["id"]

    # History: default pagination
    hist_res = client.get("/api/v1/assessments/attempts", headers=headers)
    assert hist_res.status_code == status.HTTP_200_OK
    assert hist_res.headers["X-Total-Count"] == "2"
    payload = hist_res.json()
    assert payload["total"] == 2
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2

    # Deterministic order check: newest created_at first (att_2 then att_1)
    assert payload["items"][0]["id"] == att_2_id
    assert payload["items"][1]["id"] == att_1_id

    # Filter by status=ABANDONED
    ab_filter = client.get(
        "/api/v1/assessments/attempts?status=ABANDONED", headers=headers
    )
    assert ab_filter.status_code == status.HTTP_200_OK
    ab_payload = ab_filter.json()
    assert ab_payload["total"] == 1
    assert ab_payload["items"][0]["id"] == att_1_id

    # Filter by definition id
    def_filter = client.get(
        f"/api/v1/assessments/attempts?assessment_definition_id={published_assessment.id}",
        headers=headers,
    )
    assert def_filter.status_code == status.HTTP_200_OK
    assert def_filter.json()["total"] == 2

    # Pagination slice: limit=1, offset=1
    slice_res = client.get(
        "/api/v1/assessments/attempts?limit=1&offset=1", headers=headers
    )
    assert slice_res.status_code == status.HTTP_200_OK
    slice_payload = slice_res.json()
    assert slice_payload["total"] == 2
    assert len(slice_payload["items"]) == 1
    assert slice_payload["items"][0]["id"] == att_1_id


# ==============================================================================
# 5. Detail & Candidate-Safe Projection (No Rubrics or Secrets)
# ==============================================================================


def test_attempt_detail_candidate_safe_projection(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that attempt detail response strictly excludes evaluation rubrics, solutions, and user_id."""
    _, headers, _ = register_user(client, "projection_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]

    detail_res = client.get(
        f"/api/v1/assessments/attempts/{attempt_id}", headers=headers
    )
    assert detail_res.status_code == status.HTTP_200_OK
    data = detail_res.json()

    # User ID is strictly not exposed
    assert "user_id" not in data

    # Pinned assessment attributes
    assert data["assessment_identifier"] == published_assessment.identifier
    assert data["assessment_version"] == 1
    assert data["assessment_title"] == published_assessment.title

    # Candidate tasks: must have prompt and fixtures, but NO rubrics
    assert len(data["tasks"]) == 2
    for task in data["tasks"]:
        assert "prompt" in task
        assert "payload" in task
        assert "rubric" not in task
        assert "rubrics" not in task
        assert "evaluation_rubric" not in task

    # Confirm raw response string does NOT contain hidden secret keys
    raw_response_text = detail_res.text
    assert "hidden_eval_rubric_secret_xyz" not in raw_response_text
    assert "correct_choice_id" not in raw_response_text


# ==============================================================================
# 6. Start Attempt Lifecycle (Idempotent 200)
# ==============================================================================


def test_start_attempt_idempotency_and_timestamps(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies starting an attempt sets timestamps and is idempotent."""
    _, headers, _ = register_user(client, "start_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]

    # Start attempt
    start_res_1 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers
    )
    assert start_res_1.status_code == status.HTTP_200_OK
    data_1 = start_res_1.json()
    assert data_1["status"] == "IN_PROGRESS"
    assert data_1["started_at"] is not None
    assert data_1["expires_at"] is not None
    started_at_1 = data_1["started_at"]
    expires_at_1 = data_1["expires_at"]

    # Second start attempt call is idempotent: returns 200, keeps timestamps identical
    start_res_2 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers
    )
    assert start_res_2.status_code == status.HTTP_200_OK
    data_2 = start_res_2.json()
    assert data_2["status"] == "IN_PROGRESS"
    assert data_2["started_at"] == started_at_1
    assert data_2["expires_at"] == expires_at_1


# ==============================================================================
# 7. Task Submission Autosave & Validations
# ==============================================================================


def test_task_submission_autosave_lifecycle_and_revisions(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies revision increments, optimistic concurrency conflicts, and schema validation."""
    _, headers, _ = register_user(client, "autosave_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]

    # Find the coding task and MCQ task
    coding_sub = next(
        s
        for s in init_res.json()["submissions"]
        if any(
            t["id"] == s["task_id"] and t["task_type"] == "CODING"
            for t in init_res.json()["tasks"]
        )
    )
    coding_task_id = coding_sub["task_id"]

    mcq_sub = next(
        s
        for s in init_res.json()["submissions"]
        if any(
            t["id"] == s["task_id"] and t["task_type"] == "MULTIPLE_CHOICE"
            for t in init_res.json()["tasks"]
        )
    )
    mcq_task_id = mcq_sub["task_id"]

    # Attempting to save before starting -> 409 Conflict
    pre_start_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{coding_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {
                "code": "def binary_search(): pass",
                "language": "python",
            },
        },
    )
    assert pre_start_res.status_code == status.HTTP_409_CONFLICT

    # Start attempt
    client.post(f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers)

    # 1. Valid autosave for coding task (revision 1 -> 2)
    save_1 = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{coding_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {
                "code": "def binary_search(arr, t): return 0",
                "language": "python",
            },
            "status": "IN_PROGRESS",
        },
    )
    assert save_1.status_code == status.HTTP_200_OK
    assert save_1.json()["revision"] == 2
    assert save_1.json()["status"] == "IN_PROGRESS"
    assert (
        save_1.json()["submission_payload"]["code"]
        == "def binary_search(arr, t): return 0"
    )

    # 2. Second autosave (revision 2 -> 3)
    save_2 = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{coding_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 2,
            "submission_payload": {
                "code": "def binary_search(arr, t): return 1",
                "language": "python",
            },
            "status": "COMPLETED",
        },
    )
    assert save_2.status_code == status.HTTP_200_OK
    assert save_2.json()["revision"] == 3
    assert save_2.json()["status"] == "COMPLETED"

    # 3. Optimistic revision conflict: send expected_revision=1 when current is 3 -> 409 Conflict
    conflict_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{coding_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"code": "stale overwrite", "language": "python"},
        },
    )
    assert conflict_res.status_code == status.HTTP_409_CONFLICT

    # 4. Schema validation failure: invalid language for coding task -> 422 Unprocessable Content
    invalid_lang_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{coding_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 3,
            "submission_payload": {"code": "code", "language": "brainfuck"},
        },
    )
    assert invalid_lang_res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 5. MCQ validation: valid selection
    mcq_save = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{mcq_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"selected_option_ids": ["opt-1"]},
            "status": "COMPLETED",
        },
    )
    assert mcq_save.status_code == status.HTTP_200_OK
    assert mcq_save.json()["revision"] == 2

    # 6. MCQ validation failure: invalid option ID not in choices -> 422 Unprocessable Content
    invalid_mcq_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{mcq_task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 2,
            "submission_payload": {"selected_option_ids": ["non-existent-opt-999"]},
        },
    )
    assert invalid_mcq_res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_task_submission_payload_size_limit(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that payloads exceeding 128 KB return 413 Content Too Large."""
    _, headers, _ = register_user(client, "size_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]
    task_id = init_res.json()["submissions"][0]["task_id"]

    client.post(f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers)

    # 1. 130 KB ASCII payload
    oversized_code = "x" * (130 * 1024)
    oversized_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"code": oversized_code, "language": "python"},
        },
    )
    assert oversized_res.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "128 KB" in oversized_res.text

    # 2. Multibyte UTF-8 accounting: 33,000 4-byte emojis = 132,000 UTF-8 bytes (string length is only 33,000)
    emoji_code = "🚀" * 33000
    emoji_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"code": emoji_code, "language": "python"},
        },
    )
    assert emoji_res.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "128 KB" in emoji_res.text


# ==============================================================================
# 8. Final Submission & Atomicity
# ==============================================================================


def test_submit_attempt_and_idempotency(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies final submission lifecycle, idempotency, and post-submission immutability."""
    _, headers, _ = register_user(client, "submit_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]
    task_id = init_res.json()["submissions"][0]["task_id"]

    # Start attempt
    client.post(f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers)

    # Submit attempt -> 200 OK
    sub_res_1 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/submit", headers=headers
    )
    assert sub_res_1.status_code == status.HTTP_200_OK
    assert sub_res_1.json()["status"] == "SUBMITTED"
    assert sub_res_1.json()["submitted_at"] is not None
    submitted_at = sub_res_1.json()["submitted_at"]

    # Second submit attempt call is idempotent -> 200 OK
    sub_res_2 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/submit", headers=headers
    )
    assert sub_res_2.status_code == status.HTTP_200_OK
    assert sub_res_2.json()["status"] == "SUBMITTED"
    assert sub_res_2.json()["submitted_at"] == submitted_at

    # Cannot save submission on submitted attempt -> 409 Conflict
    save_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"code": "new code", "language": "python"},
        },
    )
    assert save_res.status_code == status.HTTP_409_CONFLICT

    # Cannot abandon submitted attempt -> 409 Conflict
    ab_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/abandon", headers=headers
    )
    assert ab_res.status_code == status.HTTP_409_CONFLICT


# ==============================================================================
# 9. Abandonment & Idempotency
# ==============================================================================


def test_abandon_attempt_and_idempotency(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies attempt abandonment, idempotency, and terminal protection."""
    _, headers, _ = register_user(client, "abandon_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = init_res.json()["id"]

    # Abandon attempt -> 200 OK
    ab_res_1 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/abandon", headers=headers
    )
    assert ab_res_1.status_code == status.HTTP_200_OK
    assert ab_res_1.json()["status"] == "ABANDONED"

    # Second abandon call is idempotent -> 200 OK
    ab_res_2 = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/abandon", headers=headers
    )
    assert ab_res_2.status_code == status.HTTP_200_OK
    assert ab_res_2.json()["status"] == "ABANDONED"

    # Cannot start abandoned attempt -> 409 Conflict
    start_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers
    )
    assert start_res.status_code == status.HTTP_409_CONFLICT

    # Cannot submit abandoned attempt -> 409 Conflict
    submit_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/submit", headers=headers
    )
    assert submit_res.status_code == status.HTTP_409_CONFLICT


# ==============================================================================
# 10. Expiration Handling (410 Gone)
# ==============================================================================


def test_expiration_handling_and_retake(
    client: TestClient, published_assessment: AssessmentDefinition, db: Session
) -> None:
    """Verifies 410 Gone on expired attempt, database transition to EXPIRED, and retake support."""
    _, headers, user_id = register_user(client, "expiry_candidate@example.com")

    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    attempt_id = uuid.UUID(init_res.json()["id"])
    task_id = init_res.json()["submissions"][0]["task_id"]

    # Start attempt
    client.post(f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers)

    # Force expiration in DB by backdating started_at and expires_at
    att = db.get(AssessmentAttempt, attempt_id)
    assert att is not None
    past_time = datetime.now(UTC) - timedelta(hours=2)
    att.started_at = past_time - timedelta(minutes=60)
    att.expires_at = past_time
    db.commit()

    # Autosave on expired in-progress attempt -> 410 Gone (persists EXPIRED in DB)
    save_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{task_id}/submission",
        headers=headers,
        json={
            "expected_revision": 1,
            "submission_payload": {"code": "pass", "language": "python"},
        },
    )
    assert save_res.status_code == status.HTTP_410_GONE

    # Attempt detail now shows EXPIRED
    detail_res = client.get(
        f"/api/v1/assessments/attempts/{attempt_id}", headers=headers
    )
    assert detail_res.status_code == status.HTTP_200_OK
    assert detail_res.json()["status"] == "EXPIRED"

    # Subsequent submit on an already-EXPIRED attempt -> 409 Conflict
    sub_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/submit", headers=headers
    )
    assert sub_res.status_code == status.HTTP_409_CONFLICT

    # Retake: Candidate initializes a new attempt against same assessment definition -> 201 Created
    retake_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers,
    )
    assert retake_res.status_code == status.HTTP_201_CREATED
    retake_data = retake_res.json()
    assert retake_data["id"] != str(attempt_id)
    assert retake_data["attempt_number"] == 2
    assert retake_data["status"] == "INITIALIZED"

    # Also verify direct submit on an expired in-progress attempt returns 410 Gone
    att2_id = uuid.UUID(retake_data["id"])
    client.post(f"/api/v1/assessments/attempts/{att2_id}/start", headers=headers)
    att2 = db.get(AssessmentAttempt, att2_id)
    assert att2 is not None
    att2.started_at = past_time - timedelta(minutes=60)
    att2.expires_at = past_time
    db.commit()

    direct_sub_res = client.post(
        f"/api/v1/assessments/attempts/{att2_id}/submit", headers=headers
    )
    assert direct_sub_res.status_code == status.HTTP_410_GONE


# ==============================================================================
# 11. Deprecation Continuation & New Attempt Restriction
# ==============================================================================


def test_existing_attempt_continues_after_assessment_deprecation(
    client: TestClient, published_assessment: AssessmentDefinition, db: Session
) -> None:
    """Verifies that an attempt created before deprecation can still be completed, but new attempts fail."""
    _, headers_candidate_1, _ = register_user(client, "active_c1@example.com")
    _, headers_candidate_2, _ = register_user(client, "new_c2@example.com")

    # Candidate 1 initializes attempt while PUBLISHED
    init_res = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers_candidate_1,
    )
    assert init_res.status_code == status.HTTP_201_CREATED
    attempt_id = init_res.json()["id"]
    task_id = init_res.json()["submissions"][0]["task_id"]

    # Assessment is now deprecated by admin
    published_assessment.status = AssessmentStatus.DEPRECATED
    db.commit()

    # Candidate 2 tries to initialize a new attempt on the deprecated assessment -> 400 Bad Request
    c2_init = client.post(
        f"/api/v1/assessments/{published_assessment.id}/attempts",
        headers=headers_candidate_2,
    )
    assert c2_init.status_code == status.HTTP_400_BAD_REQUEST
    assert "DEPRECATED" in c2_init.text

    # Candidate 1 can still start, autosave, and submit their existing pinned attempt!
    start_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/start", headers=headers_candidate_1
    )
    assert start_res.status_code == status.HTTP_200_OK
    assert start_res.json()["status"] == "IN_PROGRESS"

    save_res = client.put(
        f"/api/v1/assessments/attempts/{attempt_id}/tasks/{task_id}/submission",
        headers=headers_candidate_1,
        json={
            "expected_revision": 1,
            "submission_payload": {
                "code": "def binary_search(): return 0",
                "language": "python",
            },
        },
    )
    assert save_res.status_code == status.HTTP_200_OK

    submit_res = client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/submit",
        headers=headers_candidate_1,
    )
    assert submit_res.status_code == status.HTTP_200_OK
    assert submit_res.json()["status"] == "SUBMITTED"


# ==============================================================================
# 12. Route Precedence & Catalog Endpoint Regression
# ==============================================================================


def test_route_precedence_and_catalog_endpoint_regression(
    client: TestClient, published_assessment: AssessmentDefinition
) -> None:
    """Verifies that /assessments/attempts does not collide with /assessments/{assessment_id}."""
    _, headers, _ = register_user(client, "precedence_candidate@example.com")

    # 1. GET /assessments/attempts hits the attempts endpoint, returning a list envelope
    attempts_res = client.get("/api/v1/assessments/attempts", headers=headers)
    assert attempts_res.status_code == status.HTTP_200_OK
    assert "items" in attempts_res.json()
    assert "total" in attempts_res.json()

    # 2. GET /assessments hits the catalog list endpoint
    catalog_res = client.get("/api/v1/assessments", headers=headers)
    assert catalog_res.status_code == status.HTTP_200_OK
    assert isinstance(catalog_res.json(), list)

    # 3. GET /assessments/{id} hits the catalog detail endpoint
    def_res = client.get(
        f"/api/v1/assessments/{published_assessment.id}", headers=headers
    )
    assert def_res.status_code == status.HTTP_200_OK
    assert def_res.json()["id"] == str(published_assessment.id)
    assert def_res.json()["identifier"] == published_assessment.identifier
