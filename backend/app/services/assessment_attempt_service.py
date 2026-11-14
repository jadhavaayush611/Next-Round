import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, overload

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment_attempt import AssessmentAttempt, AttemptStatus
from app.models.assessment_definition import AssessmentStatus
from app.models.assessment_task import AssessmentTask
from app.models.task_submission import TaskSubmission, TaskSubmissionStatus
from app.repositories.assessment_attempt import AssessmentAttemptRepository
from app.repositories.assessment_definition import AssessmentDefinitionRepository
from app.repositories.assessment_task import AssessmentTaskRepository
from app.repositories.task_submission import TaskSubmissionRepository
from app.schemas.task_submission import (
    MAX_AGGREGATE_PAYLOAD_BYTES,
    MAX_SUBMISSION_PAYLOAD_BYTES,
    calculate_payload_bytes,
    validate_submission_payload,
)

# ==============================================================================
# Domain Exceptions
# ==============================================================================


class AssessmentAttemptError(Exception):
    """Base exception for all assessment attempt service errors."""

    pass


class AttemptNotFoundError(AssessmentAttemptError):
    """Raised when an assessment attempt cannot be found for the candidate."""

    pass


class TaskNotFoundError(AssessmentAttemptError):
    """Raised when a task does not exist or does not belong to the assessment definition."""

    pass


class AttemptStateError(AssessmentAttemptError):
    """Raised when an attempt lifecycle operation is invalid for its current status."""

    pass


class AttemptExpiredError(AssessmentAttemptError):
    """Raised when an operation is attempted on an expired assessment attempt."""

    pass


class StaleRevisionError(AssessmentAttemptError):
    """Raised when an optimistic revision conflict is detected during an autosave."""

    pass


class PayloadTooLargeError(AssessmentAttemptError):
    """Raised when an individual submission or aggregate attempt payload exceeds limits."""

    pass


class SubmissionValidationError(AssessmentAttemptError):
    """Raised when a candidate task submission payload is malformed or invalid."""

    pass


class AssessmentUnavailableError(AssessmentAttemptError):
    """Raised when attempting to initialize an attempt on a non-published assessment."""

    pass


# ==============================================================================
# DateTime Helpers
# ==============================================================================


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensures a datetime instance is timezone-aware and set to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ==============================================================================
# Service Implementation
# ==============================================================================


class AssessmentAttemptService:
    """
    Domain service orchestrating assessment attempt lifecycles, autosave submissions,
    and strict version/payload integrity.

    Architectural guarantees:
    - Service layer owns all transaction boundaries and commits.
    - Universal Lock Order: Always lock AssessmentAttempt first, TaskSubmission second.
    - Expiration: Server-side UTC evaluation with a 120-second grace period for timed attempts.
    - Expiration Persistence: Always commits the EXPIRED transition cleanly before raising.
    - Strict Payload Validation: Task-specific schema validation, deterministic UTF-8 byte
      measurement, 128 KB single submission limit, and 2 MB aggregate attempt limit.
    """

    GRACE_PERIOD_SECONDS: int = 120

    def __init__(self, db: Session):
        self.db = db
        self.attempt_repo = AssessmentAttemptRepository(db)
        self.submission_repo = TaskSubmissionRepository(db)
        self.definition_repo = AssessmentDefinitionRepository(db)
        self.task_repo = AssessmentTaskRepository(db)

    # ==========================================================================
    # Expiration Helpers
    # ==========================================================================

    def _is_expired(
        self, attempt: AssessmentAttempt, now: datetime | None = None
    ) -> bool:
        """
        Determines whether a timed attempt has exceeded its allotted time plus grace period.
        Untimed attempts (expires_at is None) never expire automatically.
        """
        expires_at = _ensure_utc(attempt.expires_at)
        if expires_at is None:
            return False
        if now is None:
            now = datetime.now(UTC)
        else:
            now = _ensure_utc(now) or datetime.now(UTC)
        cutoff = expires_at + timedelta(seconds=self.GRACE_PERIOD_SECONDS)
        return now > cutoff

    def _apply_expiration(
        self,
        attempt: AssessmentAttempt,
        raise_error: bool = True,
    ) -> AssessmentAttempt:
        """
        Transitions an expired attempt to EXPIRED and commits the update cleanly
        using an isolated database session so that:
        - EXPIRED is committed reliably and atomically in the database.
        - Unrelated pending dirty/new objects in the caller's session are NOT silently discarded.
        - Unrelated pending dirty/new objects in the caller's session are NOT accidentally committed.
        - Terminal states (SUBMITTED, ABANDONED, etc.) are protected against overwrite.
        - Concurrent transitions (rowcount == 0) reload the actual state from DB and never report EXPIRED falsely.
        - Missing database rows are handled safely.
        """
        attempt_id = attempt.id
        now = datetime.now(UTC)

        # 1. Terminal state check on in-memory object
        if attempt.status in (
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATING,
            AttemptStatus.EVALUATED,
            AttemptStatus.MANUAL_REVIEW_PENDING,
            AttemptStatus.ABANDONED,
            AttemptStatus.EXPIRED,
        ):
            if raise_error and attempt.status == AttemptStatus.EXPIRED:
                raise AttemptExpiredError(
                    f"Assessment attempt '{attempt_id}' has expired beyond its time limit "
                    f"and grace period."
                )
            return attempt

        # 2. Persist EXPIRED atomically via an isolated database session bound to the same engine
        bind = self.db.get_bind()
        rowcount = 0
        actual_persisted_status: AttemptStatus | None = None
        actual_updated_at: datetime | None = None
        row_found = False

        with Session(bind=bind) as isolated_db:
            stmt = (
                update(AssessmentAttempt)
                .where(
                    AssessmentAttempt.id == attempt_id,
                    AssessmentAttempt.status.notin_(
                        [
                            AttemptStatus.SUBMITTED,
                            AttemptStatus.EVALUATING,
                            AttemptStatus.EVALUATED,
                            AttemptStatus.MANUAL_REVIEW_PENDING,
                            AttemptStatus.ABANDONED,
                            AttemptStatus.EXPIRED,
                        ]
                    ),
                )
                .values(status=AttemptStatus.EXPIRED, updated_at=now)
            )
            result = isolated_db.execute(stmt)
            isolated_db.commit()
            rowcount = result.rowcount if isinstance(result, CursorResult) else 0

            if rowcount == 0:
                # Reload the actual persisted status and updated_at from the database
                row = isolated_db.execute(
                    select(
                        AssessmentAttempt.status, AssessmentAttempt.updated_at
                    ).where(AssessmentAttempt.id == attempt_id)
                ).first()
                if row is not None:
                    row_found = True
                    actual_persisted_status = row[0]
                    actual_updated_at = row[1]

        # 3. Synchronize status on current session object
        if rowcount == 1:
            attempt.status = AttemptStatus.EXPIRED
            attempt.updated_at = now
            if raise_error:
                raise AttemptExpiredError(
                    f"Assessment attempt '{attempt_id}' has expired beyond its time limit "
                    f"and grace period."
                )
            return attempt

        # rowcount == 0: another transaction concurrently modified the attempt, or row is missing
        if not row_found:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found in database."
            )

        if actual_persisted_status is not None:
            attempt.status = actual_persisted_status
            if actual_updated_at is not None:
                attempt.updated_at = actual_updated_at

            # Never report AttemptExpiredError if the database state is a terminal non-expired state
            if attempt.status in (
                AttemptStatus.SUBMITTED,
                AttemptStatus.EVALUATING,
                AttemptStatus.EVALUATED,
                AttemptStatus.MANUAL_REVIEW_PENDING,
                AttemptStatus.ABANDONED,
            ):
                return attempt

            # If the database was already EXPIRED, report AttemptExpiredError if requested
            if attempt.status == AttemptStatus.EXPIRED:
                if raise_error:
                    raise AttemptExpiredError(
                        f"Assessment attempt '{attempt_id}' has expired beyond its time limit "
                        f"and grace period."
                    )
                return attempt

        return attempt

    # ==========================================================================
    # Attempt Lifecycle Operations
    # ==========================================================================

    @overload
    def initialize_attempt(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID,
        *,
        return_created: Literal[False] = False,
    ) -> AssessmentAttempt: ...

    @overload
    def initialize_attempt(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID,
        *,
        return_created: Literal[True],
    ) -> tuple[AssessmentAttempt, bool]: ...

    @overload
    def initialize_attempt(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID,
        *,
        return_created: bool,
    ) -> AssessmentAttempt | tuple[AssessmentAttempt, bool]: ...

    def initialize_attempt(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID,
        *,
        return_created: bool = False,
    ) -> AssessmentAttempt | tuple[AssessmentAttempt, bool]:
        """
        Initializes an assessment attempt for a candidate against a published assessment definition.
        - Idempotent: returns existing active attempt (INITIALIZED or IN_PROGRESS) if one exists.
        - Assigns sequential attempt numbers safely.
        - Eagerly seeds empty TaskSubmission records for all tasks in the assessment definition.
        - Concurrently safe: catches unique constraint collisions and recovers the active attempt.
        - When return_created=True, returns tuple (attempt, created: bool).
        """
        definition = self.definition_repo.get_by_id(assessment_definition_id)
        if not definition:
            raise AssessmentUnavailableError(
                f"Assessment definition '{assessment_definition_id}' was not found."
            )

        if definition.status == AssessmentStatus.DRAFT:
            raise AssessmentUnavailableError(
                f"Cannot initialize attempt on unpublished draft assessment '{definition.identifier}'."
            )
        if definition.status == AssessmentStatus.DEPRECATED:
            raise AssessmentUnavailableError(
                f"Cannot initialize attempt on deprecated assessment '{definition.identifier}'."
            )

        # Check for an existing active attempt (INITIALIZED or IN_PROGRESS)
        active_attempt = self.attempt_repo.get_active_attempt(
            user_id, assessment_definition_id
        )
        if active_attempt:
            # If the active attempt has already expired, finalize it and allow a new attempt
            if self._is_expired(active_attempt):
                self._apply_expiration(active_attempt, raise_error=False)
            else:
                return (active_attempt, False) if return_created else active_attempt

        # Calculate the next attempt number for this user and definition version
        next_attempt_number = (
            self.attempt_repo.get_max_attempt_number(user_id, assessment_definition_id)
            + 1
        )

        attempt = AssessmentAttempt(
            user_id=user_id,
            assessment_definition_id=assessment_definition_id,
            status=AttemptStatus.INITIALIZED,
            attempt_number=next_attempt_number,
        )

        try:
            with self.db.begin_nested():
                self.attempt_repo.create_attempt(attempt)

                # Eagerly seed task submissions for every task in the assessment definition
                submissions = [
                    TaskSubmission(
                        attempt_id=attempt.id,
                        task_id=task.id,
                        assessment_definition_id=assessment_definition_id,
                        revision=1,
                        status=TaskSubmissionStatus.NOT_STARTED,
                        submission_payload={},
                    )
                    for task in (definition.tasks or [])
                ]
                if submissions:
                    self.submission_repo.create_submissions_batch(submissions)

            self.db.commit()
            # Refresh to load relationships
            res = (
                self.attempt_repo.get_candidate_attempt(
                    attempt.id, user_id, for_update=False
                )
                or attempt
            )
            return (res, True) if return_created else res

        except IntegrityError:
            # Concurrent initialization recovery: another worker/request created an attempt
            self.db.rollback()
            existing_active = self.attempt_repo.get_active_attempt(
                user_id, assessment_definition_id
            )
            if existing_active:
                if self._is_expired(existing_active):
                    self._apply_expiration(existing_active, raise_error=False)
                    # Retry recursive initialization once expired attempt is cleared
                    if return_created:
                        return self.initialize_attempt(
                            user_id,
                            assessment_definition_id,
                            return_created=True,
                        )
                    return self.initialize_attempt(
                        user_id,
                        assessment_definition_id,
                        return_created=False,
                    )
                return (existing_active, False) if return_created else existing_active
            raise

    def start_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> AssessmentAttempt:
        """
        Starts an attempt, transitioning it from INITIALIZED to IN_PROGRESS.
        - Acquires parent row lock on AssessmentAttempt.
        - Idempotent: if already IN_PROGRESS, returns the attempt without mutating timestamps.
        - Calculates expires_at based on definition duration_minutes (untimed if None).
        - Existing attempts remain playable even if the definition was subsequently deprecated.
        """
        attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=False
        )
        if not attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if attempt.status == AttemptStatus.IN_PROGRESS:
            if self._is_expired(attempt):
                self._apply_expiration(attempt)
            return attempt

        if attempt.status != AttemptStatus.INITIALIZED:
            raise AttemptStateError(
                f"Cannot start assessment attempt '{attempt_id}' in status '{attempt.status}'."
            )

        locked_attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=True
        )
        if not locked_attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if locked_attempt.status == AttemptStatus.IN_PROGRESS:
            if self._is_expired(locked_attempt):
                self._apply_expiration(locked_attempt)
            return locked_attempt

        if locked_attempt.status != AttemptStatus.INITIALIZED:
            raise AttemptStateError(
                f"Cannot start assessment attempt '{attempt_id}' in status '{locked_attempt.status}'."
            )

        now = datetime.now(UTC)
        locked_attempt.status = AttemptStatus.IN_PROGRESS
        locked_attempt.started_at = now

        duration_minutes = (
            locked_attempt.assessment_definition.duration_minutes
            if locked_attempt.assessment_definition
            else None
        )
        if duration_minutes and duration_minutes > 0:
            locked_attempt.expires_at = now + timedelta(minutes=duration_minutes)
        else:
            locked_attempt.expires_at = None

        self.db.flush()
        self.db.commit()
        return locked_attempt

    def save_task_submission(
        self,
        attempt_id: uuid.UUID,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        submission_payload: dict[str, Any],
        expected_revision: int,
        status: TaskSubmissionStatus = TaskSubmissionStatus.IN_PROGRESS,
    ) -> TaskSubmission:
        """
        Saves candidate progress on an individual task within an attempt.
        - Universal Lock Order:
            1. Lock parent AssessmentAttempt row first.
            2. Lock target TaskSubmission row second.
        - Strict state & expiration checks:
            - Attempt must be IN_PROGRESS.
            - Timed attempts accept submissions within the 120-second grace period.
            - Past grace period: transitions to EXPIRED, persists, and raises AttemptExpiredError.
        - Payload validation:
            - Strictly enforces task-specific Pydantic schemas (CODING, MCQ, FREE_RESPONSE, CODE_ANALYSIS).
            - Enforces 128 KB per submission payload limit.
            - Calculates aggregate payload size across all tasks and enforces 2 MB limit while holding
              the parent attempt lock.
        - Optimistic concurrency:
            - Verifies expected_revision matches current submission revision.
        """
        # Step 0: Check existence, status, and expiration before acquiring exclusive locks
        read_attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=False
        )
        if not read_attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if read_attempt.status == AttemptStatus.INITIALIZED:
            raise AttemptStateError(
                f"Cannot save submission for attempt '{attempt_id}' because it has not been started."
            )

        if read_attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError(
                f"Cannot save submission for attempt '{attempt_id}' in terminal status '{read_attempt.status}'."
            )

        # Check expiration before acquiring exclusive row locks
        if self._is_expired(read_attempt):
            res_attempt = self._apply_expiration(read_attempt)
            if res_attempt.status != AttemptStatus.IN_PROGRESS:
                raise AttemptStateError(
                    f"Cannot save submission for attempt '{attempt_id}' in terminal status '{res_attempt.status}'."
                )

        # Step 1: Universal lock order - Lock parent AssessmentAttempt first
        attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=True
        )
        if not attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError(
                f"Cannot save submission for attempt '{attempt_id}' in terminal status '{attempt.status}'."
            )

        # Step 2: Universal lock order - Lock child TaskSubmission second
        submission = self.submission_repo.get_submission(
            attempt_id, task_id, for_update=True
        )
        if not submission:
            raise TaskNotFoundError(
                f"Task submission for task '{task_id}' was not found in attempt '{attempt_id}'."
            )

        # Locate the task definition to perform contextual validation
        target_task: AssessmentTask | None = None
        if attempt.assessment_definition and attempt.assessment_definition.tasks:
            for t in attempt.assessment_definition.tasks:
                if t.id == task_id:
                    target_task = t
                    break

        if not target_task:
            target_task = self.task_repo.get_by_id(task_id)

        if not target_task:
            raise TaskNotFoundError(
                f"Assessment task '{task_id}' does not exist in assessment definition."
            )

        # Validate submission payload according to task type and constraints
        try:
            validated_payload = validate_submission_payload(
                target_task, submission_payload
            )
        except (ValueError, TypeError) as exc:
            raise SubmissionValidationError(str(exc)) from exc

        # Step 3: Payload byte size verification
        incoming_bytes = calculate_payload_bytes(validated_payload)
        if incoming_bytes > MAX_SUBMISSION_PAYLOAD_BYTES:
            raise PayloadTooLargeError(
                f"Submission payload size ({incoming_bytes} bytes) exceeds the maximum "
                f"limit of 128 KB ({MAX_SUBMISSION_PAYLOAD_BYTES} bytes)."
            )

        # Aggregate payload size check across all other tasks in this attempt
        other_submissions_bytes = 0
        for sub in attempt.submissions:
            if sub.task_id != task_id and sub.submission_payload:
                try:
                    other_submissions_bytes += calculate_payload_bytes(
                        sub.submission_payload
                    )
                except Exception:
                    # In case of any unparseable prior payload, fall back safely
                    pass

        total_aggregate_bytes = other_submissions_bytes + incoming_bytes
        if total_aggregate_bytes > MAX_AGGREGATE_PAYLOAD_BYTES:
            raise PayloadTooLargeError(
                f"Aggregate attempt payload size ({total_aggregate_bytes} bytes) exceeds "
                f"the maximum limit of 2 MB ({MAX_AGGREGATE_PAYLOAD_BYTES} bytes)."
            )

        # Step 4: Optimistic revision check
        if submission.revision != expected_revision:
            raise StaleRevisionError(
                f"Stale revision conflict for task '{task_id}': expected revision "
                f"{expected_revision}, but current revision is {submission.revision}."
            )

        now = datetime.now(UTC)
        updated_sub = self.submission_repo.update_submission_with_revision(
            attempt_id=attempt_id,
            task_id=task_id,
            expected_revision=expected_revision,
            submission_payload=validated_payload,
            status=status,
            last_saved_at=now,
        )

        if updated_sub is None:
            raise StaleRevisionError(
                f"Concurrent modification detected for task '{task_id}'. Expected revision was {expected_revision}."
            )

        self.db.commit()
        return updated_sub

    def submit_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> AssessmentAttempt:
        """
        Submits an attempt for evaluation.
        - Universal Lock Order: Locks parent AssessmentAttempt row, serializing cleanly against concurrent autosaves.
        - Idempotent: returns existing attempt if already SUBMITTED.
        - Validates that the attempt is IN_PROGRESS and within allowed time (+ grace period).
        """
        read_attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=False
        )
        if not read_attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if read_attempt.status == AttemptStatus.SUBMITTED:
            return read_attempt

        if read_attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError(
                f"Cannot submit attempt '{attempt_id}' in status '{read_attempt.status}'. Attempt must be IN_PROGRESS."
            )

        if self._is_expired(read_attempt):
            res_attempt = self._apply_expiration(read_attempt)
            if res_attempt.status == AttemptStatus.SUBMITTED:
                return res_attempt
            if res_attempt.status != AttemptStatus.IN_PROGRESS:
                raise AttemptStateError(
                    f"Cannot submit attempt '{attempt_id}' in status '{res_attempt.status}'. Attempt must be IN_PROGRESS."
                )

        attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=True
        )
        if not attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if attempt.status == AttemptStatus.SUBMITTED:
            return attempt

        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError(
                f"Cannot submit attempt '{attempt_id}' in status '{attempt.status}'. Attempt must be IN_PROGRESS."
            )

        now = datetime.now(UTC)
        attempt.status = AttemptStatus.SUBMITTED
        attempt.submitted_at = now

        self.db.flush()
        self.db.commit()
        return attempt

    def abandon_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> AssessmentAttempt:
        """
        Abandons an in-flight or initialized attempt.
        - Distinct from EXPIRED: abandonment is candidate-initiated.
        - Idempotent: returns existing attempt if already ABANDONED.
        - Terminal attempts (SUBMITTED, EVALUATED, etc.) cannot be abandoned.
        """
        read_attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=False
        )
        if not read_attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if read_attempt.status == AttemptStatus.ABANDONED:
            return read_attempt

        if read_attempt.status in (
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATING,
            AttemptStatus.EVALUATED,
            AttemptStatus.MANUAL_REVIEW_PENDING,
            AttemptStatus.EXPIRED,
        ):
            raise AttemptStateError(
                f"Cannot abandon attempt '{attempt_id}' in status '{read_attempt.status}'."
            )

        if self._is_expired(read_attempt):
            res_attempt = self._apply_expiration(read_attempt)
            if res_attempt.status == AttemptStatus.ABANDONED:
                return res_attempt
            if res_attempt.status != AttemptStatus.IN_PROGRESS:
                raise AttemptStateError(
                    f"Cannot abandon attempt '{attempt_id}' in status '{res_attempt.status}'."
                )

        attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=True
        )
        if not attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if attempt.status == AttemptStatus.ABANDONED:
            return attempt

        if attempt.status in (
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATING,
            AttemptStatus.EVALUATED,
            AttemptStatus.MANUAL_REVIEW_PENDING,
            AttemptStatus.EXPIRED,
        ):
            raise AttemptStateError(
                f"Cannot abandon attempt '{attempt_id}' in status '{attempt.status}'."
            )

        attempt.status = AttemptStatus.ABANDONED
        self.db.flush()
        self.db.commit()
        return attempt

    def get_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> AssessmentAttempt:
        """
        Retrieves a candidate's attempt and its submissions.
        If an in-progress attempt has expired, updates and commits EXPIRED status.
        Never exposes evaluator rubrics or hidden authoring data.
        """
        attempt = self.attempt_repo.get_candidate_attempt(
            attempt_id, user_id, for_update=False
        )
        if not attempt:
            raise AttemptNotFoundError(
                f"Assessment attempt '{attempt_id}' was not found for this candidate."
            )

        if attempt.status in (
            AttemptStatus.INITIALIZED,
            AttemptStatus.IN_PROGRESS,
        ) and self._is_expired(attempt):
            attempt = self._apply_expiration(attempt, raise_error=False)

        return attempt

    def list_attempts(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID | None = None,
        status: AttemptStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[AssessmentAttempt], int]:
        """
        Lists attempts for a candidate with optional filtering and pagination.
        """
        return self.attempt_repo.list_candidate_attempts(
            user_id=user_id,
            assessment_definition_id=assessment_definition_id,
            status=status,
            limit=limit,
            offset=offset,
        )
