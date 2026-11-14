import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment_attempt import AssessmentAttempt, AttemptStatus
from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.task_submission import TaskSubmission, TaskSubmissionStatus
from app.models.user import User
from app.repositories.assessment_attempt import AssessmentAttemptRepository
from app.repositories.task_submission import TaskSubmissionRepository


def create_test_user(db: Session, prefix: str = "attempt_user") -> User:
    """Helper to persist a test User."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@nextround.in",
        name=f"User {uid}",
        hashed_password="hashed_pwd",
        username=f"{prefix}_{uid}",
    )
    db.add(user)
    db.flush()
    return user


def create_test_definition(
    db: Session, identifier: str = "eval-test-attempt", version: int = 1
) -> AssessmentDefinition:
    """Helper to persist a test AssessmentDefinition."""
    definition = AssessmentDefinition(
        identifier=identifier,
        version=version,
        title=f"Assessment {identifier} v{version}",
        description="Assessment for attempt testing.",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.INTERMEDIATE,
        duration_minutes=60,
        status=AssessmentStatus.PUBLISHED,
    )
    db.add(definition)
    db.flush()
    return definition


def create_test_task(
    db: Session, definition: AssessmentDefinition, order_index: int = 0
) -> AssessmentTask:
    """Helper to persist an AssessmentTask."""
    task = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier=f"task-{order_index}",
        order_index=order_index,
        task_type=TaskType.CODING,
        title=f"Task {order_index}",
        prompt="Write a function.",
        payload={"language": "python", "starter_code": "def solve(): pass"},
        task_metadata={"estimated_time_minutes": 20},
    )
    db.add(task)
    db.flush()
    return task


# ==============================================================================
# Model & Relationship Tests
# ==============================================================================


def test_assessment_attempt_model_and_relationships(db: Session) -> None:
    """Verifies AssessmentAttempt creation, timezone-aware fields, and model relationships."""
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-model-rel")
    task = create_test_task(db, definition)

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=60)
    submitted = now + timedelta(minutes=45)

    attempt = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.IN_PROGRESS,
        attempt_number=1,
        started_at=now,
        expires_at=expires,
        submitted_at=submitted,
    )
    db.add(attempt)
    db.flush()

    assert attempt.id is not None
    assert attempt.user_id == user.id
    assert attempt.assessment_definition_id == definition.id
    assert attempt.status == AttemptStatus.IN_PROGRESS
    assert attempt.attempt_number == 1
    assert attempt.started_at == now
    assert attempt.expires_at == expires
    assert attempt.submitted_at == submitted
    assert attempt.created_at.tzinfo is not None
    assert attempt.updated_at.tzinfo is not None

    # Relationship to user and definition
    assert attempt.user.id == user.id
    assert attempt.assessment_definition.id == definition.id
    assert attempt in user.assessment_attempts
    assert attempt in definition.attempts

    # Add task submission
    sub = TaskSubmission(
        attempt_id=attempt.id,
        task_id=task.id,
        assessment_definition_id=definition.id,
        revision=1,
        status=TaskSubmissionStatus.NOT_STARTED,
        submission_payload={"code": "pass"},
    )
    db.add(sub)
    db.flush()

    assert sub.id is not None
    assert sub.revision == 1
    assert sub.status == TaskSubmissionStatus.NOT_STARTED
    assert sub.last_saved_at.tzinfo is not None
    assert sub.created_at.tzinfo is not None
    assert sub.updated_at.tzinfo is not None

    # Relationship to attempt and task
    assert sub.attempt.id == attempt.id
    assert sub.task.id == task.id
    assert sub in attempt.submissions


# ==============================================================================
# Database Constraint & Composite-FK Invariant Tests
# ==============================================================================


def test_composite_fk_rejects_cross_version_submission(db: Session) -> None:
    """
    Verifies that a TaskSubmission cannot reference a task from a different
    assessment version than its parent attempt.
    """
    # Enable SQLite foreign keys if on SQLite, and restore afterwards
    bind = db.get_bind()
    is_sqlite = bool(bind and bind.dialect.name == "sqlite")
    engine_obj: Any = getattr(bind, "engine", bind)
    if is_sqlite:
        with engine_obj.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as raw_conn:
            raw_conn.execute(text("PRAGMA foreign_keys = ON;"))

    try:
        user = create_test_user(db)
        # Definition v1 and Task v1
        def1 = create_test_definition(db, "eval-cross-ver", version=1)
        task1 = create_test_task(db, def1, order_index=0)

        # Definition v2 and Task v2
        def2 = create_test_definition(db, "eval-cross-ver", version=2)
        task2 = create_test_task(db, def2, order_index=0)

        # Attempt belongs to def1
        attempt1 = AssessmentAttempt(
            user_id=user.id,
            assessment_definition_id=def1.id,
            status=AttemptStatus.INITIALIZED,
            attempt_number=1,
        )
        db.add(attempt1)
        db.flush()

        # Case A: Valid submission (matches def1 on both attempt and task)
        valid_sub = TaskSubmission(
            attempt_id=attempt1.id,
            task_id=task1.id,
            assessment_definition_id=def1.id,
            revision=1,
            status=TaskSubmissionStatus.NOT_STARTED,
            submission_payload={},
        )
        db.add(valid_sub)
        db.flush()
        assert valid_sub.id is not None

        # Case B: Cross-version mismatch: attempt is from def1, but task is from def2!
        # If we set assessment_definition_id = def1.id, composite FK fk_task_submissions_task_def fails
        # because (task2.id, def1.id) does not exist in assessment_tasks!
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                invalid_sub_1 = TaskSubmission(
                    attempt_id=attempt1.id,
                    task_id=task2.id,  # Belongs to def2, not def1!
                    assessment_definition_id=def1.id,
                    revision=1,
                    status=TaskSubmissionStatus.NOT_STARTED,
                    submission_payload={},
                )
                db.add(invalid_sub_1)
                db.flush()

        # Case C: If we set assessment_definition_id = def2.id, composite FK fk_task_submissions_attempt_def fails
        # because (attempt1.id, def2.id) does not exist in assessment_attempts!
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                invalid_sub_2 = TaskSubmission(
                    attempt_id=attempt1.id,  # Belongs to def1, not def2!
                    task_id=task2.id,
                    assessment_definition_id=def2.id,
                    revision=1,
                    status=TaskSubmissionStatus.NOT_STARTED,
                    submission_payload={},
                )
                db.add(invalid_sub_2)
                db.flush()
    finally:
        if is_sqlite:
            with engine_obj.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as raw_conn:
                raw_conn.execute(text("PRAGMA foreign_keys = OFF;"))


def test_unique_attempt_number_per_user_def_constraint(db: Session) -> None:
    """Verifies that (user_id, assessment_definition_id, attempt_number) must be unique."""
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-unique-attempt-no")

    attempt1 = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.SUBMITTED,
        attempt_number=1,
    )
    db.add(attempt1)
    db.flush()

    # Duplicate attempt_number=1 for the same user and definition must fail
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            attempt_dup = AssessmentAttempt(
                user_id=user.id,
                assessment_definition_id=definition.id,
                status=AttemptStatus.INITIALIZED,
                attempt_number=1,
            )
            db.add(attempt_dup)
            db.flush()


def test_active_attempt_partial_index_constraint(db: Session) -> None:
    """
    Verifies that a user can have at most one active attempt (INITIALIZED or IN_PROGRESS)
    per assessment definition version.
    """
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-active-partial-idx")

    # Attempt 1: INITIALIZED
    attempt1 = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.INITIALIZED,
        attempt_number=1,
    )
    db.add(attempt1)
    db.flush()

    # Attempt 2: second active attempt for same user and definition must fail
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            attempt2 = AssessmentAttempt(
                user_id=user.id,
                assessment_definition_id=definition.id,
                status=AttemptStatus.IN_PROGRESS,
                attempt_number=2,
            )
            db.add(attempt2)
            db.flush()

    # Finalize attempt1 to SUBMITTED
    attempt1.status = AttemptStatus.SUBMITTED
    db.flush()

    # Now that Attempt 1 is SUBMITTED, creating Attempt 2 in INITIALIZED succeeds
    attempt2 = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.INITIALIZED,
        attempt_number=2,
    )
    db.add(attempt2)
    db.flush()
    assert attempt2.id is not None


def test_unique_task_submission_per_attempt(db: Session) -> None:
    """Verifies that an attempt cannot have duplicate submissions for the same task."""
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-unique-task-sub")
    task = create_test_task(db, definition)

    attempt = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.INITIALIZED,
        attempt_number=1,
    )
    db.add(attempt)
    db.flush()

    sub1 = TaskSubmission(
        attempt_id=attempt.id,
        task_id=task.id,
        assessment_definition_id=definition.id,
        revision=1,
        status=TaskSubmissionStatus.NOT_STARTED,
        submission_payload={},
    )
    db.add(sub1)
    db.flush()

    # Duplicate submission for the same task in this attempt must fail
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            sub_dup = TaskSubmission(
                attempt_id=attempt.id,
                task_id=task.id,
                assessment_definition_id=definition.id,
                revision=1,
                status=TaskSubmissionStatus.NOT_STARTED,
                submission_payload={},
            )
            db.add(sub_dup)
            db.flush()


def test_attempt_check_constraints(db: Session) -> None:
    """Verifies check constraints on timestamps, attempt_number, and revision."""
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-ck-constraints")

    now = datetime.now(UTC)

    # 1. attempt_number < 1 fails
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            att_invalid_no = AssessmentAttempt(
                user_id=user.id,
                assessment_definition_id=definition.id,
                status=AttemptStatus.INITIALIZED,
                attempt_number=0,
            )
            db.add(att_invalid_no)
            db.flush()

    # 2. submitted_at < started_at fails
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            att_invalid_submitted = AssessmentAttempt(
                user_id=user.id,
                assessment_definition_id=definition.id,
                status=AttemptStatus.SUBMITTED,
                attempt_number=1,
                started_at=now,
                submitted_at=now - timedelta(seconds=10),
            )
            db.add(att_invalid_submitted)
            db.flush()

    # 3. expires_at < started_at fails
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            att_invalid_expires = AssessmentAttempt(
                user_id=user.id,
                assessment_definition_id=definition.id,
                status=AttemptStatus.IN_PROGRESS,
                attempt_number=1,
                started_at=now,
                expires_at=now - timedelta(seconds=10),
            )
            db.add(att_invalid_expires)
            db.flush()


# ==============================================================================
# Repository Operations Tests
# ==============================================================================


def test_assessment_attempt_repository_operations(db: Session) -> None:
    """Verifies candidate scoping, active attempt lookup, attempt numbering, and pagination."""
    repo = AssessmentAttemptRepository(db)
    user1 = create_test_user(db, "candidate_one")
    user2 = create_test_user(db, "candidate_two")
    def1 = create_test_definition(db, "eval-repo-ops-1")
    def2 = create_test_definition(db, "eval-repo-ops-2")

    # Initial max attempt number is 0
    assert repo.get_max_attempt_number(user1.id, def1.id) == 0

    # Create attempt 1 for user1
    att1 = AssessmentAttempt(
        user_id=user1.id,
        assessment_definition_id=def1.id,
        status=AttemptStatus.INITIALIZED,
        attempt_number=1,
    )
    repo.create_attempt(att1)
    assert att1.id is not None
    assert repo.get_max_attempt_number(user1.id, def1.id) == 1

    # Candidate scoping: user1 can fetch att1; user2 cannot
    fetched_user1 = repo.get_candidate_attempt(att1.id, user1.id)
    assert fetched_user1 is not None
    assert fetched_user1.id == att1.id

    fetched_user2 = repo.get_candidate_attempt(att1.id, user2.id)
    assert fetched_user2 is None

    # Active attempt lookup finds initialized attempt
    active = repo.get_active_attempt(user1.id, def1.id)
    assert active is not None
    assert active.id == att1.id

    # Active attempt for another definition is None
    assert repo.get_active_attempt(user1.id, def2.id) is None

    # Update attempt status
    repo.update_attempt_status(att1, status=AttemptStatus.SUBMITTED)
    assert att1.status == AttemptStatus.SUBMITTED

    # Now that it's submitted, active attempt is None
    assert repo.get_active_attempt(user1.id, def1.id) is None

    # List candidate attempts with pagination
    items, total = repo.list_candidate_attempts(user1.id)
    assert total == 1
    assert len(items) == 1
    assert items[0].id == att1.id


def test_task_submission_repository_operations(db: Session) -> None:
    """Verifies eager seeding, optimistic revision updates, and aggregate payload size calculation."""
    attempt_repo = AssessmentAttemptRepository(db)
    sub_repo = TaskSubmissionRepository(db)

    user = create_test_user(db)
    definition = create_test_definition(db, "eval-sub-repo-ops")
    task1 = create_test_task(db, definition, order_index=0)
    task2 = create_test_task(db, definition, order_index=1)

    attempt = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.IN_PROGRESS,
        attempt_number=1,
    )
    attempt_repo.create_attempt(attempt)

    # 1. Eager batch seeding of task submissions
    subs_to_seed = [
        TaskSubmission(
            attempt_id=attempt.id,
            task_id=task1.id,
            assessment_definition_id=definition.id,
            revision=1,
            status=TaskSubmissionStatus.NOT_STARTED,
            submission_payload={},
        ),
        TaskSubmission(
            attempt_id=attempt.id,
            task_id=task2.id,
            assessment_definition_id=definition.id,
            revision=1,
            status=TaskSubmissionStatus.NOT_STARTED,
            submission_payload={},
        ),
    ]
    seeded = sub_repo.create_submissions_batch(subs_to_seed)
    assert len(seeded) == 2

    all_subs = sub_repo.list_by_attempt_id(attempt.id)
    assert len(all_subs) == 2

    # 2. Optimistic revision update: revision 1 matches
    updated = sub_repo.update_submission_with_revision(
        attempt_id=attempt.id,
        task_id=task1.id,
        expected_revision=1,
        submission_payload={"code": "def solve(): return 42"},
        status=TaskSubmissionStatus.COMPLETED,
    )
    assert updated is not None
    assert updated.revision == 2
    assert updated.status == TaskSubmissionStatus.COMPLETED
    assert updated.submission_payload["code"] == "def solve(): return 42"

    # 3. Stale revision update: expected_revision=1 fails because current revision is 2
    stale_update = sub_repo.update_submission_with_revision(
        attempt_id=attempt.id,
        task_id=task1.id,
        expected_revision=1,
        submission_payload={"code": "stale overwrite attempt"},
        status=TaskSubmissionStatus.COMPLETED,
    )
    assert stale_update is None

    # Fetch to ensure row was not modified by stale update
    fetched = sub_repo.get_submission(attempt.id, task1.id)
    assert fetched is not None
    assert fetched.revision == 2
    assert fetched.submission_payload["code"] == "def solve(): return 42"

    # 4. Aggregate payload size calculation
    size_all = sub_repo.get_aggregate_payload_size(attempt.id)
    assert size_all > 0

    size_excl_task1 = sub_repo.get_aggregate_payload_size(
        attempt.id, exclude_task_id=task1.id
    )
    assert size_excl_task1 < size_all


def test_sqlite_locking_dialect_compatibility(db: Session) -> None:
    """Verifies that parent-row and child-row lock calls work on SQLite without dialect syntax crashes."""
    attempt_repo = AssessmentAttemptRepository(db)
    sub_repo = TaskSubmissionRepository(db)

    user = create_test_user(db)
    definition = create_test_definition(db, "eval-dialect-compat")
    task = create_test_task(db, definition)

    attempt = AssessmentAttempt(
        user_id=user.id,
        assessment_definition_id=definition.id,
        status=AttemptStatus.INITIALIZED,
        attempt_number=1,
    )
    attempt_repo.create_attempt(attempt)

    sub = TaskSubmission(
        attempt_id=attempt.id,
        task_id=task.id,
        assessment_definition_id=definition.id,
        revision=1,
        status=TaskSubmissionStatus.NOT_STARTED,
        submission_payload={},
    )
    sub_repo.create_submission(sub)

    # Calling with for_update=True on SQLite should not raise any syntax errors
    att_locked = attempt_repo.get_candidate_attempt(
        attempt.id, user.id, for_update=True
    )
    assert att_locked is not None
    assert att_locked.id == attempt.id

    sub_locked = sub_repo.get_submission(attempt.id, task.id, for_update=True)
    assert sub_locked is not None
    assert sub_locked.id == sub.id
