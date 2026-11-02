import enum
import re
from typing import NamedTuple

from app.services.extraction.models import ExtractedElement, Provenance


class SectionType(enum.StrEnum):
    """Canonical section types supported by NextRound Semantic Resume Parser."""

    IDENTITY = "identity"
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    PROJECTS = "projects"
    SKILLS = "skills"
    CERTIFICATIONS = "certifications"
    AWARDS = "awards"
    PUBLICATIONS = "publications"
    LANGUAGES = "languages"
    VOLUNTEERING = "volunteering"
    ORGANIZATIONS = "organizations"
    LINKS = "links"
    ADDITIONAL = "additional"


# Extensible dictionary mapping normalized synonyms to canonical SectionType
SECTION_SYNONYMS: dict[str, SectionType] = {
    # Summary / Profile / Objective
    "summary": SectionType.SUMMARY,
    "professional summary": SectionType.SUMMARY,
    "career summary": SectionType.SUMMARY,
    "summary of qualifications": SectionType.SUMMARY,
    "profile": SectionType.SUMMARY,
    "professional profile": SectionType.SUMMARY,
    "executive profile": SectionType.SUMMARY,
    "career profile": SectionType.SUMMARY,
    "objective": SectionType.SUMMARY,
    "career objective": SectionType.SUMMARY,
    "about me": SectionType.SUMMARY,
    "about": SectionType.SUMMARY,
    "personal statement": SectionType.SUMMARY,
    "statement of purpose": SectionType.SUMMARY,
    "bio": SectionType.SUMMARY,
    # Experience / Employment
    "experience": SectionType.EXPERIENCE,
    "work experience": SectionType.EXPERIENCE,
    "professional experience": SectionType.EXPERIENCE,
    "professional work experience": SectionType.EXPERIENCE,
    "employment history": SectionType.EXPERIENCE,
    "career history": SectionType.EXPERIENCE,
    "work history": SectionType.EXPERIENCE,
    "internships": SectionType.EXPERIENCE,
    "internship experience": SectionType.EXPERIENCE,
    "relevant experience": SectionType.EXPERIENCE,
    "industrial experience": SectionType.EXPERIENCE,
    "industry experience": SectionType.EXPERIENCE,
    "professional background": SectionType.EXPERIENCE,
    "employment": SectionType.EXPERIENCE,
    "work & experience": SectionType.EXPERIENCE,
    "practical experience": SectionType.EXPERIENCE,
    "job experience": SectionType.EXPERIENCE,
    # Education / Academic
    "education": SectionType.EDUCATION,
    "academic background": SectionType.EDUCATION,
    "educational qualifications": SectionType.EDUCATION,
    "academic history": SectionType.EDUCATION,
    "academics": SectionType.EDUCATION,
    "qualifications": SectionType.EDUCATION,
    "educational background": SectionType.EDUCATION,
    "education & training": SectionType.EDUCATION,
    "academic credentials": SectionType.EDUCATION,
    "academic qualifications": SectionType.EDUCATION,
    "education details": SectionType.EDUCATION,
    "education & certifications": SectionType.EDUCATION,
    "scholastic achievements": SectionType.EDUCATION,
    # Projects
    "projects": SectionType.PROJECTS,
    "personal projects": SectionType.PROJECTS,
    "academic projects": SectionType.PROJECTS,
    "key projects": SectionType.PROJECTS,
    "key technical projects": SectionType.PROJECTS,
    "technical projects": SectionType.PROJECTS,
    "relevant projects": SectionType.PROJECTS,
    "notable projects": SectionType.PROJECTS,
    "software projects": SectionType.PROJECTS,
    "capstone projects": SectionType.PROJECTS,
    "selected projects": SectionType.PROJECTS,
    "major projects": SectionType.PROJECTS,
    "recent projects": SectionType.PROJECTS,
    "open source projects": SectionType.PROJECTS,
    "course projects": SectionType.PROJECTS,
    # Skills
    "skills": SectionType.SKILLS,
    "technical skills": SectionType.SKILLS,
    "core competencies": SectionType.SKILLS,
    "areas of expertise": SectionType.SKILLS,
    "proficiencies": SectionType.SKILLS,
    "programming languages": SectionType.SKILLS,
    "technologies": SectionType.SKILLS,
    "tech stack": SectionType.SKILLS,
    "skills & competencies": SectionType.SKILLS,
    "technical expertise": SectionType.SKILLS,
    "key skills": SectionType.SKILLS,
    "tools & technologies": SectionType.SKILLS,
    "frameworks & tools": SectionType.SKILLS,
    "languages & frameworks": SectionType.SKILLS,
    "skills & abilities": SectionType.SKILLS,
    "skills summary": SectionType.SKILLS,
    "technical proficiencies": SectionType.SKILLS,
    "computer skills": SectionType.SKILLS,
    "it skills": SectionType.SKILLS,
    "software skills": SectionType.SKILLS,
    "technical strengths": SectionType.SKILLS,
    # Certifications / Courses
    "certifications": SectionType.CERTIFICATIONS,
    "licenses & certifications": SectionType.CERTIFICATIONS,
    "certificates": SectionType.CERTIFICATIONS,
    "professional certifications": SectionType.CERTIFICATIONS,
    "licenses": SectionType.CERTIFICATIONS,
    "courses & certifications": SectionType.CERTIFICATIONS,
    "certifications & licenses": SectionType.CERTIFICATIONS,
    "certifications & courses": SectionType.CERTIFICATIONS,
    "courses": SectionType.CERTIFICATIONS,
    "online courses": SectionType.CERTIFICATIONS,
    "trainings": SectionType.CERTIFICATIONS,
    "training & certifications": SectionType.CERTIFICATIONS,
    # Awards / Achievements / Honors / Fellowships
    "awards": SectionType.AWARDS,
    "honors & awards": SectionType.AWARDS,
    "honours & awards": SectionType.AWARDS,
    "achievements": SectionType.AWARDS,
    "accomplishments": SectionType.AWARDS,
    "honors": SectionType.AWARDS,
    "honours": SectionType.AWARDS,
    "scholarships": SectionType.AWARDS,
    "fellowships & awards": SectionType.AWARDS,
    "fellowships and awards": SectionType.AWARDS,
    "fellowships": SectionType.AWARDS,
    "awards & recognition": SectionType.AWARDS,
    "awards and recognition": SectionType.AWARDS,
    "awards & achievements": SectionType.AWARDS,
    "awards and achievements": SectionType.AWARDS,
    "key achievements": SectionType.AWARDS,
    "extracurricular achievements": SectionType.AWARDS,
    "honors & achievements": SectionType.AWARDS,
    # Publications / Patents
    "publications": SectionType.PUBLICATIONS,
    "research publications": SectionType.PUBLICATIONS,
    "papers": SectionType.PUBLICATIONS,
    "research papers": SectionType.PUBLICATIONS,
    "conference proceedings": SectionType.PUBLICATIONS,
    "journal articles": SectionType.PUBLICATIONS,
    "patents & publications": SectionType.PUBLICATIONS,
    "patents and publications": SectionType.PUBLICATIONS,
    "patents": SectionType.PUBLICATIONS,
    "published works": SectionType.PUBLICATIONS,
    "research": SectionType.PUBLICATIONS,
    # Languages
    "languages": SectionType.LANGUAGES,
    "language proficiency": SectionType.LANGUAGES,
    "languages known": SectionType.LANGUAGES,
    "spoken languages": SectionType.LANGUAGES,
    "language skills": SectionType.LANGUAGES,
    # Volunteering / Social Work
    "volunteering": SectionType.VOLUNTEERING,
    "volunteer experience": SectionType.VOLUNTEERING,
    "community service": SectionType.VOLUNTEERING,
    "social work": SectionType.VOLUNTEERING,
    "leadership & volunteering": SectionType.VOLUNTEERING,
    "volunteer work": SectionType.VOLUNTEERING,
    "community involvement": SectionType.VOLUNTEERING,
    # Organizations / Leadership / Extracurricular
    "organizations": SectionType.ORGANIZATIONS,
    "affiliations": SectionType.ORGANIZATIONS,
    "professional memberships": SectionType.ORGANIZATIONS,
    "clubs & societies": SectionType.ORGANIZATIONS,
    "activities": SectionType.ORGANIZATIONS,
    "positions of responsibility": SectionType.ORGANIZATIONS,
    "position of responsibility": SectionType.ORGANIZATIONS,
    "extracurricular activities": SectionType.ORGANIZATIONS,
    "extra-curricular activities": SectionType.ORGANIZATIONS,
    "co-curricular activities": SectionType.ORGANIZATIONS,
    "leadership": SectionType.ORGANIZATIONS,
    "leadership experience": SectionType.ORGANIZATIONS,
    "extra curricular activities": SectionType.ORGANIZATIONS,
    "memberships": SectionType.ORGANIZATIONS,
}


def normalize_heading_text(heading: str) -> str:
    """Cleans and standardizes heading text for dictionary lookup."""
    if not heading:
        return ""
    # Strip leading numbering like "1.", "1.0", "I.", "A)"
    cleaned = re.sub(
        r"^(?:(?:\d+\.|\d+\)|\([a-zA-Z\d]+\)|[a-zA-Z]\.|[IVXLCDM]+\.)\s*)+",
        "",
        heading.strip(),
    )
    # Strip trailing punctuation (colons, dashes, pipes, etc.)
    cleaned = re.sub(r"[\s:;—–\-•·|]+$", "", cleaned)
    # Strip surrounding decorative symbols (underscores, asterisks, brackets, hashes)
    cleaned = re.sub(r"^[#*_~\-\s]+|[#*_~\-\s]+$", "", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def classify_heading(heading_text: str) -> tuple[SectionType, str]:
    """
    Classifies a raw heading text into a (SectionType, original_title) tuple.
    If the heading matches a known synonym, returns the canonical SectionType.
    If not matched, returns (SectionType.ADDITIONAL, original_title).
    Never discards unknown headings.
    """
    clean_original = heading_text.strip()
    normalized = normalize_heading_text(clean_original).lower()

    if normalized in SECTION_SYNONYMS:
        return SECTION_SYNONYMS[normalized], clean_original

    # Substring / keyword heuristics for standard variations
    if any(
        k in normalized
        for k in [
            "experience",
            "internship",
            "employment",
            "work history",
            "work background",
        ]
    ):
        return SectionType.EXPERIENCE, clean_original

    if any(
        k in normalized
        for k in [
            "education",
            "academic",
            "academics",
            "qualification",
            "scholastic",
        ]
    ):
        return SectionType.EDUCATION, clean_original

    if "project" in normalized:
        return SectionType.PROJECTS, clean_original

    if (
        any(
            k in normalized
            for k in [
                "skill",
                "competenc",
                "proficienc",
                "technolog",
                "tech stack",
            ]
        )
        or normalized == "languages known"
    ):
        return SectionType.SKILLS, clean_original

    if any(k in normalized for k in ["certif", "license", "course"]):
        return SectionType.CERTIFICATIONS, clean_original

    if any(
        k in normalized
        for k in [
            "award",
            "honor",
            "honour",
            "achievement",
            "accomplishment",
            "fellowship",
            "scholarship",
        ]
    ):
        return SectionType.AWARDS, clean_original

    if any(
        k in normalized
        for k in [
            "publicat",
            "paper",
            "patent",
            "journal",
            "proceeding",
        ]
    ):
        return SectionType.PUBLICATIONS, clean_original

    if "language" in normalized and "programming" not in normalized:
        return SectionType.LANGUAGES, clean_original

    if any(k in normalized for k in ["volunteer", "community service", "social work"]):
        return SectionType.VOLUNTEERING, clean_original

    if any(
        k in normalized
        for k in [
            "organization",
            "affiliation",
            "membership",
            "position of responsibility",
            "positions of responsibility",
            "extracurricular",
            "extra-curricular",
            "co-curricular",
            "leadership",
            "club",
        ]
    ):
        return SectionType.ORGANIZATIONS, clean_original

    if any(
        k in normalized
        for k in [
            "summary",
            "profile",
            "objective",
            "about me",
            "personal statement",
            "bio",
        ]
    ):
        return SectionType.SUMMARY, clean_original

    # Fallback to additional / unknown
    return SectionType.ADDITIONAL, clean_original


def is_probable_heading(line: str) -> bool:
    """
    Determines if a standalone text line is a section heading:
    - Length <= 60 chars
    - Not starting with bullet points (- • * >)
    - If contains colon, the text after colon must be empty (e.g. 'EDUCATION:' vs 'Technologies: Python')
    - Does not contain dates, URLs, emails, or field key-value pairs
    """
    trimmed = line.strip()
    if not trimmed:
        return False

    if len(trimmed) > 60:
        return False

    # Check if bullet point
    if re.match(r"^[•\*\-\+▪▫►✓✔–—]\s*", trimmed):
        return False

    # Key-value lines with colon (e.g. 'Technologies: React, Node', 'CGPA: 9.4', 'Location: Mumbai') are NOT headings
    if ":" in trimmed:
        parts = trimmed.split(":", 1)
        if parts[1].strip():
            return False

    # Lines with dates (e.g. '(2021 - 2025)', 'Jan 2024 - Present') are item lines, not headings
    if re.search(r"\b(?:19\d{2}|20\d{2})\b", trimmed):
        return False

    # Lines with pipe separators or URLs are item lines
    if "|" in trimmed or "http" in trimmed or "@" in trimmed:
        return False

    # Sentence ending with period is an item, not heading
    if trimmed.endswith(".") and not re.match(r"^\d+\.", trimmed):
        return False

    norm = normalize_heading_text(trimmed).lower()
    if norm in SECTION_SYNONYMS:
        return True

    # Standalone ALL CAPS section title with 2 to 5 words (e.g. 'MILITARY SERVICE', 'SECURITY CLEARANCES')
    words = trimmed.split()
    if trimmed.isupper() and 1 <= len(words) <= 5 and len(trimmed) >= 4:
        # Avoid short acronyms like MIT, IBM, AWS, USA
        if len(words) == 1 and len(trimmed) <= 4:
            return False
        return True

    return False


class SectionBlock(NamedTuple):
    """Represents a bounded document section with its classified type and elements."""

    section_type: SectionType
    original_title: str
    elements: list[ExtractedElement]
    provenance: Provenance | None
    raw_text: str


def group_elements_into_sections(
    elements: list[ExtractedElement],
) -> list[SectionBlock]:
    """
    Partitions an ordered list of ExtractedElements into structured SectionBlocks.
    Preserves exact document order and provenance.
    Any content before the first section is marked as SectionType.IDENTITY (header).
    Splits elements if an internal line is a section heading.
    """
    if not elements:
        return []

    sections: list[SectionBlock] = []
    current_type = SectionType.IDENTITY
    current_title = "Header"
    current_elements: list[ExtractedElement] = []
    current_prov: Provenance | None = elements[0].provenance if elements else None

    for elem in elements:
        text = elem.text.strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            continue

        accumulated_lines: list[str] = []

        for line in lines:
            if is_probable_heading(line):
                # Flush accumulated lines from before this heading
                if accumulated_lines:
                    sub_text = "\n".join(accumulated_lines)
                    sub_elem = ExtractedElement(
                        element_id=elem.element_id,
                        page_number=elem.page_number,
                        order=elem.order,
                        element_type=elem.element_type,
                        text=sub_text,
                        metadata=elem.metadata,
                    )
                    current_elements.append(sub_elem)
                    accumulated_lines = []

                # Close previous section if it has elements
                if current_elements:
                    full_block_text = "\n\n".join(e.text for e in current_elements)
                    sections.append(
                        SectionBlock(
                            section_type=current_type,
                            original_title=current_title,
                            elements=current_elements,
                            provenance=current_prov,
                            raw_text=full_block_text,
                        )
                    )
                    current_elements = []

                # Start new section
                sec_type, orig_title = classify_heading(line)
                current_type = sec_type
                current_title = orig_title
                current_prov = elem.provenance
            else:
                accumulated_lines.append(line)

        if accumulated_lines:
            sub_text = "\n".join(accumulated_lines)
            sub_elem = ExtractedElement(
                element_id=elem.element_id,
                page_number=elem.page_number,
                order=elem.order,
                element_type=elem.element_type,
                text=sub_text,
                metadata=elem.metadata,
            )
            current_elements.append(sub_elem)

    if current_elements:
        full_block_text = "\n\n".join(e.text for e in current_elements)
        sections.append(
            SectionBlock(
                section_type=current_type,
                original_title=current_title,
                elements=current_elements,
                provenance=current_prov,
                raw_text=full_block_text,
            )
        )

    return sections
