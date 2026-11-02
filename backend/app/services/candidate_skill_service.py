import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.user import User
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_skill import CandidateSkillRepository
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.skill import SkillRepository
from app.schemas.candidate_skill import (
    CandidateSkillCreate,
    CandidateSkillEvidenceCreate,
    CandidateSkillResponse,
)


class CandidateSkillService:
    """
    Coordinates candidate skill associations and claim/evidence provenance links.
    Enforces strict candidate ownership across user, associations, claims, and evidence items,
    canonical skill existence, uniqueness of user-skill pairs, and the exactly-one-source invariant.
    """

    def __init__(self, db: Session):
        self.db = db
        self.candidate_skill_repo = CandidateSkillRepository(db)
        self.skill_repo = SkillRepository(db)
        self.claim_repo = CandidateClaimRepository(db)
        self.evidence_item_repo = EvidenceItemRepository(db)

    def create_candidate_skill(
        self, user: User, skill_in: CandidateSkillCreate
    ) -> CandidateSkillResponse:
        """
        Associate the authenticated candidate with a canonical skill from the catalog,
        requiring explicit claim or evidence item provenance.
        """
        # 1. Validate canonical skill existence in catalog
        skill = self.skill_repo.get_by_id(skill_in.skill_id)
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canonical skill {skill_in.skill_id} not found in catalog.",
            )
        skill_name = skill.canonical_name

        # 2. Check for duplicate association
        existing = self.candidate_skill_repo.get_by_user_and_skill(user.id, skill.id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Candidate already has an association for skill '{skill_name}'.",
            )

        # 3. Validate each provenance link and candidate ownership
        validated_links: list[tuple[uuid.UUID | None, uuid.UUID | None]] = []
        for link in skill_in.evidence:
            if link.candidate_claim_id is not None:
                claim = self.claim_repo.get_by_id(link.candidate_claim_id)
                if not claim:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Candidate claim {link.candidate_claim_id} not found.",
                    )
                if claim.user_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Candidate claim {link.candidate_claim_id} belongs to a different candidate.",
                    )
                validated_links.append((claim.id, None))
            elif link.evidence_item_id is not None:
                item = self.evidence_item_repo.get_by_id(link.evidence_item_id)
                if not item:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Evidence item {link.evidence_item_id} not found.",
                    )
                if item.evidence_source.user_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Evidence item {link.evidence_item_id} belongs to a different candidate.",
                    )
                validated_links.append((None, item.id))

        # 4. Create and persist candidate skill and evidence links
        candidate_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
        self.db.add(candidate_skill)

        try:
            self.db.flush()

            for claim_id, item_id in validated_links:
                link_obj = CandidateSkillEvidence(
                    candidate_skill_id=candidate_skill.id,
                    candidate_claim_id=claim_id,
                    evidence_item_id=item_id,
                )
                self.db.add(link_obj)

            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            err = str(exc).lower()
            if (
                "uq_candidate_skills_user_skill" in err
                or "unique constraint" in err
                or "duplicate key" in err
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Candidate already has an association for skill '{skill_name}'.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database integrity violation while creating candidate skill association.",
            ) from exc

        reloaded = self.candidate_skill_repo.get_by_id(candidate_skill.id)
        if not reloaded:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve created candidate skill association.",
            )
        return CandidateSkillResponse.model_validate(reloaded)

    def list_candidate_skills(
        self, user: User, skill_id: uuid.UUID | None = None
    ) -> list[CandidateSkillResponse]:
        """List all skill associations declared for the authenticated candidate."""
        skills = self.candidate_skill_repo.list_by_user(user.id, skill_id=skill_id)
        return [CandidateSkillResponse.model_validate(s) for s in skills]

    def get_candidate_skill(
        self, user: User, candidate_skill_id: uuid.UUID
    ) -> CandidateSkillResponse:
        """Fetch a specific candidate skill association by ID, enforcing ownership."""
        candidate_skill = self.candidate_skill_repo.get_by_id(candidate_skill_id)
        if not candidate_skill or candidate_skill.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate skill association not found.",
            )
        return CandidateSkillResponse.model_validate(candidate_skill)

    def add_evidence_link(
        self,
        user: User,
        candidate_skill_id: uuid.UUID,
        evidence_in: CandidateSkillEvidenceCreate,
    ) -> CandidateSkillResponse:
        """
        Attach an additional claim or evidence item provenance source to an existing
        candidate skill association owned by the candidate.
        """
        candidate_skill = self.candidate_skill_repo.get_by_id(candidate_skill_id)
        if not candidate_skill or candidate_skill.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate skill association not found.",
            )

        if evidence_in.candidate_claim_id is not None:
            claim = self.claim_repo.get_by_id(evidence_in.candidate_claim_id)
            if not claim:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Candidate claim {evidence_in.candidate_claim_id} not found.",
                )
            if claim.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Candidate claim belongs to a different candidate.",
                )
            existing = self.candidate_skill_repo.get_evidence_link(
                candidate_skill_id, claim_id=evidence_in.candidate_claim_id
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Claim is already linked to this candidate skill.",
                )
        elif evidence_in.evidence_item_id is not None:
            item = self.evidence_item_repo.get_by_id(evidence_in.evidence_item_id)
            if not item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Evidence item {evidence_in.evidence_item_id} not found.",
                )
            if item.evidence_source.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Evidence item belongs to a different candidate.",
                )
            existing = self.candidate_skill_repo.get_evidence_link(
                candidate_skill_id, item_id=evidence_in.evidence_item_id
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Evidence item is already linked to this candidate skill.",
                )

        link_obj = CandidateSkillEvidence(
            candidate_skill_id=candidate_skill.id,
            candidate_claim_id=evidence_in.candidate_claim_id,
            evidence_item_id=evidence_in.evidence_item_id,
        )
        self.db.add(link_obj)
        candidate_skill.updated_at = datetime.now(UTC)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence link already exists for this candidate skill.",
            ) from exc

        reloaded = self.candidate_skill_repo.get_by_id(candidate_skill.id)
        if not reloaded:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated candidate skill association.",
            )
        return CandidateSkillResponse.model_validate(reloaded)

    def delete_candidate_skill(self, user: User, candidate_skill_id: uuid.UUID) -> None:
        """
        Delete a candidate skill association owned by the candidate.
        Cascades deletion to join links without mutating claims or evidence items.
        """
        candidate_skill = self.candidate_skill_repo.get_by_id(candidate_skill_id)
        if not candidate_skill or candidate_skill.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate skill association not found.",
            )
        self.candidate_skill_repo.remove(candidate_skill.id)
