import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.candidate_target import CandidateTarget
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    EvidenceSource,
    EvidenceSourceStatus,
)
from app.models.role_requirement import RequirementType, RoleRequirement
from app.models.user import User
from app.models.verification_result import (
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_skill import CandidateSkillRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.repositories.role_requirement import RoleRequirementRepository
from app.repositories.skill import SkillRepository
from app.schemas.role_gap_analysis import (
    GapAnalysisStatus,
    RoleGapAnalysisReport,
    RoleGapRequirementItem,
    ScopeOutcome,
    SupportingRecords,
)


class RoleGapAnalysisService:
    """
    Deterministic, read-only domain service for evaluating role requirement coverage
    against a candidate's recorded skills, claims, evidence, and verification results.

    Domain Invariants & Principles:
    1. Read-Only: Never mutates existing claims, evidence, verification records, or targets.
       Does not write to the database or persist ephemeral analysis results.
    2. Candidate Ownership: Strictly scoped to the authenticated candidate. Unowned or
       non-existent targets return 404 to avoid information disclosure.
    3. Categorical Classifications: Explicitly distinguishes between:
       - UNRESOLVED_UNMAPPED: Requirement not mapped to a canonical skill catalog entry.
       - MISSING_RECORDED_COVERAGE: Requirement mapped to skill, but candidate has no claim
         or skill association recorded. Not an inference of candidate capability lack.
       - EVIDENCE_GAP: Candidate has asserted the skill/claim, but no external evidence or
         assessment observations are linked.
       - UNAVAILABLE_EVIDENCE: Evidence source is inaccessible, revoked, or check returned UNAVAILABLE.
         Never treated as contradictory evidence.
       - INCONCLUSIVE_VERIFICATION: Verification check executed but yielded inconclusive outcome.
       - CONTRADICTED_VERIFICATION: Verification check executed and contradicted the claim or evidence.
       - MISSING_ASSESSMENT_EVIDENCE: Qualification/assessment requirement or evidence item
         lacks demonstrated assessment verification.
       - SUPPORTED_EVIDENCE: Evidence is verified with SUPPORTED outcome. Never claims proof beyond
         the method version scope.
    4. Scope-Aware History: Multiple verification checks on the same target scope are evaluated
       chronologically; the latest check governs the scope determination without erasing history.
       Unrelated supported results do not override contradictory or inconclusive results from another scope.
    5. Assessment Semantics: Mere presence of an assessment observation is not proof of competence
       or passing; only a verified check with SUPPORTED outcome establishes supported assessment evidence.
    6. No Unsupported Scoring: No percentages, proficiency numbers, aggregate readiness scores,
       external LLMs, embeddings, or heuristic fuzzing.
    """

    def __init__(self, db: Session):
        self.db = db
        self.target_repo = CandidateTargetRepository(db)
        self.profile_repo = CandidateProfileRepository(db)
        self.requirement_repo = RoleRequirementRepository(db)
        self.skill_repo = SkillRepository(db)
        self.candidate_skill_repo = CandidateSkillRepository(db)

    def _get_validated_target(
        self, user: User, target_id: uuid.UUID
    ) -> CandidateTarget:
        """
        Validate that the target exists and belongs to the authenticated candidate.
        Returns 404 for nonexistent or unowned targets to preserve isolation.
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

    @staticmethod
    def _get_scoped_verification_groups(
        verification_results: list[VerificationResult],
    ) -> dict[tuple[str, uuid.UUID], list[VerificationResult]]:
        """
        Group verification results by specific evaluated scope.
        Preserves all historical records for auditability while preventing obsolete checks
        from overriding newer determinations for the same scope.
        """
        scoped_groups: dict[tuple[str, uuid.UUID], list[VerificationResult]] = {}
        for vr in verification_results:
            if vr.candidate_claim_id is not None:
                scope_key = ("claim", vr.candidate_claim_id)
            elif vr.evidence_source_id is not None:
                scope_key = ("source", vr.evidence_source_id)
            else:
                scope_key = ("result", vr.id)
            scoped_groups.setdefault(scope_key, []).append(vr)
        return scoped_groups

    @classmethod
    def _build_scope_outcomes(
        cls,
        scoped_groups: dict[tuple[str, uuid.UUID], list[VerificationResult]],
    ) -> tuple[list[ScopeOutcome], list[VerificationResult]]:
        """
        Build per-scope latest verification determinations.
        Preserves chronological ordering within each scope (checked_at desc, created_at desc)
        without letting results from one scope overwrite determinations from another.
        """
        outcomes: list[ScopeOutcome] = []
        latest_results: list[VerificationResult] = []
        for (scope_type, scope_id), results in scoped_groups.items():
            sorted_results = sorted(
                results,
                key=lambda r: (r.checked_at, r.created_at),
                reverse=True,
            )
            latest = sorted_results[0]
            latest_results.append(latest)
            outcomes.append(
                ScopeOutcome(
                    scope_type=scope_type,
                    scope_id=scope_id,
                    latest_outcome=latest.outcome,
                    verification_result_id=latest.id,
                    method_version=latest.method_version,
                    explanation=latest.explanation,
                )
            )
        return outcomes, latest_results

    def _analyze_requirement(
        self, user: User, req: RoleRequirement
    ) -> RoleGapRequirementItem:
        """
        Deterministically evaluate a single role requirement against the candidate's records.
        """
        # 1. Unresolved/Unmapped check
        if req.skill_id is None:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=None,
                canonical_skill_name=None,
                status=GapAnalysisStatus.UNRESOLVED_UNMAPPED,
                explanation="Requirement is not mapped to a canonical skill in the catalog and requires manual review.",
                supporting_records=SupportingRecords(),
            )

        # Retrieve canonical skill name
        canonical_name: str | None = None
        if req.skill:
            canonical_name = req.skill.canonical_name
        else:
            skill = self.skill_repo.get_by_id(req.skill_id)
            if skill:
                canonical_name = skill.canonical_name

        # 2. Candidate skill association check
        candidate_skill = self.candidate_skill_repo.get_by_user_and_skill(
            user.id, req.skill_id
        )
        if not candidate_skill:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.MISSING_RECORDED_COVERAGE,
                explanation="No candidate claim, skill association, or evidence is recorded for this skill.",
                supporting_records=SupportingRecords(),
            )

        # 3. Gather linked claims, evidence items, evidence sources, and verification results
        candidate_skill_id = candidate_skill.id
        claim_ids: list[uuid.UUID] = []
        evidence_item_ids: list[uuid.UUID] = []
        evidence_source_ids: list[uuid.UUID] = []
        verification_result_ids: list[uuid.UUID] = []

        evidence_sources: list[EvidenceSource] = []
        verification_results: list[VerificationResult] = []
        assessment_items: list[EvidenceItem] = []

        for link in candidate_skill.evidence_links:
            if link.candidate_claim_id:
                claim = link.candidate_claim
                if claim and claim.user_id == user.id:
                    claim_ids.append(claim.id)
                    if claim.verification_results:
                        for vr in claim.verification_results:
                            verification_result_ids.append(vr.id)
                            verification_results.append(vr)
            elif link.evidence_item_id:
                item = link.evidence_item
                if (
                    item
                    and item.evidence_source
                    and item.evidence_source.user_id == user.id
                ):
                    evidence_item_ids.append(item.id)
                    if item.evidence_type == EvidenceType.ASSESSMENT_RESULT:
                        assessment_items.append(item)
                    if item.evidence_source_id:
                        evidence_source_ids.append(item.evidence_source_id)
                        evidence_sources.append(item.evidence_source)
                        if item.evidence_source.verification_results:
                            for vr in item.evidence_source.verification_results:
                                verification_result_ids.append(vr.id)
                                verification_results.append(vr)
                    if item.verification_results:
                        for vr in item.verification_results:
                            verification_result_ids.append(vr.id)
                            verification_results.append(vr)

        # Deduplicate IDs preserving order
        claim_ids = list(dict.fromkeys(claim_ids))
        evidence_item_ids = list(dict.fromkeys(evidence_item_ids))
        evidence_source_ids = list(dict.fromkeys(evidence_source_ids))
        verification_result_ids = list(dict.fromkeys(verification_result_ids))

        supporting = SupportingRecords(
            candidate_skill_id=candidate_skill_id,
            candidate_claim_ids=claim_ids,
            evidence_item_ids=evidence_item_ids,
            evidence_source_ids=evidence_source_ids,
            verification_result_ids=verification_result_ids,
        )

        # 4. Association with no claims and no evidence
        if not claim_ids and not evidence_item_ids and not verification_results:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.EVIDENCE_GAP,
                explanation="Skill association is recorded, but no supporting claims or evidence items are linked.",
                supporting_records=supporting,
                scope_outcomes=[],
            )

        # 5. Check for self-declared claims without evidence
        if not evidence_item_ids and not verification_results:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.EVIDENCE_GAP,
                explanation="Self-declared claim exists, but no external evidence or assessment is linked.",
                supporting_records=supporting,
                scope_outcomes=[],
            )

        req_text_lower = req.requirement_text.lower()
        is_assessment_demanded = (
            req.requirement_type == RequirementType.QUALIFICATION
            or any(
                kw in req_text_lower
                for kw in ("assessment", "certified", "certification", "exam")
            )
        )

        available_sources = [
            s
            for s in evidence_sources
            if s.access_status == EvidenceSourceStatus.AVAILABLE
        ]
        unavailable_sources = [
            s
            for s in evidence_sources
            if s.access_status
            in (
                EvidenceSourceStatus.INACCESSIBLE,
                EvidenceSourceStatus.REVOKED,
                EvidenceSourceStatus.ERROR,
            )
        ]

        # 6. Unverified evidence handling (when no verification checks were performed)
        if not verification_results:
            if unavailable_sources and not available_sources:
                status_res = GapAnalysisStatus.UNAVAILABLE_EVIDENCE
                exp = "Evidence source is inaccessible, revoked, or errored."
            elif assessment_items:
                status_res = GapAnalysisStatus.ASSESSMENT_PENDING_VERIFICATION
                exp = "Assessment evidence record is present, but no verification check has verified demonstrated competence."
            elif is_assessment_demanded:
                status_res = GapAnalysisStatus.MISSING_ASSESSMENT_EVIDENCE
                exp = "Requirement specifies demonstrated assessment or qualification, but no assessment evidence record is linked."
            else:
                status_res = GapAnalysisStatus.UNVERIFIED_EVIDENCE
                exp = "Evidence items are recorded, but no verification check has evaluated demonstrated competence."

            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=status_res,
                explanation=exp,
                supporting_records=supporting,
                scope_outcomes=[],
            )

        # 7. Evaluate latest verification result per distinct target scope
        scoped_groups = self._get_scoped_verification_groups(verification_results)
        scope_outcomes, latest_results = self._build_scope_outcomes(scoped_groups)

        contradicted_results = [
            vr
            for vr in latest_results
            if vr.outcome == VerificationOutcome.CONTRADICTED
        ]
        inconclusive_results = [
            vr
            for vr in latest_results
            if vr.outcome == VerificationOutcome.INCONCLUSIVE
        ]
        supported_results = [
            vr for vr in latest_results if vr.outcome == VerificationOutcome.SUPPORTED
        ]
        unavailable_results = [
            vr for vr in latest_results if vr.outcome == VerificationOutcome.UNAVAILABLE
        ]

        # 8. Check for Mixed Verification Outcomes across Scopes
        # Invariant: A contradiction or inconclusive result in one scope must not automatically negate
        # independent evidence from another scope. Report as MIXED_VERIFICATION with per-scope outcomes.
        if supported_results and (contradicted_results or inconclusive_results):
            note = (
                " (Note: 1 linked scope was unavailable)."
                if unavailable_results
                else ""
            )
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.MIXED_VERIFICATION,
                explanation=f"Verification outcomes are mixed across evaluated scopes: supported evidence exists alongside contradictory or inconclusive determinations.{note}",
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 9. Check for Contradicted Outcomes (all evaluated checks contradicted)
        if contradicted_results and not supported_results:
            note = (
                " (Note: 1 linked scope was unavailable)."
                if (
                    unavailable_results
                    or (unavailable_sources and not available_sources)
                )
                else ""
            )
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.CONTRADICTED_VERIFICATION,
                explanation=f"Verification check contradicted claim or evidence under method {contradicted_results[0].method_version}.{note}",
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 10. Check if ALL linked sources are unavailable while historical verification results exist
        if unavailable_sources and not available_sources and not contradicted_results:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.UNAVAILABLE_EVIDENCE,
                explanation="All linked evidence sources are currently inaccessible or revoked despite historical verification results.",
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 11. Check for Inconclusive Outcomes (all evaluated checks inconclusive)
        if inconclusive_results and not supported_results and not contradicted_results:
            note = (
                " (Note: 1 linked scope was unavailable)."
                if unavailable_results
                else ""
            )
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.INCONCLUSIVE_VERIFICATION,
                explanation=f"Verification check was performed but yielded inconclusive results under method {inconclusive_results[0].method_version}.{note}",
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 12. Check for Supported Verification Results
        # Invariant: If qualification/assessment is demanded, verify that assessment evidence is established.
        if supported_results:
            has_verified_assessment = any(
                vr.verification_type == VerificationType.ASSESSMENT
                and vr.outcome == VerificationOutcome.SUPPORTED
                for vr in supported_results
            )

            if is_assessment_demanded and not has_verified_assessment:
                if assessment_items:
                    status_res = GapAnalysisStatus.ASSESSMENT_PENDING_VERIFICATION
                    exp = "Assessment evidence record is present, but no verification check has verified demonstrated competence."
                else:
                    status_res = GapAnalysisStatus.MISSING_ASSESSMENT_EVIDENCE
                    exp = "Requirement specifies demonstrated assessment or qualification, but no verified assessment evidence is recorded."
                return RoleGapRequirementItem(
                    requirement_id=req.id,
                    requirement_text=req.requirement_text,
                    requirement_type=req.requirement_type,
                    importance=req.importance,
                    skill_id=req.skill_id,
                    canonical_skill_name=canonical_name,
                    status=status_res,
                    explanation=exp,
                    supporting_records=supporting,
                    scope_outcomes=scope_outcomes,
                )

            has_inaccessible_source = any(
                s.access_status
                in (
                    EvidenceSourceStatus.INACCESSIBLE,
                    EvidenceSourceStatus.REVOKED,
                    EvidenceSourceStatus.ERROR,
                )
                for s in evidence_sources
            )
            note = (
                " (Note: 1 linked source was inaccessible/unavailable)."
                if (has_inaccessible_source or unavailable_results)
                else ""
            )
            if any(
                vr.verification_type == VerificationType.ASSESSMENT
                for vr in supported_results
            ):
                exp = f"Supported by demonstrated assessment evidence (check method: {supported_results[0].method_version}).{note}"
            else:
                exp = f"Supported by verified evidence within the scope of check method {supported_results[0].method_version}.{note}"

            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.SUPPORTED_EVIDENCE,
                explanation=exp,
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 13. Check for Unavailable or Inaccessible Evidence Sources
        if unavailable_results and not supported_results:
            return RoleGapRequirementItem(
                requirement_id=req.id,
                requirement_text=req.requirement_text,
                requirement_type=req.requirement_type,
                importance=req.importance,
                skill_id=req.skill_id,
                canonical_skill_name=canonical_name,
                status=GapAnalysisStatus.UNAVAILABLE_EVIDENCE,
                explanation="Evidence source is inaccessible, revoked, or verification check was unavailable.",
                supporting_records=supporting,
                scope_outcomes=scope_outcomes,
            )

        # 14. Fallback
        if assessment_items:
            fallback_status = GapAnalysisStatus.ASSESSMENT_PENDING_VERIFICATION
            fallback_exp = "Assessment evidence record is present, but no verification check has evaluated demonstrated competence."
        else:
            fallback_status = GapAnalysisStatus.UNVERIFIED_EVIDENCE
            fallback_exp = "Evidence items are recorded, but no verification check has evaluated demonstrated competence."

        return RoleGapRequirementItem(
            requirement_id=req.id,
            requirement_text=req.requirement_text,
            requirement_type=req.requirement_type,
            importance=req.importance,
            skill_id=req.skill_id,
            canonical_skill_name=canonical_name,
            status=fallback_status,
            explanation=fallback_exp,
            supporting_records=supporting,
            scope_outcomes=scope_outcomes,
        )

    def analyze_target_gaps(
        self, user: User, target_id: uuid.UUID
    ) -> RoleGapAnalysisReport:
        """
        Execute deterministic, read-only role-gap analysis for a candidate target.
        """
        target = self._get_validated_target(user, target_id)
        requirements = self.requirement_repo.list_by_target(target.id)

        items: list[RoleGapRequirementItem] = []
        status_summary: dict[str, int] = {s.value: 0 for s in GapAnalysisStatus}

        for req in requirements:
            item = self._analyze_requirement(user, req)
            items.append(item)
            status_summary[item.status.value] += 1

        return RoleGapAnalysisReport(
            candidate_target_id=target.id,
            role_title=target.role_title,
            company=target.company,
            total_requirements=len(items),
            analyzed_at=datetime.now(UTC),
            requirements=items,
            status_summary=status_summary,
        )
