import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.candidate_target import CandidateTarget
from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
    RoleRequirement,
)
from app.models.user import User
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.repositories.role_requirement import RoleRequirementRepository
from app.repositories.skill import SkillRepository
from app.schemas.role_requirement import (
    RoleRequirementCreate,
    RoleRequirementPreviewResponse,
    RoleRequirementResponse,
)
from app.services.role_requirement_parser import RoleRequirementParser
from app.services.skill_service import SkillService


class RoleRequirementService:
    """
    Candidate-scoped service for managing CandidateTarget role requirements.
    Preserves exact original requirement text, enforces canonical skill validation,
    and isolates requirements to their specific candidate target.
    """

    def __init__(self, db: Session):
        self.db = db
        self.requirement_repo = RoleRequirementRepository(db)
        self.target_repo = CandidateTargetRepository(db)
        self.profile_repo = CandidateProfileRepository(db)
        self.skill_repo = SkillRepository(db)

    def _get_validated_target(
        self, user: User, target_id: uuid.UUID
    ) -> CandidateTarget:
        """
        Validate that the target exists and is owned by the authenticated candidate.
        Returns 404 for non-existent or unowned targets to prevent info disclosure.
        """
        profile = self.profile_repo.get_by_user_id(user.id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate target not found.",
            )

        target = self.target_repo.get_by_id(target_id)
        if not target or target.candidate_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate target not found.",
            )
        return target

    def create_requirement(
        self,
        user: User,
        target_id: uuid.UUID,
        req_in: RoleRequirementCreate,
    ) -> RoleRequirementResponse:
        """
        Create and persist a role requirement associated with the candidate's target.
        Enforces canonical skill catalog validation if skill_id is supplied,
        allows unmapped requirements with skill_id=None, and preserves original text.
        """
        target = self._get_validated_target(user, target_id)

        # Validate canonical skill if provided
        if req_in.skill_id is not None:
            skill = self.skill_repo.get_by_id(req_in.skill_id)
            if not skill:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Canonical skill {req_in.skill_id} not found in catalog.",
                )

        # Create role requirement preserving exact original requirement text
        role_requirement = RoleRequirement(
            candidate_target_id=target.id,
            skill_id=req_in.skill_id,
            requirement_text=req_in.requirement_text,
            requirement_type=req_in.requirement_type,
            importance=req_in.importance,
            source_type=req_in.source_type,
        )
        self.db.add(role_requirement)
        self.db.commit()
        self.db.refresh(role_requirement)

        return RoleRequirementResponse.model_validate(role_requirement)

    def list_requirements(
        self,
        user: User,
        target_id: uuid.UUID,
        requirement_type: RequirementType | None = None,
        importance: RequirementImportance | None = None,
        source_type: RequirementSourceType | None = None,
    ) -> list[RoleRequirementResponse]:
        """
        List all role requirements configured for a specific candidate target.
        """
        target = self._get_validated_target(user, target_id)
        reqs = self.requirement_repo.list_by_target(
            candidate_target_id=target.id,
            requirement_type=requirement_type,
            importance=importance,
            source_type=source_type,
        )
        return [RoleRequirementResponse.model_validate(r) for r in reqs]

    def get_requirement(
        self,
        user: User,
        target_id: uuid.UUID,
        requirement_id: uuid.UUID,
    ) -> RoleRequirementResponse:
        """
        Retrieve a specific role requirement by ID, enforcing target ownership.
        """
        target = self._get_validated_target(user, target_id)
        req = self.requirement_repo.get_by_id(requirement_id)
        if not req or req.candidate_target_id != target.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role requirement not found.",
            )
        return RoleRequirementResponse.model_validate(req)

    def preview_requirements(
        self, user: User, target_id: uuid.UUID
    ) -> RoleRequirementPreviewResponse:
        """
        Parse the job description stored on a candidate target into structured requirement candidates.
        Performs read-only extraction and skill catalog mapping without persisting or mutating records.
        """
        target = self._get_validated_target(user, target_id)
        if not target.job_description or not target.job_description.strip():
            return RoleRequirementPreviewResponse(
                candidate_target_id=target.id,
                requirements=[],
                total_extracted=0,
            )

        skill_service = SkillService(self.db)
        catalog_skills = skill_service.list_skills()
        parser = RoleRequirementParser()
        items = parser.parse(
            target.job_description,
            catalog_skills=catalog_skills,
            skill_resolver=skill_service.resolve_skill,
        )

        return RoleRequirementPreviewResponse(
            candidate_target_id=target.id,
            requirements=items,
            total_extracted=len(items),
        )
