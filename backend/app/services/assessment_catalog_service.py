import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask
from app.models.evaluation_rubric import EvaluationRubric
from app.repositories.assessment_definition import AssessmentDefinitionRepository
from app.repositories.assessment_task import AssessmentTaskRepository
from app.repositories.competency import CompetencyRepository
from app.repositories.evaluation_rubric import EvaluationRubricRepository
from app.schemas.assessment import (
    AssessmentCatalogItemResponse,
    AssessmentDefinitionCreate,
    AssessmentDefinitionUpdate,
    AssessmentDetailResponse,
    AssessmentTaskCreate,
    AssessmentTaskUpdate,
    CandidateCompetencySummary,
    CandidateTaskResponse,
    EvaluationRubricCreate,
    build_candidate_metadata,
    build_candidate_payload,
)


class AssessmentCatalogError(Exception):
    """Base exception for assessment catalog service errors."""

    pass


class AssessmentNotFoundError(AssessmentCatalogError):
    """Raised when an assessment definition is not found or not accessible to the candidate."""

    pass


class AssessmentImmutableError(AssessmentCatalogError):
    """Raised when attempting to modify a published or deprecated assessment version."""

    pass


class AssessmentValidationError(AssessmentCatalogError):
    """Raised when assessment structure or publication requirements are violated."""

    pass


class TaskNotFoundError(AssessmentCatalogError):
    """Raised when an assessment task is not found."""

    pass


class RubricNotFoundError(AssessmentCatalogError):
    """Raised when an evaluation rubric is not found."""

    pass


class AssessmentCatalogService:
    """
    Catalog service for managing versioned assessments and serving candidate-facing queries.
    Enforces immutability of published definitions, guarantees clean candidate payload redaction,
    and isolates evaluator-only rubrics from candidate access.
    """

    def __init__(self, db: Session):
        self.db = db
        self.definition_repo = AssessmentDefinitionRepository(db)
        self.task_repo = AssessmentTaskRepository(db)
        self.rubric_repo = EvaluationRubricRepository(db)
        self.competency_repo = CompetencyRepository(db)

    # ==========================================================================
    # Candidate-Facing API Operations (Read-Only & Sanitized)
    # ==========================================================================

    def list_published_assessments(
        self,
        assessment_type: AssessmentType | None = None,
        difficulty: AssessmentDifficulty | None = None,
        skill_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AssessmentCatalogItemResponse], int]:
        """
        List published assessments resolving strictly to the latest published version of each.
        Excludes drafts and deprecated definitions entirely.
        Returns candidate-safe catalog summary representations.
        """
        records, total = self.definition_repo.list_latest_published(
            assessment_type=assessment_type,
            difficulty=difficulty,
            skill_id=skill_id,
            search=search,
            limit=limit,
            offset=offset,
        )

        items = [
            AssessmentCatalogItemResponse(
                id=d.id,
                identifier=d.identifier,
                version=d.version,
                title=d.title,
                description=d.description,
                assessment_type=d.assessment_type,
                difficulty=d.difficulty,
                duration_minutes=d.duration_minutes,
                task_count=len(d.tasks),
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in records
        ]
        return items, total

    def get_published_assessment(
        self,
        identifier_or_id: str | uuid.UUID,
        version: int | None = None,
    ) -> AssessmentDetailResponse:
        """
        Retrieve a specific published assessment for candidate viewing.
        Resolves either by UUID primary key or by stable identifier (+ optional version).
        Raises AssessmentNotFoundError if not found or if not in PUBLISHED status.
        Candidate-facing schemas strictly omit rubrics and internal grading artifacts.
        """
        definition: AssessmentDefinition | None = None

        # Check if identifier_or_id is a valid UUID
        target_uuid: uuid.UUID | None = None
        if isinstance(identifier_or_id, uuid.UUID):
            target_uuid = identifier_or_id
        else:
            try:
                target_uuid = uuid.UUID(identifier_or_id)
            except ValueError:
                target_uuid = None

        if target_uuid is not None:
            definition = self.definition_repo.get_by_id(target_uuid)
            if definition and version is not None and definition.version != version:
                definition = None
        else:
            identifier_str = str(identifier_or_id).strip()
            if version is not None:
                definition = self.definition_repo.get_by_identifier_and_version(
                    identifier_str, version
                )
            else:
                definition = self.definition_repo.get_latest_published(identifier_str)

        if not definition or definition.status != AssessmentStatus.PUBLISHED:
            raise AssessmentNotFoundError(
                f"Published assessment '{identifier_or_id}' was not found."
            )

        # Build candidate-safe detail representation
        candidate_tasks: list[CandidateTaskResponse] = []
        for task in sorted(definition.tasks, key=lambda t: t.order_index):
            competency_summary: CandidateCompetencySummary | None = None
            if task.competency:
                competency_summary = CandidateCompetencySummary(
                    identifier=task.competency.identifier,
                    name=task.competency.name,
                    dimension=task.competency.dimension,
                    skill_canonical_name=(
                        task.competency.skill.canonical_name
                        if task.competency.skill
                        else None
                    ),
                )

            # Build candidate-visible payload and task metadata via strict allowlist validation
            candidate_payload = build_candidate_payload(task.task_type, task.payload)
            candidate_metadata = build_candidate_metadata(task.task_metadata)

            candidate_tasks.append(
                CandidateTaskResponse(
                    id=task.id,
                    identifier=task.identifier,
                    order_index=task.order_index,
                    title=task.title,
                    task_type=task.task_type,
                    prompt=task.prompt,
                    payload=candidate_payload,
                    task_metadata=candidate_metadata,
                    competency=competency_summary,
                )
            )

        return AssessmentDetailResponse(
            id=definition.id,
            identifier=definition.identifier,
            version=definition.version,
            title=definition.title,
            description=definition.description,
            assessment_type=definition.assessment_type,
            difficulty=definition.difficulty,
            duration_minutes=definition.duration_minutes,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
            tasks=candidate_tasks,
        )

    # ==========================================================================
    # Internal Authoring & Version Management Operations
    # ==========================================================================

    def create_definition(
        self, definition_in: AssessmentDefinitionCreate
    ) -> AssessmentDefinition:
        """
        Create a new assessment definition in DRAFT status.
        Calculates the appropriate version number (1 for new, max + 1 if previous exist).
        """
        max_ver = self.definition_repo.get_max_version(definition_in.identifier)
        next_ver = max_ver + 1

        db_definition = AssessmentDefinition(
            identifier=definition_in.identifier,
            version=next_ver,
            title=definition_in.title,
            description=definition_in.description,
            assessment_type=definition_in.assessment_type,
            difficulty=definition_in.difficulty,
            duration_minutes=definition_in.duration_minutes,
            status=AssessmentStatus.DRAFT,
        )
        self.db.add(db_definition)
        self.db.flush()

        # Add initial tasks if specified
        for task_in in definition_in.tasks:
            self._add_task_internal(db_definition, task_in)

        try:
            self.db.commit()
            self.db.refresh(db_definition)
        except IntegrityError as exc:
            self.db.rollback()
            raise AssessmentValidationError(
                f"Failed to persist assessment definition '{definition_in.identifier}': {exc}"
            ) from exc

        return db_definition

    def update_draft_definition(
        self, definition_id: uuid.UUID, update_in: AssessmentDefinitionUpdate
    ) -> AssessmentDefinition:
        """Update metadata on an existing DRAFT assessment definition."""
        definition = self.definition_repo.get_by_id(definition_id)
        if not definition:
            raise AssessmentNotFoundError(
                f"Assessment definition '{definition_id}' not found."
            )

        if definition.status != AssessmentStatus.DRAFT:
            raise AssessmentImmutableError(
                f"Assessment version {definition.version} has status '{definition.status}' and cannot be modified. Create a new revision instead."
            )

        update_dict: dict[str, Any] = {}
        if update_in.title is not None:
            update_dict["title"] = update_in.title
        if update_in.description is not None:
            update_dict["description"] = update_in.description
        if update_in.assessment_type is not None:
            update_dict["assessment_type"] = update_in.assessment_type
        if update_in.difficulty is not None:
            update_dict["difficulty"] = update_in.difficulty
        if update_in.duration_minutes is not None:
            update_dict["duration_minutes"] = update_in.duration_minutes

        return self.definition_repo.update(definition, update_dict)

    def add_task_to_draft(
        self, definition_id: uuid.UUID, task_in: AssessmentTaskCreate
    ) -> AssessmentTask:
        """Add a task to an existing DRAFT assessment definition."""
        definition = self.definition_repo.get_by_id(definition_id)
        if not definition:
            raise AssessmentNotFoundError(
                f"Assessment definition '{definition_id}' not found."
            )

        if definition.status != AssessmentStatus.DRAFT:
            raise AssessmentImmutableError(
                f"Assessment version {definition.version} is {definition.status} and immutable. Tasks cannot be added."
            )

        task = self._add_task_internal(definition, task_in)
        try:
            self.db.commit()
            self.db.refresh(task)
        except IntegrityError as exc:
            self.db.rollback()
            raise AssessmentValidationError(
                f"Failed to add task '{task_in.identifier}': {exc}"
            ) from exc

        return task

    def update_draft_task(
        self, task_id: uuid.UUID, update_in: AssessmentTaskUpdate
    ) -> AssessmentTask:
        """Modify a task in a DRAFT assessment definition."""
        task = self.task_repo.get_by_id(task_id)
        if not task:
            raise TaskNotFoundError(f"Assessment task '{task_id}' not found.")

        if task.assessment_definition.status != AssessmentStatus.DRAFT:
            raise AssessmentImmutableError(
                "Cannot modify task of a published or deprecated assessment version."
            )

        update_dict: dict[str, Any] = {}
        if update_in.title is not None:
            update_dict["title"] = update_in.title
        if update_in.order_index is not None:
            update_dict["order_index"] = update_in.order_index
        if update_in.task_type is not None:
            update_dict["task_type"] = update_in.task_type
        if update_in.prompt is not None:
            update_dict["prompt"] = update_in.prompt
        if update_in.payload is not None:
            update_dict["payload"] = update_in.payload
        if update_in.task_metadata is not None:
            update_dict["task_metadata"] = update_in.task_metadata
        if update_in.competency_id is not None:
            # Validate competency exists and is active
            comp = self.competency_repo.get_by_id(update_in.competency_id)
            if not comp:
                raise AssessmentValidationError(
                    f"Competency with id '{update_in.competency_id}' does not exist."
                )
            if not comp.is_active:
                raise AssessmentValidationError(
                    f"Competency '{comp.identifier}' is inactive and cannot be assigned to an assessment task."
                )
            update_dict["competency_id"] = update_in.competency_id

        return self.task_repo.update(task, update_dict)

    def delete_draft_task(self, task_id: uuid.UUID) -> None:
        """Remove a task from a DRAFT assessment definition."""
        task = self.task_repo.get_by_id(task_id)
        if not task:
            raise TaskNotFoundError(f"Assessment task '{task_id}' not found.")

        if task.assessment_definition.status != AssessmentStatus.DRAFT:
            raise AssessmentImmutableError(
                "Cannot delete task of a published or deprecated assessment version."
            )

        self.task_repo.remove(task_id)

    def set_task_rubric(
        self, task_id: uuid.UUID, rubric_in: EvaluationRubricCreate
    ) -> EvaluationRubric:
        """Configure or update the evaluation rubric for a draft task."""
        task = self.task_repo.get_by_id(task_id)
        if not task:
            raise TaskNotFoundError(f"Assessment task '{task_id}' not found.")

        if task.assessment_definition.status != AssessmentStatus.DRAFT:
            raise AssessmentImmutableError(
                "Cannot modify rubric of a published or deprecated assessment version."
            )

        criteria_dicts = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in rubric_in.criteria
        ]

        existing_rubric = self.rubric_repo.get_by_task_id(task_id)
        if existing_rubric:
            updated = self.rubric_repo.update(
                existing_rubric,
                {
                    "evaluation_mode": rubric_in.evaluation_mode,
                    "criteria": criteria_dicts,
                    "rubric_metadata": rubric_in.rubric_metadata,
                },
            )
            return updated
        else:
            new_rubric = EvaluationRubric(
                task_id=task_id,
                evaluation_mode=rubric_in.evaluation_mode,
                criteria=criteria_dicts,
                rubric_metadata=rubric_in.rubric_metadata,
            )
            created = self.rubric_repo.create(new_rubric)
            return created

    def publish_assessment(self, definition_id: uuid.UUID) -> AssessmentDefinition:
        """
        Transition an assessment definition from DRAFT to PUBLISHED.
        Verifies that:
        - Assessment is currently in DRAFT status.
        - Has at least one AssessmentTask.
        - Every task has a prompt and an EvaluationRubric.
        Once published, the assessment and its tasks/rubrics are permanently immutable.
        """
        definition = self.definition_repo.get_by_id(definition_id)
        if not definition:
            raise AssessmentNotFoundError(
                f"Assessment definition '{definition_id}' not found."
            )

        if definition.status == AssessmentStatus.PUBLISHED:
            return definition

        if definition.status == AssessmentStatus.DEPRECATED:
            raise AssessmentImmutableError(
                "Cannot publish an assessment that has been deprecated."
            )

        if not definition.tasks or len(definition.tasks) == 0:
            raise AssessmentValidationError(
                f"Cannot publish assessment '{definition.identifier}' without any tasks."
            )

        for task in definition.tasks:
            if not task.prompt or not task.prompt.strip():
                raise AssessmentValidationError(
                    f"Task '{task.identifier}' has an empty prompt and cannot be published."
                )
            if not task.rubric:
                raise AssessmentValidationError(
                    f"Task '{task.identifier}' must have an EvaluationRubric before publication."
                )
            if task.competency_id:
                comp = self.competency_repo.get_by_id(task.competency_id)
                if not comp:
                    raise AssessmentValidationError(
                        f"Task '{task.identifier}' references non-existent competency '{task.competency_id}'."
                    )
                if not comp.is_active:
                    raise AssessmentValidationError(
                        f"Cannot publish assessment '{definition.identifier}': task '{task.identifier}' references inactive competency '{comp.identifier}'."
                    )

        definition.status = AssessmentStatus.PUBLISHED
        self.db.commit()
        self.db.refresh(definition)
        return definition

    def deprecate_assessment(self, definition_id: uuid.UUID) -> AssessmentDefinition:
        """
        Transition a PUBLISHED assessment definition to DEPRECATED.
        Preserves historical attempts and prevents new catalog listings.
        """
        definition = self.definition_repo.get_by_id(definition_id)
        if not definition:
            raise AssessmentNotFoundError(
                f"Assessment definition '{definition_id}' not found."
            )

        if definition.status != AssessmentStatus.PUBLISHED:
            raise AssessmentValidationError(
                f"Only published assessments can be deprecated. Current status: '{definition.status}'."
            )

        definition.status = AssessmentStatus.DEPRECATED
        self.db.commit()
        self.db.refresh(definition)
        return definition

    def create_revision(
        self, identifier_or_id: str | uuid.UUID
    ) -> AssessmentDefinition:
        """
        Create a new DRAFT revision from an existing assessment definition.
        Copies definition fields, tasks, and rubrics into a new version record (version = current_max + 1).
        The original published version remains completely untouched.
        """
        # Resolve source
        source: AssessmentDefinition | None = None
        if isinstance(identifier_or_id, uuid.UUID):
            source = self.definition_repo.get_by_id(identifier_or_id)
        else:
            try:
                target_uuid = uuid.UUID(identifier_or_id)
                source = self.definition_repo.get_by_id(target_uuid)
            except ValueError:
                source = self.definition_repo.get_latest_published(identifier_or_id)

        if not source:
            raise AssessmentNotFoundError(
                f"Source assessment definition '{identifier_or_id}' not found."
            )

        max_ver = self.definition_repo.get_max_version(source.identifier)
        new_version = max_ver + 1

        new_def = AssessmentDefinition(
            identifier=source.identifier,
            version=new_version,
            title=source.title,
            description=source.description,
            assessment_type=source.assessment_type,
            difficulty=source.difficulty,
            duration_minutes=source.duration_minutes,
            status=AssessmentStatus.DRAFT,
        )
        self.db.add(new_def)
        self.db.flush()

        # Clone tasks and their rubrics
        for t in sorted(source.tasks, key=lambda x: x.order_index):
            new_task = AssessmentTask(
                assessment_definition_id=new_def.id,
                competency_id=t.competency_id,
                identifier=t.identifier,
                order_index=t.order_index,
                task_type=t.task_type,
                title=t.title,
                prompt=t.prompt,
                payload=dict(t.payload) if t.payload else {},
                task_metadata=dict(t.task_metadata) if t.task_metadata else {},
            )
            self.db.add(new_task)
            self.db.flush()

            if t.rubric:
                new_rubric = EvaluationRubric(
                    task_id=new_task.id,
                    evaluation_mode=t.rubric.evaluation_mode,
                    criteria=[dict(c) for c in (t.rubric.criteria or [])],
                    rubric_metadata=dict(t.rubric.rubric_metadata or {}),
                )
                self.db.add(new_rubric)

        self.db.commit()
        self.db.refresh(new_def)
        return new_def

    # ==========================================================================
    # Internal Helpers
    # ==========================================================================

    def _add_task_internal(
        self,
        definition: AssessmentDefinition,
        task_in: AssessmentTaskCreate,
    ) -> AssessmentTask:
        """Internal helper to construct and attach a task and its rubric."""
        # Validate competency if provided (must exist and be active)
        if task_in.competency_id:
            comp = self.competency_repo.get_by_id(task_in.competency_id)
            if not comp:
                raise AssessmentValidationError(
                    f"Competency with id '{task_in.competency_id}' does not exist."
                )
            if not comp.is_active:
                raise AssessmentValidationError(
                    f"Competency '{comp.identifier}' is inactive and cannot be assigned to an assessment task."
                )

        # Check task identifier collision within this definition
        for existing in definition.tasks:
            if existing.identifier == task_in.identifier:
                raise AssessmentValidationError(
                    f"Task identifier '{task_in.identifier}' is already used in this definition."
                )
            if existing.order_index == task_in.order_index:
                raise AssessmentValidationError(
                    f"Task order index {task_in.order_index} is already used in this definition."
                )

        db_task = AssessmentTask(
            assessment_definition_id=definition.id,
            competency_id=task_in.competency_id,
            identifier=task_in.identifier,
            order_index=task_in.order_index,
            task_type=task_in.task_type,
            title=task_in.title,
            prompt=task_in.prompt,
            payload=task_in.payload,
            task_metadata=task_in.task_metadata,
        )
        self.db.add(db_task)
        self.db.flush()

        if task_in.rubric:
            criteria_dicts = [
                c.model_dump() if hasattr(c, "model_dump") else c
                for c in task_in.rubric.criteria
            ]
            rubric = EvaluationRubric(
                task_id=db_task.id,
                evaluation_mode=task_in.rubric.evaluation_mode,
                criteria=criteria_dicts,
                rubric_metadata=task_in.rubric.rubric_metadata,
            )
            self.db.add(rubric)

        return db_task
