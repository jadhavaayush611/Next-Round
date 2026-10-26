# NextRound — Milestone 0 Data Contract

**Status:** Proposed contract for architectural review  
**Scope:** Candidate claims, evidence, verification, skill intelligence, and target-role requirements  
**Product direction:** Candidate-first placement intelligence; no recruiter portal in the MVP  
**Initial role family:** Backend / software engineering placements  
**AI constraint:** The core product must function without external LLM API keys.

## 1. Purpose and guiding principle

This contract defines the meaning, ownership, relationships, and lifecycle of the data used by NextRound's candidate intelligence layer.

> Preserve what the candidate claims, record what NextRound observes, and keep conclusions traceable to the evidence that supports them.

The contract builds on the existing Phase 2 components:

- `Resume`: the uploaded source file and its metadata.
- `ExtractedDocument`: extracted document content.
- `CanonicalResume`: the structured interpretation of the resume.
- `ResumeParse`: a persisted, versioned snapshot of that interpretation.

These components remain separate. Candidate claims, external observations, verification results, and skill associations must not be written back into `CanonicalResume`.

## 2. Conceptual data flow

```text
CanonicalResume
      |
      v
CandidateClaim
      |
      +------------------------------+
      |                              |
      v                              v
EvidenceSource -----------------> EvidenceItem
                                      |
                                      v
                              VerificationResult
                                      |
                                      v
                             Skill Intelligence
                                      |
                                      v
                              Role Requirements
```

This is a conceptual relationship diagram, not a mandatory execution sequence. Evidence may be collected before a claim is evaluated. One evidence item may support or contradict multiple claims, and a claim may have multiple evidence items.

## 3. CandidateProfile

**Purpose:** Store candidate-owned placement goals and preferences that cannot reliably be derived from a resume.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required foreign key to `users.id`; unique |
| `target_role_title` | String, nullable | Candidate's current target role |
| `target_company` | String, nullable | Optional target company |
| `target_job_description` | Text, nullable | User-supplied description for the initial MVP |
| `preferred_locations` | JSONB, nullable | Candidate location preferences |
| `graduation_year` | Integer, nullable | Explicitly supplied or confirmed by candidate |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### Rules

- One current `CandidateProfile` per user, with a one-to-one relationship to `User`.
- The target job description belongs to the candidate's current target configuration, not the resume parser.
- Changing the target must not silently rewrite requirements used by historical assessments.
- Do not duplicate resume-derived education, skills, or experience in this table.
- Multiple saved targets may be supported later; they are not required for the initial implementation.

## 4. CandidateClaim

**Purpose:** Represent a specific assertion made by the candidate, preserving its origin.

Examples:

- "I built an inventory management API."
- "I have experience with PostgreSQL."
- "I worked as a software engineering intern."

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner foreign key |
| `resume_parse_id` | UUID, nullable | Source parse snapshot when resume-derived |
| `claim_type` | Enum | `SKILL`, `PROJECT`, `EXPERIENCE`, `EDUCATION`, `CERTIFICATION`, `OTHER` |
| `claim_text` | Text | Claim as represented by the source |
| `canonical_reference` | JSONB, nullable | Pointer into the canonical resume or another structured source |
| `origin` | Enum | `RESUME`, `USER_DECLARED` |
| `created_at` | Timestamp | Creation time |

### Rules and lifecycle

- A resume-derived claim must reference the parse snapshot from which it was extracted.
- A user-declared claim must not be represented as resume-derived.
- Reprocessing a resume creates claims associated with the new parse snapshot; it must not silently overwrite claims associated with the old snapshot.
- A claim is not proof that the assertion is true.
- Do not add a `confidence_score` or `is_verified` field to `CandidateClaim`.
- Claim extraction should be deterministic and conservative.
- `CandidateClaim` is not a second copy of `CanonicalResume`; it represents a placement-relevant assertion.

## 5. EvidenceSource

**Purpose:** Identify an external account, repository, profile, document, or internal assessment that NextRound can inspect.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner foreign key |
| `source_type` | Enum | `GITHUB_REPOSITORY`, `GITHUB_PROFILE`, `LINKEDIN_PROFILE`, `PORTFOLIO`, `ASSESSMENT`, `OTHER` |
| `source_uri` | String | Normalized source URL or internal reference |
| `access_mode` | Enum | `PUBLIC`, `AUTHORIZED`, `INTERNAL` |
| `access_status` | Enum | `AVAILABLE`, `INACCESSIBLE`, `REVOKED`, `ERROR`, `NOT_CHECKED` |
| `last_checked_at` | Timestamp, nullable | Last successful or attempted check |
| `created_at` | Timestamp | Creation time |

### Rules

- A URL is not an identity or an authorization mechanism by itself.
- URL normalization and duplicate-link behavior must be defined before adding uniqueness constraints.
- `LINKEDIN_PROFILE` may exist as a future-compatible enum value, but LinkedIn integration is deferred until permitted access is practical.
- The first external evidence integration is GitHub, using public data and candidate-supplied links. Private repository access requires explicit authorization and a suitable integration.

## 6. EvidenceItem

**Purpose:** Record a specific observation obtained from an evidence source.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `evidence_source_id` | UUID | Required foreign key |
| `evidence_type` | Enum | `REPOSITORY_METADATA`, `CODE_ARTIFACT`, `DOCUMENTATION`, `CONTRIBUTION_ACTIVITY`, `ASSESSMENT_RESULT`, `OTHER` |
| `description` | Text | Human-readable observation |
| `observed_data` | JSONB, nullable | Minimal structured facts needed for the check |
| `source_locator` | String, nullable | File path, URL, or artifact identifier |
| `observed_at` | Timestamp | When the observation was made |
| `created_at` | Timestamp | Record creation time |

### Rules

- Store the minimum information needed to substantiate the observation.
- Do not blindly store complete repositories, whole profiles, or arbitrary social-media content.
- Prefer a locator back to the source when possible.
- Evidence may support, contradict, partially support, or be irrelevant to a claim.
- Do not label evidence as inherently "good" or "bad" without considering the claim and the check.

## 7. VerificationResult

**Purpose:** Record the outcome of a defined verification check, including its method and limitations.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `candidate_claim_id` | UUID | Required foreign key |
| `verification_type` | Enum | `SOURCE_EXISTENCE`, `CLAIM_SUPPORT`, `ASSESSMENT`, `OTHER` |
| `outcome` | Enum | `SUPPORTED`, `CONTRADICTED`, `INCONCLUSIVE`, `UNAVAILABLE`, `NOT_ASSESSED` |
| `method_version` | String | Version of the check logic |
| `explanation` | Text | Concise, evidence-based reasoning |
| `checked_at` | Timestamp | When the check ran |
| `created_at` | Timestamp | Record creation time |

### Evidence relationships

A verification check may use multiple evidence items. Model this as a many-to-many relationship using a join table such as `verification_evidence`.

### Verification invariants

1. Failed source access does not contradict the candidate's claim.
2. A repository containing a technology may support a project claim, but does not independently prove authorship or proficiency.
3. An assessment result establishes performance on that assessment, not universal mastery.
4. New checks create new historical results rather than rewriting previous results.
5. Contradictory evidence must be explained, not silently discarded.
6. Do not aggregate outcomes into a universal authenticity score.

## 8. Skill

**Purpose:** Represent a skill consistently across resumes, repositories, assessments, and target-role requirements.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `canonical_name` | String | Unique normalized name |
| `category` | String | For example, programming language, framework, database, or technical concept |
| `aliases` | JSONB | Known equivalent names and abbreviations |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### Rules

- `Postgres` and `PostgreSQL` may map to one canonical skill.
- `JS` and `JavaScript` may map together when the context is unambiguous.
- `FastAPI` remains distinct from `Python`.
- Use of FastAPI does not automatically prove independently demonstrated Python proficiency.
- Start with a small seeded skill catalog; do not build a large ontology in the initial milestone.

## 9. CandidateSkill

**Purpose:** Associate a candidate with a canonical skill mentioned in claims or supported by evidence.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required owner foreign key |
| `skill_id` | UUID | Required foreign key to `Skill` |
| `created_at` | Timestamp | Creation time |
| `updated_at` | Timestamp | Last update |

### Supporting links

Candidate-skill associations must be supported by linked claims, evidence items, or assessment results. Use explicit relationships rather than placing all supporting evidence in an unstructured JSON field.

### Rules

- Do not add a proficiency score yet.
- Do not infer expertise from framework usage or repository counts.
- Do not store arbitrary confidence scores without a defined methodology.
- Assessment definitions, attempts, task-level results, and rubric versions belong to a future assessment domain. For this contract, assessments can be represented as evidence sources and their results as evidence items.

## 10. RoleRequirement

**Purpose:** Represent a skill or qualification required by a target role.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `candidate_profile_id` | UUID | Required foreign key to the target configuration |
| `skill_id` | UUID, nullable | Canonical skill when the requirement is skill-based |
| `requirement_text` | Text | Original or faithfully extracted requirement |
| `requirement_type` | Enum | `SKILL`, `QUALIFICATION`, `EXPERIENCE`, `OTHER` |
| `importance` | Enum | `REQUIRED`, `PREFERRED`, `UNSPECIFIED` |
| `source_type` | Enum | `JOB_DESCRIPTION`, `CURATED_ROLE` |
| `created_at` | Timestamp | Creation time |

### Rules

- Not every requirement is a skill; `skill_id` is nullable.
- Preserve the original requirement text even when mapping it to a canonical skill.
- Leave ambiguous mappings unmapped rather than forcing a match.
- A requirement extracted from a job description is not necessarily universal to that role.
- Allow candidates to review or correct extracted requirements.
- Do not claim to reproduce a company's internal hiring criteria.

## 11. Relationship summary

- `User` 1:1 `CandidateProfile`
- `User` 1:N `CandidateClaim`
- `User` 1:N `EvidenceSource`
- `EvidenceSource` 1:N `EvidenceItem`
- `CandidateClaim` 1:N `VerificationResult`
- `VerificationResult` N:M `EvidenceItem`, through `verification_evidence`
- `User` N:M `Skill`, through `CandidateSkill`
- `CandidateProfile` 1:N `RoleRequirement`
- Resume-derived `CandidateClaim` references the relevant `ResumeParse` snapshot

This is a conceptual model. Exact ORM relationships, indexes, delete behavior, and constraints must be specified during implementation.

## 12. Persistence boundary

| Data | Persist? | Reason |
|---|---|---|
| `CanonicalResume` | Already persisted | Versioned source interpretation |
| `CandidateProfile` | Yes | Candidate-owned goals and preferences |
| `CandidateClaim` | Yes | Traceable assertions tied to their origin |
| `EvidenceSource` | Yes | Connected sources and access state |
| `EvidenceItem` | Yes | Historical observations |
| `VerificationResult` | Yes | Auditable results of defined checks |
| `Skill` | Yes | Shared canonical skill catalog |
| `CandidateSkill` | Yes | Candidate-to-skill associations |
| `RoleRequirement` | Yes | Target-specific requirements |
| Readiness score | Not yet | Requires a defined and validated methodology |
| Skill proficiency estimate | Not yet | Requires assessment and scoring design |
| Aggregate candidate-intelligence JSON | Not yet | Would duplicate normalized records |
| Full copied repository contents | No | Excessive storage and data-retention risk |

Use typed relational columns for identities, ownership, relationships, statuses, and timestamps. Use JSONB only where structure genuinely varies, such as minimal observed metadata.

## 13. Lifecycle, security, and integrity rules

1. **Ownership:** Every candidate-specific record must be scoped to the authenticated user. The server determines ownership.
2. **Historical traceability:** Claims, evidence, and verification results retain origin and timestamps. New checks create new results.
3. **Source versioning:** Resume-derived claims reference their `ResumeParse` snapshot. Reprocessing must not silently rewrite the history of earlier claims.
4. **Deletion:** Account deletion and deactivation require explicit retention behavior. Do not rely on accidental database cascades to define audit retention.
5. **Access revocation:** Revocation prevents future retrieval through that authorization. Historical observations are handled under explicit retention and deletion policies.
6. **No automatic dishonesty labels:** Missing, inaccessible, or inconclusive evidence is not proof that a claim is false.
7. **No unsupported inference:** Technology appearing in a repository is not automatic proof of authorship, proficiency, or production experience.
8. **Versioned interpretation:** Changes to claim-extraction or verification logic must be identifiable.
9. **API safety:** Never expose access tokens, secrets, private repository contents, internal filesystem paths, or unrestricted raw source data in public responses.

## 14. Milestone 0 scope boundaries

### Included in the contract

- One candidate profile per user, with one current target configuration.
- Claims and external evidence as independent concepts.
- Historical verification results traceable to supporting evidence.
- Canonical skills without proficiency scores.
- Target-role requirements separate from candidate skills.
- Compatibility with existing resume parsing and versioned snapshots.
- GitHub as the first external evidence integration.
- Operation without external AI API keys.

### Explicitly excluded

- Recruiter portal, employer accounts, and hiring workflows.
- Readiness scoring and proficiency inference.
- A full assessment engine.
- Automated fraud detection.
- General-purpose scraping of arbitrary social media.
- LinkedIn integration until permitted access is practical.
- A large skill ontology.
- An aggregate candidate-intelligence snapshot that duplicates normalized records.

## 15. Implementation guidance

This is a data contract, not an instruction to build every table immediately.

Implement the smallest coherent vertical slice first. Define shared models and invariants now, then persist only the entities needed by the next working workflow. This avoids unused infrastructure while preserving architectural consistency.

The next implementation slice should establish:

1. `CandidateProfile`
2. Resume-derived `CandidateClaim`
3. Provenance links to `ResumeParse`
4. Ownership, validation, and tests

Evidence-source ingestion and verification can follow as the next slice, with skill intelligence built on those foundations.
