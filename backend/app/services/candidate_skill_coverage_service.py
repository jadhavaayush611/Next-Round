import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.candidate_claim import ClaimOrigin, ClaimType
from app.models.candidate_skill import CandidateSkill
from app.models.evidence_source import EvidenceSourceStatus
from app.models.user import User
from app.models.verification_result import (
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_skill import CandidateSkillRepository
from app.repositories.skill import SkillRepository
from app.schemas.candidate_skill_coverage import (
    CandidateSkillCoverageItem,
    CandidateSkillCoverageReport,
    CandidateSkillCoverageStatus,
    ClaimProvenance,
    ClaimScopeOutcome,
    SkillClaimCoverageDetail,
    SkillEvidenceCoverageDetail,
    SourceScopeOutcome,
    UnassociatedSkillClaimDetail,
)
from app.schemas.claim_evidence_match import EvidenceMatchItem
from app.services.claim_evidence_matching_service import (
    MATCH_PRIORITY,
    ClaimEvidenceMatchingService,
)
from app.utils.skill_normalization import build_skill_pattern


class CandidateSkillCoverageService:
    """
    Deterministic, candidate-scoped, read-only domain service for evaluating
    evidence-backed skill coverage across candidate skills, claims, evidence items,
    verification outcomes, and Phase 3.11 claim-to-evidence matching.

    Invariants:
    1. Read-Only: Zero database mutations, record creation, or deletions.
    2. Candidate Isolation: Strictly scoped to current_user.id; unowned resources raise 404.
    3. No Inferred Proficiency: Disclaims authorship and competency; no readiness scores.
    4. Scope Disambiguation: Verification checks are mapped to exactly one logical scope.
       Source existence checks never establish claim validity.
    5. Conservative Aggregation: MIXED_VERIFICATION applies only to conflicting claim evaluations.
       Supported claims alongside unavailable claims are not classified as mixed.
    6. Separation of Concerns: Source status, observation timestamp, and verification outcome
       are modeled and evaluated independently.
    """

    def __init__(self, db: Session):
        self.db = db
        self.candidate_skill_repo = CandidateSkillRepository(db)
        self.skill_repo = SkillRepository(db)
        self.claim_repo = CandidateClaimRepository(db)
        self.matching_service = ClaimEvidenceMatchingService(db)

    def get_coverage_report(
        self,
        user: User,
        skill_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        freshness_threshold_days: int | None = None,
        unassociated_claims_limit: int = 20,
        unassociated_claims_offset: int = 0,
    ) -> CandidateSkillCoverageReport:
        """
        Build an evidence-backed skill coverage report for the candidate.
        Summary counts and status tallies cover the complete filtered population before pagination.
        """
        # 1. Fetch filtered candidate skills
        all_candidate_skills = list(
            self.candidate_skill_repo.list_by_user(user.id, skill_id=skill_id)
        )
        total_skills_evaluated = len(all_candidate_skills)

        # 2. Initialize status summary with 0 for all enum values
        status_summary = {st.value: 0 for st in CandidateSkillCoverageStatus}

        # 3. Evaluate coverage for all matching skills
        evaluated_items: list[CandidateSkillCoverageItem] = []
        for cs in all_candidate_skills:
            item = self._evaluate_candidate_skill(
                user=user,
                candidate_skill=cs,
                freshness_threshold_days=freshness_threshold_days,
            )
            status_summary[item.coverage_status.value] += 1
            evaluated_items.append(item)

        # 4. Paginate skill items
        paginated_skills = evaluated_items[offset : offset + limit]

        # 5. Retrieve and bound unassociated SKILL claims
        unassociated_claims_details, unassociated_total = (
            self._get_unassociated_skill_claims(
                user=user,
                skill_id=skill_id,
                limit=unassociated_claims_limit,
                offset=unassociated_claims_offset,
            )
        )

        return CandidateSkillCoverageReport(
            user_id=user.id,
            generated_at=datetime.now(UTC),
            total_skills_evaluated=total_skills_evaluated,
            status_summary=status_summary,
            skills=paginated_skills,
            unassociated_skill_claims=unassociated_claims_details,
            unassociated_skill_claims_total=unassociated_total,
        )

    def get_skill_coverage(
        self,
        user: User,
        candidate_skill_id: uuid.UUID,
        freshness_threshold_days: int | None = None,
    ) -> CandidateSkillCoverageItem:
        """
        Retrieve coverage determination and supporting records for a specific candidate skill.
        Enforces candidate ownership; returns 404 for unowned or nonexistent associations.
        """
        cs = self.candidate_skill_repo.get_by_id(candidate_skill_id)
        if not cs or cs.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate skill not found.",
            )

        return self._evaluate_candidate_skill(
            user=user,
            candidate_skill=cs,
            freshness_threshold_days=freshness_threshold_days,
        )

    # -------------------------------------------------------------------------
    # Core Skill Evaluation Logic
    # -------------------------------------------------------------------------

    def _evaluate_candidate_skill(
        self,
        user: User,
        candidate_skill: CandidateSkill,
        freshness_threshold_days: int | None,
    ) -> CandidateSkillCoverageItem:
        """
        Deterministically evaluate coverage for a single CandidateSkill record.
        """
        # Resolve canonical skill metadata
        skill = candidate_skill.skill or self.skill_repo.get_by_id(
            candidate_skill.skill_id
        )
        canonical_name = skill.canonical_name if skill else "Unknown"
        category = skill.category if skill else "Other"

        claims_details: list[SkillClaimCoverageDetail] = []
        active_evidence_items: list[SkillEvidenceCoverageDetail] = []
        historical_unavailable_evidence: list[SkillEvidenceCoverageDetail] = []

        raw_potential_matches: list[EvidenceMatchItem] = []
        claim_scope_outcomes_dict: dict[uuid.UUID, ClaimScopeOutcome] = {}
        source_scope_outcomes_dict: dict[uuid.UUID, SourceScopeOutcome] = {}

        now_utc = datetime.now(UTC)

        # Iterate over attached provenance links
        for link in candidate_skill.evidence_links:
            # 1. Linked Claim
            if link.candidate_claim_id:
                claim = link.candidate_claim
                if not claim or claim.user_id != user.id:
                    continue

                # Find latest verification check targeting this claim
                claim_vrs = [
                    vr
                    for vr in (claim.verification_results or [])
                    if self._is_claim_scope_check(vr)
                ]
                latest_claim_vr: VerificationResult | None = None
                if claim_vrs:
                    sorted_vrs = sorted(
                        claim_vrs,
                        key=lambda r: (r.checked_at, r.created_at),
                        reverse=True,
                    )
                    latest_claim_vr = sorted_vrs[0]

                latest_outcome = latest_claim_vr.outcome if latest_claim_vr else None
                latest_vr_id = latest_claim_vr.id if latest_claim_vr else None

                if latest_claim_vr:
                    claim_scope_outcomes_dict[claim.id] = ClaimScopeOutcome(
                        claim_id=claim.id,
                        latest_outcome=latest_claim_vr.outcome,
                        verification_result_id=latest_claim_vr.id,
                        method_version=latest_claim_vr.method_version,
                        explanation=latest_claim_vr.explanation,
                        checked_at=latest_claim_vr.checked_at,
                    )

                # Query Phase 3.11 claim-to-evidence matching service (reused without duplication)
                match_resp = self.matching_service.find_evidence_matches(
                    user=user, claim_id=claim.id
                )
                raw_potential_matches.extend(match_resp.matches)

                provenance = None
                if (
                    claim.origin == ClaimOrigin.RESUME
                    and claim.resume_parse_id
                    and claim.canonical_path
                ):
                    provenance = ClaimProvenance(
                        resume_parse_id=claim.resume_parse_id,
                        canonical_path=claim.canonical_path,
                    )

                claims_details.append(
                    SkillClaimCoverageDetail(
                        claim_id=claim.id,
                        claim_text=claim.claim_text,
                        claim_type=claim.claim_type,
                        origin=claim.origin,
                        provenance=provenance,
                        latest_verification_outcome=latest_outcome,
                        latest_verification_result_id=latest_vr_id,
                        potential_matches_count=match_resp.total_matches,
                    )
                )

            # 2. Linked Evidence Item
            elif link.evidence_item_id:
                item = link.evidence_item
                if (
                    not item
                    or not item.evidence_source
                    or item.evidence_source.user_id != user.id
                ):
                    continue

                source = item.evidence_source

                # Staleness evaluation (only when freshness_threshold_days is caller-supplied)
                is_stale: bool | None = None
                if freshness_threshold_days is not None:
                    if (
                        source.access_status == EvidenceSourceStatus.NOT_CHECKED
                        or not item.observed_at
                    ):
                        is_stale = True
                    else:
                        obs_time = (
                            item.observed_at.replace(tzinfo=UTC)
                            if item.observed_at.tzinfo is None
                            else item.observed_at
                        )
                        age_days = (now_utc - obs_time).days
                        is_stale = age_days > freshness_threshold_days

                # Latest check targeting this evidence item via VerificationEvidence
                item_vrs = list(item.verification_results or [])
                latest_item_vr: VerificationResult | None = None
                if item_vrs:
                    sorted_item_vrs = sorted(
                        item_vrs,
                        key=lambda r: (r.checked_at, r.created_at),
                        reverse=True,
                    )
                    latest_item_vr = sorted_item_vrs[0]

                item_detail = SkillEvidenceCoverageDetail(
                    evidence_item_id=item.id,
                    evidence_source_id=source.id,
                    source_uri=source.source_uri,
                    source_type=source.source_type,
                    source_status=source.access_status,
                    observed_at=item.observed_at,
                    source_last_checked_at=source.last_checked_at,
                    is_stale=is_stale,
                    evidence_type=item.evidence_type,
                    description=item.description,
                    source_locator=item.source_locator,
                    latest_verification_outcome=(
                        latest_item_vr.outcome if latest_item_vr else None
                    ),
                    latest_verification_result_id=(
                        latest_item_vr.id if latest_item_vr else None
                    ),
                )

                # Partition into active vs historical non-available evidence
                if source.access_status == EvidenceSourceStatus.AVAILABLE:
                    active_evidence_items.append(item_detail)
                else:
                    historical_unavailable_evidence.append(item_detail)

                # Evaluate source-level verification checks (e.g. SOURCE_EXISTENCE)
                source_vrs = [
                    vr
                    for vr in (source.verification_results or [])
                    if self._is_source_scope_check(vr)
                ]
                if source_vrs and source.id not in source_scope_outcomes_dict:
                    sorted_source_vrs = sorted(
                        source_vrs,
                        key=lambda r: (r.checked_at, r.created_at),
                        reverse=True,
                    )
                    latest_source_vr = sorted_source_vrs[0]
                    source_scope_outcomes_dict[source.id] = SourceScopeOutcome(
                        evidence_source_id=source.id,
                        source_uri=source.source_uri,
                        source_type=source.source_type,
                        source_status=source.access_status,
                        latest_outcome=latest_source_vr.outcome,
                        verification_result_id=latest_source_vr.id,
                        method_version=latest_source_vr.method_version,
                        explanation=latest_source_vr.explanation,
                        checked_at=latest_source_vr.checked_at,
                    )

        # Deduplicate potential matches by evidence_item_id using MATCH_PRIORITY
        best_matches_by_item: dict[uuid.UUID, EvidenceMatchItem] = {}
        for m in raw_potential_matches:
            existing = best_matches_by_item.get(m.evidence_item_id)
            if (
                not existing
                or MATCH_PRIORITY[m.matching_basis]
                > MATCH_PRIORITY[existing.matching_basis]
            ):
                best_matches_by_item[m.evidence_item_id] = m

        sorted_matches = sorted(
            best_matches_by_item.values(),
            key=lambda m: (-MATCH_PRIORITY[m.matching_basis], str(m.evidence_item_id)),
        )

        claim_outcomes = list(claim_scope_outcomes_dict.values())
        source_outcomes = list(source_scope_outcomes_dict.values())

        # Determine aggregate skill coverage status and summary
        status_res, summary = self._derive_coverage_status(
            claims_count=len(claims_details),
            active_items_count=len(active_evidence_items),
            historical_items_count=len(historical_unavailable_evidence),
            potential_matches_count=len(sorted_matches),
            claim_outcomes=claim_outcomes,
            source_outcomes=source_outcomes,
        )

        return CandidateSkillCoverageItem(
            candidate_skill_id=candidate_skill.id,
            skill_id=candidate_skill.skill_id,
            canonical_name=canonical_name,
            category=category,
            coverage_status=status_res,
            summary=summary,
            claims=claims_details,
            active_evidence_items=active_evidence_items,
            historical_unavailable_evidence=historical_unavailable_evidence,
            potential_evidence_matches=sorted_matches,
            claim_outcomes=claim_outcomes,
            source_outcomes=source_outcomes,
        )

    # -------------------------------------------------------------------------
    # Status Derivation & Precedence Rules
    # -------------------------------------------------------------------------

    @staticmethod
    def _derive_coverage_status(
        claims_count: int,
        active_items_count: int,
        historical_items_count: int,
        potential_matches_count: int,
        claim_outcomes: list[ClaimScopeOutcome],
        source_outcomes: list[SourceScopeOutcome],
    ) -> tuple[CandidateSkillCoverageStatus, str]:
        """
        Derive aggregate status strictly using approved precedence rules:
        - MIXED_VERIFICATION applies ONLY to conflicting claim-support evaluations.
        - Supported claims alongside unavailable claims are NOT mixed.
        - Source verification (e.g. SOURCE_EXISTENCE) is kept distinct from claim verification.
        - Inaccessible/revoked sources are never treated as negative candidate findings.
        """
        has_any_links = (
            claims_count > 0 or active_items_count > 0 or historical_items_count > 0
        )
        if not has_any_links:
            return (
                CandidateSkillCoverageStatus.NO_EVIDENCE,
                "Candidate has declared this skill, but no claims or evidence items are linked.",
            )

        limitation_note = ""
        if historical_items_count > 0:
            limitation_note = (
                f" Note: {historical_items_count} observation(s) from non-available "
                "(revoked, inaccessible, or errored) sources were excluded from active matching."
            )

        # 1. Claim-level verification checks evaluated
        if claim_outcomes:
            supported_claims = [
                co
                for co in claim_outcomes
                if co.latest_outcome == VerificationOutcome.SUPPORTED
            ]
            contradicted_claims = [
                co
                for co in claim_outcomes
                if co.latest_outcome == VerificationOutcome.CONTRADICTED
            ]
            inconclusive_claims = [
                co
                for co in claim_outcomes
                if co.latest_outcome == VerificationOutcome.INCONCLUSIVE
            ]
            unavailable_claims = [
                co
                for co in claim_outcomes
                if co.latest_outcome == VerificationOutcome.UNAVAILABLE
            ]

            # Rule 1: MIXED_VERIFICATION applies strictly when independent claims conflict
            if supported_claims and (contradicted_claims or inconclusive_claims):
                return (
                    CandidateSkillCoverageStatus.MIXED_VERIFICATION,
                    (
                        "Independent claim-support evaluations yielded conflicting outcomes: "
                        f"{len(supported_claims)} supported claim scope(s) exist alongside "
                        f"{len(contradicted_claims)} contradicted and {len(inconclusive_claims)} inconclusive determination(s). "
                        f"Scope outcomes are listed individually.{limitation_note}"
                    ),
                )

            # Rule 2: All evaluated claims contradicted
            if contradicted_claims and not supported_claims:
                return (
                    CandidateSkillCoverageStatus.CLAIM_CONTRADICTED,
                    (
                        "Evaluated claim-support verification check(s) contradicted the candidate's claim "
                        f"({len(contradicted_claims)} contradicted scope(s)).{limitation_note}"
                    ),
                )

            # Rule 3: All evaluated claims inconclusive
            if inconclusive_claims and not supported_claims and not contradicted_claims:
                return (
                    CandidateSkillCoverageStatus.CLAIM_INCONCLUSIVE,
                    (
                        "Evaluated claim-support verification check(s) yielded inconclusive determinations "
                        f"({len(inconclusive_claims)} inconclusive scope(s)). Evidence neither confirmed nor refuted the claims.{limitation_note}"
                    ),
                )

            # Rule 4: At least one claim supported
            # Supported plus unavailable alone must NOT be classified as mixed or imply complete support.
            if supported_claims:
                unavail_note = (
                    f" (Note: {len(unavailable_claims)} claim check(s) were unavailable due to access limitations)."
                    if unavailable_claims
                    else ""
                )
                return (
                    CandidateSkillCoverageStatus.CLAIM_SUPPORTED,
                    (
                        "One or more candidate claims have verified support "
                        f"({len(supported_claims)} supported scope(s)). Relevance indicates verified claim support only; "
                        f"does not establish universal proficiency.{unavail_note}{limitation_note}"
                    ),
                )

            # Rule 5: All claim checks returned UNAVAILABLE
            if unavailable_claims and not supported_claims:
                return (
                    CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE,
                    (
                        "Claim-support verification check(s) returned UNAVAILABLE due to external host or authorization limitations "
                        f"({len(unavailable_claims)} unavailable scope(s)). This is an access limitation, not a negative candidate finding.{limitation_note}"
                    ),
                )

        # 2. Source-level checks evaluated (claims unverified)
        if source_outcomes:
            supported_sources = [
                so
                for so in source_outcomes
                if so.latest_outcome == VerificationOutcome.SUPPORTED
            ]
            if supported_sources:
                return (
                    CandidateSkillCoverageStatus.SUPPORTED_SOURCE_UNVERIFIED_CLAIM,
                    (
                        f"Connected evidence source is verified to exist ({len(supported_sources)} source(s)), "
                        f"but candidate claims for this skill remain unverified assertions.{limitation_note}"
                    ),
                )
            # All source checks were unavailable
            return (
                CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE,
                (
                    "Source verification checks returned UNAVAILABLE or could not verify source existence. "
                    f"Not a negative candidate finding.{limitation_note}"
                ),
            )

        # 3. No verification checks ran on claims or sources
        if active_items_count == 0 and historical_items_count > 0:
            return (
                CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE,
                (
                    f"All linked evidence sources ({historical_items_count} observation(s)) are currently inaccessible, "
                    "revoked, or errored. Not a negative candidate finding."
                ),
            )

        if active_items_count > 0:
            return (
                CandidateSkillCoverageStatus.UNVERIFIED_EVIDENCE,
                (
                    f"Active evidence observations ({active_items_count} item(s)) are linked, "
                    f"but no verification check has evaluated them.{limitation_note}"
                ),
            )

        if potential_matches_count > 0:
            return (
                CandidateSkillCoverageStatus.UNVERIFIED_MATCHES,
                (
                    f"Identified {potential_matches_count} potential evidence match(es) in connected repositories "
                    f"based on keyword/topic heuristics. Authorship and proficiency remain unverified.{limitation_note}"
                ),
            )

        return (
            CandidateSkillCoverageStatus.NO_EVIDENCE,
            f"Candidate has declared this skill or claim, but zero evidence items or repository matches exist.{limitation_note}",
        )

    # -------------------------------------------------------------------------
    # Verification Scope Disambiguation Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_claim_scope_check(vr: VerificationResult) -> bool:
        """
        Determine whether a VerificationResult targets a claim scope.
        A check targeting both claim and source where verification_type is CLAIM_SUPPORT
        or ASSESSMENT is evaluated as a claim scope check only (never double-counted as a source check).
        """
        if vr.candidate_claim_id is not None:
            if vr.verification_type in (
                VerificationType.CLAIM_SUPPORT,
                VerificationType.ASSESSMENT,
            ):
                return True
            if vr.verification_type != VerificationType.SOURCE_EXISTENCE:
                return True
        return False

    @staticmethod
    def _is_source_scope_check(vr: VerificationResult) -> bool:
        """
        Determine whether a VerificationResult targets a source scope.
        A check is a source scope check if it is of type SOURCE_EXISTENCE or
        targets a source without a claim reference.
        """
        if vr.verification_type == VerificationType.SOURCE_EXISTENCE:
            return True
        if vr.candidate_claim_id is None and vr.evidence_source_id is not None:
            return True
        return False

    # -------------------------------------------------------------------------
    # Unassociated Claims Query Helper
    # -------------------------------------------------------------------------

    def _get_unassociated_skill_claims(
        self,
        user: User,
        skill_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[UnassociatedSkillClaimDetail], int]:
        """
        Retrieve candidate claims classified as SKILL that are NOT associated with any CandidateSkill.
        If skill_id is supplied, filters claims to those referencing the canonical skill name or aliases.
        Bounds and paginates results independently.
        """
        all_skill_claims = list(
            self.claim_repo.list_by_user(user.id, claim_type=ClaimType.SKILL)
        )

        # Collect claim IDs already associated with ANY candidate skill for this candidate
        user_candidate_skills = self.candidate_skill_repo.list_by_user(user.id)
        associated_claim_ids = {
            link.candidate_claim_id
            for cs in user_candidate_skills
            for link in cs.evidence_links
            if link.candidate_claim_id is not None
        }

        unassociated = [c for c in all_skill_claims if c.id not in associated_claim_ids]

        # Optional skill_id filtering
        if skill_id is not None:
            target_skill = self.skill_repo.get_by_id(skill_id)
            if target_skill:
                terms = [target_skill.canonical_name] + (target_skill.aliases or [])
                filtered_unassociated = []
                for claim in unassociated:
                    if any(
                        build_skill_pattern(t).search(claim.claim_text)
                        for t in terms
                        if t.strip()
                    ):
                        filtered_unassociated.append(claim)
                unassociated = filtered_unassociated
            else:
                unassociated = []

        total_unassociated = len(unassociated)
        paginated = unassociated[offset : offset + limit]

        details: list[UnassociatedSkillClaimDetail] = []
        for c in paginated:
            prov = None
            if (
                c.origin == ClaimOrigin.RESUME
                and c.resume_parse_id
                and c.canonical_path
            ):
                prov = ClaimProvenance(
                    resume_parse_id=c.resume_parse_id,
                    canonical_path=c.canonical_path,
                )
            details.append(
                UnassociatedSkillClaimDetail(
                    claim_id=c.id,
                    claim_text=c.claim_text,
                    origin=c.origin,
                    created_at=c.created_at,
                    provenance=prov,
                )
            )

        return details, total_unassociated
