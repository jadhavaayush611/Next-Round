import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_profile import CandidateProfile
from app.models.candidate_target import CandidateTarget
from app.models.resume_parse import ParseStatus, ResumeParse
from app.models.user import User
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.schemas.candidate_claim import (
    CandidateClaimCreate,
    CandidateClaimResponse,
)
from app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileResponse,
    CandidateProfileUpdate,
)
from app.schemas.candidate_target import (
    CandidateTargetCreate,
    CandidateTargetResponse,
)
from app.utils.json_pointer import resolve_json_pointer


class CandidateService:
    """
    Coordinates candidate profile, target management, and claim provenance logic.
    Enforces strict server-side ownership, transactional target state management,
    and provenance invariants between claims and resume parses.
    """

    @staticmethod
    def _is_target_uniqueness_conflict(exc: IntegrityError) -> bool:
        """
        Determine if an IntegrityError corresponds to a genuine violation of the
        one-active-target partial unique index rather than unrelated database errors.
        """
        err_msg = str(exc).lower()
        if "uq_candidate_targets_active_profile" in err_msg:
            return True
        if (
            "unique constraint failed" in err_msg
            and "candidate_targets.candidate_profile_id" in err_msg
        ):
            return True
        if "duplicate key" in err_msg and "candidate_targets" in err_msg:
            return True
        return False

    def __init__(self, db: Session):
        self.db = db
        self.profile_repo = CandidateProfileRepository(db)
        self.target_repo = CandidateTargetRepository(db)
        self.claim_repo = CandidateClaimRepository(db)

    # =========================================================================
    # Candidate Profile Operations
    # =========================================================================

    def get_profile(self, user: User) -> CandidateProfile:
        """Fetch candidate profile for the authenticated user, or raise 404."""
        profile = self.profile_repo.get_by_user_id(user.id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate profile not found.",
            )
        return profile

    def get_or_create_profile(self, user: User) -> CandidateProfile:
        """Retrieve existing profile or create a default empty profile for user."""
        profile = self.profile_repo.get_by_user_id(user.id)
        if not profile:
            profile = CandidateProfile(user_id=user.id)
            profile = self.profile_repo.create(profile)
        return profile

    def create_profile(
        self, user: User, profile_in: CandidateProfileCreate
    ) -> CandidateProfileResponse:
        """
        Create a new CandidateProfile for the authenticated user.
        Rejects if a profile already exists (enforcing 1:1 user to profile).
        """
        existing = self.profile_repo.get_by_user_id(user.id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate profile already exists for this user.",
            )

        db_profile = CandidateProfile(
            user_id=user.id,
            preferred_locations=profile_in.preferred_locations,
            graduation_year=profile_in.graduation_year,
        )
        created = self.profile_repo.create(db_profile)
        return CandidateProfileResponse.model_validate(created)

    def update_profile(
        self, user: User, profile_in: CandidateProfileUpdate
    ) -> CandidateProfileResponse:
        """Update mutable fields of the current user's profile."""
        profile = self.get_profile(user)
        update_data: dict[str, Any] = profile_in.model_dump(exclude_unset=True)

        updated = self.profile_repo.update(profile, update_data)
        active_target = self.target_repo.get_active_target(updated.id)

        response = CandidateProfileResponse.model_validate(updated)
        if active_target:
            response.active_target = CandidateTargetResponse.model_validate(
                active_target
            )
        return response

    def get_profile_response(self, user: User) -> CandidateProfileResponse:
        """Return the validated profile response including the currently active target if present."""
        profile = self.get_profile(user)
        active_target = self.target_repo.get_active_target(profile.id)
        response = CandidateProfileResponse.model_validate(profile)
        if active_target:
            response.active_target = CandidateTargetResponse.model_validate(
                active_target
            )
        return response

    # =========================================================================
    # Candidate Target Operations
    # =========================================================================

    def create_target(
        self, user: User, target_in: CandidateTargetCreate
    ) -> CandidateTargetResponse:
        """
        Create a new target for the candidate's profile.
        If is_active is True, transactionally deactivates existing active targets
        to preserve historical targets while enforcing at most one active target.
        """
        profile = self.get_or_create_profile(user)

        if target_in.is_active:
            self.target_repo.deactivate_all_for_profile(profile.id)
            self.db.flush()

        db_target = CandidateTarget(
            candidate_profile_id=profile.id,
            role_title=target_in.role_title,
            company=target_in.company,
            job_description=target_in.job_description,
            is_active=target_in.is_active,
        )
        try:
            created = self.target_repo.create(db_target)
        except IntegrityError as exc:
            self.db.rollback()
            if self._is_target_uniqueness_conflict(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Target conflict: another target is currently active for this candidate profile.",
                ) from exc
            raise
        return CandidateTargetResponse.model_validate(created)

    def list_targets(
        self, user: User, active_only: bool = False
    ) -> list[CandidateTargetResponse]:
        """List all targets for the candidate's profile in reverse chronological order."""
        profile = self.profile_repo.get_by_user_id(user.id)
        if not profile:
            return []
        targets = self.target_repo.list_by_profile(profile.id, active_only=active_only)
        return [CandidateTargetResponse.model_validate(t) for t in targets]

    def get_active_target(self, user: User) -> CandidateTargetResponse:
        """Retrieve the active target for the authenticated candidate."""
        profile = self.get_profile(user)
        active_target = self.target_repo.get_active_target(profile.id)
        if not active_target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active target found for candidate profile.",
            )
        return CandidateTargetResponse.model_validate(active_target)

    def activate_target(
        self, user: User, target_id: uuid.UUID
    ) -> CandidateTargetResponse:
        """
        Activate a historical target, transactionally deactivating any previously active target.
        """
        profile = self.get_profile(user)
        target = self.target_repo.get(target_id)
        if not target or target.candidate_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate target not found.",
            )

        if not target.is_active:
            self.target_repo.deactivate_all_for_profile(profile.id)
            self.db.flush()
            target.is_active = True
            self.db.add(target)
            try:
                self.db.commit()
                self.db.refresh(target)
            except IntegrityError as exc:
                self.db.rollback()
                if self._is_target_uniqueness_conflict(exc):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Target conflict: another target is currently active for this candidate profile.",
                    ) from exc
                raise

        return CandidateTargetResponse.model_validate(target)

    def deactivate_target(
        self, user: User, target_id: uuid.UUID
    ) -> CandidateTargetResponse:
        """
        Deactivate a target, leaving the profile with no active target.
        """
        profile = self.get_profile(user)
        target = self.target_repo.get(target_id)
        if not target or target.candidate_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate target not found.",
            )

        if target.is_active:
            target.is_active = False
            self.db.add(target)
            self.db.commit()
            self.db.refresh(target)

        return CandidateTargetResponse.model_validate(target)

    # =========================================================================
    # Candidate Claim Operations
    # =========================================================================

    def create_claim(
        self, user: User, claim_in: CandidateClaimCreate
    ) -> CandidateClaimResponse:
        """
        Persist a candidate claim with strict provenance verification.
        - RESUME claims require valid resume_parse_id and canonical_path.
        - Verifies that the referenced ResumeParse belongs to a Resume owned by user.
        - USER_DECLARED claims forbid resume provenance fields.
        """
        if claim_in.origin == ClaimOrigin.RESUME:
            if not claim_in.resume_parse_id or not claim_in.canonical_path:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Resume-derived claims require both resume_parse_id and canonical_path.",
                )

            # Follow relationship to Resume and User to verify ownership
            query = (
                select(ResumeParse)
                .options(joinedload(ResumeParse.resume))
                .where(ResumeParse.id == claim_in.resume_parse_id)
            )
            parse_record = self.db.execute(query).scalars().first()

            if (
                not parse_record
                or not parse_record.resume
                or parse_record.resume.user_id != user.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced resume parse does not exist or is not owned by the current user.",
                )

            if parse_record.status != ParseStatus.READY:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced resume parse snapshot is not in READY status.",
                )

            if not parse_record.canonical_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Referenced resume parse snapshot contains no canonical data.",
                )

            try:
                resolve_json_pointer(
                    parse_record.canonical_data, claim_in.canonical_path
                )
            except (KeyError, IndexError, LookupError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"canonical_path '{claim_in.canonical_path}' does not resolve within the referenced ResumeParse snapshot: {exc}",
                ) from exc

        elif claim_in.origin == ClaimOrigin.USER_DECLARED:
            if (
                claim_in.resume_parse_id is not None
                or claim_in.canonical_path is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="User-declared claims must not specify resume provenance.",
                )

        db_claim = CandidateClaim(
            user_id=user.id,
            claim_type=claim_in.claim_type,
            claim_text=claim_in.claim_text,
            origin=claim_in.origin,
            resume_parse_id=claim_in.resume_parse_id,
            canonical_path=claim_in.canonical_path,
        )
        created = self.claim_repo.create(db_claim)
        return CandidateClaimResponse.model_validate(created)

    def list_claims(
        self,
        user: User,
        claim_type: ClaimType | None = None,
        origin: ClaimOrigin | None = None,
    ) -> list[CandidateClaimResponse]:
        """List claims owned by the authenticated candidate."""
        claims = self.claim_repo.list_by_user(
            user.id, claim_type=claim_type, origin=origin
        )
        return [CandidateClaimResponse.model_validate(c) for c in claims]

    def get_claim(self, user: User, claim_id: uuid.UUID) -> CandidateClaimResponse:
        """Retrieve a specific claim, enforcing candidate ownership."""
        claim = self.claim_repo.get(claim_id)
        if not claim or claim.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )
        return CandidateClaimResponse.model_validate(claim)
