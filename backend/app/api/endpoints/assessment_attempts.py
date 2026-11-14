import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.assessment_attempt import AttemptStatus
from app.models.assessment_definition import AssessmentStatus
from app.models.user import User
from app.repositories.assessment_definition import AssessmentDefinitionRepository
from app.schemas.task_submission import (
    AssessmentAttemptListResponse,
    AssessmentAttemptResponse,
    TaskSubmissionResponse,
    TaskSubmissionSaveRequest,
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
    TaskNotFoundError,
)

router = APIRouter()


@router.post(
    "/{assessment_id}/attempts",
    response_model=AssessmentAttemptResponse,
    summary="Initialize assessment attempt",
    description=(
        "Initializes an assessment attempt against a published assessment definition. "
        "Accepts either an exact definition UUID or a stable identifier slug (resolving "
        "to the latest published version). Returns 201 Created for a new attempt or "
        "200 OK if an existing active attempt is returned idempotently."
    ),
)
def initialize_attempt(
    assessment_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptResponse:
    """Initialize or recover an active candidate assessment attempt."""
    definition_repo = AssessmentDefinitionRepository(db)
    service = AssessmentAttemptService(db)

    # Resolution: UUID resolves to exact definition; slug resolves to latest published
    definition = None
    try:
        def_uuid = uuid.UUID(assessment_id)
        definition = definition_repo.get_by_id(def_uuid)
    except ValueError:
        definition = definition_repo.get_latest_published(assessment_id)

    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment '{assessment_id}' was not found.",
        )

    # New attempts are allowed strictly on PUBLISHED definitions
    if definition.status != AssessmentStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot initialize attempt on assessment '{assessment_id}' "
                f"with status '{definition.status.value}'."
            ),
        )

    try:
        attempt, created = service.initialize_attempt(
            user_id=current_user.id,
            assessment_definition_id=definition.id,
            return_created=True,
        )
    except AssessmentUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if created:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK

    return AssessmentAttemptResponse.from_orm_attempt(attempt)


@router.get(
    "/attempts",
    response_model=AssessmentAttemptListResponse,
    status_code=status.HTTP_200_OK,
    summary="List candidate assessment attempts",
    description=(
        "Lists candidate's own assessment attempts with optional status and "
        "assessment definition filtering, structured in a paginated envelope "
        "with stable deterministic ordering."
    ),
)
def list_attempts(
    response: Response,
    assessment_definition_id: uuid.UUID | None = Query(
        default=None,
        description="Filter attempts by exact assessment definition ID",
    ),
    status_filter: AttemptStatus | None = Query(
        default=None,
        alias="status",
        description="Filter attempts by status",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of attempts to return",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of attempts to skip",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptListResponse:
    """Fetch paginated candidate attempt history."""
    service = AssessmentAttemptService(db)
    items, total = service.list_attempts(
        user_id=current_user.id,
        assessment_definition_id=assessment_definition_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return AssessmentAttemptListResponse(
        items=[AssessmentAttemptResponse.from_orm_attempt(att) for att in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/attempts/{attempt_id}",
    response_model=AssessmentAttemptResponse,
    status_code=status.HTTP_200_OK,
    summary="Get candidate assessment attempt detail",
    description=(
        "Retrieves a candidate's assessment attempt with candidate-safe tasks "
        "and submissions. Evaluator rubrics and authoring secrets are strictly omitted."
    ),
)
def get_attempt(
    attempt_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptResponse:
    """Fetch candidate-safe attempt detail."""
    service = AssessmentAttemptService(db)
    try:
        attempt = service.get_attempt(attempt_id=attempt_id, user_id=current_user.id)
    except AttemptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment attempt '{attempt_id}' was not found.",
        ) from exc
    return AssessmentAttemptResponse.from_orm_attempt(attempt)


@router.post(
    "/attempts/{attempt_id}/start",
    response_model=AssessmentAttemptResponse,
    status_code=status.HTTP_200_OK,
    summary="Start assessment attempt",
    description=(
        "Transitions an attempt from INITIALIZED to IN_PROGRESS. "
        "Sets started_at and expires_at timestamps. Idempotently returns 200 "
        "if already IN_PROGRESS."
    ),
)
def start_attempt(
    attempt_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptResponse:
    """Start an initialized assessment attempt."""
    service = AssessmentAttemptService(db)
    try:
        attempt = service.start_attempt(attempt_id=attempt_id, user_id=current_user.id)
    except AttemptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment attempt '{attempt_id}' was not found.",
        ) from exc
    except AttemptExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
    except AttemptStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return AssessmentAttemptResponse.from_orm_attempt(attempt)


@router.put(
    "/attempts/{attempt_id}/tasks/{task_id}/submission",
    response_model=TaskSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Autosave task submission",
    description=(
        "Autosaves candidate progress on an individual task within an active attempt. "
        "Validates optimistic revision, payload limits (128 KB single, 2 MB aggregate), "
        "and task-specific schema."
    ),
)
def save_task_submission(
    attempt_id: uuid.UUID,
    task_id: uuid.UUID,
    request: TaskSubmissionSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskSubmissionResponse:
    """Autosave task submission with revision and size validation."""
    service = AssessmentAttemptService(db)
    try:
        sub = service.save_task_submission(
            attempt_id=attempt_id,
            task_id=task_id,
            user_id=current_user.id,
            submission_payload=request.submission_payload,
            expected_revision=request.expected_revision,
            status=request.status,
        )
    except AttemptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment attempt '{attempt_id}' was not found.",
        ) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AttemptExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
    except StaleRevisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except SubmissionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except AttemptStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TaskSubmissionResponse.model_validate(sub)


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=AssessmentAttemptResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit assessment attempt",
    description=(
        "Final submission of an assessment attempt. Atomically transitions "
        "the attempt from IN_PROGRESS to SUBMITTED. Serializes cleanly against autosaves."
    ),
)
def submit_attempt(
    attempt_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptResponse:
    """Finalize and submit assessment attempt."""
    service = AssessmentAttemptService(db)
    try:
        attempt = service.submit_attempt(attempt_id=attempt_id, user_id=current_user.id)
    except AttemptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment attempt '{attempt_id}' was not found.",
        ) from exc
    except AttemptExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
    except AttemptStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return AssessmentAttemptResponse.from_orm_attempt(attempt)


@router.post(
    "/attempts/{attempt_id}/abandon",
    response_model=AssessmentAttemptResponse,
    status_code=status.HTTP_200_OK,
    summary="Abandon assessment attempt",
    description=(
        "Candidate voluntarily abandons an initialized or in-progress attempt. "
        "Idempotent: returning existing attempt if already ABANDONED."
    ),
)
def abandon_attempt(
    attempt_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAttemptResponse:
    """Voluntarily abandon an assessment attempt."""
    service = AssessmentAttemptService(db)
    try:
        attempt = service.abandon_attempt(
            attempt_id=attempt_id, user_id=current_user.id
        )
    except AttemptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment attempt '{attempt_id}' was not found.",
        ) from exc
    except AttemptExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
    except AttemptStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return AssessmentAttemptResponse.from_orm_attempt(attempt)
