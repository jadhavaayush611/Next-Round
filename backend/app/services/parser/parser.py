import re

from app.schemas.canonical_resume import (
    AdditionalSection,
    AwardItem,
    CandidateIdentity,
    CanonicalResume,
    CertificationItem,
    DateInfo,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    LinkItem,
    OrganizationItem,
    ProjectItem,
    PublicationItem,
    SkillCategory,
    SummarySection,
    VolunteeringItem,
)
from app.services.extraction.models import (
    ExtractedDocument,
    ExtractedElement,
    ExtractionResult,
    Provenance,
)
from app.services.parser.dates import (
    extract_date_from_text,
)
from app.services.parser.sections import (
    SectionBlock,
    SectionType,
    group_elements_into_sections,
)

# Common regex patterns
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(
    r"(?:\+?91[-.\s]?)?[6-9]\d{4}[-.\s]?\d{5}|\+?\d{1,3}[-.\s]?(?:\(\d{2,4}\)|\d{2,4})[-.\s]?\d{3,4}[-.\s]?\d{3,4}|\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)

URL_REGEX = re.compile(
    r"(?:https?://[^\s,]+|www\.[^\s,]+|github\.com/[^\s,]+|linkedin\.com/in/[^\s,]+)",
    re.IGNORECASE,
)

DEGREE_PATTERNS = [
    r"\bB\.?Tech(?:\.|\b|(?=\s))",
    r"\bB\.?E(?:\.|\b|(?=\s))",
    r"\bM\.?Tech(?:\.|\b|(?=\s))",
    r"\bM\.?E(?:\.|\b|(?=\s))",
    r"\bB\.?C\.?A(?:\.|\b|(?=\s))",
    r"\bM\.?C\.?A(?:\.|\b|(?=\s))",
    r"\bB\.?Sc(?:\.|\b|(?=\s))",
    r"\bM\.?Sc(?:\.|\b|(?=\s))",
    r"\bB\.?S\.?(?:\b|(?=\s))",
    r"\bM\.?S\.?(?:\b|(?=\s))",
    r"\bB\.?A\.?(?:\b|(?=\s))",
    r"\bM\.?A\.?(?:\b|(?=\s))",
    r"\bPh\.?D\.?(?:\b|(?=\s))",
    r"\bDoctor of Philosophy\b",
    r"\bBachelor of Technology\b",
    r"\bBachelor of Engineering\b",
    r"\bBachelor of Science\b",
    r"\bBachelor of Arts\b",
    r"\bMaster of Technology\b",
    r"\bMaster of Science\b",
    r"\bMaster of Business Administration\b",
    r"\bMBA\b",
    r"\bHigher Secondary(?:\s+School)?\b",
    r"\bSenior Secondary\b",
    r"\bClass\s+(?:XII|12th|X|10th)\b",
    r"\b(?:CBSE|ICSE|State Board|HSC|SSC)\b",
]

DEGREE_REGEX = re.compile(r"|".join(DEGREE_PATTERNS), re.IGNORECASE)


class SemanticResumeParser:
    """
    Deterministic, explainable Semantic Resume Parser.
    Transforms an ExtractedDocument into a CanonicalResume representation.
    Adheres strictly to core principles:
    - Standardize meaning. Preserve evidence.
    - Never invent candidate information.
    - Preserve unknown or ambiguous content in additional_sections.
    - Preserve original dates and original section titles.
    - Numeric provenance throughout.
    """

    def parse(self, document: ExtractedDocument) -> CanonicalResume:
        """Parse an ExtractedDocument into CanonicalResume."""
        if not document.elements and document.full_text:
            document = ExtractedDocument.from_text(
                text=document.full_text,
                issues=document.extraction_issues,
                metadata=document.metadata,
            )

        section_blocks = group_elements_into_sections(document.elements)

        # 1. Parse Identity and Global Links
        identity, global_links = self._parse_identity_and_links(
            section_blocks, document
        )

        # 2. Initialize canonical collections
        summary: SummarySection | None = None
        experience: list[ExperienceItem] = []
        education: list[EducationItem] = []
        projects: list[ProjectItem] = []
        skills: list[SkillCategory] = []
        certifications: list[CertificationItem] = []
        awards: list[AwardItem] = []
        publications: list[PublicationItem] = []
        languages: list[LanguageItem] = []
        volunteering: list[VolunteeringItem] = []
        organizations: list[OrganizationItem] = []
        additional_sections: list[AdditionalSection] = []

        # 3. Parse each section according to its classified type in document order
        for block in section_blocks:
            sec_type = block.section_type

            if sec_type == SectionType.IDENTITY:
                # Already processed for identity
                continue
            elif sec_type == SectionType.SUMMARY:
                if summary is None:
                    summary = self._parse_summary(block)
            elif sec_type == SectionType.EXPERIENCE:
                exp_items = self._parse_experience(block)
                experience.extend(exp_items)
            elif sec_type == SectionType.EDUCATION:
                edu_items = self._parse_education(block)
                education.extend(edu_items)
            elif sec_type == SectionType.PROJECTS:
                proj_items = self._parse_projects(block)
                projects.extend(proj_items)
            elif sec_type == SectionType.SKILLS:
                skill_cats = self._parse_skills(block)
                skills.extend(skill_cats)
            elif sec_type == SectionType.CERTIFICATIONS:
                cert_items = self._parse_certifications(block)
                certifications.extend(cert_items)
            elif sec_type == SectionType.AWARDS:
                award_items = self._parse_awards(block)
                awards.extend(award_items)
            elif sec_type == SectionType.PUBLICATIONS:
                pub_items = self._parse_publications(block)
                publications.extend(pub_items)
            elif sec_type == SectionType.LANGUAGES:
                lang_items = self._parse_languages(block)
                languages.extend(lang_items)
            elif sec_type == SectionType.VOLUNTEERING:
                vol_items = self._parse_volunteering(block)
                volunteering.extend(vol_items)
            elif sec_type == SectionType.ORGANIZATIONS:
                org_items = self._parse_organizations(block)
                organizations.extend(org_items)
            elif sec_type == SectionType.ADDITIONAL:
                add_sec = self._parse_additional_section(block)
                additional_sections.append(add_sec)

        return CanonicalResume(
            identity=identity,
            summary=summary,
            experience=experience,
            education=education,
            projects=projects,
            skills=skills,
            certifications=certifications,
            awards=awards,
            publications=publications,
            languages=languages,
            volunteering=volunteering,
            organizations=organizations,
            links=global_links,
            additional_sections=additional_sections,
        )

    def parse_text(self, text: str) -> CanonicalResume:
        """Helper to parse a plain text string."""
        doc = ExtractedDocument.from_text(text)
        return self.parse(doc)

    def parse_extraction_result(self, result: ExtractionResult) -> CanonicalResume:
        """Helper to parse an ExtractionResult directly."""
        doc = ExtractedDocument.from_extraction_result(result)
        return self.parse(doc)

    # =========================================================================
    # Section Parsers
    # =========================================================================

    def _parse_identity_and_links(
        self, blocks: list[SectionBlock], document: ExtractedDocument
    ) -> tuple[CandidateIdentity, list[LinkItem]]:
        """Extracts identity info and all hyperlinks from the document."""
        # Header block is usually the first block (before any recognized section)
        header_block = (
            blocks[0]
            if blocks and blocks[0].section_type == SectionType.IDENTITY
            else None
        )
        header_text = header_block.raw_text if header_block else ""
        header_prov = header_block.provenance if header_block else None

        # If header_text is empty, fallback to looking at top lines of document
        scan_text = header_text or "\n".join(e.text for e in document.elements[:2])

        name = self._extract_name(scan_text)
        email = self._extract_email(document.full_text)
        phone = self._extract_phone(document.full_text)
        location = self._extract_location(scan_text)

        all_links = self._extract_all_links(document.elements)
        header_links = (
            self._extract_all_links(header_block.elements)
            if header_block
            else (
                self._extract_all_links(document.elements[:1])
                if document.elements
                else []
            )
        )
        identity_links = [
            link
            for link in header_links
            if link.label in {"linkedin", "github", "portfolio", "custom"}
        ]

        identity = CandidateIdentity(
            name=name,
            email=email,
            phone=phone,
            location=location,
            links=identity_links,
            provenance=header_prov,
        )

        return identity, all_links

    def _extract_name(self, text: str) -> str | None:
        """Extracts candidate name deterministically from header text."""
        if not text:
            return None

        for line in text.split("\n"):
            clean = line.strip()
            if not clean:
                continue

            # Explicit "Name: ..." format
            m_label = re.match(
                r"^(?:Name|Full Name)\s*[:\-]\s*([A-Za-z\s\.\'\-]+)",
                clean,
                re.IGNORECASE,
            )
            if m_label:
                return m_label.group(1).strip()

            # Skip lines that are purely contacts, emails, urls, or phone numbers
            if EMAIL_REGEX.search(clean) or PHONE_REGEX.search(clean):
                # If name is before the email on the same line (e.g. "John Doe | john@example.com")
                parts = re.split(r"\s*[|•·,]\s*", clean)
                for part in parts:
                    p = part.strip()
                    if (
                        p
                        and not EMAIL_REGEX.search(p)
                        and not PHONE_REGEX.search(p)
                        and not URL_REGEX.search(p)
                        and self._is_valid_name_token(p)
                    ):
                        return p
                continue

            if URL_REGEX.search(clean):
                continue

            if self._is_valid_name_token(clean):
                return clean

        return None

    def _is_valid_name_token(self, token: str) -> bool:
        """Validates if a line/token looks like a real person name."""
        words = token.split()
        if not (1 <= len(words) <= 5):
            return False
        if len(token) > 45:
            return False
        # Avoid common titles/headings
        lower = token.lower()
        if any(
            bad in lower
            for bad in [
                "resume",
                "curriculum",
                "vitae",
                "engineer",
                "developer",
                "analyst",
                "manager",
                "intern",
                "profile",
                "contact",
                "page",
                "http",
                "university",
                "college",
                "school",
            ]
        ):
            return False
        # Must contain only letters, dots, hyphens, and spaces
        if re.match(r"^[A-Za-z\s\.\'\-]+$", token):
            return True
        return False

    def _extract_email(self, text: str) -> str | None:
        m = EMAIL_REGEX.search(text)
        return m.group(0).strip() if m else None

    def _extract_phone(self, text: str) -> str | None:
        m = PHONE_REGEX.search(text)
        if m:
            clean = m.group(0).strip()
            # Clean leading/trailing junk
            clean = clean.strip(".- \t")
            if len(re.findall(r"\d", clean)) >= 10:
                return clean
        return None

    def _extract_location(self, text: str) -> str | None:
        """Detects location (e.g. 'City, State' or 'City, Country')."""
        if not text:
            return None

        # Common location patterns in headers: e.g. "Mumbai, India", "San Francisco, CA", "Bengaluru, Karnataka"
        loc_pattern = re.compile(
            r"\b([A-Z][a-zA-Z\s]+,\s*(?:[A-Z]{2}|[A-Z][a-zA-Z\s]+))\b"
        )
        for line in text.split("\n"):
            # Avoid matching name or email lines
            if EMAIL_REGEX.search(line) or URL_REGEX.search(line):
                # Search within parts
                parts = re.split(r"\s*[|•·]\s*", line)
                for part in parts:
                    m = loc_pattern.search(part)
                    if (
                        m
                        and not EMAIL_REGEX.search(part)
                        and not URL_REGEX.search(part)
                    ):
                        cand = m.group(0).strip()
                        if len(cand.split()) <= 4:
                            return cand
            else:
                m = loc_pattern.search(line)
                if m:
                    cand = m.group(0).strip()
                    if len(cand.split()) <= 4 and not self._is_valid_name_token(cand):
                        return cand
        return None

    def _extract_all_links(self, elements: list[ExtractedElement]) -> list[LinkItem]:
        """Extracts all unique hyperlinks from all extracted elements preserving source order."""
        seen_urls: set[str] = set()
        links: list[LinkItem] = []

        for elem in elements:
            found = URL_REGEX.findall(elem.text)
            for raw_url in found:
                url_clean = raw_url.strip().rstrip(".,;)")
                if not url_clean:
                    continue
                # Normalize protocol
                normalized_url = url_clean
                if not (
                    url_clean.startswith("http://") or url_clean.startswith("https://")
                ):
                    normalized_url = f"https://{url_clean}"

                if normalized_url.lower() in seen_urls:
                    continue
                seen_urls.add(normalized_url.lower())

                # Classify label
                label = "custom"
                lower = normalized_url.lower()
                if "linkedin.com" in lower:
                    label = "linkedin"
                elif "github.com" in lower:
                    label = "github"
                elif any(
                    k in lower
                    for k in [
                        "portfolio",
                        "gitlab.com",
                        "bitbucket.org",
                        "kaggle.com",
                        "leetcode.com",
                        "hackerrank.com",
                        "codeforces.com",
                        "medium.com",
                        "dev.to",
                    ]
                ):
                    label = "portfolio"
                elif "doi.org" in lower or "arxiv.org" in lower:
                    label = "publication"

                links.append(
                    LinkItem(
                        url=normalized_url,
                        label=label,
                        provenance=elem.provenance,
                    )
                )

        return links

    def _parse_summary(self, block: SectionBlock) -> SummarySection:
        """Parses summary statement preserving exact normalized text."""
        return SummarySection(
            text=block.raw_text.strip(),
            original_title=block.original_title,
            provenance=block.provenance,
        )

    def _parse_experience(self, block: SectionBlock) -> list[ExperienceItem]:
        """Parses experience entries preserving organization, role, dates, bullets, provenance."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[ExperienceItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            date_info: DateInfo | None = None
            role: str | None = None
            org: str | None = None
            location: str | None = None
            description: list[str] = []

            # Check for dates in header lines (first 1-2 lines)
            header_lines = lines[:2]
            desc_start_idx = 1

            # Extract date from first line
            d1, clean_line1 = extract_date_from_text(header_lines[0])
            if d1:
                date_info = d1
                header_lines[0] = clean_line1

            # If second line exists and has date, check it
            if len(lines) > 1 and not date_info:
                d2, clean_line2 = extract_date_from_text(header_lines[1])
                if d2:
                    date_info = d2
                    header_lines[1] = clean_line2
                    desc_start_idx = 2

            # Parse Org, Role, Location from header line(s)
            h_text = " | ".join(h for h in header_lines[:desc_start_idx] if h)
            org, role, loc = self._parse_org_role_location(h_text)
            if loc:
                location = loc

            # If org/role not separated in first line, but we have 2 header lines
            if len(lines) > 1 and not (org and role):
                line1 = header_lines[0]
                line2 = lines[1]
                # If line2 is not a bullet point, it could be the role/org
                if not self._is_bullet_point(line2):
                    desc_start_idx = 2
                    d_in_2, c_line2 = extract_date_from_text(line2)
                    if d_in_2 and not date_info:
                        date_info = d_in_2
                        line2 = c_line2
                    if not org:
                        org = line1
                        role = line2
                    elif not role:
                        role = line2

            # Collect bullet points / description
            for line in lines[desc_start_idx:]:
                cleaned_bullet = self._clean_bullet_point(line)
                if cleaned_bullet:
                    description.append(cleaned_bullet)

            items.append(
                ExperienceItem(
                    organization=org,
                    role=role,
                    location=location,
                    dates=date_info,
                    description=description,
                    provenance=prov,
                )
            )

        return items

    def _parse_education(self, block: SectionBlock) -> list[EducationItem]:
        """Parses education entries preserving institution, degree, field of study, dates, provenance."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[EducationItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            date_info: DateInfo | None = None
            degree: str | None = None
            field_of_study: str | None = None
            institution: str | None = None
            location: str | None = None
            description: list[str] = []

            for _idx, line in enumerate(lines):
                # Extract date if present
                d, clean_l = extract_date_from_text(line)
                if d and not date_info:
                    date_info = d
                    line = clean_l

                # Check for degree
                deg_match = DEGREE_REGEX.search(line)
                if deg_match and not degree:
                    degree = deg_match.group(0).strip()
                    # Try extracting field of study (e.g. "B.Tech in Computer Science")
                    fos_match = re.search(
                        r"(?:in|of|,|-)\s+([A-Za-z\s&]+)",
                        line[deg_match.end() :],
                    )
                    if fos_match:
                        field_of_study = fos_match.group(1).strip()
                    continue

                # Check for institution
                if not institution and not self._is_bullet_point(line):
                    # Strip dates or locations
                    inst_parts = re.split(r"\s*[|•·,]\s*", line)
                    if inst_parts:
                        institution = inst_parts[0].strip()
                        if len(inst_parts) > 1 and not location:
                            location = inst_parts[-1].strip()
                    continue

                # Collect details (GPA, percentages, coursework)
                cleaned_bullet = self._clean_bullet_point(line)
                if cleaned_bullet:
                    description.append(cleaned_bullet)

            items.append(
                EducationItem(
                    institution=institution,
                    degree=degree,
                    field_of_study=field_of_study,
                    location=location,
                    dates=date_info,
                    description=description,
                    provenance=prov,
                )
            )

        return items

    def _parse_projects(self, block: SectionBlock) -> list[ProjectItem]:
        """Parses project entries preserving name, tech stack, dates, links, bullets, provenance."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[ProjectItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            name: str | None = None
            date_info: DateInfo | None = None
            technologies: list[str] = []
            links: list[LinkItem] = []
            description: list[str] = []

            # First line usually contains project title, dates, and possibly tech/links
            first_line = lines[0]
            d, clean_title = extract_date_from_text(first_line)
            date_info = d

            # Check for technologies in first line (e.g. "Project Name | React, Python")
            tech_match = re.search(
                r"(?:Technologies|Tech Stack|Tools|Built with|Stack)\s*[:\-]\s*([^\n|]+)",
                first_line,
                re.IGNORECASE,
            )
            if tech_match:
                raw_tech = tech_match.group(1).strip()
                technologies = [
                    t.strip() for t in re.split(r"[,/|•·]", raw_tech) if t.strip()
                ]
                clean_title = (
                    first_line[: tech_match.start()] + first_line[tech_match.end() :]
                ).strip()

            # Extract URLs in first line
            for u in URL_REGEX.findall(first_line):
                u_norm = (u if u.startswith("http") else f"https://{u}").rstrip(".,;)")
                links.append(LinkItem(url=u_norm, label="project", provenance=prov))
                clean_title = clean_title.replace(u, "").strip()

            # Strip separators from title
            name_parts = re.split(r"\s*[|•·]\s*", clean_title)
            name = name_parts[0].strip(" -:,()[]")

            # If second line is explicit tech stack
            desc_start = 1
            if len(lines) > 1:
                sec_line = lines[1]
                t_match2 = re.search(
                    r"^(?:Technologies|Tech Stack|Tools|Built with|Stack)\s*[:\-]\s*(.+)$",
                    sec_line,
                    re.IGNORECASE,
                )
                if t_match2:
                    raw_tech = t_match2.group(1).strip()
                    technologies.extend(
                        [t.strip() for t in re.split(r"[,/|•·]", raw_tech) if t.strip()]
                    )
                    desc_start = 2

            # Parse remaining description lines
            for line in lines[desc_start:]:
                # Extract any link inside bullets
                for u in URL_REGEX.findall(line):
                    u_norm = (u if u.startswith("http") else f"https://{u}").rstrip(
                        ".,;)"
                    )
                    links.append(LinkItem(url=u_norm, label="project", provenance=prov))

                cleaned_b = self._clean_bullet_point(line)
                if cleaned_b:
                    description.append(cleaned_b)

            items.append(
                ProjectItem(
                    name=name or clean_title,
                    description=description,
                    dates=date_info,
                    technologies=technologies,
                    links=links,
                    provenance=prov,
                )
            )

        return items

    def _parse_skills(self, block: SectionBlock) -> list[SkillCategory]:
        """Parses skills into categorized or flat skill lists preserving explicit source values."""
        categories: list[SkillCategory] = []
        raw_lines = [
            line.strip() for line in block.raw_text.split("\n") if line.strip()
        ]

        for elem in block.elements:
            lines = [line.strip() for line in elem.text.split("\n") if line.strip()]
            for line in lines:
                # Check for category pattern: "Category Name: Skill 1, Skill 2, Skill 3"
                cat_match = re.match(r"^([A-Za-z\s&/\\-]+)\s*[:\-]\s*(.+)$", line)
                if cat_match:
                    cat_name = cat_match.group(1).strip()
                    skill_text = cat_match.group(2).strip()
                    # Split skills by comma, semicolon, bullet, or pipe
                    tokens = [
                        s.strip()
                        for s in re.split(r"[,;•·|/]\s*", skill_text)
                        if s.strip()
                    ]
                    if tokens:
                        categories.append(
                            SkillCategory(
                                category=cat_name,
                                skills=tokens,
                                provenance=elem.provenance,
                            )
                        )
                else:
                    # Flat bullet or comma separated list
                    cleaned = self._clean_bullet_point(line)
                    tokens = [
                        s.strip() for s in re.split(r"[,;•·|]\s*", cleaned) if s.strip()
                    ]
                    if tokens:
                        categories.append(
                            SkillCategory(
                                category=None,
                                skills=tokens,
                                provenance=elem.provenance,
                            )
                        )

        # If no categories were extracted, produce single category with raw tokens
        if not categories and raw_lines:
            all_tokens: list[str] = []
            for raw_l in raw_lines:
                cleaned = self._clean_bullet_point(raw_l)
                all_tokens.extend(
                    [s.strip() for s in re.split(r"[,;•·|]\s*", cleaned) if s.strip()]
                )
            if all_tokens:
                categories.append(
                    SkillCategory(
                        category=None,
                        skills=all_tokens,
                        provenance=block.provenance,
                    )
                )

        return categories

    def _parse_certifications(self, block: SectionBlock) -> list[CertificationItem]:
        """Parses certification entries."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[CertificationItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            first_line = lines[0]
            d, clean_l = extract_date_from_text(first_line)
            clean_first = self._clean_bullet_point(clean_l)

            # Check for issuer in first line: e.g. "AWS Solutions Architect - Professional | Amazon Web Services"
            issuer: str | None = None
            name = clean_first
            if " | " in clean_first:
                parts = clean_first.split(" | ", maxsplit=1)
                name = parts[0].strip()
                issuer = parts[1].strip()
            elif " by " in clean_first:
                parts = clean_first.split(" by ", maxsplit=1)
                name = parts[0].strip()
                issuer = parts[1].strip()
            elif " - " in clean_first:
                parts = clean_first.split(" - ", maxsplit=1)
                name = parts[0].strip()
                issuer = parts[1].strip()

            # Check for Credential ID or Link in remaining lines
            credential_id: str | None = None
            links: list[LinkItem] = []
            for line in lines[1:]:
                cid_match = re.search(
                    r"(?:Credential ID|License|ID)\s*[:\-]\s*([A-Za-z0-9\-_]+)",
                    line,
                    re.IGNORECASE,
                )
                if cid_match:
                    credential_id = cid_match.group(1).strip()
                for u in URL_REGEX.findall(line):
                    u_norm = (u if u.startswith("http") else f"https://{u}").rstrip(
                        ".,;)"
                    )
                    links.append(
                        LinkItem(url=u_norm, label="certification", provenance=prov)
                    )

            items.append(
                CertificationItem(
                    name=name,
                    issuer=issuer,
                    dates=d,
                    credential_id=credential_id,
                    links=links,
                    provenance=prov,
                )
            )

        return items

    def _parse_awards(self, block: SectionBlock) -> list[AwardItem]:
        """Parses awards and achievements."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[AwardItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            d, clean_l = extract_date_from_text(lines[0])
            clean_first = self._clean_bullet_point(clean_l)
            title = clean_first
            issuer: str | None = None
            desc: str | None = None

            if " by " in clean_first:
                parts = clean_first.split(" by ", maxsplit=1)
                title = parts[0].strip()
                issuer = parts[1].strip()
            elif " | " in clean_first:
                parts = clean_first.split(" | ", maxsplit=1)
                title = parts[0].strip()
                issuer = parts[1].strip()

            if len(lines) > 1:
                desc = "\n".join(
                    self._clean_bullet_point(txt_line) for txt_line in lines[1:]
                ).strip()

            items.append(
                AwardItem(
                    title=title,
                    issuer=issuer,
                    dates=d,
                    description=desc,
                    provenance=prov,
                )
            )

        return items

    def _parse_publications(self, block: SectionBlock) -> list[PublicationItem]:
        """Parses publications and research papers."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[PublicationItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            d, clean_l = extract_date_from_text(lines[0])
            title = self._clean_bullet_point(clean_l)
            authors: list[str] = []
            venue: str | None = None
            links: list[LinkItem] = []
            description: str | None = None

            # Collect links
            for line in lines:
                for u in URL_REGEX.findall(line):
                    u_norm = (u if u.startswith("http") else f"https://{u}").rstrip(
                        ".,;)"
                    )
                    links.append(
                        LinkItem(url=u_norm, label="publication", provenance=prov)
                    )

            if len(lines) > 1:
                sec_line = lines[1]
                if "in " in sec_line.lower() or "proceedings" in sec_line.lower():
                    venue = sec_line.strip()
                else:
                    description = "\n".join(
                        self._clean_bullet_point(txt_line) for txt_line in lines[1:]
                    )

            items.append(
                PublicationItem(
                    title=title,
                    authors=authors,
                    venue=venue,
                    dates=d,
                    links=links,
                    description=description,
                    provenance=prov,
                )
            )

        return items

    def _parse_languages(self, block: SectionBlock) -> list[LanguageItem]:
        """Parses language proficiencies."""
        items: list[LanguageItem] = []
        for elem in block.elements:
            lines = [line.strip() for line in elem.text.split("\n") if line.strip()]
            for line in lines:
                cleaned = self._clean_bullet_point(line)
                # Check for "Language (Proficiency)" or "Language: Proficiency"
                m_prof = re.match(
                    r"^([A-Za-z\s]+)(?:\s*\(([^)]+)\)|[:\-]\s*([A-Za-z\s]+))$",
                    cleaned,
                )
                if m_prof:
                    lang = m_prof.group(1).strip()
                    prof = (m_prof.group(2) or m_prof.group(3) or "").strip() or None
                    items.append(
                        LanguageItem(
                            language=lang,
                            proficiency=prof,
                            provenance=elem.provenance,
                        )
                    )
                else:
                    # Comma separated list of languages without proficiency
                    for token in re.split(r"[,;•·|]", cleaned):
                        t = token.strip()
                        if t and len(t.split()) <= 2:
                            items.append(
                                LanguageItem(
                                    language=t,
                                    proficiency=None,
                                    provenance=elem.provenance,
                                )
                            )

        return items

    def _parse_volunteering(self, block: SectionBlock) -> list[VolunteeringItem]:
        """Parses volunteering and community service entries."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[VolunteeringItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            d, clean_l = extract_date_from_text(lines[0])
            org, role, _ = self._parse_org_role_location(clean_l)
            desc = [
                self._clean_bullet_point(txt_line)
                for txt_line in lines[1:]
                if self._clean_bullet_point(txt_line)
            ]

            items.append(
                VolunteeringItem(
                    organization=org,
                    role=role,
                    dates=d,
                    description=desc,
                    provenance=prov,
                )
            )

        return items

    def _parse_organizations(self, block: SectionBlock) -> list[OrganizationItem]:
        """Parses memberships, leadership, and club affiliations."""
        entries = self._split_section_into_entry_chunks(block)
        items: list[OrganizationItem] = []

        for chunk_text, prov in entries:
            lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
            if not lines:
                continue

            d, clean_l = extract_date_from_text(lines[0])
            org, role, _ = self._parse_org_role_location(clean_l)
            desc = [
                self._clean_bullet_point(txt_line)
                for txt_line in lines[1:]
                if self._clean_bullet_point(txt_line)
            ]

            items.append(
                OrganizationItem(
                    organization=org,
                    role=role,
                    dates=d,
                    description=desc,
                    provenance=prov,
                )
            )

        return items

    def _parse_additional_section(self, block: SectionBlock) -> AdditionalSection:
        """Preserves unclassified custom section with original title and content lines."""
        content_lines = [
            line.strip() for line in block.raw_text.split("\n") if line.strip()
        ]
        return AdditionalSection(
            original_title=block.original_title,
            content=content_lines,
            provenance=block.provenance,
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _split_section_into_entry_chunks(
        self, block: SectionBlock
    ) -> list[tuple[str, Provenance | None]]:
        """
        Splits a section block's elements/text into separate entry chunks.
        Combines multi-paragraph entries (e.g. Org line, Date line, Bullet points).
        """
        if not block.elements:
            raw = block.raw_text.strip()
            if not raw:
                return []
            sub_chunks = self._split_text_into_entries(raw)
            return [(sc, block.provenance) for sc in sub_chunks]

        entries: list[tuple[str, Provenance | None]] = []
        current_elem_texts: list[str] = []
        current_prov: Provenance | None = None
        has_seen_bullet_or_content = False

        for elem in block.elements:
            elem_txt = elem.text.strip()
            if not elem_txt:
                continue

            lines = [line.strip() for line in elem_txt.split("\n") if line.strip()]
            first_line = lines[0] if lines else ""
            is_bullet = self._is_bullet_point(first_line)
            d, _ = extract_date_from_text(first_line)

            is_new_entry_start = False
            if current_elem_texts and not is_bullet:
                if has_seen_bullet_or_content:
                    is_new_entry_start = True
                elif d and any(
                    extract_date_from_text(l_txt)[0] is not None
                    for t in current_elem_texts
                    for l_txt in t.split("\n")
                ):
                    is_new_entry_start = True

            if is_new_entry_start:
                combined_txt = "\n".join(current_elem_texts)
                sub_chunks = self._split_text_into_entries(combined_txt)
                for sc in sub_chunks:
                    entries.append((sc, current_prov))
                current_elem_texts = [elem_txt]
                current_prov = elem.provenance
                has_seen_bullet_or_content = any(
                    self._is_bullet_point(l_item) for l_item in lines
                )
            else:
                if not current_elem_texts:
                    current_prov = elem.provenance
                current_elem_texts.append(elem_txt)
                if any(self._is_bullet_point(l_item) for l_item in lines):
                    has_seen_bullet_or_content = True

        if current_elem_texts:
            combined_txt = "\n".join(current_elem_texts)
            sub_chunks = self._split_text_into_entries(combined_txt)
            for sc in sub_chunks:
                entries.append((sc, current_prov))

        return entries

    def _split_text_into_entries(self, text: str) -> list[str]:
        """Splits raw text of a section into distinct entry strings."""
        if not text:
            return []

        initial_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        result_entries: list[str] = []

        for para in initial_paragraphs:
            lines = [line.strip() for line in para.split("\n") if line.strip()]
            if not lines:
                continue

            current_entry_lines: list[str] = []
            has_seen_bullet_or_content = False

            for idx, line in enumerate(lines):
                is_bullet = self._is_bullet_point(line)
                d, _ = extract_date_from_text(line)

                is_new_entry_start = False
                if idx > 0 and not is_bullet:
                    if has_seen_bullet_or_content:
                        is_new_entry_start = True
                    elif d and any(
                        extract_date_from_text(l_txt)[0] is not None
                        for l_txt in current_entry_lines
                    ):
                        is_new_entry_start = True

                if is_new_entry_start:
                    if current_entry_lines:
                        result_entries.append("\n".join(current_entry_lines))
                    current_entry_lines = [line]
                    has_seen_bullet_or_content = False
                else:
                    current_entry_lines.append(line)
                    if is_bullet:
                        has_seen_bullet_or_content = True

            if current_entry_lines:
                result_entries.append("\n".join(current_entry_lines))

        return result_entries

    def _parse_org_role_location(
        self, line: str
    ) -> tuple[str | None, str | None, str | None]:
        """Extracts (organization, role, location) from a line."""
        clean = self._clean_bullet_point(line)
        if not clean:
            return None, None, None

        # Pattern: Role at Org, Location
        m_at = re.match(r"^(.+?)\s+at\s+([^,]+)(?:,\s*(.+))?$", clean, re.IGNORECASE)
        if m_at:
            return (
                m_at.group(2).strip(),
                m_at.group(1).strip(),
                m_at.group(3).strip() if m_at.group(3) else None,
            )

        # Pattern: Org | Role | Location
        parts = [p.strip() for p in re.split(r"\s*[|•·]\s*", clean) if p.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            # Check if second part looks like a role or location
            return parts[0], parts[1], None
        elif len(parts) == 1:
            # Check for dash separator "Org - Role"
            if " - " in parts[0]:
                sub_parts = parts[0].split(" - ")
                return sub_parts[0].strip(), sub_parts[1].strip(), None
            return parts[0], None, None

        return None, None, None

    def _is_bullet_point(self, line: str) -> bool:
        return bool(re.match(r"^[•\*\-\+▪▫►✓✔–—]\s*", line.strip()))

    def _clean_bullet_point(self, line: str) -> str:
        """Strips leading bullet point symbols and whitespace."""
        return re.sub(r"^[•\*\-\+▪▫►✓✔–—]\s*", "", line.strip()).strip()
