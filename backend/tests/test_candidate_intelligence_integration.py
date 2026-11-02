import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_profile import CandidateProfile
from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.candidate_target import CandidateTarget
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
from app.models.user import User
from app.models.verification_result import (
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)
from app.services.candidate_intelligence_service import (
    OVERVIEW_AUDIT_DISCLAIMERS,
    CandidateIntelligenceService,
)

# =============================================================================
# Helper Fixtures & Factories
# =============================================================================


def create_user(db: Session, prefix: str = "intel_user") -> User:
    """Helper to persist a test User."""
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{unique_id}@nextround.in",
        name=f"Intelligence User {unique_id}",
        hashed_password="hashed_pw_test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_profile(
    db: Session,
    user: User,
    graduation_year: int = 2024,
    preferred_locations: list[str] | None = None,
) -> CandidateProfile:
    """Helper to persist a CandidateProfile."""
    profile = CandidateProfile(
        user_id=user.id,
        graduation_year=graduation_year,
        preferred_locations=preferred_locations or ["Bengaluru", "Remote"],
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def create_target(
    db: Session,
    profile: CandidateProfile,
    role_title: str = "Backend Software Engineer",
    company: str | None = "NextRound Labs",
    is_active: bool = True,
) -> CandidateTarget:
    """Helper to persist a CandidateTarget."""
    target = CandidateTarget(
        candidate_profile_id=profile.id,
        role_title=role_title,
        company=company,
        is_active=is_active,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def create_skill(
    db: Session,
    name: str = "Python",
    category: str = "Programming Language",
    aliases: list[str] | None = None,
) -> Skill:
    """Helper to persist a canonical Skill."""
    skill = Skill(
        canonical_name=name,
        category=category,
        aliases=aliases or [],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def create_requirement(
    db: Session,
    target: CandidateTarget,
    text: str,
    skill: Skill | None = None,
    req_type: RequirementType = RequirementType.SKILL,
    importance: RequirementImportance = RequirementImportance.REQUIRED,
) -> RoleRequirement:
    """Helper to persist a RoleRequirement."""
    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id if skill else None,
        requirement_text=text,
        requirement_type=req_type,
        importance=importance,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def create_resume_with_parse(
    db: Session,
    user: User,
    version: int = 1,
    status: ParseStatus = ParseStatus.READY,
) -> tuple[Resume, ResumeParse]:
    """Helper to persist a Resume and corresponding ResumeParse snapshot."""
    storage_unique = uuid.uuid4().hex
    resume = Resume(
        user_id=user.id,
        original_filename=f"resume_v{version}.pdf",
        storage_key=f"resumes/{user.id}/resume_v{version}_{storage_unique}.pdf",
        mime_type="application/pdf",
        file_size=1024,
        version=version,
        status=ResumeStatus.READY,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    parse = ResumeParse(
        resume_id=resume.id,
        resume_version=version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=status,
        canonical_data={"basics": {"name": user.name}},
    )
    db.add(parse)
    db.commit()
    db.refresh(parse)
    return resume, parse


def create_claim(
    db: Session,
    user: User,
    claim_text: str,
    claim_type: ClaimType = ClaimType.SKILL,
    origin: ClaimOrigin = ClaimOrigin.USER_DECLARED,
    resume_parse_id: uuid.UUID | None = None,
    canonical_path: str | None = None,
) -> CandidateClaim:
    """Helper to persist a CandidateClaim."""
    claim = CandidateClaim(
        user_id=user.id,
        claim_type=claim_type,
        claim_text=claim_text,
        origin=origin,
        resume_parse_id=resume_parse_id,
        canonical_path=canonical_path,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def create_source(
    db: Session,
    user: User,
    source_uri: str,
    source_type: EvidenceSourceType = EvidenceSourceType.GITHUB_REPOSITORY,
    access_status: EvidenceSourceStatus = EvidenceSourceStatus.AVAILABLE,
) -> EvidenceSource:
    """Helper to persist an EvidenceSource."""
    source = EvidenceSource(
        user_id=user.id,
        source_type=source_type,
        source_uri=source_uri,
        access_mode=AccessMode.PUBLIC,
        access_status=access_status,
        last_checked_at=datetime.now(UTC),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def create_candidate_skill(
    db: Session,
    user: User,
    skill: Skill,
    claims: list[CandidateClaim] | None = None,
    items: list[EvidenceItem] | None = None,
) -> CandidateSkill:
    """Helper to persist a CandidateSkill with attached evidence links."""
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cs)
    db.commit()
    db.refresh(cs)

    for c in claims or []:
        link = CandidateSkillEvidence(
            candidate_skill_id=cs.id,
            candidate_claim_id=c.id,
        )
        db.add(link)

    for item in items or []:
        link = CandidateSkillEvidence(
            candidate_skill_id=cs.id,
            evidence_item_id=item.id,
        )
        db.add(link)

    db.commit()
    db.refresh(cs)
    return cs


def create_verification_result(
    db: Session,
    claim: CandidateClaim | None = None,
    source: EvidenceSource | None = None,
    outcome: VerificationOutcome = VerificationOutcome.SUPPORTED,
    verification_type: VerificationType = VerificationType.CLAIM_SUPPORT,
) -> VerificationResult:
    """Helper to persist a VerificationResult."""
    vr = VerificationResult(
        candidate_claim_id=claim.id if claim else None,
        evidence_source_id=source.id if source else None,
        verification_type=verification_type,
        outcome=outcome,
        method_version="1.0.0",
        explanation=f"Evaluated with outcome {outcome}",
    )
    db.add(vr)
    db.commit()
    db.refresh(vr)
    return vr


# =============================================================================
# 1. Complete Overview & Target Correlation Tests
# =============================================================================


def test_complete_candidate_intelligence_overview(db: Session) -> None:
    """
    Verify complete overview aggregation for a candidate with profile, active target,
    parsed resume, verified and unverified skills, and external evidence sources.
    """
    user = create_user(db, "complete")
    profile = create_profile(db, user, graduation_year=2023, preferred_locations=["Remote"])
    target = create_target(db, profile, role_title="Senior Python Backend Engineer", company="Acme Corp")

    # Skills: Python (target-required), Go (target-required), Docker (not in target)
    s_py = create_skill(db, "Python")
    s_go = create_skill(db, "Go")
    s_doc = create_skill(db, "Docker")

    # Requirements on target: Python (mapped), Go (mapped), AWS (unmapped)
    create_requirement(db, target, "Expert Python development", skill=s_py)
    create_requirement(db, target, "Go concurrency experience", skill=s_go)
    create_requirement(db, target, "Cloud architecture with AWS", skill=None, req_type=RequirementType.QUALIFICATION)

    # Resume & Parse
    resume, parse = create_resume_with_parse(db, user, version=1)

    # Claims: 1 resume claim, 1 user-declared claim
    c_py = create_claim(
        db,
        user,
        claim_text="5 years building Python services",
        origin=ClaimOrigin.RESUME,
        resume_parse_id=parse.id,
        canonical_path="/experience/0",
    )
    create_claim(
        db,
        user,
        claim_text="Built microservices in Go",
        origin=ClaimOrigin.USER_DECLARED,
    )

    # Verification: Python is SUPPORTED
    create_verification_result(db, claim=c_py, outcome=VerificationOutcome.SUPPORTED)

    # Candidate Skills
    create_candidate_skill(db, user, s_py, claims=[c_py])
    create_candidate_skill(db, user, s_doc)  # No claims/evidence -> NO_EVIDENCE

    # Evidence sources: 1 GitHub (available), 1 Portfolio (revoked)
    create_source(db, user, "https://github.com/complete-user/backend-repo", access_status=EvidenceSourceStatus.AVAILABLE)
    create_source(db, user, "https://portfolio.me/complete-user", source_type=EvidenceSourceType.PORTFOLIO, access_status=EvidenceSourceStatus.REVOKED)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    # A. Audit Disclaimers
    assert len(overview.audit_disclaimers) == 3
    for disc in OVERVIEW_AUDIT_DISCLAIMERS:
        assert disc in overview.audit_disclaimers

    # B. Profile & Target Context
    assert overview.profile is not None
    assert overview.profile.profile_id == profile.id
    assert overview.profile.graduation_year == 2023
    assert overview.profile.has_active_target is True
    assert overview.profile.active_target is not None
    assert overview.profile.active_target.target_id == target.id
    assert overview.profile.active_target.role_title == "Senior Python Backend Engineer"

    # C. Target Alignment Overview
    assert overview.target_alignment is not None
    assert overview.target_alignment.target_id == target.id
    assert overview.target_alignment.total_requirements == 3
    # Check that unmapped requirement is preserved
    unmapped = [r for r in overview.target_alignment.requirements if r.skill_id is None]
    assert len(unmapped) == 1
    assert unmapped[0].requirement_text == "Cloud architecture with AWS"

    # D. Resume Provenance
    assert overview.resume_provenance is not None
    assert overview.resume_provenance.latest_resume_id == resume.id
    assert overview.resume_provenance.latest_resume_version == 1
    assert overview.resume_provenance.latest_parse_id == parse.id
    assert overview.resume_provenance.parse_status == ParseStatus.READY
    assert overview.resume_provenance.total_claims_recorded == 2
    assert overview.resume_provenance.resume_derived_claims_count == 1
    assert overview.resume_provenance.user_declared_claims_count == 1
    assert overview.resume_provenance.claims_from_latest_parse_count == 1

    # E. Evidence Sources Overview
    assert overview.evidence_sources.total_sources == 2
    assert overview.evidence_sources.available_sources_count == 1
    assert overview.evidence_sources.non_available_sources_count == 1
    assert len(overview.evidence_sources.sources) == 2

    # F. Skill Coverage & Target Correlation
    assert overview.skill_coverage.total_skills_evaluated == 2
    assert overview.skill_coverage.status_summary["CLAIM_SUPPORTED"] == 1
    assert overview.skill_coverage.status_summary["NO_EVIDENCE"] == 1

    # Python is required by target; Docker is not
    skills_by_name = {s.canonical_name: s for s in overview.skill_coverage.skills_preview}
    assert skills_by_name["Python"].is_required_by_active_target is True
    assert skills_by_name["Docker"].is_required_by_active_target is False


# =============================================================================
# 2. Empty & Minimal State Tests
# =============================================================================


def test_candidate_without_profile(db: Session) -> None:
    """
    Verify candidate without a CandidateProfile receives an overview with profile=None,
    target_alignment=None, without fabricating database records or raising 404.
    """
    user = create_user(db, "no_profile")

    # Add a skill and evidence source directly
    s = create_skill(db, "Rust")
    create_candidate_skill(db, user, s)
    create_source(db, user, "https://github.com/rust-user/core")

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.profile is None
    assert overview.target_alignment is None
    assert overview.resume_provenance is None
    assert overview.evidence_sources.total_sources == 1
    assert overview.skill_coverage.total_skills_evaluated == 1
    assert overview.skill_coverage.skills_preview[0].canonical_name == "Rust"
    assert overview.skill_coverage.skills_preview[0].is_required_by_active_target is False

    # Confirm no profile was silently created in database
    db_profile = db.query(CandidateProfile).filter_by(user_id=user.id).first()
    assert db_profile is None


def test_candidate_with_profile_but_no_active_target(db: Session) -> None:
    """
    Verify candidate with profile but no active target returns profile with
    has_active_target=False, target_alignment=None, and all skill preview items
    with is_required_by_active_target=False.
    """
    user = create_user(db, "no_target")
    profile = create_profile(db, user, graduation_year=2025)

    s = create_skill(db, "Java")
    create_candidate_skill(db, user, s)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.profile is not None
    assert overview.profile.profile_id == profile.id
    assert overview.profile.has_active_target is False
    assert overview.profile.active_target is None
    assert overview.target_alignment is None
    assert overview.skill_coverage.total_skills_evaluated == 1
    assert overview.skill_coverage.skills_preview[0].is_required_by_active_target is False


def test_candidate_with_no_resumes_or_parses(db: Session) -> None:
    """
    Verify candidate with zero resume uploads returns resume_provenance=None.
    """
    user = create_user(db, "no_resume")
    create_profile(db, user)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.resume_provenance is None


def test_candidate_with_resume_but_failed_parse(db: Session) -> None:
    """
    Verify candidate with uploaded resume whose parse failed returns the resume version,
    failed parse status, and 0 latest-parse claims.
    """
    user = create_user(db, "failed_parse")
    create_profile(db, user)
    resume, parse = create_resume_with_parse(db, user, version=1, status=ParseStatus.FAILED)

    # User declared a claim manually
    create_claim(db, user, "Self-taught Python", origin=ClaimOrigin.USER_DECLARED)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.resume_provenance is not None
    assert overview.resume_provenance.latest_resume_id == resume.id
    assert overview.resume_provenance.latest_resume_version == 1
    assert overview.resume_provenance.latest_parse_id == parse.id
    assert overview.resume_provenance.parse_status == ParseStatus.FAILED
    assert overview.resume_provenance.total_claims_recorded == 1
    assert overview.resume_provenance.user_declared_claims_count == 1
    assert overview.resume_provenance.resume_derived_claims_count == 0
    assert overview.resume_provenance.claims_from_latest_parse_count == 0


# =============================================================================
# 3. Provenance & Claim Partitioning Tests
# =============================================================================


def test_historical_resume_claims_versus_latest_parse_claims(db: Session) -> None:
    """
    Verify claims tied to an earlier resume version parse snapshot are correctly partitioned
    and distinguishable from claims tied to the latest parse snapshot.
    """
    user = create_user(db, "multi_version")
    create_profile(db, user)

    # Resume v1 with parse snapshot 1
    _r1, p1 = create_resume_with_parse(db, user, version=1, status=ParseStatus.READY)
    create_claim(db, user, "v1 Python", origin=ClaimOrigin.RESUME, resume_parse_id=p1.id, canonical_path="/exp/0")
    create_claim(db, user, "v1 Django", origin=ClaimOrigin.RESUME, resume_parse_id=p1.id, canonical_path="/exp/1")

    # Resume v2 with parse snapshot 2
    r2, p2 = create_resume_with_parse(db, user, version=2, status=ParseStatus.READY)
    create_claim(db, user, "v2 FastAPI", origin=ClaimOrigin.RESUME, resume_parse_id=p2.id, canonical_path="/exp/0")

    # User-declared claim
    create_claim(db, user, "User declared Kubernetes", origin=ClaimOrigin.USER_DECLARED)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.resume_provenance is not None
    assert overview.resume_provenance.latest_resume_id == r2.id
    assert overview.resume_provenance.latest_resume_version == 2
    assert overview.resume_provenance.latest_parse_id == p2.id
    assert overview.resume_provenance.parse_status == ParseStatus.READY

    assert overview.resume_provenance.total_claims_recorded == 4
    assert overview.resume_provenance.resume_derived_claims_count == 3
    assert overview.resume_provenance.user_declared_claims_count == 1
    # Only 1 claim belongs to latest parse snapshot (p2)
    assert overview.resume_provenance.claims_from_latest_parse_count == 1


# =============================================================================
# 4. Preview Pagination & Full-Population Counters
# =============================================================================


def test_full_population_skill_counts_with_preview_pagination(db: Session) -> None:
    """
    Verify full-population skill coverage status counters and total evaluated
    cover 100% of candidate skills, while preview_count reflects the paginated slice.
    """
    user = create_user(db, "skills_paging")
    create_profile(db, user)

    # Create 6 skills: 2 SUPPORTED, 2 NO_EVIDENCE, 2 UNVERIFIED_EVIDENCE
    for i in range(6):
        skill = create_skill(db, f"TechSkill_{i}")
        if i < 2:
            claim = create_claim(db, user, f"Claim for TechSkill_{i}")
            create_verification_result(db, claim=claim, outcome=VerificationOutcome.SUPPORTED)
            create_candidate_skill(db, user, skill, claims=[claim])
        elif i < 4:
            src = create_source(db, user, f"https://github.com/paging/repo_{i}")
            item = EvidenceItem(
                evidence_source_id=src.id,
                evidence_type=EvidenceType.REPOSITORY_METADATA,
                description=f"Evidence for TechSkill_{i}",
                observed_at=datetime.now(UTC),
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            create_candidate_skill(db, user, skill, items=[item])
        else:
            create_candidate_skill(db, user, skill)

    service = CandidateIntelligenceService(db)

    # Request slice with limit=2, offset=0
    overview_page1 = service.get_intelligence_overview(
        user, skills_preview_limit=2, skills_preview_offset=0
    )

    cov1 = overview_page1.skill_coverage
    assert cov1.total_skills_evaluated == 6
    assert sum(cov1.status_summary.values()) == 6
    assert cov1.status_summary["CLAIM_SUPPORTED"] == 2
    assert cov1.status_summary["UNVERIFIED_EVIDENCE"] == 2
    assert cov1.status_summary["NO_EVIDENCE"] == 2

    assert cov1.preview_limit == 2
    assert cov1.preview_offset == 0
    assert cov1.preview_count == 2
    assert len(cov1.skills_preview) == 2

    # Request slice with limit=3, offset=4
    overview_page2 = service.get_intelligence_overview(
        user, skills_preview_limit=3, skills_preview_offset=4
    )
    cov2 = overview_page2.skill_coverage
    assert cov2.total_skills_evaluated == 6
    assert cov2.preview_count == 2
    assert len(cov2.skills_preview) == 2


# =============================================================================
# 5. Evidence Source URI Sanitization Tests
# =============================================================================


def test_source_uri_sanitization_across_types(db: Session) -> None:
    """
    Verify offline URL sanitization strips queries, fragments, credentials,
    and restricts sub-path disclosure according to source type.
    """
    user = create_user(db, "sanitize")
    create_profile(db, user)

    # 1. GitHub Repo with query and fragment
    create_source(
        db,
        user,
        "https://github.com/nextround-org/core-api?branch=main#readme",
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
    )
    # 2. LinkedIn Profile with tracking query
    create_source(
        db,
        user,
        "https://linkedin.com/in/john-doe?trackingId=123",
        source_type=EvidenceSourceType.LINKEDIN_PROFILE,
    )
    # 3. Portfolio with deep private subpath
    create_source(
        db,
        user,
        "https://candidate-portfolio.dev/projects/confidential-internal-spec/doc",
        source_type=EvidenceSourceType.PORTFOLIO,
    )
    # 4. Other source with nested path
    create_source(
        db,
        user,
        "https://custom-host.io/internal/system/logs",
        source_type=EvidenceSourceType.OTHER,
    )

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    sources_by_host = {s.source_host: s for s in overview.evidence_sources.sources}

    # GitHub: host + path preserved without query/fragment
    gh = sources_by_host["github.com"]
    assert gh.source_path == "nextround-org/core-api"

    # LinkedIn: host + path preserved without query
    li = sources_by_host["linkedin.com"]
    assert li.source_path == "in/john-doe"

    # Portfolio: host + only first segment preserved
    port = sources_by_host["candidate-portfolio.dev"]
    assert port.source_path == "projects"

    # Other: host + only first segment preserved
    other = sources_by_host["custom-host.io"]
    assert other.source_path == "internal"


# =============================================================================
# 6. Tenant Isolation & API Route Tests
# =============================================================================


def test_tenant_isolation(db: Session) -> None:
    """
    Verify User B's overview request does not leak or observe User A's data.
    """
    user_a = create_user(db, "tenant_a")
    user_b = create_user(db, "tenant_b")

    profile_a = create_profile(db, user_a)
    create_target(db, profile_a, role_title="Target A Role")
    s_a = create_skill(db, "SkillA")
    create_candidate_skill(db, user_a, s_a)

    service = CandidateIntelligenceService(db)
    overview_b = service.get_intelligence_overview(user_b)

    assert overview_b.profile is None
    assert overview_b.target_alignment is None
    assert overview_b.skill_coverage.total_skills_evaluated == 0
    assert len(overview_b.skill_coverage.skills_preview) == 0


def test_more_than_50_evidence_sources_counted_accurately(db: Session) -> None:
    """
    Verify candidate with > 50 registered evidence sources has the complete population
    tallied accurately in EvidenceSourcesOverview.
    """
    user = create_user(db, "large_sources")
    # Register 60 sources: 40 AVAILABLE, 20 REVOKED
    for i in range(60):
        status = EvidenceSourceStatus.AVAILABLE if i < 40 else EvidenceSourceStatus.REVOKED
        create_source(
            db,
            user,
            f"https://github.com/large-source-user/repo_{i}",
            access_status=status,
        )

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.evidence_sources.total_sources == 60
    assert overview.evidence_sources.available_sources_count == 40
    assert overview.evidence_sources.non_available_sources_count == 20
    assert len(overview.evidence_sources.sources) == 60


def test_malformed_and_unusual_source_uris(db: Session) -> None:
    """
    Verify handling of unusual, malformed, or encoded URIs without crashing or leaking sensitive info.
    """
    user = create_user(db, "unusual_uris")
    # 1. Invalid scheme/URI
    create_source(db, user, "not-a-valid-url", source_type=EvidenceSourceType.OTHER)
    # 2. URI with userinfo credentials and port
    create_source(db, user, "https://user:password@gitlab.com:8443/org/repo.git", source_type=EvidenceSourceType.OTHER)
    # 3. URI with percent-encoded characters and spaces
    create_source(db, user, "https://github.com/candidate%20org/special-repo%2Fname", source_type=EvidenceSourceType.GITHUB_REPOSITORY)

    service = CandidateIntelligenceService(db)
    overview = service.get_intelligence_overview(user)

    assert overview.evidence_sources.total_sources == 3
    sources = overview.evidence_sources.sources
    # Neither password nor port should leak in source_host or source_path
    hosts = [s.source_host for s in sources]
    paths = [s.source_path for s in sources]

    assert "user:password" not in "".join(hosts)
    assert "user:password" not in "".join(paths)
    assert ":8443" not in "".join(hosts)


def test_read_only_invariance_no_session_mutations(db: Session) -> None:
    """
    Verify get_intelligence_overview leaves session completely unmutated (no dirty, new, or deleted objects).
    """
    user = create_user(db, "readonly_check")
    profile = create_profile(db, user)
    create_target(db, profile, role_title="DevOps Lead")

    service = CandidateIntelligenceService(db)
    _overview = service.get_intelligence_overview(user)

    # Session inspection: zero pending objects
    assert len(db.dirty) == 0
    assert len(db.new) == 0
    assert len(db.deleted) == 0
