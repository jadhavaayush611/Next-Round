import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate_claim import ClaimOrigin
from app.models.evidence_source import (
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.resume import Resume
from app.models.resume_parse import ResumeParse
from app.models.user import User
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.repositories.resume import ResumeRepository
from app.repositories.resume_parse import ResumeParseRepository
from app.repositories.role_requirement import RoleRequirementRepository
from app.schemas.candidate_intelligence import (
    CandidateIntelligenceOverviewResponse,
    EvidenceSourceOverviewItem,
    EvidenceSourcesOverview,
    ProfileSummary,
    ResumeProvenanceSummary,
    SkillCoverageOverview,
    SkillPreviewItem,
    TargetAlignmentOverview,
    TargetRequirementAlignmentItem,
    TargetSummary,
)
from app.services.candidate_skill_coverage_service import (
    CandidateSkillCoverageService,
)
from app.services.role_gap_analysis_service import RoleGapAnalysisService

# Static invariant disclaimers required by Milestone 0 & Shared Invariants contract
OVERVIEW_AUDIT_DISCLAIMERS: list[str] = [
    "Relevance and support determinations reflect recorded candidate assertions and verified check scopes only.",
    "External repository access limitations and unverified matches do not constitute negative candidate determinations.",
    "No aggregate readiness score or universal proficiency is calculated or implied.",
]


class CandidateIntelligenceService:
    """
    Deterministic, candidate-scoped, read-only domain orchestration service
    integrating profile context, target role requirements, evidence sources,
    resume provenance, and evidence-backed skill coverage.

    Invariants:
    1. Read-Only: Zero database mutations or external HTTP calls.
    2. Candidate Isolation: Strictly scoped to current_user.id.
    3. No Fabrication: Missing profiles or missing targets return None without synthesizing records.
    4. Authoritative Delegation: Reuses CandidateSkillCoverageService and RoleGapAnalysisService.
    5. Disclaimed Proficiency: Never calculates readiness scores or infers skill mastery.
    6. Sanitized Metadata: Evidence source URLs are parsed and sanitized according to source type.
    """

    def __init__(self, db: Session):
        self.db = db
        self.profile_repo = CandidateProfileRepository(db)
        self.target_repo = CandidateTargetRepository(db)
        self.resume_repo = ResumeRepository(db)
        self.parse_repo = ResumeParseRepository(db)
        self.claim_repo = CandidateClaimRepository(db)
        self.source_repo = EvidenceSourceRepository(db)
        self.requirement_repo = RoleRequirementRepository(db)

        # Delegated authoritative services
        self.coverage_service = CandidateSkillCoverageService(db)
        self.gap_analysis_service = RoleGapAnalysisService(db)

    def get_intelligence_overview(
        self,
        user: User,
        freshness_threshold_days: int | None = None,
        skills_preview_limit: int = 10,
        skills_preview_offset: int = 0,
    ) -> CandidateIntelligenceOverviewResponse:
        """
        Build an evidence-backed candidate intelligence overview for the authenticated user.
        """
        generated_at = datetime.now(UTC)

        # 1. Profile and Active Target Context
        profile_summary, active_target_id = self._resolve_profile_and_target(user)

        # 2. Target Alignment & Role Gap Analysis (only if active target exists)
        target_alignment_overview, target_canonical_skill_ids = (
            self._resolve_target_alignment(user, active_target_id)
        )

        # 3. Evidence-Backed Skill Coverage (Full population status + bounded preview)
        skill_coverage_overview = self._resolve_skill_coverage(
            user=user,
            target_canonical_skill_ids=target_canonical_skill_ids,
            freshness_threshold_days=freshness_threshold_days,
            preview_limit=skills_preview_limit,
            preview_offset=skills_preview_offset,
        )

        # 4. Resume Provenance and Claim Origin Partitions
        resume_provenance_summary = self._resolve_resume_provenance(user)

        # 5. Connected Evidence Sources Overview (Sanitized, full-population counts)
        evidence_sources_overview = self._resolve_evidence_sources(user)

        return CandidateIntelligenceOverviewResponse(
            generated_at=generated_at,
            profile=profile_summary,
            resume_provenance=resume_provenance_summary,
            evidence_sources=evidence_sources_overview,
            skill_coverage=skill_coverage_overview,
            target_alignment=target_alignment_overview,
            audit_disclaimers=list(OVERVIEW_AUDIT_DISCLAIMERS),
        )

    # -------------------------------------------------------------------------
    # Section Resolvers
    # -------------------------------------------------------------------------

    def _resolve_profile_and_target(
        self, user: User
    ) -> tuple[ProfileSummary | None, uuid.UUID | None]:
        """
        Inspect CandidateProfile and active CandidateTarget for user.
        Never fabricates records; returns None if absent.
        """
        profile = self.profile_repo.get_by_user_id(user.id)
        if not profile:
            return None, None

        active_target = self.target_repo.get_active_target(profile.id)
        active_target_id: uuid.UUID | None = active_target.id if active_target else None

        target_summary: TargetSummary | None = None
        if active_target:
            target_summary = TargetSummary(
                target_id=active_target.id,
                role_title=active_target.role_title,
                company=active_target.company,
                created_at=active_target.created_at,
            )

        profile_summary = ProfileSummary(
            profile_id=profile.id,
            graduation_year=profile.graduation_year,
            preferred_locations=profile.preferred_locations,
            has_active_target=active_target is not None,
            active_target=target_summary,
        )
        return profile_summary, active_target_id

    def _resolve_target_alignment(
        self, user: User, active_target_id: uuid.UUID | None
    ) -> tuple[TargetAlignmentOverview | None, set[uuid.UUID]]:
        """
        Evaluate target role requirements and gap analysis for active target via RoleGapAnalysisService.
        Extracts mapped canonical skill IDs for target correlation.
        """
        if not active_target_id:
            return None, set()

        report = self.gap_analysis_service.analyze_target_gaps(user, active_target_id)

        target_canonical_skill_ids: set[uuid.UUID] = set()
        req_items: list[TargetRequirementAlignmentItem] = []

        for req in report.requirements:
            if req.skill_id:
                target_canonical_skill_ids.add(req.skill_id)

            req_items.append(
                TargetRequirementAlignmentItem(
                    requirement_id=req.requirement_id,
                    requirement_text=req.requirement_text,
                    requirement_type=req.requirement_type,
                    importance=req.importance,
                    skill_id=req.skill_id,
                    canonical_skill_name=req.canonical_skill_name,
                    gap_status=req.status,
                    explanation=req.explanation,
                )
            )

        overview = TargetAlignmentOverview(
            target_id=report.candidate_target_id,
            role_title=report.role_title,
            company=report.company,
            total_requirements=report.total_requirements,
            gap_status_summary=report.status_summary,
            requirements=req_items,
        )
        return overview, target_canonical_skill_ids

    def _resolve_skill_coverage(
        self,
        user: User,
        target_canonical_skill_ids: set[uuid.UUID],
        freshness_threshold_days: int | None,
        preview_limit: int,
        preview_offset: int,
    ) -> SkillCoverageOverview:
        """
        Evaluate full candidate skill population via CandidateSkillCoverageService.
        Decorates returned preview items with is_required_by_active_target without altering
        underlying status derivations or full-population status summaries.
        """
        coverage_report = self.coverage_service.get_coverage_report(
            user=user,
            skill_id=None,
            limit=preview_limit,
            offset=preview_offset,
            freshness_threshold_days=freshness_threshold_days,
            unassociated_claims_limit=0,
            unassociated_claims_offset=0,
        )

        preview_items: list[SkillPreviewItem] = []
        for item in coverage_report.skills:
            is_required = item.skill_id in target_canonical_skill_ids
            preview_items.append(
                SkillPreviewItem(
                    candidate_skill_id=item.candidate_skill_id,
                    skill_id=item.skill_id,
                    canonical_name=item.canonical_name,
                    category=item.category,
                    coverage_status=item.coverage_status,
                    summary=item.summary,
                    is_required_by_active_target=is_required,
                )
            )

        return SkillCoverageOverview(
            total_skills_evaluated=coverage_report.total_skills_evaluated,
            status_summary=coverage_report.status_summary,
            unassociated_skill_claims_total=coverage_report.unassociated_skill_claims_total,
            preview_limit=preview_limit,
            preview_offset=preview_offset,
            preview_count=len(preview_items),
            skills_preview=preview_items,
        )

    def _resolve_resume_provenance(
        self, user: User
    ) -> ResumeProvenanceSummary | None:
        """
        Retrieve latest resume, latest successful parse snapshot, and partitioned claim counts.
        Distinguishes latest uploaded resume from latest parsed snapshot.
        """
        # Find latest uploaded resume (ordered by version descending)
        user_resumes = self.resume_repo.list_user_resumes(user.id, skip=0, limit=1)
        if not user_resumes:
            return None

        latest_resume: Resume = user_resumes[0]

        # Latest successful (READY) parse snapshot for this resume
        latest_ready_parse: ResumeParse | None = (
            self.parse_repo.get_latest_successful_parse(latest_resume.id)
        )

        # If no READY parse, fetch the most recent parse record of any status
        fallback_parse: ResumeParse | None = None
        if not latest_ready_parse:
            all_parses = self.parse_repo.list_by_resume(latest_resume.id)
            if all_parses:
                fallback_parse = all_parses[0]

        active_parse = latest_ready_parse or fallback_parse

        # Partition claim counts over the entire candidate population
        all_user_claims = self.claim_repo.list_by_user(user.id)
        total_claims_recorded = len(all_user_claims)

        resume_derived_claims_count = sum(
            1 for c in all_user_claims if c.origin == ClaimOrigin.RESUME
        )
        user_declared_claims_count = sum(
            1 for c in all_user_claims if c.origin == ClaimOrigin.USER_DECLARED
        )

        claims_from_latest_parse_count = 0
        if latest_ready_parse:
            claims_from_latest_parse_count = sum(
                1
                for c in all_user_claims
                if c.resume_parse_id == latest_ready_parse.id
            )

        return ResumeProvenanceSummary(
            latest_resume_id=latest_resume.id,
            latest_resume_version=latest_resume.version,
            latest_parse_id=active_parse.id if active_parse else None,
            parse_status=active_parse.status if active_parse else None,
            parsed_at=active_parse.created_at if active_parse else None,
            total_claims_recorded=total_claims_recorded,
            resume_derived_claims_count=resume_derived_claims_count,
            user_declared_claims_count=user_declared_claims_count,
            claims_from_latest_parse_count=claims_from_latest_parse_count,
        )

    def _resolve_evidence_sources(self, user: User) -> EvidenceSourcesOverview:
        """
        Fetch all registered evidence sources for candidate.
        Calculates full-population counts and sanitizes URIs according to source type.
        """
        sources_stmt = (
            select(EvidenceSource)
            .where(EvidenceSource.user_id == user.id)
            .order_by(EvidenceSource.created_at.desc())
        )
        sources = list(self.db.execute(sources_stmt).scalars().all())

        total_sources = len(sources)
        available_sources_count = sum(
            1 for s in sources if s.access_status == EvidenceSourceStatus.AVAILABLE
        )
        non_available_sources_count = total_sources - available_sources_count

        sanitized_items: list[EvidenceSourceOverviewItem] = []
        for s in sources:
            source_host, source_path = self._sanitize_source_uri(s.source_type, s.source_uri)
            sanitized_items.append(
                EvidenceSourceOverviewItem(
                    source_id=s.id,
                    source_type=s.source_type,
                    source_host=source_host,
                    source_path=source_path,
                    access_status=s.access_status,
                    last_checked_at=s.last_checked_at,
                )
            )

        return EvidenceSourcesOverview(
            total_sources=total_sources,
            available_sources_count=available_sources_count,
            non_available_sources_count=non_available_sources_count,
            sources=sanitized_items,
        )

    @staticmethod
    def _sanitize_source_uri(
        source_type: EvidenceSourceType, source_uri: str
    ) -> tuple[str, str]:
        """
        Deterministic, offline sanitization of source URI.
        Discards query parameters, fragments, userinfo, and auth credentials.
        For GitHub repositories and profiles, formats the clean repo/profile path.
        For OTHER sources, restricts path disclosure to avoid leaking arbitrary sub-paths.
        """
        try:
            parsed = urlsplit(source_uri)
            host = (parsed.hostname or "").lower().strip()
            raw_path = parsed.path.strip("/")
        except Exception:
            return "unknown", "invalid"

        if not host:
            return "unknown", "invalid"

        if source_type in (
            EvidenceSourceType.GITHUB_REPOSITORY,
            EvidenceSourceType.GITHUB_PROFILE,
        ):
            # Safe to expose public repository/user path segment (e.g. "owner/repo" or "owner")
            return host, raw_path

        if source_type == EvidenceSourceType.LINKEDIN_PROFILE:
            # Safe to expose linkedin profile slug without query params
            return host, raw_path

        # For PORTFOLIO, ASSESSMENT, and OTHER:
        # Expose only the first path segment (or empty) to prevent exposing arbitrary private filepaths
        first_segment = raw_path.split("/")[0] if raw_path else ""
        return host, first_segment
