import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.candidate_target import CandidateTarget
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
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
from app.schemas.candidate_target import CandidateTargetCreate
from app.schemas.role_gap_analysis import GapAnalysisStatus
from app.services.candidate_service import CandidateService
from app.services.role_gap_analysis_service import RoleGapAnalysisService


def create_test_user(db: Session, email_prefix: str = "gap_user") -> User:
    """Create a unique test user in the database."""
    unique_email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@nextround.in"
    user = User(
        email=unique_email,
        hashed_password="hashed_test_password",
        name="Gap Analysis Candidate",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_target(
    db: Session, user: User, role_title: str = "Senior Backend Engineer"
) -> CandidateTarget:
    """Create and return a candidate target for the user."""
    candidate_service = CandidateService(db)
    candidate_service.get_or_create_profile(user)
    dto = candidate_service.create_target(
        user,
        CandidateTargetCreate(
            role_title=role_title,
            company="Acme Corp",
            job_description="Backend Python role requiring databases and cloud infrastructure.",
            is_active=True,
        ),
    )
    return db.query(CandidateTarget).filter(CandidateTarget.id == dto.id).one()


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Register/login user and return Bearer auth headers."""
    register_payload = {
        "email": email,
        "password": "Password123!",
        "name": "API Candidate",
    }
    client.post("/api/v1/auth/register", json=register_payload)

    login_res = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "Password123!"},
    )
    assert login_res.status_code == status.HTTP_200_OK
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Classification & Status Tests
# =============================================================================


def test_gap_analysis_unresolved_unmapped_requirement(db: Session) -> None:
    """Verify requirements with skill_id=None are classified as UNRESOLVED_UNMAPPED."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=None,
        requirement_text="5+ years working in agile distributed teams",
        requirement_type=RequirementType.EXPERIENCE,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.requirement_id == req.id
    assert item.status == GapAnalysisStatus.UNRESOLVED_UNMAPPED
    assert item.skill_id is None
    assert item.canonical_skill_name is None
    assert "not mapped" in item.explanation.lower()
    assert report.status_summary[GapAnalysisStatus.UNRESOLVED_UNMAPPED.value] == 1


def test_gap_analysis_missing_recorded_coverage(db: Session) -> None:
    """Verify mapped requirements with no candidate claim or skill association are MISSING_RECORDED_COVERAGE."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Rust", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Hands-on experience with Rust systems programming",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.PREFERRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.status == GapAnalysisStatus.MISSING_RECORDED_COVERAGE
    assert item.skill_id == skill.id
    assert item.canonical_skill_name == "Rust"
    assert "no candidate claim, skill association" in item.explanation.lower()
    assert report.status_summary[GapAnalysisStatus.MISSING_RECORDED_COVERAGE.value] == 1


def test_gap_analysis_association_with_no_claims_or_evidence(db: Session) -> None:
    """Verify a CandidateSkill association with empty evidence_links is EVIDENCE_GAP."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Scala", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Scala programming experience",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.status == GapAnalysisStatus.EVIDENCE_GAP
    assert (
        "no supporting claims or evidence items are linked" in item.explanation.lower()
    )


def test_gap_analysis_evidence_gap_claim_without_evidence(db: Session) -> None:
    """Verify skills with self-declared claims but no external evidence items or checks are EVIDENCE_GAP."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Python", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Proficiency in Python programming",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="Proficient in Python",
        origin=ClaimOrigin.USER_DECLARED,
    )
    db.add(claim)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.status == GapAnalysisStatus.EVIDENCE_GAP
    assert (
        "self-declared claim exists, but no external evidence"
        in item.explanation.lower()
    )
    assert item.supporting_records.candidate_skill_id == cand_skill.id
    assert item.supporting_records.candidate_claim_ids == [claim.id]
    assert item.supporting_records.evidence_item_ids == []
    assert report.status_summary[GapAnalysisStatus.EVIDENCE_GAP.value] == 1


def test_gap_analysis_unavailable_evidence_inaccessible_source(
    db: Session,
) -> None:
    """Verify skills with inaccessible/revoked sources and no available alternative are UNAVAILABLE_EVIDENCE."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Go", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Experience in Go microservices",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/private-go-repo",
        access_mode=AccessMode.AUTHORIZED,
        access_status=EvidenceSourceStatus.INACCESSIBLE,
    )
    db.add(source)
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Go repository metadata",
    )
    db.add(item)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    assert report.requirements[0].status == GapAnalysisStatus.UNAVAILABLE_EVIDENCE
    assert "inaccessible" in report.requirements[0].explanation.lower()


def test_gap_analysis_inconclusive_verification(db: Session) -> None:
    """Verify skills with INCONCLUSIVE check outcomes are classified as INCONCLUSIVE_VERIFICATION."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Kubernetes", category="DevOps", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Hands-on Kubernetes cluster management",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.PREFERRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/k8s-infra",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Kubernetes manifests",
    )
    db.add(item)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="Kubernetes experience",
        origin=ClaimOrigin.USER_DECLARED,
    )
    db.add(claim)
    db.commit()

    vr = VerificationResult(
        candidate_claim_id=claim.id,
        evidence_source_id=source.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.INCONCLUSIVE,
        method_version="k8s_manifest_check_v1",
        explanation="Repository contains generic Helm charts with minimal commit history.",
    )
    db.add(vr)
    db.commit()

    link_claim = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    db.add(link_claim)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    assert item_res.status == GapAnalysisStatus.INCONCLUSIVE_VERIFICATION
    assert "inconclusive" in item_res.explanation.lower()
    assert "k8s_manifest_check_v1" in item_res.explanation


def test_gap_analysis_contradicted_verification_and_chronology(db: Session) -> None:
    """
    Verify:
    1. CONTRADICTED verification result produces CONTRADICTED_VERIFICATION status.
    2. An older SUPPORTED result does NOT override a newer CONTRADICTED result for the same scope.
    """
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Java", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="5+ years Java enterprise development",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="5+ years Java",
        origin=ClaimOrigin.USER_DECLARED,
    )
    db.add(claim)
    db.commit()

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/java-service",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()

    now = datetime.now(UTC)

    # Older check at T-10 days: SUPPORTED
    vr_old = VerificationResult(
        candidate_claim_id=claim.id,
        evidence_source_id=source.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="java_static_check_v1",
        explanation="Initial shallow check found Java files.",
        checked_at=now - timedelta(days=10),
    )
    # Newer check at T-1 day: CONTRADICTED (deep authorship analysis revealed third-party code)
    vr_new = VerificationResult(
        candidate_claim_id=claim.id,
        evidence_source_id=source.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.CONTRADICTED,
        method_version="java_authorship_check_v2",
        explanation="Deep git analysis confirmed 0% author commits to Java sources.",
        checked_at=now - timedelta(days=1),
    )
    db.add_all([vr_old, vr_new])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    # Older SUPPORTED must NOT override newer CONTRADICTED!
    assert item_res.status == GapAnalysisStatus.CONTRADICTED_VERIFICATION
    assert "contradicted" in item_res.explanation.lower()
    assert "java_authorship_check_v2" in item_res.explanation
    # Both IDs preserved for historical auditability
    assert vr_old.id in item_res.supporting_records.verification_result_ids
    assert vr_new.id in item_res.supporting_records.verification_result_ids


def test_gap_analysis_unrelated_supported_does_not_override_contradicted_or_inconclusive(
    db: Session,
) -> None:
    """Verify an unrelated supported result on one scope does not override a contradicted or inconclusive scope."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="C++", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="C++ systems engineering",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Claim 1: Contradicted
    claim1 = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="10 years C++ kernel development",
        origin=ClaimOrigin.USER_DECLARED,
    )
    # Source 2: Supported
    source2 = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/cpp-sandbox",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([claim1, source2])
    db.commit()

    item2 = EvidenceItem(
        evidence_source_id=source2.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="C++ test file",
    )
    db.add(item2)
    db.commit()

    vr_contradicted = VerificationResult(
        candidate_claim_id=claim1.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.CONTRADICTED,
        method_version="claim_timeline_validator_v1",
        explanation="Candidate career history contradicts 10 years experience claim.",
    )
    vr_supported = VerificationResult(
        evidence_source_id=source2.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="repo_validator_v1",
        explanation="C++ repository exists and is public.",
    )
    db.add_all([vr_contradicted, vr_supported])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim1.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item2.id
    )
    db.add_all([link1, link2])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    # Supported source must NOT erase contradicted claim; reported as MIXED_VERIFICATION with per-scope outcomes
    assert report.total_requirements == 1
    req_item = report.requirements[0]
    assert req_item.status == GapAnalysisStatus.MIXED_VERIFICATION
    assert "mixed" in req_item.explanation.lower()
    assert len(req_item.scope_outcomes) == 2
    claim_outcome = next(
        so for so in req_item.scope_outcomes if so.scope_type == "claim"
    )
    assert claim_outcome.latest_outcome == VerificationOutcome.CONTRADICTED
    assert claim_outcome.verification_result_id == vr_contradicted.id
    source_outcome = next(
        so for so in req_item.scope_outcomes if so.scope_type == "source"
    )
    assert source_outcome.latest_outcome == VerificationOutcome.SUPPORTED
    assert source_outcome.verification_result_id == vr_supported.id


def test_gap_analysis_assessment_evidence_without_verification_not_supported(
    db: Session,
) -> None:
    """
    Verify the mere presence of an ASSESSMENT_RESULT EvidenceItem without a SUPPORTED verification check
    is classified as ASSESSMENT_PENDING_VERIFICATION rather than missing or supported.
    """
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="AWS", category="Cloud", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="AWS Certified Solutions Architect examination",
        requirement_type=RequirementType.QUALIFICATION,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.ASSESSMENT,
        source_uri="internal://assessments/aws-arch",
        access_mode=AccessMode.INTERNAL,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()

    # Observation exists, but NO verification check has evaluated it
    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.ASSESSMENT_RESULT,
        description="Assessment attempt submission",
        observed_data={"score": 85},  # Raw data does not imply verified competence
    )
    db.add(item)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    # Must NOT be SUPPORTED_EVIDENCE or MISSING_ASSESSMENT_EVIDENCE
    assert item_res.status == GapAnalysisStatus.ASSESSMENT_PENDING_VERIFICATION
    assert (
        "assessment evidence record is present, but no verification check has verified demonstrated competence"
        in item_res.explanation.lower()
    )


def test_gap_analysis_mixed_evidence_preserves_independently_available_source(
    db: Session,
) -> None:
    """
    Verify that if Source A is INACCESSIBLE, but Source B is AVAILABLE and verified as SUPPORTED,
    the independently available evidence is preserved rather than marking the whole requirement UNAVAILABLE.
    """
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="PostgreSQL", category="Database", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="PostgreSQL database query tuning",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Source 1: Inaccessible legacy repo
    source_inaccessible = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/old-private-repo",
        access_mode=AccessMode.AUTHORIZED,
        access_status=EvidenceSourceStatus.INACCESSIBLE,
    )
    # Source 2: Available public repo with verified SQL code
    source_available = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/public-pg-service",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([source_inaccessible, source_available])
    db.commit()

    item_inaccessible = EvidenceItem(
        evidence_source_id=source_inaccessible.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Inaccessible metadata",
    )
    item_available = EvidenceItem(
        evidence_source_id=source_available.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="PostgreSQL schema migrations and indexes",
    )
    db.add_all([item_inaccessible, item_available])
    db.commit()

    vr_supported = VerificationResult(
        evidence_source_id=source_available.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="pg_migration_validator_v1",
        explanation="Validated production PostgreSQL schema definitions.",
    )
    db.add(vr_supported)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item_inaccessible.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item_available.id
    )
    db.add_all([link1, link2])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    # Independently available evidence is preserved as SUPPORTED_EVIDENCE
    assert item_res.status == GapAnalysisStatus.SUPPORTED_EVIDENCE
    assert "pg_migration_validator_v1" in item_res.explanation
    # Inaccessible source is explicitly documented in the note
    assert "1 linked source was inaccessible/unavailable" in item_res.explanation


def test_gap_analysis_supported_evidence_via_code_and_assessment(
    db: Session,
) -> None:
    """Verify SUPPORTED verification outcomes on code artifacts and assessment checks."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill_py = Skill(canonical_name="Python", category="Language", aliases=[])
    skill_sql = Skill(canonical_name="SQL", category="Database", aliases=[])
    db.add_all([skill_py, skill_sql])
    db.commit()

    # Requirement 1: Python (supported via verified code artifact)
    req_py = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill_py.id,
        requirement_text="Strong Python engineering experience",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    # Requirement 2: SQL (supported via verified assessment check)
    req_sql = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill_sql.id,
        requirement_text="SQL assessment certification",
        requirement_type=RequirementType.QUALIFICATION,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add_all([req_py, req_sql])
    db.commit()

    # Setup Python supported code artifact
    source_gh = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/backend-api",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source_gh)
    db.commit()

    item_py = EvidenceItem(
        evidence_source_id=source_gh.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="FastAPI service endpoints",
    )
    db.add(item_py)
    db.commit()

    claim_py = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="Python API development",
        origin=ClaimOrigin.USER_DECLARED,
    )
    db.add(claim_py)
    db.commit()

    vr_py = VerificationResult(
        candidate_claim_id=claim_py.id,
        evidence_source_id=source_gh.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="ast_import_scanner_v1",
        explanation="Repository contains multiple validated Python modules with author commits.",
    )
    db.add(vr_py)
    db.commit()

    cand_skill_py = CandidateSkill(user_id=user.id, skill_id=skill_py.id)
    db.add(cand_skill_py)
    db.commit()

    link_py_claim = CandidateSkillEvidence(
        candidate_skill_id=cand_skill_py.id, candidate_claim_id=claim_py.id
    )
    link_py_item = CandidateSkillEvidence(
        candidate_skill_id=cand_skill_py.id, evidence_item_id=item_py.id
    )
    db.add_all([link_py_claim, link_py_item])
    db.commit()

    # Setup SQL verified assessment result
    source_assess = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.ASSESSMENT,
        source_uri="internal://assessments/sql-intermediate-2026",
        access_mode=AccessMode.INTERNAL,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source_assess)
    db.commit()

    item_sql = EvidenceItem(
        evidence_source_id=source_assess.id,
        evidence_type=EvidenceType.ASSESSMENT_RESULT,
        description="SQL indexing and query optimization evaluation",
    )
    db.add(item_sql)
    db.commit()

    vr_sql = VerificationResult(
        evidence_source_id=source_assess.id,
        verification_type=VerificationType.ASSESSMENT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="sql_assessment_evaluator_v1",
        explanation="Candidate scored above mastery threshold on SQL query optimization benchmarks.",
    )
    db.add(vr_sql)
    db.commit()

    cand_skill_sql = CandidateSkill(user_id=user.id, skill_id=skill_sql.id)
    db.add(cand_skill_sql)
    db.commit()

    link_sql = CandidateSkillEvidence(
        candidate_skill_id=cand_skill_sql.id, evidence_item_id=item_sql.id
    )
    db.add(link_sql)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 2

    py_res = next(r for r in report.requirements if r.requirement_id == req_py.id)
    assert py_res.status == GapAnalysisStatus.SUPPORTED_EVIDENCE
    assert "ast_import_scanner_v1" in py_res.explanation
    assert vr_py.id in py_res.supporting_records.verification_result_ids

    sql_res = next(r for r in report.requirements if r.requirement_id == req_sql.id)
    assert sql_res.status == GapAnalysisStatus.SUPPORTED_EVIDENCE
    assert "sql_assessment_evaluator_v1" in sql_res.explanation
    assert vr_sql.id in sql_res.supporting_records.verification_result_ids

    assert report.status_summary[GapAnalysisStatus.SUPPORTED_EVIDENCE.value] == 2


def test_gap_analysis_empty_candidate_skill_evidence_links(db: Session) -> None:
    """Verify CandidateSkill with empty evidence_links list is classified as EVIDENCE_GAP."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Rust", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Rust systems programming",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.status == GapAnalysisStatus.EVIDENCE_GAP
    assert (
        "no supporting claims or evidence items are linked" in item.explanation.lower()
    )
    assert item.supporting_records.candidate_skill_id == cand_skill.id
    assert item.supporting_records.candidate_claim_ids == []
    assert item.supporting_records.evidence_item_ids == []
    assert item.scope_outcomes == []


def test_gap_analysis_unverified_general_evidence_item(db: Session) -> None:
    """Verify unverified repository/code evidence is classified as UNVERIFIED_EVIDENCE."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Redis", category="Database", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Redis caching architecture",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/redis-cache",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Redis cache wrapper implementation",
    )
    db.add(item)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    assert item_res.status == GapAnalysisStatus.UNVERIFIED_EVIDENCE
    assert (
        "no verification check has evaluated demonstrated competence"
        in item_res.explanation.lower()
    )
    assert item_res.supporting_records.evidence_item_ids == [item.id]
    assert item_res.scope_outcomes == []


def test_gap_analysis_missing_assessment_evidence_when_demanded(db: Session) -> None:
    """Verify requirement demanding qualification without assessment item is MISSING_ASSESSMENT_EVIDENCE."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Kubernetes", category="DevOps", aliases=[])
    db.add(skill)
    db.commit()

    # Requirement demands certified qualification
    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="CKA Certified Kubernetes Administrator certification",
        requirement_type=RequirementType.QUALIFICATION,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Candidate has general repo evidence, but NO assessment evidence
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/k8s-homelab",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Kubernetes manifests",
    )
    db.add(item)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    assert item_res.status == GapAnalysisStatus.MISSING_ASSESSMENT_EVIDENCE
    assert "no assessment evidence record is linked" in item_res.explanation.lower()


def test_gap_analysis_mixed_verification_inconclusive_and_supported(
    db: Session,
) -> None:
    """Verify supported scope alongside inconclusive scope produces MIXED_VERIFICATION."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="TypeScript", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Fullstack TypeScript development",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="5 years TypeScript",
        origin=ClaimOrigin.USER_DECLARED,
    )
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/ts-app",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([claim, source])
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="TypeScript application code",
    )
    db.add(item)
    db.commit()

    # Scope 1 (claim): INCONCLUSIVE
    vr_claim = VerificationResult(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.INCONCLUSIVE,
        method_version="ts_claim_checker_v1",
        explanation="Repository commit history is inconclusive regarding 5 years claim.",
    )
    # Scope 2 (source): SUPPORTED
    vr_source = VerificationResult(
        evidence_source_id=source.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="repo_checker_v1",
        explanation="Repository is accessible and valid TypeScript project.",
    )
    db.add_all([vr_claim, vr_source])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add_all([link1, link2])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    assert item_res.status == GapAnalysisStatus.MIXED_VERIFICATION
    assert "mixed" in item_res.explanation.lower()
    assert len(item_res.scope_outcomes) == 2


def test_gap_analysis_supported_inconclusive_unavailable_across_scopes(
    db: Session,
) -> None:
    """Verify SUPPORTED + INCONCLUSIVE + UNAVAILABLE across distinct scopes produces MIXED_VERIFICATION."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Golang", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Production Golang microservices",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Scope 1 (source): SUPPORTED
    source1 = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/go-service",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    # Scope 2 (claim): INCONCLUSIVE
    claim2 = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="Lead Go architect",
        origin=ClaimOrigin.USER_DECLARED,
    )
    # Scope 3 (source): UNAVAILABLE
    source3 = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/go-legacy",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([source1, claim2, source3])
    db.commit()

    item1 = EvidenceItem(
        evidence_source_id=source1.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Go main entrypoint",
    )
    item3 = EvidenceItem(
        evidence_source_id=source3.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Legacy Go code",
    )
    db.add_all([item1, item3])
    db.commit()

    vr1 = VerificationResult(
        evidence_source_id=source1.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="go_repo_scanner_v1",
        explanation="Repository is valid and contains verified Go service architecture.",
    )
    vr2 = VerificationResult(
        candidate_claim_id=claim2.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.INCONCLUSIVE,
        method_version="go_claim_scanner_v1",
        explanation="Commit history shows contributor status but leadership claim is inconclusive.",
    )
    vr3 = VerificationResult(
        evidence_source_id=source3.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.UNAVAILABLE,
        method_version="go_repo_scanner_v1",
        explanation="Upstream rate limits prevented full repository verification.",
    )
    db.add_all([vr1, vr2, vr3])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item1.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim2.id
    )
    link3 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item3.id
    )
    db.add_all([link1, link2, link3])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item = report.requirements[0]
    assert item.status == GapAnalysisStatus.MIXED_VERIFICATION
    assert "mixed" in item.explanation.lower()
    assert "1 linked scope was unavailable" in item.explanation
    assert len(item.scope_outcomes) == 3

    so1 = next(so for so in item.scope_outcomes if so.scope_id == source1.id)
    assert so1.scope_type == "source"
    assert so1.latest_outcome == VerificationOutcome.SUPPORTED
    assert so1.verification_result_id == vr1.id

    so2 = next(so for so in item.scope_outcomes if so.scope_id == claim2.id)
    assert so2.scope_type == "claim"
    assert so2.latest_outcome == VerificationOutcome.INCONCLUSIVE
    assert so2.verification_result_id == vr2.id

    so3 = next(so for so in item.scope_outcomes if so.scope_id == source3.id)
    assert so3.scope_type == "source"
    assert so3.latest_outcome == VerificationOutcome.UNAVAILABLE
    assert so3.verification_result_id == vr3.id


def test_gap_analysis_contradicted_and_unavailable_across_scopes(
    db: Session,
) -> None:
    """Verify CONTRADICTED + UNAVAILABLE across distinct scopes produces CONTRADICTED_VERIFICATION."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="C++", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Advanced C++ memory management",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="Author of production C++ memory allocator",
        origin=ClaimOrigin.USER_DECLARED,
    )
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/cpp-allocator",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([claim, source])
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="C++ allocator source",
    )
    db.add(item)
    db.commit()

    # Scope 1 (claim): CONTRADICTED
    vr_claim = VerificationResult(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.CONTRADICTED,
        method_version="cpp_allocator_checker_v1",
        explanation="Code authorship analysis revealed the allocator was forked verbatim from an open-source library.",
    )
    # Scope 2 (source): UNAVAILABLE
    vr_source = VerificationResult(
        evidence_source_id=source.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.UNAVAILABLE,
        method_version="git_source_probe_v1",
        explanation="Repository endpoint timed out during verification.",
    )
    db.add_all([vr_claim, vr_source])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add_all([link1, link2])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    assert item_res.status == GapAnalysisStatus.CONTRADICTED_VERIFICATION
    assert "contradicted" in item_res.explanation.lower()
    assert "1 linked scope was unavailable" in item_res.explanation
    assert len(item_res.scope_outcomes) == 2

    so_claim = next(so for so in item_res.scope_outcomes if so.scope_type == "claim")
    assert so_claim.latest_outcome == VerificationOutcome.CONTRADICTED
    assert so_claim.verification_result_id == vr_claim.id

    so_source = next(so for so in item_res.scope_outcomes if so.scope_type == "source")
    assert so_source.latest_outcome == VerificationOutcome.UNAVAILABLE
    assert so_source.verification_result_id == vr_source.id


def test_gap_analysis_all_sources_unavailable_with_historical_verification(
    db: Session,
) -> None:
    """Verify UNAVAILABLE_EVIDENCE when all sources are currently unavailable despite historical SUPPORTED checks."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Scala", category="Language", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Scala Akka actor systems",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Source was verified in the past, but is now REVOKED / INACCESSIBLE
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/candidate/scala-actors-private",
        access_mode=AccessMode.AUTHORIZED,
        access_status=EvidenceSourceStatus.REVOKED,
    )
    db.add(source)
    db.commit()

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Akka actor system implementation",
    )
    db.add(item)
    db.commit()

    # Historical verification check was SUPPORTED when access was available
    vr_historical = VerificationResult(
        evidence_source_id=source.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="scala_actor_verifier_v1",
        explanation="Previously verified Akka actor definitions and message passing protocols.",
        checked_at=datetime.now(UTC) - timedelta(days=30),
    )
    db.add(vr_historical)
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item.id
    )
    db.add(link)
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    # Inaccessible/revoked sources must produce UNAVAILABLE_EVIDENCE, not SUPPORTED_EVIDENCE
    assert item_res.status == GapAnalysisStatus.UNAVAILABLE_EVIDENCE
    assert (
        "inaccessible or revoked despite historical verification results"
        in item_res.explanation.lower()
    )
    # Historical record IDs are preserved for auditability
    assert vr_historical.id in item_res.supporting_records.verification_result_ids
    assert len(item_res.scope_outcomes) == 1
    assert item_res.scope_outcomes[0].latest_outcome == VerificationOutcome.SUPPORTED


def test_gap_analysis_supported_assessment_alongside_unrelated_contradicted_claim(
    db: Session,
) -> None:
    """Verify an explicitly supported assessment check alongside an unrelated contradictory claim produces MIXED_VERIFICATION."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="AWS Cloud Architecture", category="Cloud", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Demonstrated cloud architecture skills",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)

    # Scope 1: Contradicted self-declared claim ("15 years cloud architect")
    claim = CandidateClaim(
        user_id=user.id,
        claim_type=ClaimType.SKILL,
        claim_text="15 years AWS Cloud Solutions Architect",
        origin=ClaimOrigin.USER_DECLARED,
    )
    # Scope 2: Assessment source with verified passing benchmark
    source_assess = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.ASSESSMENT,
        source_uri="internal://assessments/aws-pro-architect-2026",
        access_mode=AccessMode.INTERNAL,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add_all([claim, source_assess])
    db.commit()

    item_assess = EvidenceItem(
        evidence_source_id=source_assess.id,
        evidence_type=EvidenceType.ASSESSMENT_RESULT,
        description="Proctor-verified AWS cloud solutions architecture assessment",
    )
    db.add(item_assess)
    db.commit()

    vr_contradicted = VerificationResult(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.CONTRADICTED,
        method_version="career_timeline_check_v1",
        explanation="Candidate career history spans 6 years total; 15 years claim is contradictory.",
    )
    vr_assessment_supported = VerificationResult(
        evidence_source_id=source_assess.id,
        verification_type=VerificationType.ASSESSMENT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="aws_cloud_exam_evaluator_v1",
        explanation="Candidate achieved 94% on verified AWS architecture exam benchmarks.",
    )
    db.add_all([vr_contradicted, vr_assessment_supported])
    db.commit()

    cand_skill = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cand_skill)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, candidate_claim_id=claim.id
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cand_skill.id, evidence_item_id=item_assess.id
    )
    db.add_all([link1, link2])
    db.commit()

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)

    assert report.total_requirements == 1
    item_res = report.requirements[0]
    # Assessment is supported, but claim is contradicted -> MIXED_VERIFICATION
    assert item_res.status == GapAnalysisStatus.MIXED_VERIFICATION
    assert "mixed" in item_res.explanation.lower()
    assert len(item_res.scope_outcomes) == 2

    so_claim = next(so for so in item_res.scope_outcomes if so.scope_type == "claim")
    assert so_claim.latest_outcome == VerificationOutcome.CONTRADICTED
    assert so_claim.verification_result_id == vr_contradicted.id

    so_assess = next(so for so in item_res.scope_outcomes if so.scope_type == "source")
    assert so_assess.latest_outcome == VerificationOutcome.SUPPORTED
    assert so_assess.verification_result_id == vr_assessment_supported.id
    assert so_assess.method_version == "aws_cloud_exam_evaluator_v1"


# =============================================================================
# 2. Ownership, Isolation & Zero-Persistence Tests
# =============================================================================


def test_gap_analysis_target_ownership_enforcement(db: Session) -> None:
    """Verify gap analysis raises 404 for nonexistent target or target owned by another user."""
    user1 = create_test_user(db, email_prefix="cand1")
    user2 = create_test_user(db, email_prefix="cand2")

    target1 = create_test_target(db, user1)
    service = RoleGapAnalysisService(db)

    # 1. Unowned target returns 404
    with pytest.raises(HTTPException) as exc_info:
        service.analyze_target_gaps(user2, target1.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # 2. Non-existent target returns 404
    with pytest.raises(HTTPException) as exc_info:
        service.analyze_target_gaps(user1, uuid.uuid4())
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_gap_analysis_zero_persistence_guarantee(db: Session) -> None:
    """Verify running role-gap analysis creates zero database mutations or side-effects."""
    user = create_test_user(db)
    target = create_test_target(db, user)

    skill = Skill(canonical_name="Docker", category="DevOps", aliases=[])
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Experience containerizing applications with Docker",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()

    # Capture record counts before analysis
    counts_before = {
        "targets": db.query(CandidateTarget).count(),
        "requirements": db.query(RoleRequirement).count(),
        "skills": db.query(Skill).count(),
        "candidate_skills": db.query(CandidateSkill).count(),
        "claims": db.query(CandidateClaim).count(),
        "sources": db.query(EvidenceSource).count(),
        "items": db.query(EvidenceItem).count(),
        "verification_results": db.query(VerificationResult).count(),
    }

    service = RoleGapAnalysisService(db)
    report = service.analyze_target_gaps(user, target.id)
    assert report.total_requirements == 1

    # Verify counts after analysis remain identical
    counts_after = {
        "targets": db.query(CandidateTarget).count(),
        "requirements": db.query(RoleRequirement).count(),
        "skills": db.query(Skill).count(),
        "candidate_skills": db.query(CandidateSkill).count(),
        "claims": db.query(CandidateClaim).count(),
        "sources": db.query(EvidenceSource).count(),
        "items": db.query(EvidenceItem).count(),
        "verification_results": db.query(VerificationResult).count(),
    }

    assert counts_before == counts_after


# =============================================================================
# 3. API Endpoints Integration Tests
# =============================================================================


def test_api_gap_analysis_unauthenticated_rejected(client: TestClient) -> None:
    """Verify unauthenticated GET /candidate-targets/{id}/gap-analysis returns 401."""
    tid = uuid.uuid4()
    res_get = client.get(f"/api/v1/candidate-targets/{tid}/gap-analysis")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_gap_analysis_authenticated_workflow(
    client: TestClient, db: Session
) -> None:
    """Verify authenticated GET /candidate-targets/{id}/gap-analysis returns structured report."""
    email = f"api_gap_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    target = create_test_target(db, user, role_title="Principal Architect")

    skill = Skill(
        canonical_name="PostgreSQL", category="Database", aliases=["postgres"]
    )
    db.add(skill)
    db.commit()

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="PostgreSQL database query tuning",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()

    # GET endpoint test
    res_get = client.get(
        f"/api/v1/candidate-targets/{target.id}/gap-analysis",
        headers=headers,
    )
    assert res_get.status_code == status.HTTP_200_OK
    data_get = res_get.json()

    assert data_get["candidate_target_id"] == str(target.id)
    assert data_get["role_title"] == "Principal Architect"
    assert data_get["total_requirements"] == 1
    assert data_get["requirements"][0]["status"] == "MISSING_RECORDED_COVERAGE"
    assert data_get["requirements"][0]["canonical_skill_name"] == "PostgreSQL"
    assert "status_summary" in data_get
    assert data_get["status_summary"]["MISSING_RECORDED_COVERAGE"] == 1
