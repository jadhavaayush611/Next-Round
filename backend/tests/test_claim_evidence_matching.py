import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_skill import CandidateSkillEvidence
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.skill import Skill
from app.models.user import User
from app.models.verification_result import VerificationResult
from app.schemas.claim_evidence_match import (
    ClaimMatchStatus,
    MatchingBasis,
)
from app.services.claim_evidence_matching_service import (
    ClaimEvidenceMatchingService,
)

# =============================================================================
# Helper Factories
# =============================================================================


def create_test_user(db: Session, prefix: str = "matching_user") -> User:
    """Helper to persist a test User."""
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{unique_id}@nextround.in",
        name=f"Matching Candidate {unique_id}",
        hashed_password="hashed_pw_test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_claim(
    db: Session,
    user: User,
    claim_type: ClaimType = ClaimType.SKILL,
    claim_text: str = "Python",
    origin: ClaimOrigin = ClaimOrigin.USER_DECLARED,
) -> CandidateClaim:
    """Helper to persist a test CandidateClaim."""
    claim = CandidateClaim(
        user_id=user.id,
        claim_type=claim_type,
        claim_text=claim_text,
        origin=origin,
        canonical_path=None,
        resume_parse_id=None,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def create_test_source(
    db: Session,
    user: User,
    source_uri: str = "https://github.com/octocat/Hello-World",
    access_status: EvidenceSourceStatus = EvidenceSourceStatus.AVAILABLE,
) -> EvidenceSource:
    """Helper to persist a test EvidenceSource."""
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri=source_uri,
        access_mode=AccessMode.PUBLIC,
        access_status=access_status,
        last_checked_at=datetime.now(UTC),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def create_test_item(
    db: Session,
    source: EvidenceSource,
    evidence_type: EvidenceType = EvidenceType.REPOSITORY_METADATA,
    description: str = "Repository metadata",
    observed_data: dict[str, Any] | None = None,
    source_locator: str | None = "repository_metadata",
) -> EvidenceItem:
    """Helper to persist a test EvidenceItem."""
    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=evidence_type,
        description=description,
        observed_data=observed_data or {},
        source_locator=source_locator,
        observed_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def ensure_skill(
    db: Session,
    canonical_name: str,
    category: str = "Programming Languages",
    aliases: list[str] | None = None,
) -> Skill:
    """Ensure a skill exists in the canonical catalog."""
    existing = db.query(Skill).filter(Skill.canonical_name == canonical_name).first()
    if existing:
        return existing
    skill = Skill(
        canonical_name=canonical_name,
        category=category,
        aliases=aliases or [],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Register and login candidate, returning Authorization Bearer headers."""
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
# 1. SKILL Claims Matching Tests
# =============================================================================


def test_skill_claim_matches_primary_language(db: Session) -> None:
    """Verify SKILL claim matches repository primary_language."""
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "primary_language": "Python",
            "full_name": "octocat/Hello-World",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.CANONICAL_SKILL_NAME
    assert match.matched_term == "Python"
    assert "primary language" in match.explanation.lower()
    assert "authorship and proficiency remain unverified" in match.explanation.lower()


def test_skill_claim_matches_skill_alias(db: Session) -> None:
    """Verify SKILL claim using alias matches repository primary_language."""
    user = create_test_user(db)
    ensure_skill(db, "JavaScript", "Programming Languages", aliases=["JS"])
    claim = create_test_claim(db, user, ClaimType.SKILL, "JS")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "JavaScript"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matched_term == "JavaScript"


def test_skill_claim_matches_topics(db: Session) -> None:
    """Verify SKILL claim matches repository topics."""
    user = create_test_user(db)
    ensure_skill(db, "FastAPI", "Frameworks")
    claim = create_test_claim(db, user, ClaimType.SKILL, "FastAPI")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "primary_language": "Python",
            "topics": ["fastapi", "sqlalchemy", "pydantic"],
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matched_term == "fastapi"
    assert "topic" in match.explanation.lower()


def test_skill_claim_matches_repo_description(db: Session) -> None:
    """Verify SKILL claim matches keyword in repository description."""
    user = create_test_user(db)
    ensure_skill(db, "PostgreSQL", "Databases")
    claim = create_test_claim(db, user, ClaimType.SKILL, "PostgreSQL")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "description": "Backend API built with Python and PostgreSQL database",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.REPOSITORY_DESCRIPTION
    assert "description" in match.explanation.lower()


def test_skill_claim_matches_readme_documentation(db: Session) -> None:
    """Verify SKILL claim matches documentation keyword in README."""
    user = create_test_user(db)
    ensure_skill(db, "Docker", "DevOps")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Docker")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.DOCUMENTATION,
        source_locator="README.md",
        observed_data={
            "content": "# Deployment\nRun container using Docker Compose.\n"
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.DOCUMENTATION_KEYWORD
    assert "README.md" in match.explanation


def test_skill_claim_boundary_handling_c_vs_cpp(db: Session) -> None:
    """Verify single-letter skill 'C' does not falsely match 'C++' or 'CSS'."""
    user = create_test_user(db)
    ensure_skill(db, "C", "Programming Languages")
    ensure_skill(db, "C++", "Programming Languages")
    ensure_skill(db, "CSS", "Styling")

    claim_c = create_test_claim(db, user, ClaimType.SKILL, "C")
    source = create_test_source(db, user)

    # Item with C++ and CSS in description
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "primary_language": "C++",
            "description": "Modern frontend with CSS styles and C++ backend",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim_c.id)

    # 'C' must NOT match 'C++' or 'CSS'
    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0


def test_skill_claim_no_matching_evidence_returns_no_match(db: Session) -> None:
    """Verify NO_MATCH status when available evidence items contain no relevant skills."""
    user = create_test_user(db)
    ensure_skill(db, "Rust", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Rust")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python", "description": "Python repo"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0
    assert response.matches == []


# =============================================================================
# 2. PROJECT Claims Matching Tests
# =============================================================================


def test_project_claim_matches_exact_repository_name(db: Session) -> None:
    """Verify PROJECT claim matches exact repository name."""
    user = create_test_user(db)
    claim = create_test_claim(db, user, ClaimType.PROJECT, "Spoon-Knife")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"full_name": "octocat/Spoon-Knife"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.REPOSITORY_NAME
    assert match.matched_term == "Spoon-Knife"
    assert (
        "authorship and contribution scope remain unverified"
        in match.explanation.lower()
    )


def test_project_claim_matches_hyphenated_and_spaced_name(db: Session) -> None:
    """Verify PROJECT claim matches repository name with spaces/hyphens."""
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.PROJECT, "Developed the task scheduler platform"
    )
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"full_name": "candidate/task-scheduler"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.REPOSITORY_NAME
    assert match.matched_term == "task-scheduler"


def test_project_claim_matches_documentation_in_repo(db: Session) -> None:
    """Verify PROJECT claim identifies README documentation in matching repository."""
    user = create_test_user(db)
    claim = create_test_claim(db, user, ClaimType.PROJECT, "Spoon-Knife")
    source = create_test_source(db, user)
    meta = create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"full_name": "octocat/Spoon-Knife"},
    )
    doc = create_test_item(
        db,
        source,
        EvidenceType.DOCUMENTATION,
        source_locator="README.md",
        observed_data={"content": "# Spoon-Knife Project\nA repository for testing."},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 2
    item_ids = {m.evidence_item_id for m in response.matches}
    assert item_ids == {meta.id, doc.id}


# =============================================================================
# 3. EXPERIENCE Claims Matching Tests
# =============================================================================


def test_experience_claim_matches_technologies_with_strict_disclaimer(
    db: Session,
) -> None:
    """Verify EXPERIENCE claim matches technologies while explicitly disclaiming employment verification."""
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(
        db,
        user,
        ClaimType.EXPERIENCE,
        "Senior Software Engineer at Stripe (2020-2023), architecting payments in Python",
    )
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    match = response.matches[0]
    assert match.matched_term == "Python"
    # Mandatory disclaimer invariant
    assert (
        "Does NOT verify employment, employer, job title, duration, or professional responsibility"
        in match.explanation
    )


# =============================================================================
# 4. Non-Applicable Claims: EDUCATION, CERTIFICATION, OTHER
# =============================================================================


def test_education_claim_returns_not_applicable(db: Session) -> None:
    """Verify EDUCATION claims always return NOT_APPLICABLE status."""
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.EDUCATION, "B.S. in Computer Science from MIT"
    )
    source = create_test_source(db, user)
    create_test_item(db, source, EvidenceType.REPOSITORY_METADATA)

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NOT_APPLICABLE
    assert response.total_matches == 0
    assert response.matches == []
    assert "cannot verify education" in response.summary


def test_certification_claim_returns_not_applicable(db: Session) -> None:
    """Verify CERTIFICATION claims always return NOT_APPLICABLE status."""
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.CERTIFICATION, "AWS Certified Solutions Architect"
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NOT_APPLICABLE
    assert response.total_matches == 0
    assert response.matches == []
    assert "cannot verify education or certification" in response.summary


def test_other_claim_returns_not_applicable(db: Session) -> None:
    """Verify OTHER claims always return NOT_APPLICABLE status."""
    user = create_test_user(db)
    claim = create_test_claim(db, user, ClaimType.OTHER, "Open source enthusiast")

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NOT_APPLICABLE
    assert response.total_matches == 0
    assert response.matches == []
    assert "not supported for claims classified as OTHER" in response.summary


# =============================================================================
# 5. Source State Handling & Insufficient Data Tests
# =============================================================================


def test_insufficient_data_when_no_sources_or_items(db: Session) -> None:
    """Verify INSUFFICIENT_DATA status when candidate has no evidence sources or items."""
    user = create_test_user(db)
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.INSUFFICIENT_DATA
    assert response.total_matches == 0
    assert response.sources_inspected == 0
    assert response.items_inspected == 0


def test_inaccessible_and_revoked_sources_are_skipped(db: Session) -> None:
    """Verify items from non-AVAILABLE sources (INACCESSIBLE, REVOKED) are excluded, yielding INSUFFICIENT_DATA."""
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")

    # Source 1 is INACCESSIBLE
    source1 = create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/inaccessible-repo",
        access_status=EvidenceSourceStatus.INACCESSIBLE,
    )
    create_test_item(
        db,
        source1,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    # Source 2 is REVOKED
    source2 = create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/revoked-repo",
        access_status=EvidenceSourceStatus.REVOKED,
    )
    create_test_item(
        db,
        source2,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.INSUFFICIENT_DATA
    assert response.total_matches == 0
    assert response.items_inspected == 0
    assert "2 observation(s) from 2 non-available" in response.summary
    assert response.sources_summary["INACCESSIBLE"] == 1
    assert response.sources_summary["REVOKED"] == 1
    assert response.sources_summary["AVAILABLE"] == 0


def test_revoked_source_with_items_and_available_source_with_no_items_returns_insufficient_data(
    db: Session,
) -> None:
    """
    Verify a candidate with a REVOKED source having historical matching items alongside
    an AVAILABLE source with no collected observations returns INSUFFICIENT_DATA rather than NO_MATCH.
    """
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")

    # Historical revoked source with matching item
    revoked_source = create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/old-revoked-repo",
        access_status=EvidenceSourceStatus.REVOKED,
    )
    create_test_item(
        db,
        revoked_source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    # Currently available source with 0 observations collected
    create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/new-available-repo",
        access_status=EvidenceSourceStatus.AVAILABLE,
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    # Must be INSUFFICIENT_DATA, NOT NO_MATCH
    assert response.status == ClaimMatchStatus.INSUFFICIENT_DATA
    assert response.total_matches == 0
    assert response.items_inspected == 0
    assert response.sources_inspected == 2
    assert "1 observation(s) from 1 non-available" in response.summary
    assert response.sources_summary["REVOKED"] == 1
    assert response.sources_summary["AVAILABLE"] == 1


def test_available_source_with_irrelevant_items_and_errored_source_with_items_returns_no_match(
    db: Session,
) -> None:
    """
    Verify an AVAILABLE source with irrelevant observations alongside an ERROR source
    with historical observations returns NO_MATCH with limitation note explaining excluded sources.
    """
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")

    # Errored source with historical matching items
    errored_source = create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/error-repo",
        access_status=EvidenceSourceStatus.ERROR,
    )
    create_test_item(
        db,
        errored_source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    # Available source with non-matching observations (Rust)
    available_source = create_test_source(
        db,
        user,
        source_uri="https://github.com/octocat/active-rust-repo",
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    create_test_item(
        db,
        available_source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Rust", "description": "Systems tooling"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    # Evaluated active evidence yielded NO_MATCH, but limitation note explains excluded non-available source
    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0
    assert response.items_inspected == 1
    assert "1 observation(s) from 1 non-available" in response.summary
    assert response.sources_summary["ERROR"] == 1
    assert response.sources_summary["AVAILABLE"] == 1


# =============================================================================
# False-Positive Boundary Tests: Generic Claims and Technical Skill Tokens
# =============================================================================


def test_generic_project_claim_developed_a_web_application_does_not_false_match(
    db: Session,
) -> None:
    """
    Verify generic PROJECT claims like 'developed a web application' do not falsely match
    repositories having common words ('web', 'application') in their descriptions.
    """
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.PROJECT, "developed a web application"
    )

    source = create_test_source(db, user)
    # Repo with description containing common words 'web' and 'application'
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/culinary-delight",
            "description": "A web application for sharing cooking recipes and culinary tips.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    # Generic tokens alone must not produce a match
    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0
    assert response.matches == []


def test_generic_project_claim_does_not_match_generic_repo_name_substring(
    db: Session,
) -> None:
    """
    Verify a generic sentence does not falsely match a repository whose name is composed solely
    of generic development tokens (e.g. 'web-app').
    """
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.PROJECT, "developed a web app and backend system"
    )

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/web-app",
            "description": "Internal test utility",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0


def test_distinctive_project_claim_matches_description_keywords(
    db: Session,
) -> None:
    """
    Verify a distinctive PROJECT claim matches repository description when distinctive non-generic
    tokens are present.
    """
    user = create_test_user(db)
    claim = create_test_claim(
        db, user, ClaimType.PROJECT, "NextRound candidate interview platform"
    )

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/ai-harness",
            "description": "Candidate evaluation engine for the NextRound interview platform.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches >= 1
    match = response.matches[0]
    assert match.matching_basis == MatchingBasis.REPOSITORY_DESCRIPTION
    assert match.matched_term is not None and "nextround" in match.matched_term.lower()


def test_skill_matching_react_does_not_match_react_native(db: Session) -> None:
    """Verify claim for 'React' does not falsely match 'React Native' evidence."""
    user = create_test_user(db)
    ensure_skill(db, "React", "Frontend")
    claim = create_test_claim(db, user, ClaimType.SKILL, "React")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/mobile-client",
            "description": "A cross-platform mobile client built with React Native and Expo.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0


def test_skill_matching_react_native_matches_react_native(db: Session) -> None:
    """Verify claim for 'React Native' correctly matches 'React Native' evidence."""
    user = create_test_user(db)
    ensure_skill(db, "React Native", "Mobile")
    claim = create_test_claim(db, user, ClaimType.SKILL, "React Native")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/mobile-client",
            "description": "A cross-platform mobile client built with React Native and Expo.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    assert response.matches[0].matched_term == "React Native"


def test_skill_matching_dotnet_does_not_match_aspnet(db: Session) -> None:
    """Verify claim for '.NET' does not falsely match 'ASP.NET' evidence."""
    user = create_test_user(db)
    ensure_skill(db, ".NET", "Frameworks")
    claim = create_test_claim(db, user, ClaimType.SKILL, ".NET")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/web-api",
            "description": "Enterprise microservice implementation in ASP.NET Core.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0


def test_skill_matching_aspnet_matches_aspnet(db: Session) -> None:
    """Verify claim for 'ASP.NET' matches 'ASP.NET' evidence."""
    user = create_test_user(db)
    ensure_skill(db, "ASP.NET", "Frameworks")
    claim = create_test_claim(db, user, ClaimType.SKILL, "ASP.NET")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/web-api",
            "description": "Enterprise microservice implementation in ASP.NET Core.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    assert response.matches[0].matched_term == "ASP.NET"


def test_skill_matching_c_does_not_match_cpp_csharp_or_css(db: Session) -> None:
    """Verify single-letter skill 'C' does not falsely match 'C++', 'C#', or 'CSS'."""
    user = create_test_user(db)
    ensure_skill(db, "C", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "C")

    source = create_test_source(db, user)
    # Repo 1 with C++
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/cpp-engine",
            "primary_language": "C++",
            "description": "High performance 3D graphics engine written in modern C++.",
        },
    )
    # Repo 2 with C#
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/csharp-service",
            "primary_language": "C#",
            "description": "Backend services using C# and WPF.",
        },
    )
    # Repo 3 with CSS
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/style-system",
            "description": "Responsive layout themes crafted using CSS styling.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.NO_MATCH
    assert response.total_matches == 0


def test_skill_matching_c_matches_c_isolated(db: Session) -> None:
    """Verify single-letter skill 'C' matches genuine isolated C evidence."""
    user = create_test_user(db)
    ensure_skill(db, "C", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "C")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/kernel-module",
            "primary_language": "C",
            "description": "A Linux kernel module written in C for device drivers.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    assert response.matches[0].matched_term == "C"


def test_skill_matching_nodejs_matches_with_punctuation(db: Session) -> None:
    """Verify 'Node.js' matches with internal dot punctuation."""
    user = create_test_user(db)
    ensure_skill(db, "Node.js", "Backend", aliases=["NodeJS"])
    claim = create_test_claim(db, user, ClaimType.SKILL, "Node.js")

    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={
            "full_name": "octocat/backend-service",
            "description": "RESTful API built with Node.js and Express.",
        },
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)

    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH
    assert response.total_matches == 1
    assert response.matches[0].matched_term == "Node.js"


# =============================================================================
# 6. Candidate Isolation Tests
# =============================================================================


def test_candidate_isolation_claim_owned_by_another_user_returns_404(
    db: Session,
) -> None:
    """Verify requesting claim belonging to another candidate raises 404."""
    user1 = create_test_user(db, prefix="user1")
    user2 = create_test_user(db, prefix="user2")

    claim1 = create_test_claim(db, user1, ClaimType.SKILL, "Python")

    service = ClaimEvidenceMatchingService(db)
    with pytest.raises(HTTPException) as exc_info:
        service.find_evidence_matches(user2, claim1.id)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate claim not found" in exc_info.value.detail


def test_candidate_isolation_does_not_match_other_user_evidence(
    db: Session,
) -> None:
    """Verify Candidate A never matches Candidate B's evidence items."""
    user1 = create_test_user(db, prefix="user_a")
    user2 = create_test_user(db, prefix="user_b")

    ensure_skill(db, "Python", "Programming Languages")
    claim_a = create_test_claim(db, user1, ClaimType.SKILL, "Python")

    # User B owns Python evidence
    source_b = create_test_source(db, user2)
    create_test_item(
        db,
        source_b,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user1, claim_a.id)

    # User A has no items -> INSUFFICIENT_DATA
    assert response.status == ClaimMatchStatus.INSUFFICIENT_DATA
    assert response.total_matches == 0


# =============================================================================
# 7. Bounded Output & Verification Boundaries Tests
# =============================================================================


def test_bounded_output_limit_respected(db: Session) -> None:
    """Verify limit parameter bounds returned match items while total_matches tracks total."""
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")

    source = create_test_source(db, user)
    for i in range(5):
        create_test_item(
            db,
            source,
            EvidenceType.DOCUMENTATION,
            source_locator=f"doc_{i}.md",
            observed_data={"content": f"Python content in file {i}"},
        )

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id, limit=2)

    assert len(response.matches) == 2
    assert response.total_matches == 5


def test_read_only_and_zero_verification_results_invariant(db: Session) -> None:
    """Verify matching is strictly read-only and creates zero VerificationResults."""
    user = create_test_user(db)
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python"},
    )

    # Record counts before
    claim_count_before = db.query(CandidateClaim).count()
    source_count_before = db.query(EvidenceSource).count()
    item_count_before = db.query(EvidenceItem).count()
    skill_ev_before = db.query(CandidateSkillEvidence).count()
    vr_before = db.query(VerificationResult).count()

    service = ClaimEvidenceMatchingService(db)
    response = service.find_evidence_matches(user, claim.id)
    assert response.status == ClaimMatchStatus.POTENTIAL_MATCH

    # Verify zero mutations
    assert db.query(CandidateClaim).count() == claim_count_before
    assert db.query(EvidenceSource).count() == source_count_before
    assert db.query(EvidenceItem).count() == item_count_before
    assert db.query(CandidateSkillEvidence).count() == skill_ev_before
    assert db.query(VerificationResult).count() == vr_before


# =============================================================================
# 8. API Endpoint Integration Tests
# =============================================================================


def test_api_get_claim_evidence_matches_unauthenticated_rejected_401(
    client: TestClient,
) -> None:
    """Verify unauthenticated GET /api/v1/candidate-claims/{id}/evidence-matches returns 401."""
    random_id = uuid.uuid4()
    res = client.get(f"/api/v1/candidate-claims/{random_id}/evidence-matches")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_get_claim_evidence_matches_successful_workflow(
    client: TestClient, db: Session
) -> None:
    """Verify authenticated GET /api/v1/candidate-claims/{id}/evidence-matches workflow."""
    email = f"match_api_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    ensure_skill(db, "Python", "Programming Languages")
    claim = create_test_claim(db, user, ClaimType.SKILL, "Python")
    source = create_test_source(db, user)
    create_test_item(
        db,
        source,
        EvidenceType.REPOSITORY_METADATA,
        observed_data={"primary_language": "Python", "full_name": "api/test-repo"},
    )

    res = client.get(
        f"/api/v1/candidate-claims/{claim.id}/evidence-matches",
        headers=headers,
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()

    assert data["claim_id"] == str(claim.id)
    assert data["claim_type"] == "SKILL"
    assert data["claim_text"] == "Python"
    assert data["status"] == "POTENTIAL_MATCH"
    assert data["total_matches"] == 1
    assert len(data["matches"]) == 1
    match = data["matches"][0]
    assert match["matching_basis"] == "CANONICAL_SKILL_NAME"
    assert match["matched_term"] == "Python"
    # Verify no raw observed_data is exposed in the API response
    assert "observed_data" not in match
    assert "content" not in match


def test_api_get_claim_evidence_matches_unowned_returns_404(
    client: TestClient, db: Session
) -> None:
    """Verify attempting to fetch matches for another candidate's claim returns 404."""
    email1 = f"match_api_{uuid.uuid4().hex[:6]}@nextround.in"
    email2 = f"match_api_{uuid.uuid4().hex[:6]}@nextround.in"
    _ = get_auth_headers(client, email1)
    headers2 = get_auth_headers(client, email2)

    user1 = db.query(User).filter(User.email == email1).one()
    claim1 = create_test_claim(db, user1, ClaimType.SKILL, "Python")

    res = client.get(
        f"/api/v1/candidate-claims/{claim1.id}/evidence-matches",
        headers=headers2,
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate claim not found" in res.json()["detail"]
