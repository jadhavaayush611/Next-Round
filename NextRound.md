# NextRound

## Overview

NextRound is an AI-powered placement readiness platform designed specifically for Indian engineering students preparing for internships and campus placements.

Unlike traditional ATS resume scanners that only evaluate resume formatting and keyword matching, NextRound provides a holistic assessment of a student's placement readiness by analyzing their resume, technical skills, projects, job descriptions, and interview preparedness.

The platform acts as a personalized placement mentor, helping students understand where they currently stand, identify gaps in their profile, and receive actionable roadmaps to improve their chances of securing internships and full-time software engineering roles.

The core philosophy behind NextRound is:

"Don't just tell students whether their resume is ATS-friendly. Tell them whether they are actually placement-ready."

---

# Problem Statement

Most engineering students face several challenges during placement preparation:

* They do not know whether their resume is good enough.
* They do not know which skills are missing for their target roles.
* They have no objective way to measure placement readiness.
* They struggle to compare themselves against industry expectations.
* They receive generic advice from YouTube and LinkedIn.
* Existing ATS scanners only evaluate resumes and ignore actual technical preparedness.

Current solutions typically provide:

* ATS score
* Formatting feedback
* Keyword suggestions

However, they fail to answer:

* Am I ready for a Backend Internship?
* Am I ready for an SDE role?
* What skills am I missing?
* What should I learn next?
* How far am I from my target role?

NextRound aims to solve these problems.

---

# Target Audience

Primary Users:

* Engineering students
* Placement candidates
* Internship seekers
* Fresh graduates
* Computer Science students
* IT students

Secondary Users:

* Career counselors
* Placement cells
* Coding clubs
* Student communities

---

# Core Objectives

The platform should:

1. Analyze resumes.
2. Extract and understand skills.
3. Evaluate ATS compatibility.
4. Compare resumes against job descriptions.
5. Identify missing skills.
6. Assess placement readiness.
7. Generate personalized improvement roadmaps.
8. Track student progress over time.

---

# MVP Features (Phase 1)

## User Authentication

Features:

* Register
* Login
* Logout
* JWT Authentication
* Secure password storage
* Profile management

Stored Information:

* Name
* Email
* College
* Graduation year
* Branch
* CGPA
* Target role

---

## Resume Upload System

Supported Formats:

* PDF
* DOCX

Capabilities:

* Upload resume
* Store resume
* Parse resume content
* Extract text

Libraries:

* pdfplumber
* PyPDF2
* python-docx

Output:

Raw resume text for further processing.

---

## Resume Parsing Engine

Automatically identify sections such as:

* Education
* Skills
* Projects
* Experience
* Certifications
* Achievements
* Positions of Responsibility

Example Output:

Education:
B.E. Computer Engineering

Skills:
Java, Spring Boot, MySQL

Projects:
CampusGuide, PricePilot

Experience:
Software Intern

---

## ATS Scoring Engine

Generate an ATS score out of 100.

Scoring Categories:

Formatting:

* Clear headings
* Consistent structure
* ATS-friendly design

Content:

* Skill density
* Project quality
* Resume completeness

Keywords:

* Relevant technical skills
* Industry-recognized technologies

Example:

ATS Score: 82/100

Formatting: 18/20
Skills: 17/20
Projects: 20/20
Keywords: 15/20
Completeness: 12/20

---

## Skill Extraction Engine

Extract technical skills from resume text.

Examples:

Languages:

* Java
* Python
* JavaScript

Backend:

* Spring Boot
* Node.js
* Django

Databases:

* MySQL
* PostgreSQL
* MongoDB

Cloud:

* AWS
* Azure

Tools:

* Git
* Docker

Initially implemented using:

* Skill dictionaries
* Regex patterns

---

# Phase 2 Features (Mid July)

## NLP-Based Resume Analysis

Integrate NLP using spaCy.

Capabilities:

* Better skill detection
* Phrase recognition
* Technology extraction
* Context-aware parsing

Examples:

Recognize:

"Developed REST APIs using Spring Boot"

and correctly infer:

* REST APIs
* Spring Boot
* Backend Development

---

## Job Description Matching

User uploads:

Resume

*

Job Description

The system compares:

Resume Skills

vs

Job Requirements

Output:

Match Score: 72%

Matched Skills:

* Java
* Spring Boot
* SQL

Missing Skills:

* Docker
* AWS
* Redis

---

## Skill Gap Analysis

Determine what skills are missing for the target role.

Example:

Target Role:
Backend Developer

Current Skills:
Java
Spring Boot
MySQL

Missing:
Docker
Redis
AWS
CI/CD

---

## Resume Improvement Suggestions

Generate recommendations such as:

* Add quantified project impact.
* Add deployment links.
* Add GitHub repository links.
* Add internship experience.
* Improve project descriptions.

---

# Phase 3 Features (Late July)

## Placement Readiness Score

This is the flagship feature of NextRound.

The score evaluates overall placement readiness.

Score Range:

0 - 100

Categories:

Resume Quality:
20 points

Projects:
20 points

Technical Skills:
20 points

DSA Readiness:
20 points

Interview Readiness:
20 points

Example:

Resume: 16/20
Projects: 18/20
Skills: 14/20
DSA: 10/20
Interview: 8/20

Total:
66/100

---

## Role-Specific Evaluation

Students select target roles.

Examples:

* Backend Developer
* Full Stack Developer
* Software Engineer
* Data Analyst
* ML Engineer

The evaluation changes dynamically.

Backend Developer:

Higher weight:

* Java
* Spring Boot
* Databases
* APIs

ML Engineer:

Higher weight:

* Python
* NumPy
* Pandas
* Machine Learning

---

## Personalized Roadmap Generator

Generate customized improvement plans.

Example:

Target:
Backend Internship

Current Score:
68%

Roadmap:

Week 1:
Learn Docker

Week 2:
Deploy Spring Boot project

Week 3:
Complete Graph problems

Week 4:
Learn Redis basics

---

## Placement Readiness Dashboard

Visualize:

* ATS Score
* Placement Score
* Skill Coverage
* Missing Skills
* Resume History

Students can monitor progress over time.

---

# Future Features (August and Beyond)

## Placement Progress Tracking

Track:

* ATS score changes
* New skills acquired
* Project additions
* Resume improvements

---

## DSA Readiness Module

Students manually enter:

* LeetCode count
* Contest ratings
* Topic coverage

Generate:

DSA Readiness Score

Topics:

* Arrays
* Strings
* Trees
* Graphs
* DP

---

## Mock Interview Generator

Based on:

Resume
+
Target Role

Generate:

* HR questions
* Technical questions
* Project discussion questions

---

## Company-Specific Readiness

Examples:

Google Readiness

Amazon Readiness

Microsoft Readiness

Evaluate profile against company expectations.

---

## Local LLM Integration

Future integration through:

* Ollama
* Llama
* Qwen

Potential Features:

* Resume rewriting
* Personalized feedback
* Interview simulations
* Advanced career guidance

No paid API dependencies required.

---

# Recommended Tech Stack

Frontend:

* Next.js
* TypeScript
* Tailwind CSS
* shadcn/ui

Backend:

* FastAPI
* Python

Database:

* PostgreSQL

Authentication:

* JWT

ORM:

* SQLAlchemy

File Storage:

* Local Storage (MVP)
* AWS S3 (Future)

NLP:

* spaCy
* NLTK

Deployment:

Frontend:

* Vercel

Backend:

* Railway / Render

Database:

* Neon PostgreSQL

---

# Learning Outcomes

This project should help demonstrate:

Frontend Development:

* React
* Next.js
* Tailwind

Backend Development:

* FastAPI
* Authentication
* REST APIs

Databases:

* PostgreSQL
* SQLAlchemy

Python:

* Intermediate Python development

NLP:

* Text processing
* Skill extraction
* Resume analysis

Software Engineering:

* Architecture
* Deployment
* Security
* Product design

AI Foundations:

* NLP pipelines
* Feature extraction
* Recommendation systems

---

# Why This Project Matters

NextRound is not merely an ATS scanner.

It is a placement intelligence platform designed specifically for Indian engineering students.

It combines resume analysis, skill evaluation, placement readiness assessment, and personalized growth recommendations into a single product.

The long-term vision is to become a student's personal placement mentor, capable of guiding them from resume creation to offer acquisition.
