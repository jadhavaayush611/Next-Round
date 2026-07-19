# NextRound 🎓🚀

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Monorepo](https://img.shields.io/badge/Monorepo-Next.js%20%2B%20FastAPI-green.svg)](#)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](#)
[![Next.js Version](https://img.shields.io/badge/Next.js-14%2B-black.svg)](#)

NextRound is an **AI-powered Placement Readiness Platform** designed specifically for Indian engineering candidates preparing for internships and campus placements. 

---

## 🌟 Vision

Traditional Applicant Tracking Systems (ATS) evaluate formatting and keyword densities. But a good resume doesn't guarantee technical preparedness. 

> **"Don't just tell students whether their resume is ATS-friendly. Tell them whether they are actually placement-ready."**

NextRound acts as a personalized placement mentor. It analyzes a student's resume, tech stack, and experience against target job roles, determines skill gaps, and recommends personalized, actionable learning roadmaps to ensure candidates succeed in their *next round*.

---

## 🛠️ Tech Stack

NextRound is built using a modern, decoupled monorepo approach:

* **Frontend**: Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui.
* **Backend**: FastAPI, Python 3.10+, SQLAlchemy (ORM), Pydantic (validation).
* **Database**: PostgreSQL (Neon for cloud, local instance for dev).
* **NLP & Parsing**: spaCy, pdfplumber, python-docx.
* **Containers**: Docker, Docker Compose.

---

## 📂 Folder Structure

```
NextRound/
├── backend/                # FastAPI Application & ML Engines
├── frontend/               # Next.js Application Interface
├── docs/                   # Product & Engineering Documentation
├── docker/                 # Deployment Configurations
├── scripts/                # Database Migrations & Tooling
├── .github/workflows/      # CI/CD Action Pipelines
├── README.md               # Project Summary & Guide
├── LICENSE                 # MIT License details
├── docker-compose.yml      # Local Multi-container Setup
├── .gitignore              # Ignored files list
└── architecture.md         # System Architecture & Engine Details
```

For a detailed look at system diagrams and parser designs, see [architecture.md](file:///D:/NextRound/architecture.md).

---

## 🎯 Planned Features

### 📋 Phase 1: MVP & Core Evaluation
* **Secure Authentication**: JWT-based secure user profiles containing target roles, Branch, CGPA, and year.
* **Resume Parsing Engine**: Text and section extraction (Education, Projects, Skills) from PDF and DOCX uploads using `pdfplumber`.
* **ATS Scoring Engine**: Scoring algorithm evaluating formatting, keyword densities, completeness, and phrasing out of 100.

### 🧠 Phase 2: NLP & JD Matching
* **NLP-driven Profiles**: Enhanced skill detection using spaCy pipelines, understanding complex project phrases.
* **Job Description Matching**: Comparison of profile skills against job descriptions with percentage matching scores.
* **Skill Gap Analysis**: Identification of specific tools, technologies, and practices missing for target opportunities.

### 🏆 Phase 3: Placement Readiness & Roadmap
* **Placement Readiness Score**: A flagship metric aggregating five dimensions: Resume, Projects, Tech Stack, DSA, and Mock Interviews.
* **Personalized Roadmaps**: Automatic generation of weekly learning schedules mapping target roles to missing skills.
* **Role-Specific Weighted Evaluation**: Dynamic score recalculation based on target roles (e.g. backend developer vs. ML engineer).

### 🔮 Future Upgrades
* **Local LLM Integration**: Off-network feedback generation, resume rewriting, and mock interviews using local models (e.g. Qwen/Llama via Ollama).
* **DSA Tracker**: Integrations or manual logs mapping problem counts against major algorithms.
* **Company-Specific Readiness**: Evaluating candidate metrics against expectations from major recruiting firms.

---

## 🗺️ Development Roadmap

| Phase | Milestone | Focus Areas | Timeline |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Foundation & MVP | Auth, Upload pipelines, Parsing API, basic ATS calculations | Mid July |
| **Phase 2** | NLP & JD Matching | spaCy models, Semantic similarity matching, Skill Gap metrics | Late July |
| **Phase 3** | Mentor & Dashboards | Placement Readiness metric, Timeline Roadmaps, Candidate tracking | Early August |
| **Phase 4** | Advanced Integrations | Local LLMs (Ollama), DSA problem tracking, Mock interviews | Late August |

---

## 🤝 Contribution Guidelines

We welcome contributions from engineering students, developers, and designers!

1. **Fork the Repository**: Create a personal copy of the repository.
2. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/amazing-feature
   ```
3. **Commit Changes**: Use clean, descriptive commit messages.
4. **Push & Pull Request**: Push to your fork and submit a PR to `main`. Ensure all lint checks pass.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](file:///D:/NextRound/LICENSE) for more information.
