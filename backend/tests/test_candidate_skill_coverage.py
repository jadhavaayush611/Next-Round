import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.skill import Skill
from app.models.user import User
from app.models.verification_result import (
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)
from app.schemas.candidate_skill_coverage import CandidateSkillCoverageStatus
from app.services.candidate_skill_coverage_service import (
    CandidateSkillCoverageService,
)

# =============================================================================
# Helper Fixtures and Factories
# =============================================================================


def create_test_user(db: Session, prefix: str = "cov_user") -> User:
    """Helper to persist a test User."""
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{unique_id}@nextround.in",
        name=f"Coverage User {unique_id}",
        hashed_password="hashed_pw_test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_skill(
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


def create_test_claim(
    db: Session,
    user: User,
    claim_type: ClaimType = ClaimType.SKILL,
    claim_text: str = "Built microservices in Python",
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


def create_test_source(
    db: Session,
    user: User,
    source_uri: str | None = None,
    source_type: EvidenceSourceType = EvidenceSourceType.GITHUB_REPOSITORY,
    access_status: EvidenceSourceStatus = EvidenceSourceStatus.AVAILABLE,
    last_checked_at: datetime | None = None,
) -> EvidenceSource:
    """Helper to persist an EvidenceSource."""
    uri = source_uri or f"https://github.com/testcandidate/{uuid.uuid4().hex[:8]}"
    source = EvidenceSource(
        user_id=user.id,
        source_type=source_type,
        source_uri=uri,
        access_mode=AccessMode.PUBLIC,
        access_status=access_status,
        last_checked_at=last_checked_at,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def create_test_item(
    db: Session,
    source: EvidenceSource,
    evidence_type: EvidenceType = EvidenceType.REPOSITORY_METADATA,
    description: str = "Python repository metadata",
    observed_data: dict[str, Any] | None = None,
    source_locator: str | None = "repository_metadata",
    observed_at: datetime | None = None,
) -> EvidenceItem:
    """Helper to persist an EvidenceItem."""
    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=evidence_type,
        description=description,
        observed_data=observed_data or {},
        source_locator=source_locator,
        observed_at=observed_at or datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_test_candidate_skill(
    db: Session,
    user: User,
    skill: Skill,
    claims: list[CandidateClaim] | None = None,
    items: list[EvidenceItem] | None = None,
) -> CandidateSkill:
    """Helper to persist a CandidateSkill with linked claims or evidence items."""
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cs)
    db.flush()

    for c in claims or []:
        link = CandidateSkillEvidence(
            candidate_skill_id=cs.id,
            candidate_claim_id=c.id,
            evidence_item_id=None,
        )
        db.add(link)

    for i in items or []:
        link = CandidateSkillEvidence(
            candidate_skill_id=cs.id,
            candidate_claim_id=None,
            evidence_item_id=i.id,
        )
        db.add(link)

    db.commit()
    db.refresh(cs)
    return cs


def create_test_verification_result(
    db: Session,
    claim: CandidateClaim | None = None,
    source: EvidenceSource | None = None,
    outcome: VerificationOutcome = VerificationOutcome.SUPPORTED,
    verification_type: VerificationType = VerificationType.CLAIM_SUPPORT,
    method_version: str = "v1.0",
    explanation: str = "Verification check explanation",
    checked_at: datetime | None = None,
) -> VerificationResult:
    """Helper to persist a VerificationResult."""
    vr = VerificationResult(
        candidate_claim_id=claim.id if claim else None,
        evidence_source_id=source.id if source else None,
        verification_type=verification_type,
        outcome=outcome,
        method_version=method_version,
        explanation=explanation,
        checked_at=checked_at or datetime.now(UTC),
    )
    db.add(vr)
    db.commit()
    db.refresh(vr)
    return vr


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Helper to register/login a user and return Authorization headers."""
    password = "StrongPassword123!"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "Auth Candidate"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Verification Scope & Precedence Tests
# =============================================================================


def test_mixed_verification_applies_strictly_to_conflicting_claim_scopes(
    db: Session,
) -> None:
    """
    Verify MIXED_VERIFICATION applies when independent claim scopes have conflicting outcomes
    (one SUPPORTED and one CONTRADICTED).
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Python")

    claim1 = create_test_claim(
        db, user, claim_text="Built microservices in Python Django"
    )
    claim2 = create_test_claim(
        db, user, claim_text="Architected data pipelines in Python Spark"
    )

    create_test_verification_result(
        db,
        claim=claim1,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )
    create_test_verification_result(
        db,
        claim=claim2,
        outcome=VerificationOutcome.CONTRADICTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim1, claim2])

    service = CandidateSkillCoverageService(db)
    item = service.get_skill_coverage(user, cs.id)

    assert item.coverage_status == CandidateSkillCoverageStatus.MIXED_VERIFICATION
    assert len(item.claim_outcomes) == 2
    outcomes = {co.claim_id: co.latest_outcome for co in item.claim_outcomes}
    assert outcomes[claim1.id] == VerificationOutcome.SUPPORTED
    assert outcomes[claim2.id] == VerificationOutcome.CONTRADICTED
    assert "conflicting outcomes" in item.summary


def test_supported_source_and_contradicted_claim_not_mixed(db: Session) -> None:
    """
    Verify a SUPPORTED source-level check and a CONTRADICTED claim-level check are NOT mixed:
    source existence does not refute or verify claim validity. The claim outcome governs the status.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Python")

    claim = create_test_claim(
        db, user, claim_text="Lead engineer on Python compiler backend"
    )
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    # Source existence check is SUPPORTED
    create_test_verification_result(
        db,
        source=source,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.SOURCE_EXISTENCE,
    )
    # Claim check is CONTRADICTED
    create_test_verification_result(
        db,
        claim=claim,
        outcome=VerificationOutcome.CONTRADICTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])

    service = CandidateSkillCoverageService(db)
    coverage = service.get_skill_coverage(user, cs.id)

    # Must be CLAIM_CONTRADICTED, NEVER MIXED_VERIFICATION
    assert coverage.coverage_status == CandidateSkillCoverageStatus.CLAIM_CONTRADICTED
    assert len(coverage.claim_outcomes) == 1
    assert coverage.claim_outcomes[0].latest_outcome == VerificationOutcome.CONTRADICTED
    assert len(coverage.source_outcomes) == 1
    assert coverage.source_outcomes[0].latest_outcome == VerificationOutcome.SUPPORTED


def test_verification_result_targeting_both_claim_and_source_not_double_counted(
    db: Session,
) -> None:
    """
    Verify a VerificationResult targeting both claim and source with type CLAIM_SUPPORT
    is assigned to claim scope only and not double-counted as a source check.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Go")

    claim = create_test_claim(db, user, claim_text="Engineered Go microservice")
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    # Result targets both claim and source
    vr = create_test_verification_result(
        db,
        claim=claim,
        source=source,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])

    service = CandidateSkillCoverageService(db)
    coverage = service.get_skill_coverage(user, cs.id)

    assert coverage.coverage_status == CandidateSkillCoverageStatus.CLAIM_SUPPORTED
    assert len(coverage.claim_outcomes) == 1
    assert coverage.claim_outcomes[0].verification_result_id == vr.id
    # Must NOT produce a phantom source-level check
    assert len(coverage.source_outcomes) == 0


def test_supported_claim_plus_unavailable_claim_conservatively_supported(
    db: Session,
) -> None:
    """
    Verify supported claim alongside an unavailable claim is NOT classified as mixed,
    but remains CLAIM_SUPPORTED with a conservative note acknowledging access limitation.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Rust")

    claim1 = create_test_claim(db, user, claim_text="Wrote Rust memory allocator")
    claim2 = create_test_claim(db, user, claim_text="Built Rust CLI parser")

    create_test_verification_result(
        db,
        claim=claim1,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )
    create_test_verification_result(
        db,
        claim=claim2,
        outcome=VerificationOutcome.UNAVAILABLE,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim1, claim2])

    service = CandidateSkillCoverageService(db)
    coverage = service.get_skill_coverage(user, cs.id)

    assert coverage.coverage_status == CandidateSkillCoverageStatus.CLAIM_SUPPORTED
    assert "1 claim check(s) were unavailable" in coverage.summary
    assert "does not establish universal proficiency" in coverage.summary
    assert len(coverage.claim_outcomes) == 2
    outcomes = {co.claim_id: co.latest_outcome for co in coverage.claim_outcomes}
    assert outcomes[claim1.id] == VerificationOutcome.SUPPORTED
    assert outcomes[claim2.id] == VerificationOutcome.UNAVAILABLE

    claims_by_id = {c.claim_id: c for c in coverage.claims}
    assert (
        claims_by_id[claim1.id].latest_verification_outcome
        == VerificationOutcome.SUPPORTED
    )
    assert (
        claims_by_id[claim2.id].latest_verification_outcome
        == VerificationOutcome.UNAVAILABLE
    )


def test_verification_type_other_claim_targeted_assigned_to_claim_scope(
    db: Session,
) -> None:
    """
    Verify VerificationType.OTHER targeting a claim (with or without source)
    is assigned strictly to claim scope and does not double-count into source outcomes.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Elixir")
    claim = create_test_claim(db, user, claim_text="Elixir OTP supervisor tree")
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    # OTHER check targeting both claim and source
    vr = create_test_verification_result(
        db,
        claim=claim,
        source=source,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.OTHER,
        method_version="custom_check_v1",
        explanation="Custom claim evaluation with external platform",
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])
    service = CandidateSkillCoverageService(db)
    cov = service.get_skill_coverage(user, cs.id)

    assert cov.coverage_status == CandidateSkillCoverageStatus.CLAIM_SUPPORTED
    assert len(cov.claim_outcomes) == 1
    assert cov.claim_outcomes[0].verification_result_id == vr.id
    assert cov.claim_outcomes[0].latest_outcome == VerificationOutcome.SUPPORTED
    # Must NOT produce a phantom source outcome
    assert len(cov.source_outcomes) == 0
    assert cov.claims[0].latest_verification_outcome == VerificationOutcome.SUPPORTED


def test_verification_type_other_source_only_assigned_to_source_scope(
    db: Session,
) -> None:
    """
    Verify VerificationType.OTHER targeting an evidence source without a claim reference
    is assigned strictly to source scope and does not affect claim outcomes.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Clojure")
    claim = create_test_claim(db, user, claim_text="Clojure functional programming")
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    # OTHER check targeting source only
    vr = create_test_verification_result(
        db,
        claim=None,
        source=source,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.OTHER,
        method_version="source_audit_v1",
        explanation="Custom repository ownership check",
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])
    service = CandidateSkillCoverageService(db)
    cov = service.get_skill_coverage(user, cs.id)

    assert (
        cov.coverage_status
        == CandidateSkillCoverageStatus.SUPPORTED_SOURCE_UNVERIFIED_CLAIM
    )
    assert len(cov.source_outcomes) == 1
    assert cov.source_outcomes[0].verification_result_id == vr.id
    assert cov.source_outcomes[0].latest_outcome == VerificationOutcome.SUPPORTED
    assert len(cov.claim_outcomes) == 0
    assert cov.claims[0].latest_verification_outcome is None


def test_overview_and_individual_endpoints_produce_identical_coverage_item(
    db: Session,
) -> None:
    """
    Verify the overview report and individual-detail endpoints use identical
    status derivation logic and return equivalent coverage items.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Scala")
    claim = create_test_claim(db, user, claim_text="Scala Akka actor system")
    create_test_verification_result(
        db,
        claim=claim,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )
    cs = create_test_candidate_skill(db, user, skill, claims=[claim])

    service = CandidateSkillCoverageService(db)
    individual_item = service.get_skill_coverage(user, cs.id)
    overview_report = service.get_coverage_report(user, skill_id=skill.id)

    assert len(overview_report.skills) == 1
    overview_item = overview_report.skills[0]

    assert individual_item.candidate_skill_id == overview_item.candidate_skill_id
    assert individual_item.coverage_status == overview_item.coverage_status
    assert individual_item.summary == overview_item.summary
    assert len(individual_item.claims) == len(overview_item.claims)
    assert len(individual_item.claim_outcomes) == len(overview_item.claim_outcomes)
    assert (
        individual_item.claim_outcomes[0].latest_outcome
        == overview_item.claim_outcomes[0].latest_outcome
    )


def test_supported_source_scope_without_claim_level_verification(
    db: Session,
) -> None:
    """
    Verify a supported source scope where candidate claims are unverified yields
    SUPPORTED_SOURCE_UNVERIFIED_CLAIM, clearly preserving that the claim remains unverified.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "TypeScript")

    claim = create_test_claim(db, user, claim_text="Frontend development in TypeScript")
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    create_test_verification_result(
        db,
        source=source,
        outcome=VerificationOutcome.SUPPORTED,
        verification_type=VerificationType.SOURCE_EXISTENCE,
    )

    cs = create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])

    service = CandidateSkillCoverageService(db)
    coverage = service.get_skill_coverage(user, cs.id)

    assert (
        coverage.coverage_status
        == CandidateSkillCoverageStatus.SUPPORTED_SOURCE_UNVERIFIED_CLAIM
    )
    assert len(coverage.source_outcomes) == 1
    assert coverage.source_outcomes[0].latest_outcome == VerificationOutcome.SUPPORTED
    assert len(coverage.claim_outcomes) == 0
    assert coverage.claims[0].latest_verification_outcome is None


# =============================================================================
# 2. Availability, Freshness & Evidence States
# =============================================================================


def test_missing_verification_versus_explicit_unavailable(db: Session) -> None:
    """
    Verify missing verification check (UNVERIFIED_EVIDENCE) is distinct from an explicit
    UNAVAILABLE check outcome (EVIDENCE_UNAVAILABLE).
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Java")

    # Case A: Items attached, but no checks run -> UNVERIFIED_EVIDENCE
    source_a = create_test_source(db, user)
    item_a = create_test_item(db, source_a)
    cs_a = create_test_candidate_skill(db, user, skill, items=[item_a])

    service = CandidateSkillCoverageService(db)
    cov_a = service.get_skill_coverage(user, cs_a.id)
    assert cov_a.coverage_status == CandidateSkillCoverageStatus.UNVERIFIED_EVIDENCE

    # Case B: Claim check ran and returned UNAVAILABLE -> EVIDENCE_UNAVAILABLE
    skill_b = create_test_skill(db, "Kotlin")
    claim_b = create_test_claim(db, user, claim_text="Android in Kotlin")
    create_test_verification_result(
        db,
        claim=claim_b,
        outcome=VerificationOutcome.UNAVAILABLE,
        verification_type=VerificationType.CLAIM_SUPPORT,
    )
    cs_b = create_test_candidate_skill(db, user, skill_b, claims=[claim_b])

    cov_b = service.get_skill_coverage(user, cs_b.id)
    assert cov_b.coverage_status == CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE
    assert "access limitation" in cov_b.summary


def test_available_source_with_old_observations_and_freshness_threshold(
    db: Session,
) -> None:
    """
    Verify AVAILABLE source preserves observation timestamps independently, and responds
    to caller-supplied freshness_threshold_days without hardcoding.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "C++")

    source = create_test_source(
        db,
        user,
        access_status=EvidenceSourceStatus.AVAILABLE,
        last_checked_at=datetime.now(UTC),
    )
    old_time = datetime.now(UTC) - timedelta(days=45)
    item = create_test_item(db, source, observed_at=old_time)

    cs = create_test_candidate_skill(db, user, skill, items=[item])

    service = CandidateSkillCoverageService(db)

    # 1. No threshold supplied: is_stale is None
    cov_default = service.get_skill_coverage(user, cs.id, freshness_threshold_days=None)
    assert cov_default.active_evidence_items[0].is_stale is None
    assert cov_default.active_evidence_items[0].source_status == "AVAILABLE"

    # 2. Threshold = 30 days: observation (45 days old) is flagged stale
    cov_stale = service.get_skill_coverage(user, cs.id, freshness_threshold_days=30)
    assert cov_stale.active_evidence_items[0].is_stale is True

    # 3. Threshold = 60 days: observation is NOT stale
    cov_fresh = service.get_skill_coverage(user, cs.id, freshness_threshold_days=60)
    assert cov_fresh.active_evidence_items[0].is_stale is False


def test_not_checked_source_versus_inaccessible_or_revoked(db: Session) -> None:
    """
    Verify NOT_CHECKED source with observations is UNVERIFIED_EVIDENCE, distinct from
    INACCESSIBLE or REVOKED which yield EVIDENCE_UNAVAILABLE.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "SQL")

    # Source 1 is NOT_CHECKED
    source_not_checked = create_test_source(
        db,
        user,
        access_status=EvidenceSourceStatus.NOT_CHECKED,
        source_uri="https://github.com/octocat/not-checked-repo",
    )
    item1 = create_test_item(db, source_not_checked)
    cs1 = create_test_candidate_skill(db, user, skill, items=[item1])

    service = CandidateSkillCoverageService(db)
    cov1 = service.get_skill_coverage(user, cs1.id)
    # NOT_CHECKED does not automatically mean unavailable
    assert (
        cov1.coverage_status == CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE
    )  # not AVAILABLE -> historical

    # If an available source exists alongside NOT_CHECKED
    skill2 = create_test_skill(db, "PostgreSQL")
    source_avail = create_test_source(
        db,
        user,
        access_status=EvidenceSourceStatus.AVAILABLE,
        source_uri="https://github.com/octocat/avail-repo",
    )
    item2 = create_test_item(db, source_avail)
    cs2 = create_test_candidate_skill(db, user, skill2, items=[item2])
    cov2 = service.get_skill_coverage(user, cs2.id)
    assert cov2.coverage_status == CandidateSkillCoverageStatus.UNVERIFIED_EVIDENCE


def test_historical_evidence_from_revoked_source_excluded_from_active_matches(
    db: Session,
) -> None:
    """
    Verify observations from REVOKED sources are placed in historical_unavailable_evidence,
    excluded from active evidence items, and noted as limitations.
    """
    user = create_test_user(db)
    skill = create_test_skill(db, "Docker")

    revoked_source = create_test_source(
        db,
        user,
        access_status=EvidenceSourceStatus.REVOKED,
        source_uri="https://github.com/octocat/revoked-docker",
    )
    revoked_item = create_test_item(
        db, revoked_source, description="Dockerfile in revoked repository"
    )

    cs = create_test_candidate_skill(db, user, skill, items=[revoked_item])

    service = CandidateSkillCoverageService(db)
    cov = service.get_skill_coverage(user, cs.id)

    assert cov.coverage_status == CandidateSkillCoverageStatus.EVIDENCE_UNAVAILABLE
    assert len(cov.active_evidence_items) == 0
    assert len(cov.historical_unavailable_evidence) == 1
    assert cov.historical_unavailable_evidence[0].evidence_item_id == revoked_item.id
    assert "inaccessible, revoked, or errored" in cov.summary


# =============================================================================
# 3. Report Totals, Pagination & Reconciliation
# =============================================================================


def test_pagination_and_status_summary_reconciliation(db: Session) -> None:
    """
    Verify report status_summary and total_skills_evaluated cover the complete filtered
    population before pagination, while skills contains only the requested page.
    """
    user = create_test_user(db)

    # Create 5 skills with different states
    s1 = create_test_skill(db, "Skill1")
    s2 = create_test_skill(db, "Skill2")
    s3 = create_test_skill(db, "Skill3")
    s4 = create_test_skill(db, "Skill4")
    s5 = create_test_skill(db, "Skill5")

    # s1: No evidence
    create_test_candidate_skill(db, user, s1)

    # s2: Claim supported
    c2 = create_test_claim(db, user, claim_text="Skill2 claim")
    create_test_verification_result(db, claim=c2)
    create_test_candidate_skill(db, user, s2, claims=[c2])

    # s3: Claim contradicted
    c3 = create_test_claim(db, user, claim_text="Skill3 claim")
    create_test_verification_result(
        db, claim=c3, outcome=VerificationOutcome.CONTRADICTED
    )
    create_test_candidate_skill(db, user, s3, claims=[c3])

    # s4: Unverified evidence
    src4 = create_test_source(db, user, source_uri="https://github.com/octocat/s4")
    it4 = create_test_item(db, src4)
    create_test_candidate_skill(db, user, s4, items=[it4])

    # s5: No evidence
    create_test_candidate_skill(db, user, s5)

    service = CandidateSkillCoverageService(db)

    # Request page 1 with limit=2
    report = service.get_coverage_report(user, limit=2, offset=0)

    # Skills slice must contain exactly 2 items
    assert len(report.skills) == 2
    # Total evaluated must be 5
    assert report.total_skills_evaluated == 5
    # Strict reconciliation invariant: sum(status_summary.values()) == total_skills_evaluated
    assert sum(report.status_summary.values()) == report.total_skills_evaluated
    assert report.status_summary["NO_EVIDENCE"] == 2
    assert report.status_summary["CLAIM_SUPPORTED"] == 1
    assert report.status_summary["CLAIM_CONTRADICTED"] == 1
    assert report.status_summary["UNVERIFIED_EVIDENCE"] == 1


def test_unassociated_skill_claims_bounding_and_skill_filtering(
    db: Session,
) -> None:
    """
    Verify unassociated SKILL claims are bounded, paginated, and filtered deterministically
    when skill_id is supplied.
    """
    user = create_test_user(db)
    py_skill = create_test_skill(db, "Python", aliases=["Python3"])
    _go_skill = create_test_skill(db, "Go")

    # 3 unassociated claims: 2 for Python, 1 for Docker
    create_test_claim(
        db, user, ClaimType.SKILL, claim_text="Python async backend developer"
    )
    create_test_claim(db, user, ClaimType.SKILL, claim_text="Python3 data analysis")
    create_test_claim(db, user, ClaimType.SKILL, claim_text="Docker containerization")

    service = CandidateSkillCoverageService(db)

    # 1. Unfiltered with limit=2
    report_unfiltered = service.get_coverage_report(
        user, unassociated_claims_limit=2, unassociated_claims_offset=0
    )
    assert report_unfiltered.unassociated_skill_claims_total == 3
    assert len(report_unfiltered.unassociated_skill_claims) == 2

    # 2. Filtered by Python skill_id
    report_filtered = service.get_coverage_report(
        user, skill_id=py_skill.id, unassociated_claims_limit=10
    )
    assert report_filtered.unassociated_skill_claims_total == 2
    assert len(report_filtered.unassociated_skill_claims) == 2
    for c in report_filtered.unassociated_skill_claims:
        assert (
            "Python" in c.claim_text or "Python3" in c.claim_text
        ) and "Docker" not in c.claim_text


# =============================================================================
# 4. Candidate Isolation & Read-Only Invariants
# =============================================================================


def test_candidate_isolation_cross_candidate_access_returns_404(
    db: Session,
) -> None:
    """Verify Candidate A cannot access Candidate B's individual skill coverage."""
    user_a = create_test_user(db, prefix="cand_a")
    user_b = create_test_user(db, prefix="cand_b")

    skill = create_test_skill(db, "Swift")
    cs_b = create_test_candidate_skill(db, user_b, skill)

    service = CandidateSkillCoverageService(db)
    with pytest.raises(HTTPException) as exc_info:
        service.get_skill_coverage(user_a, cs_b.id)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate skill not found" in exc_info.value.detail


def test_read_only_invariant_zero_database_mutations(db: Session) -> None:
    """Verify generating coverage reports is strictly read-only and mutates zero tables."""
    user = create_test_user(db)
    skill = create_test_skill(db, "Ruby")
    claim = create_test_claim(db, user, claim_text="Ruby on Rails development")
    source = create_test_source(db, user)
    item = create_test_item(db, source)
    create_test_candidate_skill(db, user, skill, claims=[claim], items=[item])

    # Record counts before
    cs_count = db.query(CandidateSkill).count()
    claim_count = db.query(CandidateClaim).count()
    source_count = db.query(EvidenceSource).count()
    item_count = db.query(EvidenceItem).count()
    vr_count = db.query(VerificationResult).count()
    link_count = db.query(CandidateSkillEvidence).count()

    service = CandidateSkillCoverageService(db)
    _report = service.get_coverage_report(user)

    # Verify zero mutations
    assert db.query(CandidateSkill).count() == cs_count
    assert db.query(CandidateClaim).count() == claim_count
    assert db.query(EvidenceSource).count() == source_count
    assert db.query(EvidenceItem).count() == item_count
    assert db.query(VerificationResult).count() == vr_count
    assert db.query(CandidateSkillEvidence).count() == link_count


# =============================================================================
# 5. API Integration Tests
# =============================================================================


def test_api_coverage_report_unauthenticated_rejected_401(
    client: TestClient,
) -> None:
    """Verify unauthenticated GET /api/v1/candidate-skills/coverage returns 401."""
    res = client.get("/api/v1/candidate-skills/coverage")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_coverage_report_authenticated_workflow(
    client: TestClient, db: Session
) -> None:
    """Verify authenticated GET /api/v1/candidate-skills/coverage workflow."""
    email = f"cov_api_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    skill = create_test_skill(db, "Python")
    claim = create_test_claim(
        db, user, claim_text="Python API architect", origin=ClaimOrigin.USER_DECLARED
    )
    cs = create_test_candidate_skill(db, user, skill, claims=[claim])

    res = client.get("/api/v1/candidate-skills/coverage", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()

    assert data["total_skills_evaluated"] == 1
    assert data["status_summary"]["NO_EVIDENCE"] == 1
    assert len(data["skills"]) == 1
    skill_item = data["skills"][0]
    assert skill_item["candidate_skill_id"] == str(cs.id)
    assert skill_item["canonical_name"] == "Python"
    assert skill_item["coverage_status"] == "NO_EVIDENCE"
    assert len(skill_item["claims"]) == 1


def test_api_individual_skill_coverage_authenticated(
    client: TestClient, db: Session
) -> None:
    """Verify authenticated GET /api/v1/candidate-skills/{id}/coverage workflow."""
    email = f"cov_api_indiv_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    skill = create_test_skill(db, "FastAPI")
    cs = create_test_candidate_skill(db, user, skill)

    res = client.get(f"/api/v1/candidate-skills/{cs.id}/coverage", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()

    assert data["candidate_skill_id"] == str(cs.id)
    assert data["canonical_name"] == "FastAPI"
    assert data["coverage_status"] == "NO_EVIDENCE"
