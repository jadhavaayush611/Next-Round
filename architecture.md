# NextRound Architecture Design Document

This document outlines the architectural specifications, system designs, and data flow pipelines for **NextRound**, an AI-powered placement readiness platform for engineering candidates.

---

## 1. System Overview

NextRound uses a decoupled monorepo architecture with a React-based Next.js frontend, a Python-based FastAPI backend, and a PostgreSQL database. The backend uses NLP (via spaCy) for parsing and matching, and incorporates local LLMs (via Ollama/Qwen) for complex feedback and mock interviews in future phases.

### High-Level System Architecture

```mermaid
graph TD
    User([Student / Candidate]) -->|Interacts with| FE[Next.js Frontend]
    FE -->|API Requests / JWT Auth| BE[FastAPI Backend]
    
    subgraph Backend Core Services
        BE --> Auth[Authentication Service]
        BE --> Parsing[Resume Parsing Engine]
        BE --> Scoring[ATS & Placement Scoring Engine]
        BE --> GapAnalysis[Skill Gap & JD Matcher]
        BE --> Roadmap[Roadmap Generator]
    end

    Parsing -->|Extracts Text & Entities| spaCy[spaCy NLP Model]
    Scoring -->|Analyzes Profiles| DB[(PostgreSQL Database)]
    GapAnalysis --> DB
    Roadmap --> DB

    subgraph Future Enhancements
        BE --> LocalLLM[Ollama Local LLM API]
    end
```

---

## 2. Directory Structure

The monorepo structure is organized as follows:

```
NextRound/
├── .github/
│   └── workflows/          # CI/CD pipelines (Linters, Tests, Docker builds)
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── api/            # API endpoints (v1)
│   │   ├── core/           # Config, security, DB connections
│   │   ├── engines/        # Parsing, ATS, scoring, roadmap, NLP engines
│   │   ├── models/         # SQLAlchemy DB models
│   │   ├── schemas/        # Pydantic validation schemas
│   │   └── services/       # Business logic (users, resume uploads)
│   ├── tests/              # Pytest suite
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
├── frontend/               # Next.js 14+ typescript frontend
│   ├── src/
│   │   ├── app/            # App Router pages and layouts
│   │   ├── components/     # UI components (shadcn/ui based)
│   │   ├── hooks/          # Custom React hooks
│   │   ├── lib/            # Utilities (API client, helpers)
│   │   └── types/          # TypeScript definitions
│   ├── public/
│   ├── Dockerfile
│   ├── package.json
│   └── tailwind.config.js
├── docs/                   # API specs, manuals, and templates
├── docker/                 # Production-specific Docker configurations
├── scripts/                # Database migrations, seed scripts, utility scripts
├── docker-compose.yml      # Local multi-container development environment
├── README.md
├── LICENSE
└── architecture.md         # This document
```

---

## 3. Database Schema Design (ERD)

The relational database model captures user details, parsed resume histories, job descriptions, evaluation scores, and personalized roadmap plans.

```mermaid
erDiagram
    USER {
        uuid id PK
        string email UK
        string hashed_password
        string name
        string college
        int graduation_year
        string branch
        float cgpa
        string target_role
        datetime created_at
    }

    RESUME {
        uuid id PK
        uuid user_id FK
        string file_path
        string file_name
        string parsed_text
        jsonb parsed_sections
        datetime uploaded_at
    }

    PLACEMENT_ASSESSMENT {
        uuid id PK
        uuid user_id FK
        uuid resume_id FK
        int overall_readiness_score
        int resume_quality_score
        int projects_score
        int technical_skills_score
        int dsa_readiness_score
        int interview_readiness_score
        jsonb sub_scores
        datetime assessed_at
    }

    JOB_DESCRIPTION {
        uuid id PK
        uuid user_id FK
        string company_name
        string job_title
        string raw_text
        jsonb required_skills
        datetime created_at
    }

    JD_MATCH {
        uuid id PK
        uuid resume_id FK
        uuid jd_id FK
        int match_percentage
        jsonb matched_skills
        jsonb missing_skills
        datetime matched_at
    }

    ROADMAP {
        uuid id PK
        uuid user_id FK
        uuid assessment_id FK
        jsonb timeline_steps
        boolean is_active
        datetime created_at
    }

    USER ||--o{ RESUME : uploads
    USER ||--o{ PLACEMENT_ASSESSMENT : completes
    USER ||--o{ JOB_DESCRIPTION : saves
    USER ||--o{ ROADMAP : follows
    RESUME ||--o{ PLACEMENT_ASSESSMENT : evaluated_by
    RESUME ||--o{ JD_MATCH : matches
    JOB_DESCRIPTION ||--o{ JD_MATCH : matched_with
```

---

## 4. Key Engines and Algorithms

### 4.1 Secure Resume Upload & Storage Pipeline
1. **Document Ingestion**: Backend accepts `.pdf` and `.docx` files via `POST /api/v1/resumes`.
2. **Intentional Security Boundary (Phase 2.2 vs Phase 2.3)**: 
   - **Untrusted Client Metadata**: Client-supplied `Content-Type` and `filename` are treated as untrusted inputs.
   - **Phase 2.2 Lightweight Checks**: Combines case-insensitive extension whitelist (`.pdf`, `.docx`), MIME type consistency, and lightweight magic-byte signature validation (`%PDF-` for PDF, `PK` ZIP archive header for DOCX).
   - **Phase 2.3 Scope Boundary**: Full structural validation (PDF object tree inspection, DOCX OpenXML DOM verification, text extraction) belongs strictly to Phase 2.3.
3. **Upload Size Enforcement**:
   - Starlette / FastAPI multipart parser receives the incoming multipart stream into a managed temporary buffer (`UploadFile`).
   - The permanent storage persistence limit (default 5 MB, configurable via `MAX_UPLOAD_SIZE_BYTES`) is actively enforced during the chunked copy into permanent storage.
   - If the incoming stream exceeds the limit, chunked copying terminates immediately, partial disk files are unlinked, and an HTTP `413 Payload Too Large` is returned, guaranteeing oversized uploads are never permanently stored.
4. **Storage Abstraction Layer**:
   - Resumes are stored using safe storage keys (`users/{user_id}/resumes/{resume_id}.{ext}`) where the filename is generated from the Resume UUID, never user-controlled filenames.
   - All filesystem operations are decoupled behind `BaseStorageService` and implemented via `LocalStorageService` with configurable root (`STORAGE_LOCAL_ROOT`).
   - Clean boundary for future replacement with object storage (e.g., S3/GCS/MinIO).
5. **Transactional Integrity & Rollback**:
   - If database persistence or commits fail after saving the file to storage, the database transaction is rolled back and the physical file is immediately purged to eliminate orphaned storage artifacts.

```mermaid
flowchart TD
    Client[Client / Frontend] -->|POST /api/v1/resumes| Endpoint[FastAPI Resume Endpoint]
    Endpoint -->|Authenticate JWT| Auth[User Auth Dependency]
    Endpoint -->|Delegate Upload| Service[Resume Service]
    Service -->|Extension, MIME, Magic Sig, Limit| Validator[Validation Layer]
    Service -->|Save Chunks with Cap| Storage[Storage Abstraction]
    Storage -->|Write users/:uid/resumes/:rid.ext| LocalFS[Local Filesystem Storage]
    Service -->|Create Record version=N+1 status=UPLOADED| DB[(PostgreSQL Database)]
    Service -->|On Failure: Purge File| Cleanup[Storage Cleanup Handler]
```

### 4.2 Document Text Extraction Layer (Phase 2.3)
Converts stored binary resumes into normalized, deterministic plain text without semantic interpretation.

```mermaid
flowchart TD
    Resume[Resume Metadata / storage_key] --> Storage[BaseStorageService / LocalStorageService]
    Storage --> TrustedPath[Resolved Trusted Local File Path]
    TrustedPath --> Registry[Extractor Registry]
    Registry -->|application/pdf| PDFExt[PDF Extractor - pdfplumber]
    Registry -->|docx MIME| DOCXExt[DOCX Extractor - python-docx]
    PDFExt --> Normalizer[Text Normalizer]
    DOCXExt --> Normalizer
    Normalizer --> Result[ExtractionResult: text, status, extraction_issues, char_count, extractor_type]
```

#### Extraction Status & Issue Semantics:
The extraction contract models document processing outcomes with three explicit statuses and fine-grained issue tracking:
- **`COMPLETE`**:
  - All relevant document portions (pages/paragraphs/tables) were processed successfully without errors.
  - May yield non-empty text (or multi-page content with textless pages such as diagrams/images if no parser error occurred).
  - `extraction_issues` is guaranteed to be empty (`[]`).
- **`EMPTY`**:
  - Document is valid and was fully processed without error, but contains zero extractable text (e.g., scanned/image-only PDFs, blank DOCX files).
  - `extraction_issues` is guaranteed to be empty (`[]`).
  - OCR is intentionally not performed in this phase.
- **`PARTIAL`**:
  - The document is processable and some content was successfully extracted, but one or more isolated portions (specific page or table/paragraph element) encountered an extraction error.
  - Successfully extracted text from healthy portions is preserved and returned.
  - `extraction_issues` contains structured `ExtractionIssue(location_type, location, reason)` entries pinpointing failed elements (e.g., `location_type="page", location=2` or `location_type="table", location=1`).
- **`DocumentContentError`**:
  - Raised when a document cannot be meaningfully processed at all (e.g. corrupt zip archive, unparseable PDF catalog/streams, or 100% of body elements failing). Partial results are never manufactured for completely unreadable files.

#### Architectural Boundaries:
- **Phase 2.3 (Document $\rightarrow$ Plain Text)**:
  - Strict conversion of `.pdf` and `.docx` binary containers into plain text.
  - Page order and natural document reading order (paragraphs and tables) are preserved.
  - Text normalization enforces NFKC unicode cleanup, CRLF $\rightarrow$ LF, whitespace trimming, and consecutive newline compaction while preserving technical tokens (`C++`, `C#`, `.NET`, `Node.js`, `SQL`, URLs, emails).
  - Corrupt or unreadable documents raise controlled application exceptions (`DocumentReadError`, `DocumentContentError`).
- **Phase 2.4 (Plain Text $\rightarrow$ Structured Resume Data)**:
  - Section classification (Education, Experience, Skills), spaCy NLP parsing, and entity harvesting occur in Phase 2.4 downstream from normalized text output.

### 4.3 Resume Parsing Engine (Phase 2.4+)
1. **NLP Section Classification**: Rules combined with spaCy NLP identify section boundaries (e.g., separating "Projects" from "Experience").
2. **Skill & Tech Stack Harvesting**: Runs text through custom spaCy NER models and regular expression mapping layers to categorize languages, frameworks, databases, and DevOps tools.

```mermaid
flowchart TD
    Result[ExtractionResult Normalized Text] --> Sections[Parse Sections: Education, Skills, Projects, etc.]
    Sections --> spaCy[spaCy NLP Entity Recognizer]
    Sections --> Regex[Regex Phrase Dictionary Matcher]
    spaCy --> EntityCombine[Aggregate & Categorize Skills]
    Regex --> EntityCombine
    EntityCombine --> ParsedResult[Structured JSON Resume Output]
```

### 4.4 ATS Scoring Engine
Generates a score out of 100 based on standard industry filters:
* **Formatting (20%)**: Checks for single-page layout compatibility, clear standard headings, and absence of complex non-parseable structures (e.g., complex multi-column tables, vector graphics, image-based pages).
* **Content Completeness (20%)**: Verifies presence of contact details, education history, projects, and skills.
* **Skill Density (20%)**: Evaluates quantity and variety of technology classifications (Languages, Backend, Frontend, DBs).
* **Keywords (20%)**: Evaluates alignment with core software engineering keywords (e.g., git, API, database, testing, optimization).
* **Action Verb / Impact Analysis (20%)**: Uses NLP to analyze project descriptions for action-oriented verbs (e.g., "Led", "Optimized", "Architected") and quantified metrics (e.g., percentage improvements, response time drops).

### 4.3 Placement Readiness Score (Core Metric)
The flagship feature evaluates the candidate's absolute preparedness for entry-level roles:

$$\text{Readiness Score} = \text{Resume (20\%)} + \text{Projects (20\%)} + \text{Technical Skills (20\%)} + \text{DSA (20\%)} + \text{Interview (20\%)} $$

* **Resume (20 pts)**: Evaluated directly from the ATS score.
* **Projects (20 pts)**: Scored on tech stack completeness, deployment links presence (GitHub, Vercel/Render), and complexity index.
* **Technical Skills (20 pts)**: Evaluated relative to the selected **target role** requirements (e.g., backend, fullstack).
* **DSA Readiness (20 pts)**: Evaluated from self-reported or linked LeetCode totals, platform metrics, and coverage of major structures (Trees, Graphs, DP).
* **Interview Readiness (20 pts)**: Evaluated based on progress logs from mock questions or behavioral self-assessments.

### 4.4 Job Description Matching & Skill Gap Analysis
Matches candidate's parsed profiles against specific JD texts:
1. **Extraction**: Extracts requirements from the uploaded Job Description.
2. **Intersection Matrix**: Compares profile skills against job requirements.
3. **Similarity Vectors**: Uses spaCy's semantic similarity vectors to identify synonyms (e.g., mapping "MySQL" in a resume to "Relational Databases" in a JD).
4. **Output**: Computes a percentage score, generates list of **matched skills** and **missing skills** that must be acquired.

---

## 5. Implementation Roadmap

```
Phase 1: Foundations (Late July)
├── User Auth (JWT) & Profile setup
├── PDF/DOCX Parsing API (pdfplumber)
├── Basic Regex-based Skill Extraction
└── Formatting/Completeness ATS Score Engine

Phase 2: NLP & Matching (Early August)
├── Integration of spaCy Pipeline
├── Job Description matching endpoint
├── Similarity vectors for skill synonym alignment
└── Detailed Skill Gap output reports

Phase 3: Readiness & Roadmaps (Mid August)
├── Five-pillar Placement Readiness Scoring Engine
├── Dynamic weighted evaluation by Target Role
├── Timeline-based Roadmap Generator
└── History logging & readiness progress tracking dashboard
```
