import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem
from app.models.user import User
from app.models.verification_result import VerificationResult, VerificationType
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.repositories.verification_result import VerificationResultRepository
from app.schemas.verification_result import (
    VerificationResultCreate,
    VerificationResultResponse,
)


class VerificationResultService:
    """
    Internal domain service for recording, persisting, and querying verification check outcomes.
    Enforces cross-reference consistency, candidate authorization boundaries, and immutable audit history.

    No candidate-facing write endpoints are exposed; verification results are produced and written
    by internal domain engines and trusted verification workflows.
    """

    def __init__(self, db: Session):
        self.db = db
        self.result_repo = VerificationResultRepository(db)
        self.claim_repo = CandidateClaimRepository(db)
        self.source_repo = EvidenceSourceRepository(db)
        self.item_repo = EvidenceItemRepository(db)

    def create_verification_result(
        self,
        result_in: VerificationResultCreate,
        user: User | None = None,
    ) -> VerificationResultResponse:
        """
        Persist a new immutable verification result tied to a claim, source, or both.

        Invariants enforced:
        - Must reference at least one candidate claim or evidence source.
        - CLAIM_SUPPORT requires candidate_claim_id.
        - Referenced candidate claim and evidence source must exist.
        - If a user/candidate is provided, referenced targets must belong to that candidate.
        - If both claim and source are referenced, they must belong to the same candidate.
        - Referenced evidence items must exist and belong to the candidate owner.
        - If the result is source-scoped (no claim), referenced evidence items must belong to that source.
        - Duplicate evidence item associations are rejected.
        - Creates a new historical record for each verification attempt.
        """
        if (
            result_in.candidate_claim_id is None
            and result_in.evidence_source_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification result must target a candidate claim, an evidence source, or both.",
            )

        if (
            result_in.verification_type == VerificationType.CLAIM_SUPPORT
            and result_in.candidate_claim_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CLAIM_SUPPORT verification requires candidate_claim_id.",
            )

        claim = None
        if result_in.candidate_claim_id is not None:
            claim = self.claim_repo.get_by_id(result_in.candidate_claim_id)
            if not claim:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced candidate claim does not exist.",
                )
            if user is not None and claim.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced candidate claim does not exist or does not belong to the candidate.",
                )

        source = None
        if result_in.evidence_source_id is not None:
            source = self.source_repo.get_by_id(result_in.evidence_source_id)
            if not source:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced evidence source does not exist.",
                )
            if user is not None and source.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced evidence source does not exist or does not belong to the candidate.",
                )

        if claim is not None and source is not None:
            if claim.user_id != source.user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced candidate claim and evidence source belong to different candidates.",
                )

        candidate_owner_id = (
            claim.user_id if claim is not None else source.user_id  # type: ignore[union-attr]
        )

        if user is not None and candidate_owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced targets do not belong to the candidate.",
            )

        if len(result_in.evidence_item_ids) != len(set(result_in.evidence_item_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Duplicate evidence item associations are not permitted.",
            )

        evidence_items: list[EvidenceItem] = []
        for item_id in result_in.evidence_item_ids:
            item = self.item_repo.get_by_id(item_id)
            if not item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Referenced evidence item {item_id} does not exist.",
                )

            # Enforce candidate ownership consistency
            if item.evidence_source.user_id != candidate_owner_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evidence item {item_id} belongs to a different candidate.",
                )

            # Enforce source consistency: evidence must belong to the referenced source whenever a source is targeted
            if source is not None:
                if item.evidence_source_id != source.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Evidence item {item_id} does not belong to the "
                            f"referenced evidence source {source.id}."
                        ),
                    )

            evidence_items.append(item)

        db_result = VerificationResult(
            candidate_claim_id=result_in.candidate_claim_id,
            evidence_source_id=result_in.evidence_source_id,
            verification_type=result_in.verification_type,
            outcome=result_in.outcome,
            method_version=result_in.method_version,
            explanation=result_in.explanation,
            checked_at=result_in.checked_at,
        )
        db_result.evidence_items = evidence_items

        created = self.result_repo.create(db_result)
        return VerificationResultResponse.model_validate(created)

    def get_verification_result(
        self, result_id: uuid.UUID, user: User | None = None
    ) -> VerificationResultResponse:
        """
        Retrieve a verification result by ID with its evidence associations.
        If a candidate user is provided, validates that the underlying claim/source belongs to them.
        """
        result = self.result_repo.get_by_id(result_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification result not found.",
            )

        if user is not None:
            owner_id = (
                result.candidate_claim.user_id
                if result.candidate_claim
                else (
                    result.evidence_source.user_id if result.evidence_source else None
                )
            )
            if owner_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Verification result not found.",
                )

        return VerificationResultResponse.model_validate(result)

    def list_results_for_claim(
        self, claim_id: uuid.UUID, user: User | None = None
    ) -> list[VerificationResultResponse]:
        """
        List all verification results for a candidate claim.
        Validates claim existence and optional user ownership.
        """
        claim = self.claim_repo.get_by_id(claim_id)
        if not claim:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )

        if user is not None and claim.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )

        results = self.result_repo.list_by_claim(claim_id)
        return [VerificationResultResponse.model_validate(r) for r in results]

    def list_results_for_source(
        self, source_id: uuid.UUID, user: User | None = None
    ) -> list[VerificationResultResponse]:
        """
        List all verification results for an evidence source.
        Validates source existence and optional user ownership.
        """
        source = self.source_repo.get_by_id(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        if user is not None and source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        results = self.result_repo.list_by_source(source_id)
        return [VerificationResultResponse.model_validate(r) for r in results]

    def list_results_for_user(self, user: User) -> list[VerificationResultResponse]:
        """List all verification results associated with any of the candidate's claims or sources."""
        results = self.result_repo.list_by_user(user.id)
        return [VerificationResultResponse.model_validate(r) for r in results]

    def count_results_for_claim(
        self, claim_id: uuid.UUID, user: User | None = None
    ) -> int:
        """Count total verification attempts for a claim with authorization check."""
        claim = self.claim_repo.get_by_id(claim_id)
        if not claim:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )

        if user is not None and claim.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )

        return self.result_repo.count_by_claim(claim_id)

    def count_results_for_source(
        self, source_id: uuid.UUID, user: User | None = None
    ) -> int:
        """Count total verification attempts for a source with authorization check."""
        source = self.source_repo.get_by_id(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        if user is not None and source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        return self.result_repo.count_by_source(source_id)
