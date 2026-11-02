# NextRound — Shared Models and Invariants

**Status:** Adopted shared model contract for architectural implementation  
**Product scope:** Candidate-first placement intelligence; no recruiter portal in the MVP  
**Initial role family:** Backend / software engineering placements  
**AI constraint:** The core product must work without external LLM API keys  
**Relationship to Milestone 0:** This document refines the Milestone 0 Data Contract and adopts the `CandidateTarget` model.

## 1. Purpose

This document defines shared identifiers, enums, provenance conventions, entity-level invariants, and relationship rules for NextRound's candidate intelligence layer.

The guiding principle is:

> Preserve what the candidate claims, record what NextRound observes, and keep conclusions traceable to the evidence that supports them.

Shared domain types establish consistent meanings across the service, persistence, API, and test layers. SQLAlchemy models define persistence and relational constraints; Pydantic schemas validate requests and responses; service-layer logic enforces rules that depend on ownership, workflow, or multiple records.

Persistence models must not be exposed directly as public API schemas.

## 2. Shared identifiers and timestamps

Apply these conventions to new entities:

| Concern | Contract |
|---|---|
| Primary identifiers | UUIDs |
| Foreign keys | UUIDs referencing existing records |
| Timestamps | Timezone-aware UTC |
| Creation time | `created_at`, set by the server |
| Modification time | `updated_at`, only on mutable records |
| Ownership | Explicit `user_id` for candidate-owned records, except where ownership is inherited through a parent |
| Enum storage | Stable string values |
| Missing data | Explicit nullable fields; empty strings must not mean unknown |
| External identifiers | Source-specific identifiers, never authorization credentials |

A shared SQLAlchemy timestamp mixin is appropriate. Avoid a universal base class containing every conceivable field.

Timestamps must be generated or normalized by the backend. Clients must not be able to backdate verification results by submitting `checked_at`.

## 3. Shared enums

Enum values are part of the domain contract. Their meanings must remain stable.

### ClaimType

- `SKILL`
- `PROJECT`
- `EXPERIENCE`
- `EDUCATION`
- `CERTIFICATION`
- `OTHER`

### ClaimOrigin

- `RESUME`
- `USER_DECLARED`

### EvidenceSourceType

- `GITHUB_REPOSITORY`
- `GITHUB_PROFILE`
- `LINKEDIN_PROFILE`
- `PORTFOLIO`
- `ASSESSMENT`
- `OTHER`

`LINKEDIN_PROFILE` may be reserved for future use. Its presence does not mean the integration exists or that access is available.

### AccessMode

- `PUBLIC`
- `AUTHORIZED`
- `INTERNAL`

### EvidenceSourceStatus

- `AVAILABLE`
- `INACCESSIBLE`
- `REVOKED`
- `ERROR`
- `NOT_CHECKED`

### EvidenceType

- `REPOSITORY_METADATA`
- `CODE_ARTIFACT`
- `DOCUMENTATION`
- `CONTRIBUTION_ACTIVITY`
- `ASSESSMENT_RESULT`
- `OTHER`

### VerificationType

- `SOURCE_EXISTENCE`
- `CLAIM_SUPPORT`
- `ASSESSMENT`
- `OTHER`

### VerificationOutcome

- `SUPPORTED`
- `CONTRADICTED`
- `INCONCLUSIVE`
- `UNAVAILABLE`

`NOT_ASSESSED` is not an outcome. If no check has run, no `VerificationResult` should exist. Pending work can be represented by a future workflow model if needed.

### RequirementType

- `SKILL`
- `QUALIFICATION`
- `EXPERIENCE`
- `OTHER`

### RequirementImportance

- `REQUIRED`
- `PREFERRED`
- `UNSPECIFIED`

### RequirementSourceType

- `JOB_DESCRIPTION`
- `CURATED_ROLE`

## 4. Provenance

Resume-derived claims use a structured provenance reference:

- `resume_parse_id`: the immutable parse snapshot that supplied the claim.
- `canonical_path`: a path into the snapshot's canonical JSON, using JSON Pointer syntax where practical.

Example:

```text
resume_parse_id = 7d...
canonical_path = /projects/0/technologies/1
```

The values are illustrative. The path is meaningful only within the referenced parse snapshot, so both values must be present together.

For user-declared claims, resume provenance fields must be absent.

External evidence follows a different provenance chain:

```text
EvidenceSource
    └── EvidenceItem
           └── VerificationResult association
```

Do not create one universal provenance object that overloads resume paths, GitHub files, web URLs, and assessment attempts. The concepts share principles but have source-specific details.

## 5. CandidateProfile

**Purpose:** Store candidate-owned information and preferences that cannot reliably be derived from a resume.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id`; unique |
| `preferred_locations` | JSONB, nullable | Validated list of strings |
| `graduation_year` | Integer, nullable | Explicitly supplied or confirmed by candidate |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### Invariants

- Exactly one current profile per user.
- Graduation year, if provided, must be within a defensible calendar range.
- Target role and target company are not required; candidates can use personal resume analysis without a target.
- Changing target information must not mutate historical verification or assessment results.
- Do not duplicate resume-derived education, skills, or experience here.

## 6. CandidateTarget

**Purpose:** Represent one specific role/company/job-description configuration independently of the candidate's stable profile.

This model is adopted to preserve historical context when a candidate changes targets.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `candidate_profile_id` | UUID | Required FK to `CandidateProfile` |
| `role_title` | String | Target role |
| `company` | String, nullable | Optional target company |
| `job_description` | Text, nullable | Candidate-supplied job description |
| `created_at` | Timestamp | Creation time |
| `is_active` | Boolean | Whether this is the current target |

### Invariants

- A candidate profile may have multiple historical targets.
- At most one target per candidate profile may be active at a time.
- Changing targets creates a new `CandidateTarget` and deactivates the previous target rather than overwriting its requirements.
- Requirements, assessments, and future readiness results must refer to the specific target used.
- A target may exist without a company or job description.

## 7. CandidateClaim

**Purpose:** Represent a specific candidate assertion while preserving its origin.

Examples include claims about skills, projects, experience, education, and certifications.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner FK |
| `resume_parse_id` | UUID, nullable | Source parse snapshot when resume-derived |
| `claim_type` | Enum | `ClaimType` |
| `claim_text` | Text | Claim as represented by the source |
| `canonical_path` | String, nullable | JSON Pointer into the canonical snapshot |
| `origin` | Enum | `ClaimOrigin` |
| `created_at` | Timestamp | Creation time |

### Invariants

- Every claim belongs to one user.
- A `RESUME` claim must reference a valid `ResumeParse` owned by the same user.
- A `USER_DECLARED` claim must not reference a resume parse as its origin.
- Resume provenance consists of both `resume_parse_id` and `canonical_path`; both must be present together for resume-derived claims.
- Reprocessing creates new claims linked to the new parse snapshot; it must not silently overwrite claims tied to earlier snapshots.
- A claim is not proof that the assertion is true.
- Do not add `confidence_score` or `is_verified` fields.
- Claim extraction should be deterministic and conservative.
- A claim is not a second copy of `CanonicalResume`.

## 8. EvidenceSource

**Purpose:** Identify an external account, repository, profile, document, or internal assessment that NextRound can inspect.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner FK |
| `source_type` | Enum | `EvidenceSourceType` |
| `source_uri` | String | Normalized URL or internal reference |
| `access_mode` | Enum | `AccessMode` |
| `access_status` | Enum | `EvidenceSourceStatus` |
| `last_checked_at` | Timestamp, nullable | Last successful or attempted check |
| `created_at` | Timestamp | Creation time |

### Invariants

- A URL is not an identity or authorization mechanism by itself.
- Define URL normalization and duplicate-link behavior before adding uniqueness constraints.
- `AUTHORIZED` access requires a valid authorization mechanism outside this record; the enum value alone is not proof of permission.
- `REVOKED` prevents future retrieval through that authorization.
- Source-access failure must remain distinguishable from negative claim verification.
- Store only necessary source metadata. Never store access tokens in the source record.
- GitHub is the first external evidence integration. Private access requires explicit authorization and a suitable integration.

## 9. EvidenceItem

**Purpose:** Record a specific observation obtained from an evidence source.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `evidence_source_id` | UUID | Required FK |
| `evidence_type` | Enum | `EvidenceType` |
| `description` | Text | Human-readable observation |
| `observed_data` | JSONB, nullable | Minimal structured facts needed for the check |
| `source_locator` | String, nullable | File path, URL, or artifact identifier |
| `observed_at` | Timestamp | Observation time |
| `created_at` | Timestamp | Record creation time |

### Invariants

- Every evidence item belongs to exactly one source.
- Record observation time and retain a traceable source locator or internal reference where possible.
- Minimize stored data; do not blindly copy full repositories, profiles, or arbitrary social-media content.
- Evidence may support, contradict, partially support, or be irrelevant to a claim.
- An observation does not automatically prove authorship or proficiency.

## 10. VerificationResult

**Purpose:** Record the outcome of a defined check, including method version and limitations.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `candidate_claim_id` | UUID, nullable | Required for claim-support checks; nullable for source-only checks |
| `evidence_source_id` | UUID, nullable | Optional direct source reference |
| `verification_type` | Enum | `VerificationType` |
| `outcome` | Enum | `VerificationOutcome` |
| `method_version` | String | Version of the check logic |
| `explanation` | Text | Evidence-based reasoning |
| `checked_at` | Timestamp | Server-generated check time |
| `created_at` | Timestamp | Record creation time |

### Invariants

- Every result must target a claim, a source, or both.
- `CLAIM_SUPPORT` requires a claim reference.
- `SOURCE_EXISTENCE` may reference a source without a claim.
- Each result records the method version used.
- Associate all evidence used by the check through `VerificationEvidence`.
- New checks create new historical results rather than overwriting earlier results.
- `CONTRADICTED` requires an explanation grounded in the check and evidence.
- `UNAVAILABLE` means the check could not establish a result, not that the claim is false.
- Failed source access does not contradict a candidate's claim.
- Do not aggregate outcomes into a universal authenticity score.

## 11. VerificationEvidence

**Purpose:** Join verification results to the evidence items used by each check.

| Field | Type | Rules |
|---|---|---|
| `verification_result_id` | UUID | FK to `VerificationResult` |
| `evidence_item_id` | UUID | FK to `EvidenceItem` |

Use a composite primary key on both IDs unless a future requirement calls for multiple distinct roles for the same evidence item within one result.

## 12. Skill

**Purpose:** Represent a skill consistently across resumes, repositories, assessments, and target-role requirements.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `canonical_name` | String | Unique normalized name |
| `category` | String | For example, programming language, framework, database, or technical concept |
| `aliases` | JSONB | Known equivalent names and abbreviations |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### Invariants

- Each canonical skill has a unique normalized name.
- Alias resolution must be deterministic and conservative.
- `Postgres` and `PostgreSQL` may map together; `JS` and `JavaScript` may map together when context is unambiguous.
- `FastAPI` remains distinct from `Python`.
- Framework usage does not automatically establish independently demonstrated proficiency in its underlying language.
- Start with a small seeded catalog; do not build a large ontology in this milestone.

## 13. CandidateSkill

**Purpose:** Associate a candidate with a canonical skill referenced by claims or supported by evidence.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner FK |
| `skill_id` | UUID | Required FK to `Skill` |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### CandidateSkillEvidence

Use a join model to link a candidate-skill association to its supporting claim or observation.

| Field | Type | Rules |
|---|---|---|
| `candidate_skill_id` | UUID | Required FK |
| `candidate_claim_id` | UUID, nullable | Optional FK |
| `evidence_item_id` | UUID, nullable | Optional FK |

Exactly one of `candidate_claim_id` and `evidence_item_id` must be populated for each join row.

### Invariants

- Before a `CandidateSkill` is presented as evidence-backed, it must have at least one supporting claim, evidence item, or assessment result.
- Claim-only associations remain claims, not demonstrated proficiency.
- Do not introduce proficiency or confidence scores in this milestone.
- Assessment results may be represented as `EvidenceItem` records of type `ASSESSMENT_RESULT` until the assessment domain is implemented.

## 14. RoleRequirement

**Purpose:** Represent a skill or qualification required by a specific candidate target.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `candidate_target_id` | UUID | Required FK to `CandidateTarget` |
| `skill_id` | UUID, nullable | Canonical skill when applicable |
| `requirement_text` | Text | Original or faithfully extracted requirement |
| `requirement_type` | Enum | `RequirementType` |
| `importance` | Enum | `RequirementImportance` |
| `source_type` | Enum | `RequirementSourceType` |
| `created_at` | Timestamp | Creation time |

### Invariants

- Every requirement belongs to a specific target configuration, not merely a mutable role title.
- `skill_id` is nullable because some requirements are not skills.
- Preserve original wording after canonical mapping.
- Ambiguous mappings remain unmapped.
- Job-description requirements are not necessarily universal requirements for the role.
- Candidates should be able to review or correct extracted requirements.
- Do not claim to reproduce a company's internal hiring criteria.

## 15. Relationship summary

- `User` 1:1 `CandidateProfile`
- `CandidateProfile` 1:N `CandidateTarget`
- `CandidateProfile` has at most one active `CandidateTarget`
- `User` 1:N `CandidateClaim`
- Resume-derived `CandidateClaim` references the exact `ResumeParse` snapshot and canonical path
- `User` 1:N `EvidenceSource`
- `EvidenceSource` 1:N `EvidenceItem`
- `CandidateClaim` 1:N `VerificationResult` for claim-support checks
- `VerificationResult` may also reference an `EvidenceSource` for source-only checks
- `VerificationResult` N:M `EvidenceItem`, through `VerificationEvidence`
- `User` N:M `Skill`, through `CandidateSkill`
- `CandidateSkill` links to supporting claims or evidence through `CandidateSkillEvidence`
- `CandidateTarget` 1:N `RoleRequirement`

Ownership consistency across related records must be validated in services. A foreign key alone does not guarantee that a claim, its parse snapshot, and the authenticated user belong to the same candidate.

## 16. Persistence boundary

| Data | Persist? | Reason |
|---|---|---|
| `CanonicalResume` | Already persisted | Versioned source interpretation |
| `CandidateProfile` | Yes | Candidate-owned information and preferences |
| `CandidateTarget` | Yes | Target history and reproducible role context |
| `CandidateClaim` | Yes | Traceable assertions tied to their origin |
| `EvidenceSource` | Yes | Connected sources and access state |
| `EvidenceItem` | Yes | Historical observations |
| `VerificationResult` | Yes | Auditable outcomes of defined checks |
| `VerificationEvidence` | Yes | Traceability to evidence used by a check |
| `Skill` | Yes | Shared canonical skill catalog |
| `CandidateSkill` | Yes | Candidate-to-skill association |
| `CandidateSkillEvidence` | Yes | Traceability of skill associations |
| `RoleRequirement` | Yes | Target-specific requirements |
| Readiness score | Not yet | Requires a defined and validated methodology |
| Skill proficiency estimate | Not yet | Requires assessment and scoring design |
| Aggregate candidate-intelligence JSON | Not yet | Would duplicate normalized records |
| Full copied repository contents | No | Excessive storage and data-retention risk |

Use typed relational columns for identity, ownership, relationships, status, and timestamps. Use JSONB only where structure genuinely varies, such as minimal observed metadata or aliases.

## 17. Lifecycle, security, and integrity rules

1. **Ownership:** Every candidate-specific record must be scoped to its owner. The server determines ownership.
2. **Historical traceability:** Claims, evidence, and verification results retain origin and timestamps. New checks create new results.
3. **Source versioning:** Resume-derived claims reference the exact parse snapshot and canonical path. Reprocessing must not rewrite earlier provenance.
4. **Deletion:** Account deletion and deactivation require explicit retention behavior. Do not rely on accidental database cascades to determine audit retention.
5. **Access revocation:** Revocation prevents future retrieval through that authorization. Historical observations are governed by explicit retention and deletion policies.
6. **No automatic dishonesty labels:** Missing, inaccessible, or inconclusive evidence is not proof that a claim is false.
7. **No unsupported inference:** Technology appearing in a repository is not automatic proof of authorship, proficiency, or production experience.
8. **Versioned interpretation:** Changes to claim-extraction or verification logic must be identifiable.
9. **API safety:** Never expose access tokens, secrets, private repository contents, internal filesystem paths, or unrestricted raw source data.
10. **No external LLM dependency:** The core workflow must function without external model API keys.
11. **Candidate-first scope:** No recruiter portal, employer accounts, or hiring workflows in the MVP.
12. **YAGNI:** Implement the smallest coherent vertical slice; avoid a universal scoring system, large ontology, or unused infrastructure.

## 18. Implementation guidance

This contract defines the shared language and invariants. It is not an instruction to build every table in one batch.

The first implementation slice should establish:

1. `CandidateProfile`
2. `CandidateTarget`
3. Resume-derived `CandidateClaim`
4. Provenance links to `ResumeParse`
5. Ownership, validation, database constraints, and tests

Evidence-source ingestion and verification should follow as a subsequent slice. Skill intelligence should be built on top of those foundations.

Before implementation, inspect the existing repository conventions and reuse established shared modules where appropriate. Do not introduce a new `domain/` or `common/` package unless the current structure justifies it.
