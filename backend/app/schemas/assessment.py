import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.assessment_definition import (
    AssessmentDifficulty,
    AssessmentType,
)
from app.models.assessment_task import TaskType
from app.models.competency import CompetencyDimension
from app.models.evaluation_rubric import EvaluationMode

# ==============================================================================
# Evaluator & Authoring Schemas (Internal Only)
# ==============================================================================


class RubricCriterionSchema(BaseModel):
    """
    Structured rubric criterion definition.
    Explicitly avoids arbitrary numerical weights and percentage formulas.
    """

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(
        ...,
        description="Stable identifier for this criterion within the rubric",
    )
    name: str = Field(
        ...,
        description="Concise descriptive title of the criterion",
    )
    description: str = Field(
        ...,
        description="Detailed evaluation instructions and observable behaviors",
    )
    eval_type: str = Field(
        default="QUALITATIVE",
        description="Criterion classification (e.g. QUALITATIVE, BEHAVIORAL, CONFORMANCE)",
    )
    guidelines: list[str] = Field(
        default_factory=list,
        description="Specific evidence markers for the evaluator",
    )

    @field_validator("criterion_id", "name", "description")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty")
        return stripped


class EvaluationRubricCreate(BaseModel):
    """Private evaluation configuration and rubric criteria for an assessment task."""

    model_config = ConfigDict(extra="forbid")

    evaluation_mode: EvaluationMode
    criteria: list[RubricCriterionSchema] = Field(
        default_factory=list,
        description="Structured criteria items without numerical weights",
    )
    rubric_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Evaluator-only configuration such as hidden test cases, expected solutions, or reviewer instructions",
    )


class EvaluationRubricResponse(BaseModel):
    """Internal read schema for an evaluation rubric."""

    id: uuid.UUID
    task_id: uuid.UUID
    evaluation_mode: EvaluationMode
    criteria: list[dict[str, Any]]
    rubric_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class AssessmentTaskCreate(BaseModel):
    """Payload for creating a task within a draft assessment definition."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    order_index: int = Field(ge=0)
    title: str
    task_type: TaskType
    prompt: str
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Candidate-visible task data (e.g., initial code templates, question choices)",
    )
    task_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Candidate-visible task metadata (e.g., language, estimated duration)",
    )
    competency_id: uuid.UUID | None = None
    rubric: EvaluationRubricCreate | None = None

    @field_validator("identifier", "title", "prompt")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty")
        return stripped


class AssessmentTaskUpdate(BaseModel):
    """Payload for updating a task in a draft assessment definition."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    task_type: TaskType | None = None
    prompt: str | None = None
    payload: dict[str, Any] | None = None
    task_metadata: dict[str, Any] | None = None
    competency_id: uuid.UUID | None = None


class AssessmentDefinitionCreate(BaseModel):
    """Payload for authoring a new assessment definition in DRAFT status."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    title: str
    description: str
    assessment_type: AssessmentType
    difficulty: AssessmentDifficulty
    duration_minutes: int | None = Field(default=None, gt=0)
    tasks: list[AssessmentTaskCreate] = Field(default_factory=list)

    @field_validator("identifier", "title", "description")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty")
        return stripped


class AssessmentDefinitionUpdate(BaseModel):
    """Payload for modifying an existing DRAFT assessment definition."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    assessment_type: AssessmentType | None = None
    difficulty: AssessmentDifficulty | None = None
    duration_minutes: int | None = Field(default=None, gt=0)


# ==============================================================================
# Candidate-Facing Payload & Metadata Allowlist Schemas
# ==============================================================================


class CandidatePublicTestCase(BaseModel):
    """Candidate-safe public test case representation. Drops any unapproved keys."""

    model_config = ConfigDict(extra="ignore")

    description: str | None = None
    input: Any = None
    expected_output: Any = None
    limit: Any = None
    window_seconds: Any = None
    parameters: dict[str, Any] | None = None


class CandidateMultipleChoiceOption(BaseModel):
    """Candidate-safe multiple choice option. Strictly omits answer keys or scoring."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    text: str | None = None
    label: str | None = None
    code: str | None = None


class CandidateCodingPayload(BaseModel):
    """Candidate-visible coding task payload."""

    model_config = ConfigDict(extra="ignore")

    language: str | None = None
    starter_code: str | None = None
    code_template: str | None = None
    public_test_cases: list[CandidatePublicTestCase] | None = None
    allowed_libraries: list[str] | None = None
    instructions: str | None = None


class CandidateMultipleChoicePayload(BaseModel):
    """Candidate-visible multiple choice task payload."""

    model_config = ConfigDict(extra="ignore")

    question: str | None = None
    choices: list[CandidateMultipleChoiceOption | str] | None = None
    multi_select: bool | None = None
    code_snippet: str | None = None


class CandidateCodeAnalysisPayload(BaseModel):
    """Candidate-visible code analysis/debugging task payload."""

    model_config = ConfigDict(extra="ignore")

    language: str | None = None
    source_code: str | None = None
    code_snippet: str | None = None
    line_numbers: bool | None = None
    context: str | None = None
    file_name: str | None = None


class CandidateFreeResponsePayload(BaseModel):
    """Candidate-visible free response task payload."""

    model_config = ConfigDict(extra="ignore")

    design_requirements: list[str] | None = None
    constraints: list[str] | None = None
    deliverables: list[str] | None = None
    context: str | None = None
    format: str | None = None


class CandidateTaskMetadata(BaseModel):
    """Candidate-visible task metadata. Strictly drops evaluator configurations."""

    model_config = ConfigDict(extra="ignore")

    estimated_time_minutes: int | float | None = None
    target_language: str | None = None
    format: str | None = None
    difficulty: str | None = None
    allowed_tools: list[str] | None = None
    environment: str | None = None


def build_candidate_payload(
    task_type: TaskType, raw_payload: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Validates and transforms raw database task payload into an explicit, allowlisted
    candidate-visible dictionary. Strictly prunes unknown fields, authoring metadata,
    and nested evaluator configurations.
    """
    if not raw_payload:
        return {}

    validated_model: BaseModel
    if task_type == TaskType.CODING:
        validated_model = CandidateCodingPayload.model_validate(raw_payload)
    elif task_type == TaskType.MULTIPLE_CHOICE:
        validated_model = CandidateMultipleChoicePayload.model_validate(raw_payload)
    elif task_type == TaskType.CODE_ANALYSIS:
        validated_model = CandidateCodeAnalysisPayload.model_validate(raw_payload)
    elif task_type == TaskType.FREE_RESPONSE:
        validated_model = CandidateFreeResponsePayload.model_validate(raw_payload)
    else:
        return {}

    return validated_model.model_dump(exclude_none=True)


def build_candidate_metadata(
    raw_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Validates and transforms raw database task metadata into an explicit, allowlisted
    candidate-visible dictionary. Strictly prunes unknown fields, private benchmarks,
    and evaluator scripts.
    """
    if not raw_metadata:
        return {}

    validated_model = CandidateTaskMetadata.model_validate(raw_metadata)
    return validated_model.model_dump(exclude_none=True)


# ==============================================================================
# Candidate-Facing Schemas (Strictly Sanitized & Redacted)
# ==============================================================================


class CandidateCompetencySummary(BaseModel):
    """Candidate-visible competency metadata."""

    identifier: str
    name: str
    dimension: CompetencyDimension
    skill_canonical_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CandidateTaskResponse(BaseModel):
    """
    Candidate-visible task payload.
    Guarantees strict exclusion of:
    - evaluation rubrics
    - correct answers
    - hidden tests
    - solution code
    - grading formulas
    """

    id: uuid.UUID
    identifier: str
    order_index: int
    title: str
    task_type: TaskType
    prompt: str
    payload: dict[str, Any]
    task_metadata: dict[str, Any]
    competency: CandidateCompetencySummary | None = None

    model_config = ConfigDict(from_attributes=True)


class AssessmentCatalogItemResponse(BaseModel):
    """
    Public catalog summary card for a published assessment.
    Represents the unambiguous latest published revision.
    """

    id: uuid.UUID
    identifier: str
    version: int
    title: str
    description: str
    assessment_type: AssessmentType
    difficulty: AssessmentDifficulty
    duration_minutes: int | None
    task_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class AssessmentDetailResponse(BaseModel):
    """
    Detailed candidate-facing representation of a specific published assessment.
    Contains strictly candidate-visible tasks in sequential order.
    """

    id: uuid.UUID
    identifier: str
    version: int
    title: str
    description: str
    assessment_type: AssessmentType
    difficulty: AssessmentDifficulty
    duration_minutes: int | None
    created_at: datetime
    updated_at: datetime
    tasks: list[CandidateTaskResponse]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
