import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.assessment_attempt import AttemptStatus
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.task_submission import TaskSubmissionStatus
from app.schemas.assessment import CandidateTaskResponse

if TYPE_CHECKING:
    from app.models.assessment_attempt import AssessmentAttempt

# ==============================================================================
# Constants & Size Thresholds
# ==============================================================================

MAX_SUBMISSION_PAYLOAD_BYTES = 128 * 1024  # 128 KB
MAX_AGGREGATE_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MB

SUPPORTED_CODING_LANGUAGES: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "java",
        "cpp",
        "c",
        "csharp",
        "go",
        "rust",
        "sql",
        "ruby",
        "php",
        "swift",
        "kotlin",
        "scala",
        "html",
        "css",
        "bash",
        "shell",
    }
)


# ==============================================================================
# Canonical Serialization & Byte Measurement
# ==============================================================================


def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a Python object to JSON using deterministic, canonical formatting.
    - Rejects non-finite numbers (NaN, Infinity, -Infinity) via allow_nan=False.
    - Preserves native Unicode characters without escape sequences (ensure_ascii=False).
    - Guarantees deterministic key ordering (sort_keys=True).
    - Strips arbitrary whitespace using compact separators (',', ':').
    """
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_payload_bytes(payload: dict[str, Any]) -> int:
    """
    Calculates the exact UTF-8 byte size of a dictionary payload using the canonical
    JSON serialization protocol.
    """
    serialized = canonical_json_dumps(payload)
    return len(serialized.encode("utf-8"))


# ==============================================================================
# Task-Specific Submission Payloads
# ==============================================================================


class CodingSubmissionPayload(BaseModel):
    """Candidate submission payload for a CODING task."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        default="",
        description="Candidate source code solution",
    )
    language: str = Field(
        ...,
        description="Selected programming language for the solution",
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("Language cannot be empty.")
        if cleaned not in SUPPORTED_CODING_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{v}'. Allowed languages: "
                f"{', '.join(sorted(SUPPORTED_CODING_LANGUAGES))}"
            )
        return cleaned


class MultipleChoiceSubmissionPayload(BaseModel):
    """Candidate submission payload for a MULTIPLE_CHOICE task."""

    model_config = ConfigDict(extra="forbid")

    selected_option_ids: list[str] = Field(
        default_factory=list,
        description="List of selected option identifiers",
    )

    @field_validator("selected_option_ids")
    @classmethod
    def validate_options(cls, v: list[str]) -> list[str]:
        cleaned_list: list[str] = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError("Option ID must be a string.")
            s = item.strip()
            if not s:
                raise ValueError("Option ID cannot be empty.")
            cleaned_list.append(s)

        if len(cleaned_list) != len(set(cleaned_list)):
            raise ValueError("Duplicate option selections are not allowed.")

        return cleaned_list


class FreeResponseSubmissionPayload(BaseModel):
    """Candidate submission payload for a FREE_RESPONSE task."""

    model_config = ConfigDict(extra="forbid")

    response_text: str = Field(
        default="",
        description="Written response, architecture proposal, or design explanation",
    )
    format: str = Field(
        default="markdown",
        description="Format of the response: 'markdown' or 'text'",
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in {"markdown", "text"}:
            raise ValueError("Format must be either 'markdown' or 'text'.")
        return cleaned


class CodeAnalysisSubmissionPayload(BaseModel):
    """Candidate submission payload for a CODE_ANALYSIS or debugging task."""

    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(
        default="",
        description="Root cause defect analysis, bug explanation, or diagnosis",
    )
    proposed_fix: str | None = Field(
        default=None,
        description="Optional proposed patch or repaired code snippet",
    )
    language: str | None = Field(
        default=None,
        description="Optional language identifier for the proposed fix",
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip().lower()
        if not cleaned:
            return None
        if cleaned not in SUPPORTED_CODING_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{v}'. Allowed languages: "
                f"{', '.join(sorted(SUPPORTED_CODING_LANGUAGES))}"
            )
        return cleaned


# ==============================================================================
# Contextual Dispatch Validator
# ==============================================================================


def validate_submission_payload(
    task: AssessmentTask,
    raw_payload: Any,
) -> dict[str, Any]:
    """
    Validates a raw submission payload against its corresponding task type schema and
    task definition constraints (e.g. allowed choices, single vs multi-select, language targets).

    Raises ValueError or Pydantic ValidationError if the payload is malformed or invalid.
    """
    if not isinstance(raw_payload, dict):
        raise ValueError("Submission payload must be a JSON object (dictionary).")

    # 1. Enforce strict JSON conformance and reject non-finite numbers (NaN, Inf)
    try:
        canonical_json_dumps(raw_payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Submission payload is not strictly JSON compliant: {exc}"
        ) from exc

    # 2. Schema-level validation based on task execution type
    validated_model: BaseModel
    if task.task_type == TaskType.CODING:
        validated_model = CodingSubmissionPayload.model_validate(raw_payload)
        coding_data = validated_model.model_dump()

        # Contextual check: if the task specifies a target language in payload or metadata
        expected_lang: str | None = None
        if isinstance(task.payload, dict) and "language" in task.payload:
            expected_lang = str(task.payload["language"]).strip().lower()
        elif (
            isinstance(task.task_metadata, dict)
            and "target_language" in task.task_metadata
        ):
            expected_lang = str(task.task_metadata["target_language"]).strip().lower()

        if expected_lang and coding_data["language"] != expected_lang:
            raise ValueError(
                f"Selected language '{coding_data['language']}' does not match "
                f"required task language '{expected_lang}'."
            )
        return coding_data

    elif task.task_type == TaskType.MULTIPLE_CHOICE:
        validated_model = MultipleChoiceSubmissionPayload.model_validate(raw_payload)
        mcq_data = validated_model.model_dump()
        selected_ids: list[str] = mcq_data["selected_option_ids"]

        # Contextual check: validate option IDs against defined choices
        task_payload = task.payload if isinstance(task.payload, dict) else {}
        raw_choices = task_payload.get("choices", [])
        valid_choice_ids: set[str] = set()

        if isinstance(raw_choices, list):
            for choice in raw_choices:
                if isinstance(choice, dict):
                    c_id = choice.get("id") or choice.get("label") or choice.get("text")
                    if c_id:
                        valid_choice_ids.add(str(c_id).strip())
                elif isinstance(choice, str):
                    valid_choice_ids.add(choice.strip())

        # If choices are configured on the task, reject any unknown option ID
        if valid_choice_ids:
            for opt_id in selected_ids:
                if opt_id not in valid_choice_ids:
                    raise ValueError(
                        f"Invalid MCQ option ID '{opt_id}'. Allowed choices: "
                        f"{', '.join(sorted(valid_choice_ids))}"
                    )

        # Contextual check: enforce single-choice vs multi-choice
        multi_select = bool(task_payload.get("multi_select", False))
        if not multi_select and len(selected_ids) > 1:
            raise ValueError(
                f"This multiple choice task only allows a single selection; "
                f"{len(selected_ids)} options were submitted."
            )

        return mcq_data

    elif task.task_type == TaskType.FREE_RESPONSE:
        validated_model = FreeResponseSubmissionPayload.model_validate(raw_payload)
        return validated_model.model_dump()

    elif task.task_type == TaskType.CODE_ANALYSIS:
        validated_model = CodeAnalysisSubmissionPayload.model_validate(raw_payload)
        return validated_model.model_dump()

    else:
        raise ValueError(f"Unsupported task type '{task.task_type}'.")


# ==============================================================================
# Request Schemas for Client Submission
# ==============================================================================


class TaskSubmissionSaveRequest(BaseModel):
    """Autosave request payload for updating candidate work on an assessment task."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(
        ...,
        ge=1,
        description="Expected current revision number for optimistic concurrency checking",
    )
    submission_payload: dict[str, Any] = Field(
        ...,
        description="Candidate work payload conforming to task type schema",
    )
    status: TaskSubmissionStatus = Field(
        default=TaskSubmissionStatus.IN_PROGRESS,
        description="Candidate progress status on this task",
    )

    @field_validator("status")
    @classmethod
    def validate_autosave_status(cls, v: TaskSubmissionStatus) -> TaskSubmissionStatus:
        if v not in (TaskSubmissionStatus.IN_PROGRESS, TaskSubmissionStatus.COMPLETED):
            raise ValueError(
                f"Status '{v}' is not a valid autosave status. Allowed: "
                f"{TaskSubmissionStatus.IN_PROGRESS.value}, {TaskSubmissionStatus.COMPLETED.value}"
            )
        return v


# ==============================================================================
# Response Schemas for Client Consumption
# ==============================================================================


class TaskSubmissionResponse(BaseModel):
    """Candidate-safe task submission read schema."""

    id: uuid.UUID
    attempt_id: uuid.UUID
    task_id: uuid.UUID
    revision: int
    status: TaskSubmissionStatus
    submission_payload: dict[str, Any]
    last_saved_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("last_saved_at", "created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class AssessmentAttemptResponse(BaseModel):
    """Candidate-safe assessment attempt read schema."""

    id: uuid.UUID
    assessment_definition_id: uuid.UUID
    assessment_identifier: str
    assessment_version: int
    assessment_title: str
    status: AttemptStatus
    attempt_number: int
    started_at: datetime | None = None
    expires_at: datetime | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    submissions: list[TaskSubmissionResponse] = Field(default_factory=list)
    tasks: list[CandidateTaskResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator(
        "started_at",
        "expires_at",
        "submitted_at",
        "created_at",
        "updated_at",
        mode="after",
    )
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)

    @classmethod
    def from_orm_attempt(
        cls, attempt: "AssessmentAttempt"
    ) -> "AssessmentAttemptResponse":
        """
        Maps an ORM AssessmentAttempt into an explicit candidate-safe response.
        - Strictly projects pinned assessment metadata (identifier, version, title).
        - Sanitizes tasks, stripping internal authoring metadata and rubrics.
        - Does NOT mutate any ORM attributes.
        """
        from app.schemas.assessment import (
            CandidateCompetencySummary,
            CandidateTaskResponse,
            build_candidate_metadata,
            build_candidate_payload,
        )

        def_obj = attempt.assessment_definition
        assessment_identifier = def_obj.identifier if def_obj else ""
        assessment_version = def_obj.version if def_obj else 0
        assessment_title = def_obj.title if def_obj else ""

        # Map candidate-safe tasks
        candidate_tasks: list[CandidateTaskResponse] = []
        if def_obj and def_obj.tasks:
            sorted_tasks = sorted(def_obj.tasks, key=lambda t: (t.order_index, t.id))
            for t in sorted_tasks:
                comp = (
                    CandidateCompetencySummary.model_validate(t.competency)
                    if t.competency
                    else None
                )
                candidate_tasks.append(
                    CandidateTaskResponse(
                        id=t.id,
                        identifier=t.identifier,
                        order_index=t.order_index,
                        title=t.title,
                        task_type=t.task_type,
                        prompt=t.prompt,
                        payload=build_candidate_payload(t.task_type, t.payload),
                        task_metadata=build_candidate_metadata(t.task_metadata),
                        competency=comp,
                    )
                )

        # Map candidate-safe submissions
        candidate_subs: list[TaskSubmissionResponse] = []
        if attempt.submissions:
            task_order_map = {t.id: idx for idx, t in enumerate(candidate_tasks)}
            sorted_subs = sorted(
                attempt.submissions,
                key=lambda s: (task_order_map.get(s.task_id, 999999), s.task_id),
            )
            for s in sorted_subs:
                candidate_subs.append(TaskSubmissionResponse.model_validate(s))

        return cls(
            id=attempt.id,
            assessment_definition_id=attempt.assessment_definition_id,
            assessment_identifier=assessment_identifier,
            assessment_version=assessment_version,
            assessment_title=assessment_title,
            status=attempt.status,
            attempt_number=attempt.attempt_number,
            started_at=attempt.started_at,
            expires_at=attempt.expires_at,
            submitted_at=attempt.submitted_at,
            created_at=attempt.created_at,
            updated_at=attempt.updated_at,
            submissions=candidate_subs,
            tasks=candidate_tasks,
        )


class AssessmentAttemptListResponse(BaseModel):
    """Paginated list envelope for candidate assessment attempts."""

    items: list[AssessmentAttemptResponse]
    total: int
    limit: int
    offset: int
