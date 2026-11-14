from app.db.session import Base
from app.models.assessment_attempt import AssessmentAttempt, AttemptStatus
from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_profile import CandidateProfile
from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.candidate_target import CandidateTarget
from app.models.competency import Competency, CompetencyDimension
from app.models.evaluation_rubric import EvaluationMode, EvaluationRubric
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.resume import Resume, ResumeStatus
from app.models.resume_parse import ParseStatus, ResumeParse
from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
    RoleRequirement,
)
from app.models.skill import Skill
from app.models.task_submission import TaskSubmission, TaskSubmissionStatus
from app.models.user import User
from app.models.verification_result import (
    VerificationEvidence,
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)

__all__ = [
    "Base",
    "User",
    "Resume",
    "ResumeStatus",
    "ResumeParse",
    "ParseStatus",
    "CandidateProfile",
    "CandidateTarget",
    "CandidateClaim",
    "ClaimType",
    "ClaimOrigin",
    "EvidenceSource",
    "EvidenceSourceType",
    "AccessMode",
    "EvidenceSourceStatus",
    "EvidenceItem",
    "EvidenceType",
    "VerificationResult",
    "VerificationEvidence",
    "VerificationType",
    "VerificationOutcome",
    "Skill",
    "CandidateSkill",
    "CandidateSkillEvidence",
    "RoleRequirement",
    "RequirementType",
    "RequirementImportance",
    "RequirementSourceType",
    "Competency",
    "CompetencyDimension",
    "AssessmentDefinition",
    "AssessmentType",
    "AssessmentDifficulty",
    "AssessmentStatus",
    "AssessmentTask",
    "TaskType",
    "EvaluationRubric",
    "EvaluationMode",
    "AssessmentAttempt",
    "AttemptStatus",
    "TaskSubmission",
    "TaskSubmissionStatus",
]
