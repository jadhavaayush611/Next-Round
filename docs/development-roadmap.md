# Development Roadmap

This document outlines the implementation phases, timeline allocations, and task breakdowns for the NextRound platform.

---

## 1. Development Phases

```
Phase 1: MVP Core (Late July)
├── Setup User Authentication (JWT)
├── Implement Resume PDF/DOCX Ingestion
└── Build Formatting & completeness ATS calculations

Phase 2: NLP & Gap Analysis (Early August)
├── Integrate spaCy NLP pipelines
├── Implement Job Description parsed requirements
└── Calculate skill gap and synonym intersections

Phase 3: Readiness Score & Dashboard (Mid August)
├── Establish 5-pillar Placement Readiness assessment
├── Build adaptive Roadmap Generator
└── Display progress tracking dashboards

Phase 4: Advanced Features (August & Beyond)
├── Local LLM integration (Ollama / Qwen / Llama)
├── Live mock interview simulations
└── DSA question logging syncs
```

---

## 2. Phase 1 Details: MVP Core (Late July)
* **Goal**: Launch a functioning platform where a student can register, upload a resume, and get basic ATS formatting and checklist results.
* **Tasks**:
  1. Complete User DB models, validation schemas, and service interfaces.
  2. Implement local disk upload endpoints (later transition to S3).
  3. Integrate `pdfplumber` and `python-docx` text extraction libraries.
  4. Write standard regex mapping definitions for basic skills.
  5. Implement simple scoring logic evaluating formatting boundaries, file extensions, and section presence.

---

## 3. Phase 2 Details: NLP & JD Matching (Early August)
* **Goal**: Shift from keyword checklists to semantic job matching.
* **Tasks**:
  1. Initialize spaCy pipeline on backend bootstrap (`en_core_web_md`).
  2. Train custom NER (Named Entity Recognition) flags to parse languages, libraries, and frameworks.
  3. Implement JD text paste uploads.
  4. Compare parsed resume entities against target JD required entities using cosine similarity.
  5. Generate comprehensive list of missing skills, differentiating between nice-to-have and mandatory gaps.

---

## 4. Phase 3 Details: Readiness Dashboard & Roadmaps (Mid August)
* **Goal**: Establish the flagship assessment scoring system and generate custom week-by-week roadmaps.
* **Tasks**:
  1. Implement DSA self-reports (number of questions solved, topics covered).
  2. Calculate the 5-pillar readiness score out of 100.
  3. Implement the Roadmap engine: reads target role, extracts missing skill list, and selects timeline steps from templated skill guidelines.
  4. Design frontend dashboard displays using Tailwind, visual progress bar indicators, and history logs.

---

## 5. Phase 4 Details: AI Features (Late August & Beyond)
* **Goal**: Integrate advanced NLP and generative AI features without incurring API pricing charges.
* **Tasks**:
  1. Configure Ollama API interfaces locally to connect backend workers to `qwen2.5-coder` or similar models.
  2. Build a mock interview module: generates questions based on the candidate's projects and target role, accepts textual replies, and grades responses.
  3. Generate custom textual resume paragraphs suggesting exact improvements.
