import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.candidate_target import CandidateTarget
from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
    RoleRequirement,
)
from app.models.skill import Skill
from app.models.user import User
from app.schemas.candidate_target import CandidateTargetCreate
from app.schemas.skill import SkillResponse
from app.services.candidate_service import CandidateService
from app.services.role_requirement_parser import RoleRequirementParser
from app.services.role_requirement_service import RoleRequirementService


def create_test_user(db: Session, email_prefix: str = "parse_user") -> User:
    """Create a unique test user in the database."""
    unique_email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@nextround.in"
    user = User(
        email=unique_email,
        hashed_password="hashed_test_password",
        name="Parser Test Candidate",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_target(
    db: Session, user: User, job_description: str | None
) -> CandidateTarget:
    """Create a candidate target with an explicit job description."""
    service = CandidateService(db)
    service.get_or_create_profile(user)
    dto = service.create_target(
        user,
        CandidateTargetCreate(
            role_title="Senior Backend Engineer",
            company="Acme Corp",
            job_description=job_description,
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
# 1. Pure In-Memory Parser Tests (No Database Required)
# =============================================================================


def test_parser_empty_and_missing_job_descriptions() -> None:
    """Verify parser returns empty list for None, empty, or whitespace-only inputs without error."""
    parser = RoleRequirementParser()

    assert parser.extract_candidates(None) == []
    assert parser.extract_candidates("") == []
    assert parser.extract_candidates("    \n\t  \n  ") == []
    assert parser.parse(None) == []
    assert parser.parse("") == []


def test_parser_markdown_and_colon_headings() -> None:
    """Verify heading recognition sets section importance and skips ignored sections."""
    parser = RoleRequirementParser()
    text = """
    # About Acme Corp
    We are a fast-growing fintech startup with 500 employees.

    ## Requirements:
    - 4+ years of Python software engineering experience
    - Proficiency in relational databases

    ## Preferred Qualifications:
    - Experience with Kubernetes cluster operations
    - Bachelor's degree in Computer Science

    ## Benefits:
    - 401(k) matching
    - Comprehensive health coverage
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 4

    # Requirements section
    assert candidates[0].text == "4+ years of Python software engineering experience"
    assert candidates[0].importance == RequirementImportance.REQUIRED
    assert candidates[0].requirement_type == RequirementType.EXPERIENCE

    assert candidates[1].text == "Proficiency in relational databases"
    assert candidates[1].importance == RequirementImportance.REQUIRED
    assert candidates[1].requirement_type == RequirementType.SKILL

    # Preferred section
    assert candidates[2].text == "Experience with Kubernetes cluster operations"
    assert candidates[2].importance == RequirementImportance.PREFERRED
    assert candidates[2].requirement_type == RequirementType.EXPERIENCE

    assert candidates[3].text == "Bachelor's degree in Computer Science"
    assert candidates[3].importance == RequirementImportance.PREFERRED
    assert candidates[3].requirement_type == RequirementType.QUALIFICATION


def test_parser_bullet_formats() -> None:
    """Verify parser extracts bullet points marked by -, *, •, +, or numbers."""
    parser = RoleRequirementParser()
    text = """
    Required Qualifications:
    - Experience with Docker
    * Hands-on knowledge of Redis
    • Fluency in English
    + Minimum 3 years backend engineering
    1. Bachelor of Science in Engineering
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 5

    assert candidates[0].text == "Experience with Docker"
    assert candidates[1].text == "Hands-on knowledge of Redis"
    assert candidates[2].text == "Fluency in English"
    assert candidates[3].text == "Minimum 3 years backend engineering"
    assert candidates[4].text == "Bachelor of Science in Engineering"


def test_parser_compound_requirements_semicolons() -> None:
    """Verify compound requirements delimited by semicolons are split into distinct candidates."""
    parser = RoleRequirementParser()
    text = """
    Requirements:
    - 5+ years of software development experience; strong knowledge of Python; B.S. in Computer Science
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 3

    assert candidates[0].text == "5+ years of software development experience"
    assert candidates[0].requirement_type == RequirementType.EXPERIENCE
    assert candidates[0].importance == RequirementImportance.REQUIRED

    assert candidates[1].text == "strong knowledge of Python"
    assert candidates[1].requirement_type == RequirementType.SKILL
    assert candidates[1].importance == RequirementImportance.REQUIRED

    assert candidates[2].text == "B.S. in Computer Science"
    assert candidates[2].requirement_type == RequirementType.QUALIFICATION
    assert candidates[2].importance == RequirementImportance.REQUIRED


def test_parser_explicit_and_unspecified_importance() -> None:
    """Verify in-line cues override section defaults and unindicated text remains UNSPECIFIED."""
    parser = RoleRequirementParser()
    text = """
    Job Overview:
    - Python programming skills (mandatory)
    - Experience with Apache Kafka (nice to have)
    - Strong communication and collaboration abilities
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 3

    # In-line mandatory -> REQUIRED
    assert candidates[0].importance == RequirementImportance.REQUIRED

    # In-line nice to have -> PREFERRED
    assert candidates[1].importance == RequirementImportance.PREFERRED

    # No heading or in-line indicator -> UNSPECIFIED
    assert candidates[2].importance == RequirementImportance.UNSPECIFIED
    assert candidates[2].requirement_type == RequirementType.OTHER


def test_parser_conservative_type_classification() -> None:
    """Verify conservative classification into EXPERIENCE, QUALIFICATION, SKILL, and OTHER."""
    parser = RoleRequirementParser()
    text = """
    Requirements:
    - 3 to 5 years of industry experience building RESTful web services
    - Master's degree in Software Engineering or equivalent practical experience
    - Proficiency with asynchronous I/O and event loops
    - Ability to thrive in a fast-paced environment and mentor juniors
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 4

    assert candidates[0].requirement_type == RequirementType.EXPERIENCE
    assert candidates[1].requirement_type == RequirementType.QUALIFICATION
    assert candidates[2].requirement_type == RequirementType.SKILL
    assert candidates[3].requirement_type == RequirementType.OTHER


def test_parser_skill_matching_canonical_and_alias() -> None:
    """Verify deterministic skill matching against canonical names and aliases."""
    parser = RoleRequirementParser()

    py_id = uuid.uuid4()
    go_id = uuid.uuid4()
    k8s_id = uuid.uuid4()

    mock_skills = [
        SkillResponse(
            id=py_id,
            canonical_name="Python",
            category="Programming Language",
            aliases=["py", "python3"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=go_id,
            canonical_name="Go",
            category="Programming Language",
            aliases=["golang"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=k8s_id,
            canonical_name="Kubernetes",
            category="DevOps",
            aliases=["k8s"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]

    # 1. Exact canonical name match
    sid, sname = parser.match_skill(
        "Hands-on experience with Python", catalog_skills=mock_skills
    )
    assert sid == py_id
    assert sname == "Python"

    # 2. Exact alias match ("golang" -> Go)
    sid, sname = parser.match_skill(
        "3+ years developing in golang", catalog_skills=mock_skills
    )
    assert sid == go_id
    assert sname == "Go"

    # 3. Exact alias match ("k8s" -> Kubernetes)
    sid, sname = parser.match_skill(
        "Familiarity with k8s deployment manifests", catalog_skills=mock_skills
    )
    assert sid == k8s_id
    assert sname == "Kubernetes"

    # 4. Unmapped requirement with no known skill
    sid, sname = parser.match_skill(
        "B.S. in Computer Science", catalog_skills=mock_skills
    )
    assert sid is None
    assert sname is None

    # 5. Compound/multi-skill requirement remains unmapped for candidate review
    sid, sname = parser.match_skill(
        "Proficiency in both Python and Go", catalog_skills=mock_skills
    )
    assert sid is None
    assert sname is None


def test_parser_preserves_verbatim_text() -> None:
    """Verify original extracted requirement text is never altered or replaced by canonical names."""
    parser = RoleRequirementParser()
    raw_desc = """
    Requirements:
    - 3+ years writing scalable Python (3.11+) microservices
    """
    candidates = parser.extract_candidates(raw_desc)
    assert len(candidates) == 1
    # Must preserve exact punctuation and phrasing
    assert (
        candidates[0].text == "3+ years writing scalable Python (3.11+) microservices"
    )


# =============================================================================
# 2. Service & Target Ownership Tests (Database Integration)
# =============================================================================


def test_service_preview_requirements_with_catalog_mapping(db: Session) -> None:
    """Verify service extracts candidates, maps canonical catalog skills, and does NOT mutate DB."""
    user = create_test_user(db)
    # Seed skills
    skill_py = Skill(
        canonical_name="Python",
        category="Programming Language",
        aliases=["py", "python3"],
    )
    skill_pg = Skill(
        canonical_name="PostgreSQL", category="Database", aliases=["postgres", "psql"]
    )
    db.add_all([skill_py, skill_pg])
    db.commit()

    jd_text = """
    ## Minimum Qualifications:
    - 3+ years writing scalable Python applications
    - Solid understanding of PostgreSQL indexes and queries
    - Bachelor's degree in Computer Science or relevant field

    ## Preferred Qualifications:
    - Familiarity with CI/CD deployment pipelines
    """
    target = create_test_target(db, user, jd_text)
    service = RoleRequirementService(db)

    # Pre-check database count
    assert db.query(RoleRequirement).count() == 0

    # Execute preview
    preview = service.preview_requirements(user, target.id)

    # Post-check: preview MUST NOT write to database
    assert db.query(RoleRequirement).count() == 0

    assert preview.candidate_target_id == target.id
    assert preview.total_extracted == 4
    assert len(preview.requirements) == 4

    # Requirement 1: Python
    req0 = preview.requirements[0]
    assert req0.requirement_text == "3+ years writing scalable Python applications"
    assert req0.requirement_type == RequirementType.SKILL
    assert req0.importance == RequirementImportance.REQUIRED
    assert req0.skill_id == skill_py.id
    assert req0.matched_skill_name == "Python"
    assert req0.source_type == RequirementSourceType.JOB_DESCRIPTION

    # Requirement 2: PostgreSQL
    req1 = preview.requirements[1]
    assert (
        req1.requirement_text == "Solid understanding of PostgreSQL indexes and queries"
    )
    assert req1.requirement_type == RequirementType.SKILL
    assert req1.importance == RequirementImportance.REQUIRED
    assert req1.skill_id == skill_pg.id
    assert req1.matched_skill_name == "PostgreSQL"

    # Requirement 3: Qualification (Unmapped skill)
    req2 = preview.requirements[2]
    assert (
        req2.requirement_text
        == "Bachelor's degree in Computer Science or relevant field"
    )
    assert req2.requirement_type == RequirementType.QUALIFICATION
    assert req2.importance == RequirementImportance.REQUIRED
    assert req2.skill_id is None
    assert req2.matched_skill_name is None

    # Requirement 4: Preferred
    req3 = preview.requirements[3]
    assert req3.requirement_text == "Familiarity with CI/CD deployment pipelines"
    assert req3.importance == RequirementImportance.PREFERRED
    assert req3.skill_id is None


def test_service_preview_empty_job_description(db: Session) -> None:
    """Verify service returns empty preview when target has no job description."""
    user = create_test_user(db)
    target = create_test_target(db, user, job_description=None)
    service = RoleRequirementService(db)

    preview = service.preview_requirements(user, target.id)
    assert preview.candidate_target_id == target.id
    assert preview.requirements == []
    assert preview.total_extracted == 0


def test_service_preview_rejects_unowned_target(db: Session) -> None:
    """Verify preview raises 404 for target belonging to another candidate."""
    user1 = create_test_user(db, email_prefix="cand1")
    user2 = create_test_user(db, email_prefix="cand2")

    target1 = create_test_target(db, user1, "Requirements:\n- Python")
    service = RoleRequirementService(db)

    with pytest.raises(HTTPException) as exc_info:
        service.preview_requirements(user2, target1.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 3. API Preview Endpoints Tests
# =============================================================================


def test_api_preview_unauthenticated_rejected(client: TestClient) -> None:
    """Verify unauthenticated preview request returns 401 Unauthorized."""
    tid = uuid.uuid4()
    res_post = client.post(f"/api/v1/candidate-targets/{tid}/requirements/preview")
    assert res_post.status_code == status.HTTP_401_UNAUTHORIZED

    res_get = client.get(f"/api/v1/candidate-targets/{tid}/requirements/preview")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_preview_authenticated_workflow_and_persistence_isolation(
    client: TestClient, db: Session
) -> None:
    """
    Test full API preview workflow:
    1. Call POST /candidate-targets/{target_id}/requirements/preview.
    2. Confirm response contains preview candidates with mapped skills.
    3. Confirm ZERO records were persisted during preview.
    4. Call POST /candidate-targets/{target_id}/requirements with preview item to persist chosen requirement.
    5. Verify persisted requirement exists.
    """
    email = f"api_parser_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    skill_docker = Skill(canonical_name="Docker", category="DevOps", aliases=[])
    db.add(skill_docker)
    db.commit()

    jd = """
    ## Basic Qualifications:
    - 2+ years of production experience with Docker
    - Excellent written and verbal communication
    """
    target = create_test_target(db, user, jd)

    # Step 1: Preview via POST
    res_post = client.post(
        f"/api/v1/candidate-targets/{target.id}/requirements/preview",
        headers=headers,
    )
    assert res_post.status_code == status.HTTP_200_OK
    preview_data = res_post.json()

    assert preview_data["candidate_target_id"] == str(target.id)
    assert preview_data["total_extracted"] == 2
    assert len(preview_data["requirements"]) == 2

    docker_item = preview_data["requirements"][0]
    assert (
        docker_item["requirement_text"]
        == "2+ years of production experience with Docker"
    )
    assert docker_item["skill_id"] == str(skill_docker.id)
    assert docker_item["matched_skill_name"] == "Docker"
    assert docker_item["importance"] == "REQUIRED"

    # Step 2: Preview via GET
    res_get = client.get(
        f"/api/v1/candidate-targets/{target.id}/requirements/preview",
        headers=headers,
    )
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["total_extracted"] == 2

    # Step 3: Verify ZERO records in role_requirements table
    assert (
        db.query(RoleRequirement)
        .filter(RoleRequirement.candidate_target_id == target.id)
        .count()
        == 0
    )

    # Step 4: Persist the chosen requirement using existing creation endpoint
    create_payload = {
        "requirement_text": docker_item["requirement_text"],
        "requirement_type": docker_item["requirement_type"],
        "importance": docker_item["importance"],
        "source_type": docker_item["source_type"],
        "skill_id": docker_item["skill_id"],
    }
    res_create = client.post(
        f"/api/v1/candidate-targets/{target.id}/requirements",
        json=create_payload,
        headers=headers,
    )
    assert res_create.status_code == status.HTTP_201_CREATED
    saved_data = res_create.json()
    assert saved_data["skill_id"] == str(skill_docker.id)
    assert saved_data["requirement_text"] == docker_item["requirement_text"]

    # Step 5: Verify now exactly 1 requirement exists in DB
    assert (
        db.query(RoleRequirement)
        .filter(RoleRequirement.candidate_target_id == target.id)
        .count()
        == 1
    )


# =============================================================================
# 4. Phase 3.8 Targeted Review & Edge Case Tests
# =============================================================================


def test_parser_punctuation_skill_names_and_aliases() -> None:
    """
    Verify exact canonical and alias matching for skills with technical punctuation:
    C++, C#, .NET, Node.js, CI/CD, and case/whitespace variations.
    """
    parser = RoleRequirementParser()

    cpp_id = uuid.uuid4()
    csharp_id = uuid.uuid4()
    dotnet_id = uuid.uuid4()
    nodejs_id = uuid.uuid4()
    cicd_id = uuid.uuid4()
    ror_id = uuid.uuid4()

    mock_skills = [
        SkillResponse(
            id=cpp_id,
            canonical_name="C++",
            category="Programming Language",
            aliases=["cpp"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=csharp_id,
            canonical_name="C#",
            category="Programming Language",
            aliases=["csharp"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=dotnet_id,
            canonical_name=".NET",
            category="Framework",
            aliases=["dotnet"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=nodejs_id,
            canonical_name="Node.js",
            category="Runtime",
            aliases=["nodejs", "node"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=cicd_id,
            canonical_name="CI/CD",
            category="DevOps",
            aliases=["cicd"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=ror_id,
            canonical_name="Ruby on Rails",
            category="Framework",
            aliases=["rails"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]

    # C++
    sid, sname = parser.match_skill(
        "Strong C++ programming skills", catalog_skills=mock_skills
    )
    assert sid == cpp_id
    assert sname == "C++"

    # C#
    sid, sname = parser.match_skill(
        "Experience building C# microservices", catalog_skills=mock_skills
    )
    assert sid == csharp_id
    assert sname == "C#"

    # .NET
    sid, sname = parser.match_skill(
        "Hands-on experience with .NET core", catalog_skills=mock_skills
    )
    assert sid == dotnet_id
    assert sname == ".NET"

    # Node.js
    sid, sname = parser.match_skill(
        "Experience with Node.js async services", catalog_skills=mock_skills
    )
    assert sid == nodejs_id
    assert sname == "Node.js"

    # CI/CD
    sid, sname = parser.match_skill(
        "Setting up automated CI/CD deployment pipelines",
        catalog_skills=mock_skills,
    )
    assert sid == cicd_id
    assert sname == "CI/CD"

    # Ruby on Rails with multiple internal spaces (whitespace variation)
    sid, sname = parser.match_skill(
        "Experience with Ruby   on   Rails", catalog_skills=mock_skills
    )
    assert sid == ror_id
    assert sname == "Ruby on Rails"


def test_parser_prevents_false_positives_and_substring_collisions() -> None:
    """
    Verify:
    1. Single-letter 'C' does not falsely match within 'C++' or 'C#'.
    2. Substring terms like 'React' within 'React Native' resolve to 'React Native' without ambiguity conflict.
    3. '.NET' does not falsely match within 'ASP.NET' when only '.NET' is in catalog.
    4. Multiple distinct skills in one requirement remain unmapped.
    """
    parser = RoleRequirementParser()

    c_id = uuid.uuid4()
    cpp_id = uuid.uuid4()
    csharp_id = uuid.uuid4()
    react_id = uuid.uuid4()
    react_native_id = uuid.uuid4()
    dotnet_id = uuid.uuid4()

    catalog = [
        SkillResponse(
            id=c_id,
            canonical_name="C",
            category="Language",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=cpp_id,
            canonical_name="C++",
            category="Language",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=csharp_id,
            canonical_name="C#",
            category="Language",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=react_id,
            canonical_name="React",
            category="Frontend",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=react_native_id,
            canonical_name="React Native",
            category="Mobile",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        SkillResponse(
            id=dotnet_id,
            canonical_name=".NET",
            category="Framework",
            aliases=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]

    # 1. C++ must match C++, NOT C, when both C and C++ exist in the catalog
    sid, sname = parser.match_skill(
        "Strong C++ programming required", catalog_skills=catalog
    )
    assert sid == cpp_id
    assert sname == "C++"

    # 2. C must match C when explicitly mentioned
    sid, sname = parser.match_skill(
        "Proficiency in C programming", catalog_skills=catalog
    )
    assert sid == c_id
    assert sname == "C"

    # 3. Mentioning both C and C++ in one requirement remains unmapped
    sid, sname = parser.match_skill(
        "Experience in both C and C++", catalog_skills=catalog
    )
    assert sid is None
    assert sname is None

    # 4. Substring term 'React Native' matches 'React Native' and filters out sub-span 'React'
    sid, sname = parser.match_skill(
        "3+ years experience with React Native", catalog_skills=catalog
    )
    assert sid == react_native_id
    assert sname == "React Native"

    # 5. Distinct mentions of both React and React Native in one requirement remain unmapped
    sid, sname = parser.match_skill(
        "Proficiency in React and React Native", catalog_skills=catalog
    )
    assert sid is None
    assert sname is None

    # 6. '.NET' does not falsely match within 'ASP.NET'
    sid, sname = parser.match_skill(
        "Experience with ASP.NET core applications", catalog_skills=catalog
    )
    assert sid is None
    assert sname is None


def test_parser_heading_context_isolation_and_compound_headings() -> None:
    """
    Verify:
    1. Compound headings like 'Responsibilities & Requirements' are NOT ignored.
    2. Heading importance does NOT leak into subsequent sections.
    3. Unsupported headings (e.g. 'Other Details') remain reviewable with UNSPECIFIED importance.
    """
    parser = RoleRequirementParser()
    text = """
    # Responsibilities & Requirements:
    - 4+ years of Python engineering

    # Preferred Qualifications:
    - Experience with Docker

    # Other Details:
    - Must be authorized to work in the country
    - Willingness to travel occasionally
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 4

    # Responsibilities & Requirements -> REQUIRED
    assert candidates[0].text == "4+ years of Python engineering"
    assert candidates[0].importance == RequirementImportance.REQUIRED

    # Preferred Qualifications -> PREFERRED
    assert candidates[1].text == "Experience with Docker"
    assert candidates[1].importance == RequirementImportance.PREFERRED

    # Other Details -> Section importance reset to UNSPECIFIED (no leak from Preferred)
    # Inline 'Must be' elevates importance to REQUIRED
    assert candidates[2].text == "Must be authorized to work in the country"
    assert candidates[2].importance == RequirementImportance.REQUIRED
    assert candidates[2].requirement_type == RequirementType.OTHER

    # Unindicated item under Other Details stays UNSPECIFIED
    assert candidates[3].text == "Willingness to travel occasionally"
    assert candidates[3].importance == RequirementImportance.UNSPECIFIED
    assert candidates[3].requirement_type == RequirementType.OTHER


def test_parser_semicolon_splitting_prose_and_entities() -> None:
    """
    Verify semicolon splitting:
    1. Splits compound requirements.
    2. Does NOT split HTML entities (e.g. &amp;, &#39;).
    3. Does NOT split ordinary prose followed by transitional adverbs (e.g. ; however,).
    4. Handles trailing semicolons without creating empty fragments.
    """
    parser = RoleRequirementParser()
    text = """
    Requirements:
    - Strong knowledge of C &amp; C++; B.S. in CS;
    - Must have a B.S. degree; however, equivalent work experience is acceptable.
    - Python programming;
    """
    candidates = parser.extract_candidates(text)
    assert len(candidates) == 4

    # Bullet 1 split on semicolon, but &amp; is NOT split, trailing ; is stripped
    assert candidates[0].text == "Strong knowledge of C &amp; C++"
    assert candidates[1].text == "B.S. in CS"

    # Bullet 2: '; however,' ordinary prose is NOT split into dependent sentence fragment
    assert (
        candidates[2].text
        == "Must have a B.S. degree; however, equivalent work experience is acceptable."
    )

    # Bullet 3: trailing semicolon stripped without empty candidate
    assert candidates[3].text == "Python programming"
