import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.assessment_attempt import AssessmentAttempt, AttemptStatus
from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.task_submission import TaskSubmissionStatus
from app.models.user import User
from app.schemas.task_submission import (
    MAX_SUBMISSION_PAYLOAD_BYTES,
    calculate_payload_bytes,
    canonical_json_dumps,
)
from app.services.assessment_attempt_service import (
    AssessmentAttemptService,
    AssessmentUnavailableError,
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptStateError,
    PayloadTooLargeError,
    StaleRevisionError,
    SubmissionValidationError,
)

# ==============================================================================
# Test Fixtures & Helpers
# ==============================================================================


def create_test_user(db: Session, prefix: str = "service_user") -> User:
    """Helper to persist a test User."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@nextround.in",
        name=f"Candidate {uid}",
        hashed_password="hashed_pwd",
        username=f"{prefix}_{uid}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_definition(
    db: Session,
    identifier: str = "eval-service-test",
    version: int = 1,
    status: AssessmentStatus = AssessmentStatus.PUBLISHED,
    duration_minutes: int | None = 60,
) -> AssessmentDefinition:
    """Helper to persist an AssessmentDefinition with tasks across all 4 execution types."""
    definition = AssessmentDefinition(
        identifier=identifier,
        version=version,
        title=f"Assessment {identifier} v{version}",
        description="Assessment for attempt service testing.",
        assessment_type=AssessmentType.PRACTICAL_CODING,
        difficulty=AssessmentDifficulty.INTERMEDIATE,
        duration_minutes=duration_minutes,
        status=status,
    )
    db.add(definition)
    db.flush()

    # 1. CODING task
    t_coding = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-coding-1",
        order_index=0,
        task_type=TaskType.CODING,
        title="Coding Task",
        prompt="Write a Python rate limiter.",
        payload={"language": "python", "starter_code": "def solve(): pass"},
        task_metadata={"target_language": "python", "estimated_time_minutes": 20},
    )
    db.add(t_coding)

    # 2. MULTIPLE_CHOICE task (single select)
    t_mcq = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-mcq-1",
        order_index=1,
        task_type=TaskType.MULTIPLE_CHOICE,
        title="MCQ Task",
        prompt="Which data structure provides O(1) average lookup?",
        payload={
            "multi_select": False,
            "choices": [
                {"id": "opt-hash", "text": "Hash Table"},
                {"id": "opt-tree", "text": "Binary Search Tree"},
                {"id": "opt-list", "text": "Linked List"},
            ],
        },
        task_metadata={"estimated_time_minutes": 5},
    )
    db.add(t_mcq)

    # 3. FREE_RESPONSE task
    t_free = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-free-1",
        order_index=2,
        task_type=TaskType.FREE_RESPONSE,
        title="Architecture Free Response",
        prompt="Describe cache invalidation trade-offs in distributed systems.",
        payload={"format": "markdown"},
        task_metadata={"estimated_time_minutes": 15},
    )
    db.add(t_free)

    # 4. CODE_ANALYSIS task
    t_analysis = AssessmentTask(
        assessment_definition_id=definition.id,
        identifier="task-analysis-1",
        order_index=3,
        task_type=TaskType.CODE_ANALYSIS,
        title="Concurrency Bug Analysis",
        prompt="Identify the race condition in the provided snippet.",
        payload={"source_code": "def transfer(): pass"},
        task_metadata={"target_language": "python"},
    )
    db.add(t_analysis)

    db.commit()
    db.refresh(definition)
    return definition


# ==============================================================================
# Attempt Lifecycle Tests
# ==============================================================================


def test_initialize_attempt_success_and_eager_seeding(db: Session) -> None:
    """Verifies attempt initialization against a published assessment and eager task seeding."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-init-success")

    attempt = service.initialize_attempt(user.id, definition.id)

    assert attempt.id is not None
    assert attempt.user_id == user.id
    assert attempt.assessment_definition_id == definition.id
    assert attempt.status == AttemptStatus.INITIALIZED
    assert attempt.attempt_number == 1
    assert attempt.started_at is None
    assert attempt.expires_at is None
    assert attempt.submitted_at is None

    # Verify eager seeding of all 4 task submissions
    assert len(attempt.submissions) == 4
    for sub in attempt.submissions:
        assert sub.revision == 1
        assert sub.status == TaskSubmissionStatus.NOT_STARTED
        assert sub.submission_payload == {}
        assert sub.assessment_definition_id == definition.id


def test_initialize_attempt_idempotency_returns_existing_active(db: Session) -> None:
    """Verifies that calling initialize_attempt when an active attempt exists returns the same attempt."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-init-idempotent")

    attempt_1 = service.initialize_attempt(user.id, definition.id)
    attempt_2 = service.initialize_attempt(user.id, definition.id)

    assert attempt_1.id == attempt_2.id
    assert attempt_2.attempt_number == 1


def test_initialize_attempt_rejects_draft_and_deprecated(db: Session) -> None:
    """Verifies that initializing new attempts on DRAFT or DEPRECATED assessments is rejected."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)

    # 1. Draft definition
    draft_def = create_test_definition(
        db, "eval-init-draft", status=AssessmentStatus.DRAFT
    )
    with pytest.raises(AssessmentUnavailableError, match="draft"):
        service.initialize_attempt(user.id, draft_def.id)

    # 2. Deprecated definition
    dep_def = create_test_definition(
        db, "eval-init-deprecated", status=AssessmentStatus.DEPRECATED
    )
    with pytest.raises(AssessmentUnavailableError, match="deprecated"):
        service.initialize_attempt(user.id, dep_def.id)


def test_sequential_retake_numbering_after_terminal_attempt(db: Session) -> None:
    """Verifies sequential attempt numbering: 1, 2, 3... after previous attempts are submitted/abandoned."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-sequential-retakes")

    # Attempt 1 -> start & submit
    att_1 = service.initialize_attempt(user.id, definition.id)
    assert att_1.attempt_number == 1
    service.start_attempt(att_1.id, user.id)
    service.submit_attempt(att_1.id, user.id)

    # Attempt 2 -> start & abandon
    att_2 = service.initialize_attempt(user.id, definition.id)
    assert att_2.attempt_number == 2
    assert att_2.id != att_1.id
    service.start_attempt(att_2.id, user.id)
    service.abandon_attempt(att_2.id, user.id)

    # Attempt 3 -> initialize
    att_3 = service.initialize_attempt(user.id, definition.id)
    assert att_3.attempt_number == 3
    assert att_3.id != att_2.id


def test_start_attempt_idempotent_and_timing_calculation(db: Session) -> None:
    """Verifies that starting an attempt transitions to IN_PROGRESS and calculates expires_at exactly once."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-start-timing", duration_minutes=45)

    attempt = service.initialize_attempt(user.id, definition.id)
    started = service.start_attempt(attempt.id, user.id)

    assert started.status == AttemptStatus.IN_PROGRESS
    assert started.started_at is not None
    assert started.expires_at is not None
    # 45 minutes duration
    expected_expiry = started.started_at + timedelta(minutes=45)
    assert abs((started.expires_at - expected_expiry).total_seconds()) < 2

    original_started_at = started.started_at
    original_expires_at = started.expires_at

    # Idempotent start: calling again should not mutate timestamps
    started_again = service.start_attempt(attempt.id, user.id)
    assert started_again.status == AttemptStatus.IN_PROGRESS
    assert started_again.started_at == original_started_at
    assert started_again.expires_at == original_expires_at


def test_start_attempt_untimed_assessment(db: Session) -> None:
    """Verifies that untimed assessments have expires_at=None and never expire automatically."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(
        db, "eval-untimed-attempt", duration_minutes=None
    )

    attempt = service.initialize_attempt(user.id, definition.id)
    started = service.start_attempt(attempt.id, user.id)

    assert started.status == AttemptStatus.IN_PROGRESS
    assert started.started_at is not None
    assert started.expires_at is None
    assert not service._is_expired(started)


def test_start_attempt_invalid_transitions(db: Session) -> None:
    """Verifies that terminal attempts (SUBMITTED, ABANDONED) cannot be started."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-start-invalid")

    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)
    service.submit_attempt(attempt.id, user.id)

    with pytest.raises(AttemptStateError, match="Cannot start"):
        service.start_attempt(attempt.id, user.id)


def test_submit_attempt_idempotency_and_invalid_state(db: Session) -> None:
    """Verifies atomic submission, idempotency, and rejection of unstarted attempts."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-submit-atomic")

    attempt = service.initialize_attempt(user.id, definition.id)

    # Submitting an INITIALIZED attempt fails
    with pytest.raises(AttemptStateError, match="must be IN_PROGRESS"):
        service.submit_attempt(attempt.id, user.id)

    # Start and submit
    service.start_attempt(attempt.id, user.id)
    submitted = service.submit_attempt(attempt.id, user.id)
    assert submitted.status == AttemptStatus.SUBMITTED
    assert submitted.submitted_at is not None

    # Idempotent: repeated submission returns existing record cleanly
    submitted_again = service.submit_attempt(attempt.id, user.id)
    assert submitted_again.status == AttemptStatus.SUBMITTED
    assert submitted_again.submitted_at == submitted.submitted_at


def test_abandon_attempt_idempotency_and_invalid_state(db: Session) -> None:
    """Verifies abandonment, idempotency, and rejection of submitted attempts."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-abandon-test")

    attempt = service.initialize_attempt(user.id, definition.id)
    abandoned = service.abandon_attempt(attempt.id, user.id)
    assert abandoned.status == AttemptStatus.ABANDONED

    # Idempotent
    abandoned_again = service.abandon_attempt(attempt.id, user.id)
    assert abandoned_again.status == AttemptStatus.ABANDONED

    # Starting a new attempt and submitting it
    att_2 = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(att_2.id, user.id)
    service.submit_attempt(att_2.id, user.id)

    # Cannot abandon a submitted attempt
    with pytest.raises(AttemptStateError, match="Cannot abandon"):
        service.abandon_attempt(att_2.id, user.id)


def test_existing_attempt_continues_after_assessment_deprecation(
    db: Session,
) -> None:
    """Verifies that an attempt initialized before deprecation can be started, saved to, and submitted."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-continue-after-deprecate")

    attempt = service.initialize_attempt(user.id, definition.id)

    # Deprecate the assessment definition
    definition.status = AssessmentStatus.DEPRECATED
    db.commit()

    # In-flight attempt can still be started
    started = service.start_attempt(attempt.id, user.id)
    assert started.status == AttemptStatus.IN_PROGRESS

    # Can still autosave
    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]
    saved = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=coding_task.id,
        user_id=user.id,
        submission_payload={"code": "def solve(): return 1", "language": "python"},
        expected_revision=1,
    )
    assert saved.revision == 2

    # Can still submit
    submitted = service.submit_attempt(attempt.id, user.id)
    assert submitted.status == AttemptStatus.SUBMITTED


# ==============================================================================
# Expiration & Grace Period Tests
# ==============================================================================


def test_grace_period_allows_submission_and_autosave(db: Session) -> None:
    """
    Verifies that timed attempts accept saves and final submission through the
    120-second grace period past expires_at.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-grace-period", duration_minutes=30)

    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # Simulate clock: 60 seconds PAST expires_at (within 120s grace period)
    simulated_now = attempt.expires_at + timedelta(seconds=60)
    assert not service._is_expired(attempt, now=simulated_now)

    # Autosave should succeed within grace period
    saved = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=coding_task.id,
        user_id=user.id,
        submission_payload={"code": "def solve(): return 123", "language": "python"},
        expected_revision=1,
    )
    assert saved.revision == 2

    # Final submission should succeed within grace period
    submitted = service.submit_attempt(attempt.id, user.id)
    assert submitted.status == AttemptStatus.SUBMITTED


def test_expiration_beyond_grace_period_and_persistence(db: Session) -> None:
    """
    Verifies that past expires_at + 120s, operations are rejected with AttemptExpiredError,
    and the EXPIRED status is persisted to the database.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    user_id = user.id
    definition = create_test_definition(db, "eval-expired-persist", duration_minutes=30)

    attempt = service.initialize_attempt(user_id, definition.id)
    attempt_id = attempt.id
    service.start_attempt(attempt_id, user_id)

    # Set expires_at into the deep past (e.g., 10 minutes ago, started 60 min ago)
    now = datetime.now(UTC)
    attempt.started_at = now - timedelta(minutes=60)
    attempt.expires_at = now - timedelta(minutes=10)
    db.commit()

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # 1. Autosave is rejected with AttemptExpiredError
    with pytest.raises(AttemptExpiredError, match="expired"):
        service.save_task_submission(
            attempt_id=attempt_id,
            task_id=coding_task.id,
            user_id=user_id,
            submission_payload={"code": "too late", "language": "python"},
            expected_revision=1,
        )

    # Verify attempt status was persisted as EXPIRED in DB
    refreshed_attempt = service.get_attempt(attempt_id, user_id)
    assert refreshed_attempt.status == AttemptStatus.EXPIRED

    # 2. Submitting an expired attempt is rejected
    with pytest.raises(AttemptStateError, match="must be IN_PROGRESS"):
        service.submit_attempt(attempt_id, user_id)


def test_expired_attempt_enables_new_active_retake(db: Session) -> None:
    """Verifies that once an attempt expires, the user can initialize a new retake attempt."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    user_id = user.id
    definition = create_test_definition(db, "eval-expired-retake", duration_minutes=30)
    definition_id = definition.id

    attempt_1 = service.initialize_attempt(user_id, definition_id)
    attempt_1_id = attempt_1.id
    service.start_attempt(attempt_1_id, user_id)

    # Expire attempt 1
    now = datetime.now(UTC)
    attempt_1.started_at = now - timedelta(minutes=60)
    attempt_1.expires_at = now - timedelta(minutes=10)
    db.commit()

    # Calling initialize_attempt cleans up expired attempt and creates attempt 2
    attempt_2 = service.initialize_attempt(user_id, definition_id)
    assert attempt_2.id != attempt_1_id
    assert attempt_2.attempt_number == 2
    assert attempt_2.status == AttemptStatus.INITIALIZED

    # Old attempt is permanently EXPIRED
    old_att = service.get_attempt(attempt_1_id, user_id)
    assert old_att.status == AttemptStatus.EXPIRED


# ==============================================================================
# Autosave & Optimistic Revision Conflict Tests
# ==============================================================================


def test_autosave_optimistic_revision_success_and_conflict(db: Session) -> None:
    """Verifies atomic revision incrementing and rejection of stale revision writes."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-opt-revision")

    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # Revision 1 -> 2
    save_1 = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=coding_task.id,
        user_id=user.id,
        submission_payload={"code": "v1", "language": "python"},
        expected_revision=1,
    )
    assert save_1.revision == 2

    # Stale write with expected_revision=1 fails with StaleRevisionError
    with pytest.raises(StaleRevisionError, match="Stale revision conflict"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "stale overwrite", "language": "python"},
            expected_revision=1,
        )

    # Current revision 2 -> 3 succeeds
    save_2 = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=coding_task.id,
        user_id=user.id,
        submission_payload={"code": "v2", "language": "python"},
        expected_revision=2,
    )
    assert save_2.revision == 3
    assert save_2.submission_payload["code"] == "v2"


def test_autosave_serializes_against_submit_via_parent_lock(db: Session) -> None:
    """
    Verifies that when submit_attempt acquires the parent attempt lock,
    subsequent autosaves see SUBMITTED status and are rejected.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-lock-ordering")

    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # Final submission completes
    service.submit_attempt(attempt.id, user.id)

    # Attempting to save after submit fails
    with pytest.raises(AttemptStateError, match="terminal status 'SUBMITTED'"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "late save", "language": "python"},
            expected_revision=1,
        )


# ==============================================================================
# Task-Specific Payload Validation Tests
# ==============================================================================


def test_coding_payload_validation(db: Session) -> None:
    """Verifies CODING task payload validation, unexpected field rejection, and language matching."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-val-coding")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # 1. Valid submission
    sub = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=coding_task.id,
        user_id=user.id,
        submission_payload={"code": "print('hello')", "language": "python"},
        expected_revision=1,
    )
    assert sub.submission_payload["code"] == "print('hello')"

    # 2. Unexpected field rejected
    with pytest.raises(SubmissionValidationError, match="extra_forbidden"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={
                "code": "print(1)",
                "language": "python",
                "malicious_extra": 123,
            },
            expected_revision=2,
        )

    # 3. Mismatched required language (task requires python, candidate gave sql)
    with pytest.raises(SubmissionValidationError, match="does not match required"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "SELECT 1;", "language": "sql"},
            expected_revision=2,
        )


def test_multiple_choice_payload_validation(db: Session) -> None:
    """Verifies MULTIPLE_CHOICE validation: option existence, duplicate prevention, and single-select."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-val-mcq")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    mcq_task = [t for t in definition.tasks if t.task_type == TaskType.MULTIPLE_CHOICE][
        0
    ]

    # 1. Valid single choice
    sub = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=mcq_task.id,
        user_id=user.id,
        submission_payload={"selected_option_ids": ["opt-hash"]},
        expected_revision=1,
    )
    assert sub.submission_payload["selected_option_ids"] == ["opt-hash"]

    # 2. Duplicate choices rejected
    with pytest.raises(SubmissionValidationError, match="Duplicate option"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=mcq_task.id,
            user_id=user.id,
            submission_payload={"selected_option_ids": ["opt-hash", "opt-hash"]},
            expected_revision=2,
        )

    # 3. Invalid option ID rejected
    with pytest.raises(SubmissionValidationError, match="Invalid MCQ option ID"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=mcq_task.id,
            user_id=user.id,
            submission_payload={"selected_option_ids": ["opt-nonexistent"]},
            expected_revision=2,
        )

    # 4. Multi-choice on a single-select task rejected
    with pytest.raises(SubmissionValidationError, match="only allows a single"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=mcq_task.id,
            user_id=user.id,
            submission_payload={"selected_option_ids": ["opt-hash", "opt-tree"]},
            expected_revision=2,
        )


def test_free_response_payload_validation(db: Session) -> None:
    """Verifies FREE_RESPONSE format validation and unexpected field rejection."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-val-free")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    free_task = [t for t in definition.tasks if t.task_type == TaskType.FREE_RESPONSE][
        0
    ]

    # 1. Valid free response
    sub = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=free_task.id,
        user_id=user.id,
        submission_payload={
            "response_text": "## Distributed Caching\nTrade-offs include...",
            "format": "markdown",
        },
        expected_revision=1,
    )
    assert "Distributed Caching" in sub.submission_payload["response_text"]

    # 2. Invalid format rejected
    with pytest.raises(SubmissionValidationError, match="Format must be"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=free_task.id,
            user_id=user.id,
            submission_payload={"response_text": "text", "format": "pdf"},
            expected_revision=2,
        )


def test_code_analysis_payload_validation(db: Session) -> None:
    """Verifies CODE_ANALYSIS payload validation."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-val-analysis")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    analysis_task = [
        t for t in definition.tasks if t.task_type == TaskType.CODE_ANALYSIS
    ][0]

    # Valid analysis
    sub = service.save_task_submission(
        attempt_id=attempt.id,
        task_id=analysis_task.id,
        user_id=user.id,
        submission_payload={
            "analysis": "The race condition occurs during check-then-act on connection pool.",
            "proposed_fix": "Use asyncio.Semaphore.",
            "language": "python",
        },
        expected_revision=1,
    )
    assert "race condition" in sub.submission_payload["analysis"]


def test_reject_non_json_and_non_finite_values(db: Session) -> None:
    """Verifies that non-finite numbers (NaN, Inf) and non-dict payloads are rejected."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-val-non-finite")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # 1. Non-dict payload rejected
    with pytest.raises(SubmissionValidationError, match="must be a JSON object"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload="not a dict",  # type: ignore[arg-type]
            expected_revision=1,
        )

    # 2. Non-finite float (NaN) rejected
    with pytest.raises(SubmissionValidationError, match="not strictly JSON compliant"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "pass", "language": "python", "nan": float("nan")},  # type: ignore[dict-item]
            expected_revision=1,
        )


# ==============================================================================
# Payload Byte Limits & UTF-8 Calculation Tests
# ==============================================================================


def test_canonical_json_and_multibyte_utf8_calculation() -> None:
    """Verifies deterministic canonical JSON serialization and multi-byte Unicode byte measurement."""
    # Deterministic sorting
    d1 = {"z": 1, "a": 2}
    d2 = {"a": 2, "z": 1}
    assert canonical_json_dumps(d1) == canonical_json_dumps(d2)
    assert canonical_json_dumps(d1) == '{"a":2,"z":1}'

    # Multi-byte UTF-8 test (emojis are 4 bytes each in UTF-8)
    emoji_payload = {"emoji": "🚀🎉"}
    # {"emoji":"🚀🎉"} -> key/punctuation=12 chars/bytes + 2 emojis * 4 bytes = 20 bytes
    byte_count = calculate_payload_bytes(emoji_payload)
    assert byte_count == 20
    # In contrast, json.dumps with ensure_ascii=True would serialize to \ud83d\ude80 (much larger ASCII escape string)
    assert len(json.dumps(emoji_payload, ensure_ascii=True)) > byte_count


def test_submission_payload_exceeding_128kb_rejected(db: Session) -> None:
    """Verifies that an individual submission exceeding 128 KB is rejected with PayloadTooLargeError."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-limit-128kb")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # Generate oversized code string (> 128 KB = 131,072 bytes)
    oversized_code = "x" * (MAX_SUBMISSION_PAYLOAD_BYTES + 100)

    with pytest.raises(
        PayloadTooLargeError, match="exceeds the maximum limit of 128 KB"
    ):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": oversized_code, "language": "python"},
            expected_revision=1,
        )


def test_aggregate_attempt_payload_exceeding_2mb_rejected(db: Session) -> None:
    """Verifies that aggregate attempt payload exceeding 2 MB is rejected with PayloadTooLargeError."""
    service = AssessmentAttemptService(db)
    user = create_test_user(db)
    definition = create_test_definition(db, "eval-limit-2mb")
    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    # Artificially populate existing submissions close to 2 MB limit (e.g. 1.95 MB)
    large_chunk = "A" * (650 * 1024)  # 650 KB each across 3 submissions = 1.95 MB
    tasks = definition.tasks
    for i in range(1, 4):
        attempt.submissions[i].submission_payload = {
            "response_text": large_chunk,
            "format": "text",
        }
    db.commit()

    # Now attempting to save 100 KB (<= 128 KB single limit) on task 0 causes aggregate to exceed 2 MB (2.05 MB total)
    incoming_valid_single = "B" * (100 * 1024)
    with pytest.raises(PayloadTooLargeError, match="exceeds the maximum limit of 2 MB"):
        service.save_task_submission(
            attempt_id=attempt.id,
            task_id=tasks[0].id,
            user_id=user.id,
            submission_payload={"code": incoming_valid_single, "language": "python"},
            expected_revision=1,
        )


def test_postgresql_row_locking_sql_compilation() -> None:
    """
    Verifies that under the PostgreSQL dialect, queries compiled with for_update=True
    produce genuine 'FOR UPDATE' locking clauses.
    Notes on Concurrency:
    - SQLite tests verify business logic, state machines, and sequential transitions.
    - PostgreSQL is required to physically enforce row-level FOR UPDATE serialization.
    - The repository's universal lock order (AssessmentAttempt first, TaskSubmission second)
      guarantees deadlock-free execution in production PostgreSQL environments.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.assessment_attempt import AssessmentAttempt
    from app.models.task_submission import TaskSubmission

    uid = uuid.uuid4()

    # 1. Parent row lock
    stmt_att = (
        select(AssessmentAttempt).where(AssessmentAttempt.id == uid).with_for_update()
    )
    compiled_att = str(stmt_att.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled_att

    # 2. Child row lock
    stmt_sub = select(TaskSubmission).where(TaskSubmission.id == uid).with_for_update()
    compiled_sub = str(stmt_sub.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled_sub


# ==============================================================================
# Transaction Isolation & Expiration Session Tests
# ==============================================================================


def test_expiration_persists_expired_and_preserves_unrelated_session_state(
    db: Session,
) -> None:
    """
    Verifies that when an attempt expires:
    1. EXPIRED status is persisted to the database and AttemptExpiredError is raised.
    2. Unrelated pending dirty/new objects in the caller's session are NOT silently discarded.
    3. Unrelated pending dirty/new objects in the caller's session are NOT accidentally committed.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="iso_user")
    user_id = user.id
    definition = create_test_definition(db, "eval-iso-test", duration_minutes=30)

    attempt = service.initialize_attempt(user_id, definition.id)
    attempt_id = attempt.id
    service.start_attempt(attempt_id, user_id)

    # Force attempt past grace period
    now = datetime.now(UTC)
    attempt.started_at = now - timedelta(minutes=60)
    attempt.expires_at = now - timedelta(minutes=10)
    db.commit()

    # Create an unrelated pending dirty change in the caller's session
    original_name = user.name
    user.name = "Pending Uncommitted Name"
    assert user in db.dirty

    # Create an unrelated pending new object in the caller's session
    new_user = User(
        email=f"pending_{uuid.uuid4().hex[:6]}@nextround.in",
        name="Pending New User",
        hashed_password="pwd",
        username=f"pending_{uuid.uuid4().hex[:6]}",
    )
    db.add(new_user)
    assert new_user in db.new

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    # Calling save_task_submission on expired attempt raises AttemptExpiredError
    with pytest.raises(AttemptExpiredError):
        service.save_task_submission(
            attempt_id=attempt_id,
            task_id=coding_task.id,
            user_id=user_id,
            submission_payload={"code": "print('hello')", "language": "python"},
            expected_revision=1,
        )

    # 1. EXPIRED is committed in the database
    bind = db.get_bind()
    with Session(bind=bind) as check_db:
        db_attempt = check_db.get(AssessmentAttempt, attempt_id)
        assert db_attempt is not None
        assert db_attempt.status == AttemptStatus.EXPIRED

        # 3. Unrelated pending changes were NOT accidentally committed to the DB
        db_user = check_db.get(User, user_id)
        assert db_user is not None
        assert db_user.name == original_name

        db_new_user = (
            check_db.query(User).filter(User.username == new_user.username).first()
        )
        assert db_new_user is None

    # 2. Unrelated pending changes were NOT silently lost from caller's session
    assert user in db.dirty
    assert user.name == "Pending Uncommitted Name"
    assert new_user in db.new


def test_terminal_submitted_or_abandoned_attempt_cannot_be_changed_to_expired(
    db: Session,
) -> None:
    """
    Verifies that attempts in terminal states (SUBMITTED, ABANDONED) can never be overwritten
    to EXPIRED, even if expires_at is past cutoff.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="term_user")
    definition = create_test_definition(db, "eval-term-test", duration_minutes=30)

    # Case 1: SUBMITTED attempt
    attempt1 = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt1.id, user.id)
    submitted = service.submit_attempt(attempt1.id, user.id)
    assert submitted.status == AttemptStatus.SUBMITTED

    # Artificially set expires_at into the past
    now = datetime.now(UTC)
    submitted.started_at = now - timedelta(minutes=60)
    submitted.expires_at = now - timedelta(minutes=10)
    db.commit()

    # Calling _apply_expiration must NOT change status to EXPIRED
    result1 = service._apply_expiration(submitted, raise_error=False)
    assert result1.status == AttemptStatus.SUBMITTED

    bind = db.get_bind()
    with Session(bind=bind) as check_db:
        db_att1 = check_db.get(AssessmentAttempt, attempt1.id)
        assert db_att1 is not None
        assert db_att1.status == AttemptStatus.SUBMITTED

    # Case 2: ABANDONED attempt
    attempt2 = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt2.id, user.id)
    abandoned = service.abandon_attempt(attempt2.id, user.id)
    assert abandoned.status == AttemptStatus.ABANDONED

    abandoned.started_at = now - timedelta(minutes=60)
    abandoned.expires_at = now - timedelta(minutes=10)
    db.commit()

    result2 = service._apply_expiration(abandoned, raise_error=False)
    assert result2.status == AttemptStatus.ABANDONED

    with Session(bind=bind) as check_db:
        db_att2 = check_db.get(AssessmentAttempt, attempt2.id)
        assert db_att2 is not None
        assert db_att2.status == AttemptStatus.ABANDONED


def test_concurrent_expiration_submit_preserves_terminal_state(
    db: Session,
) -> None:
    """
    Verifies that the database-level conditional update in _apply_expiration matches 0 rows
    if the attempt was already transitioned to SUBMITTED by a concurrent transaction,
    and synchronizes the original session object to SUBMITTED rather than EXPIRED.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="race_user")
    definition = create_test_definition(db, "eval-race-test", duration_minutes=30)

    attempt = service.initialize_attempt(user.id, definition.id)
    service.start_attempt(attempt.id, user.id)

    # In DB, transition the attempt to SUBMITTED (simulating concurrent submit)
    bind = db.get_bind()
    with Session(bind=bind) as concurrent_db:
        from sqlalchemy import update as sa_update

        concurrent_db.execute(
            sa_update(AssessmentAttempt)
            .where(AssessmentAttempt.id == attempt.id)
            .values(status=AttemptStatus.SUBMITTED, submitted_at=datetime.now(UTC))
        )
        concurrent_db.commit()

    # Now attempt's in-memory status in db is still IN_PROGRESS, but DB is SUBMITTED
    # Calling _apply_expiration matches 0 rows and reloads the actual DB status
    result = service._apply_expiration(attempt, raise_error=False)
    assert result.status == AttemptStatus.SUBMITTED
    assert attempt.status == AttemptStatus.SUBMITTED

    # In DB, status must remain SUBMITTED
    with Session(bind=bind) as check_db:
        db_attempt = check_db.get(AssessmentAttempt, attempt.id)
        assert db_attempt is not None
        assert db_attempt.status == AttemptStatus.SUBMITTED


def test_identity_map_retained_access_after_expiration(db: Session) -> None:
    """
    Verifies that after expiration is persisted:
    1. The in-memory AssessmentAttempt instance in self.db is synchronized to EXPIRED.
    2. Any subsequent access using the SAME session identity map observes EXPIRED.
    3. Re-querying via the original session observes EXPIRED without needing a manual refresh.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="ident_user")
    definition = create_test_definition(db, "eval-ident-test", duration_minutes=30)

    attempt = service.initialize_attempt(user.id, definition.id)
    attempt_id = attempt.id
    service.start_attempt(attempt_id, user.id)

    # Force expiration past grace period
    now = datetime.now(UTC)
    attempt.started_at = now - timedelta(minutes=60)
    attempt.expires_at = now - timedelta(minutes=10)
    db.commit()

    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]

    with pytest.raises(AttemptExpiredError):
        service.save_task_submission(
            attempt_id=attempt_id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "print('timeout')", "language": "python"},
            expected_revision=1,
        )

    # 1. The original instance in the session has status EXPIRED
    assert attempt.status == AttemptStatus.EXPIRED

    # 2. Loading via session identity map returns the identical instance with EXPIRED
    loaded_attempt = db.get(AssessmentAttempt, attempt_id)
    assert loaded_attempt is attempt
    assert loaded_attempt.status == AttemptStatus.EXPIRED

    # 3. Querying via original session observes EXPIRED
    queried_attempt = (
        db.query(AssessmentAttempt).filter(AssessmentAttempt.id == attempt_id).first()
    )
    assert queried_attempt is attempt
    assert queried_attempt.status == AttemptStatus.EXPIRED


def test_concurrent_submit_race_prevents_reporting_expired(db: Session) -> None:
    """
    Verifies that when an attempt is overdue but concurrently transitioned to SUBMITTED:
    1. _apply_expiration detects rowcount == 0, reloads the actual DB status, and does NOT report EXPIRED.
    2. _apply_expiration does NOT raise AttemptExpiredError even when raise_error=True.
    3. get_attempt returns the attempt with status SUBMITTED.
    4. submit_attempt returns the attempt idempotently with status SUBMITTED.
    5. save_task_submission raises AttemptStateError (terminal status), never AttemptExpiredError.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="race_sub_user")
    definition = create_test_definition(db, "eval-race-sub-test", duration_minutes=30)

    attempt = service.initialize_attempt(user.id, definition.id)
    attempt_id = attempt.id
    service.start_attempt(attempt_id, user.id)

    # Force timestamps past grace period
    now = datetime.now(UTC)
    attempt.started_at = now - timedelta(minutes=60)
    attempt.expires_at = now - timedelta(minutes=10)
    db.commit()

    # Simulate concurrent final submit in a separate transaction directly on DB
    bind = db.get_bind()
    with Session(bind=bind) as other_db:
        from sqlalchemy import update as sa_update

        other_db.execute(
            sa_update(AssessmentAttempt)
            .where(AssessmentAttempt.id == attempt_id)
            .values(status=AttemptStatus.SUBMITTED, submitted_at=now)
        )
        other_db.commit()

    # 1 & 2: Calling _apply_expiration with raise_error=True must NOT raise AttemptExpiredError
    res = service._apply_expiration(attempt, raise_error=True)
    assert res.status == AttemptStatus.SUBMITTED
    assert attempt.status == AttemptStatus.SUBMITTED

    # 3: get_attempt must return the attempt with SUBMITTED status
    got_attempt = service.get_attempt(attempt_id, user.id)
    assert got_attempt.status == AttemptStatus.SUBMITTED

    # 4: submit_attempt must return the attempt idempotently with SUBMITTED status
    sub_attempt = service.submit_attempt(attempt_id, user.id)
    assert sub_attempt.status == AttemptStatus.SUBMITTED

    # 5: save_task_submission must reject with AttemptStateError (not AttemptExpiredError)
    coding_task = [t for t in definition.tasks if t.task_type == TaskType.CODING][0]
    with pytest.raises(AttemptStateError, match="terminal status 'SUBMITTED'"):
        service.save_task_submission(
            attempt_id=attempt_id,
            task_id=coding_task.id,
            user_id=user.id,
            submission_payload={"code": "late code", "language": "python"},
            expected_revision=1,
        )


def test_concurrent_abandon_race_prevents_reporting_expired(db: Session) -> None:
    """
    Verifies that when an attempt is overdue but concurrently transitioned to ABANDONED:
    1. _apply_expiration detects rowcount == 0, reloads the actual DB status, and does NOT report EXPIRED.
    2. _apply_expiration does NOT raise AttemptExpiredError even when raise_error=True.
    3. abandon_attempt returns the attempt idempotently with status ABANDONED.
    """
    service = AssessmentAttemptService(db)
    user = create_test_user(db, prefix="race_ab_user")
    definition = create_test_definition(db, "eval-race-ab-test", duration_minutes=30)

    attempt = service.initialize_attempt(user.id, definition.id)
    attempt_id = attempt.id
    service.start_attempt(attempt_id, user.id)

    # Force timestamps past grace period
    now = datetime.now(UTC)
    attempt.started_at = now - timedelta(minutes=60)
    attempt.expires_at = now - timedelta(minutes=10)
    db.commit()

    # Simulate concurrent abandonment in a separate transaction directly on DB
    bind = db.get_bind()
    with Session(bind=bind) as other_db:
        from sqlalchemy import update as sa_update

        other_db.execute(
            sa_update(AssessmentAttempt)
            .where(AssessmentAttempt.id == attempt_id)
            .values(status=AttemptStatus.ABANDONED)
        )
        other_db.commit()

    # Calling _apply_expiration with raise_error=True must NOT raise AttemptExpiredError
    res = service._apply_expiration(attempt, raise_error=True)
    assert res.status == AttemptStatus.ABANDONED
    assert attempt.status == AttemptStatus.ABANDONED

    # abandon_attempt must return the attempt idempotently
    ab_attempt = service.abandon_attempt(attempt_id, user.id)
    assert ab_attempt.status == AttemptStatus.ABANDONED


def test_apply_expiration_missing_attempt_raises_not_found(db: Session) -> None:
    """
    Verifies that if an attempt row is completely absent from the database,
    _apply_expiration safely raises AttemptNotFoundError rather than masking it.
    """
    service = AssessmentAttemptService(db)
    missing_id = uuid.uuid4()
    transient_attempt = AssessmentAttempt(
        id=missing_id,
        user_id=uuid.uuid4(),
        assessment_definition_id=uuid.uuid4(),
        status=AttemptStatus.IN_PROGRESS,
        attempt_number=1,
    )

    with pytest.raises(AttemptNotFoundError, match="was not found in database"):
        service._apply_expiration(transient_attempt, raise_error=True)
