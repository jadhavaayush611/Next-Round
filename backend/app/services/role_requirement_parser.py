import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
)
from app.schemas.role_requirement import RequirementPreviewItem
from app.schemas.skill import SkillResponse


@dataclass
class ExtractedFragment:
    """An unmapped requirement candidate extracted from raw job description text."""

    text: str
    requirement_type: RequirementType
    importance: RequirementImportance
    source_type: RequirementSourceType = RequirementSourceType.JOB_DESCRIPTION


class RoleRequirementParser:
    """
    Deterministic, rule-based parser for extracting candidate role requirements from job descriptions.
    Operates independently of database persistence for isolated testability.

    Invariants:
    - Preserves exact extracted requirement wording verbatim without normalization to canonical skill names.
    - Classifies requirement type and importance only when explicitly supported by text or recognized headings.
    - Resolves skills via exact canonical names and registered aliases; leaves ambiguous/multi-skill candidates unmapped.
    - Fully deterministic: identical input produces identical output.
    """

    # Section heading patterns
    RE_HEADING_MARKDOWN = re.compile(r"^#{1,6}\s+(.+)$")
    RE_HEADING_COLON = re.compile(r"^([A-Za-z0-9\s/&'-]{2,60}):\s*$")

    # Bullet point prefix patterns
    RE_BULLET = re.compile(r"^\s*[-*+•–—]\s+(.+)$")
    RE_NUMBERED = re.compile(r"^\s*\d+[\.\)]\s+(.+)$")

    # In-line importance cues
    RE_INLINE_REQUIRED = re.compile(
        r"\b(must(?:\s+(?:have|be))?|required|mandatory|essential|minimum(?:\s+of)?)\b",
        re.IGNORECASE,
    )
    RE_INLINE_PREFERRED = re.compile(
        r"\b(preferred|nice\s+to\s+have|bonus(?:\s+points)?|pluses?|plus|optional|desired|ideal)\b",
        re.IGNORECASE,
    )

    # In-line requirement type cues
    RE_EXPERIENCE = re.compile(
        r"(\b\d+\+?\s*(?:to\s*\d+\+?\s*)?years?(?:\s+of)?(?:\s+experience)?\b|"
        r"\b(?:proven|prior|demonstrated|hands-on|industry)\s+experience\b|"
        r"\bexperience\s+(?:with|in|building|designing|architecting|leading)\b|"
        r"\bbackground\s+in\b)",
        re.IGNORECASE,
    )
    RE_QUALIFICATION = re.compile(
        r"(?<![a-zA-Z0-9_])(?:bachelor'?s?|master'?s?|ph\.?d\.?|doctorate|b\.s\.|m\.s\.|b\.e\.|b\.tech|m\.tech|(?:bs|ms|ba)\s+(?:degree|in)|degree\s+in|diploma|certified|certification)(?![a-zA-Z0-9_])",
        re.IGNORECASE,
    )
    RE_SKILL_CUES = re.compile(
        r"(\b(?:proficien(?:t|cy)|fluent|fluency|expert|expertise|skilled\s+in|knowledge\s+of|familiarity\s+with)\b)",
        re.IGNORECASE,
    )

    # Section heading keyword sets
    REQUIRED_HEADING_KEYWORDS = {
        "requirements",
        "required",
        "required qualifications",
        "minimum qualifications",
        "basic qualifications",
        "what you need",
        "what you'll need",
        "what you will need",
        "must have",
        "must-have",
        "who you are",
        "what we are looking for",
        "what we're looking for",
        "what you bring",
        "eligibility",
        "qualifications",
    }

    PREFERRED_HEADING_KEYWORDS = {
        "preferred",
        "preferred qualifications",
        "preferred skills",
        "nice to have",
        "nice-to-have",
        "bonus",
        "bonus points",
        "bonus qualifications",
        "desired",
        "desired skills",
        "pluses",
        "additional qualifications",
        "good to have",
    }

    SKILL_HEADING_KEYWORDS = {
        "skills",
        "technical skills",
        "tech stack",
        "technologies",
        "core skills",
        "tools & technologies",
        "programming languages",
    }

    IGNORED_HEADING_KEYWORDS = {
        "about us",
        "about the company",
        "who we are",
        "our mission",
        "company overview",
        "benefits",
        "perks",
        "what we offer",
        "compensation",
        "salary",
        "equal opportunity",
        "diversity",
        "how to apply",
        "interview process",
        "responsibilities",
        "what you'll do",
        "what you will do",
        "the role",
        "job summary",
    }

    def _normalize_heading(self, text: str) -> str:
        """Strip markdown markers, trailing colons, and whitespace to match heading keywords."""
        cleaned = text.strip()
        cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
        cleaned = cleaned.rstrip(":").strip().lower()
        return cleaned

    def _classify_heading(
        self, raw_heading: str
    ) -> tuple[bool, RequirementImportance, RequirementType | None]:
        """
        Classify a section heading into (is_ignored, importance, default_type).
        Prioritizes requirement/qualification keywords over ignored keywords to prevent
        compound headings (e.g. 'Responsibilities & Requirements') from being skipped.
        """
        norm = self._normalize_heading(raw_heading)

        # 1. Preferred keywords
        for kw in self.PREFERRED_HEADING_KEYWORDS:
            if kw in norm:
                return False, RequirementImportance.PREFERRED, None

        # 2. Required keywords
        for kw in self.REQUIRED_HEADING_KEYWORDS:
            if kw in norm:
                return False, RequirementImportance.REQUIRED, None

        # 3. Technical skill keywords
        for kw in self.SKILL_HEADING_KEYWORDS:
            if kw in norm:
                return False, RequirementImportance.UNSPECIFIED, RequirementType.SKILL

        # 4. Ignored keywords (only when not containing requirement/skill keywords)
        for kw in self.IGNORED_HEADING_KEYWORDS:
            if norm == kw or norm.startswith(kw):
                return True, RequirementImportance.UNSPECIFIED, None

        return False, RequirementImportance.UNSPECIFIED, None

    def _classify_type(
        self, text: str, section_type: RequirementType | None
    ) -> RequirementType:
        """
        Conservatively determine requirement type using explicit cues or section context.
        Defaults to OTHER when text is ambiguous or lacks explicit signals.
        """
        if section_type is not None:
            return section_type

        # Check explicit cues in priority order: Experience -> Qualification -> Skill -> Other
        if self.RE_EXPERIENCE.search(text):
            return RequirementType.EXPERIENCE

        if self.RE_QUALIFICATION.search(text):
            return RequirementType.QUALIFICATION

        if self.RE_SKILL_CUES.search(text):
            return RequirementType.SKILL

        return RequirementType.OTHER

    def _classify_importance(
        self, text: str, section_importance: RequirementImportance
    ) -> RequirementImportance:
        """
        Determine requirement importance. In-line explicit cues override section defaults.
        """
        if self.RE_INLINE_REQUIRED.search(text):
            return RequirementImportance.REQUIRED

        if self.RE_INLINE_PREFERRED.search(text):
            return RequirementImportance.PREFERRED

        return section_importance

    def _split_semicolon_clauses(self, content: str) -> list[str]:
        """
        Split compound requirement text on semicolons while:
        - Ignoring semicolons inside HTML entities (e.g. '&amp;', '&#39;').
        - Ignoring trailing semicolons at the end of lines or bullets.
        - Preserving ordinary prose when followed by transitional adverbs
          (e.g. '; however,', '; therefore,', '; e.g.,', '; i.e.,').
        - Preserving exact clause wording without unneeded mutation.
        """
        s = content.strip()
        indices = [i for i, ch in enumerate(s) if ch == ";"]
        if not indices:
            return [s]

        split_points: list[int] = []
        for idx in indices:
            # Check if preceded by HTML entity (e.g. &amp; or &#123;)
            prefix = s[:idx]
            if re.search(r"&[a-zA-Z0-9#]+$", prefix):
                continue

            # Trailing semicolon at the end of the text is just sentence/bullet punctuation
            remainder = s[idx + 1 :]
            if not remainder.strip():
                continue

            # Do not split ordinary prose when followed by transitional adverbs
            if re.match(
                r"^\s*(?:however|therefore|nevertheless|e\.g\.|i\.e\.|that is)\b",
                remainder,
                re.IGNORECASE,
            ):
                continue

            # Clause boundary must be followed by whitespace or newline
            if remainder and not remainder[0].isspace():
                continue

            split_points.append(idx)

        if not split_points:
            return [s.rstrip(";").strip()]

        clauses: list[str] = []
        start = 0
        for sp in split_points:
            chunk = s[start:sp].strip()
            if chunk:
                clauses.append(chunk)
            start = sp + 1
        tail = s[start:].rstrip(";").strip()
        if tail:
            clauses.append(tail)

        return clauses

    @staticmethod
    def _build_skill_pattern(term: str) -> re.Pattern[str]:
        """
        Build a regex pattern for matching a skill term respecting technical punctuation boundaries.
        Supports:
        - Trailing punctuation: 'C++', 'C#'
        - Leading punctuation: '.NET'
        - Internal punctuation: 'Node.js', 'CI/CD', 'scikit-learn'
        - Multi-word terms with variable internal whitespace: 'Ruby on Rails'
        - Single-letter skills: 'C' avoiding false positive in 'C++' or 'C#'
        """
        term_clean = term.strip()
        parts = [re.escape(w) for w in term_clean.split()]
        escaped_term = r"\s+".join(parts)

        # Left boundary
        if term_clean and re.match(r"[a-zA-Z0-9_]", term_clean[0]):
            left = r"(?<![a-zA-Z0-9_])"
        else:
            left = r"(?<![a-zA-Z0-9_\.])"

        # Right boundary
        if term_clean and re.match(r"[a-zA-Z0-9_]", term_clean[-1]):
            if len(term_clean) == 1 and term_clean.isalpha():
                right = r"(?![a-zA-Z0-9_+#])"
            else:
                right = r"(?![a-zA-Z0-9_])"
        else:
            right = r"(?![a-zA-Z0-9_+#])"

        return re.compile(left + escaped_term + right, re.IGNORECASE)

    def extract_candidates(self, text: str | None) -> list[ExtractedFragment]:
        """
        Extract requirement candidate fragments from headings, bullets, paragraphs, and lines.
        Handles compound requirements delimited by semicolons.
        Preserves original wording without modification.
        """
        if not text or not text.strip():
            return []

        lines = text.splitlines()
        candidates: list[ExtractedFragment] = []

        is_ignored_section = False
        section_importance = RequirementImportance.UNSPECIFIED
        section_type: RequirementType | None = None
        has_any_requirements_section = False

        # First pass: check if document contains recognizable requirement sections
        for raw_line in lines:
            line_str = raw_line.strip()
            if not line_str:
                continue
            norm = self._normalize_heading(line_str)
            if (
                any(kw in norm for kw in self.REQUIRED_HEADING_KEYWORDS)
                or any(kw in norm for kw in self.PREFERRED_HEADING_KEYWORDS)
                or any(kw in norm for kw in self.SKILL_HEADING_KEYWORDS)
            ):
                has_any_requirements_section = True
                break

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Check if line is a section heading
            is_heading = False
            heading_match = self.RE_HEADING_MARKDOWN.match(line)
            if heading_match:
                is_heading = True
                raw_h = heading_match.group(1)
            else:
                colon_match = self.RE_HEADING_COLON.match(line)
                if colon_match:
                    is_heading = True
                    raw_h = colon_match.group(1)
                elif line.isupper() and len(line.split()) <= 4:
                    is_heading = True
                    raw_h = line

            if is_heading:
                (
                    is_ignored_section,
                    section_importance,
                    section_type,
                ) = self._classify_heading(raw_h)
                continue

            # If current section is marked as ignored (e.g. About Us, Benefits), skip
            if is_ignored_section:
                continue

            # If document has explicit requirement sections, only parse lines within recognized requirement sections
            # unless line is an explicit bullet point
            bullet_match = self.RE_BULLET.match(line) or self.RE_NUMBERED.match(line)
            if not bullet_match and has_any_requirements_section:
                # If under an unspecified, non-requirement section and not a bullet, skip
                if (
                    section_importance == RequirementImportance.UNSPECIFIED
                    and section_type is None
                ):
                    continue

            content = bullet_match.group(1) if bullet_match else line

            # Handle compound requirements separated by semicolons
            # e.g. "5+ years experience; strong Python skills; BS degree"
            sub_clauses = self._split_semicolon_clauses(content)

            for sub_clause in sub_clauses:
                req_type = self._classify_type(sub_clause, section_type)
                importance = self._classify_importance(sub_clause, section_importance)

                candidates.append(
                    ExtractedFragment(
                        text=sub_clause,
                        requirement_type=req_type,
                        importance=importance,
                    )
                )

        return candidates

    def match_skill(
        self,
        text: str,
        catalog_skills: list[SkillResponse] | None = None,
        skill_resolver: Callable[[str], SkillResponse | None] | None = None,
    ) -> tuple[uuid.UUID | None, str | None]:
        """
        Deterministically match exact canonical skill names or registered aliases against text.
        Conservative mapping invariants:
        - If text exactly matches a canonical skill or registered alias -> maps to that skill.
        - If text unambiguously mentions exactly one skill via boundary match -> maps to that skill.
        - If text mentions multiple distinct skills -> returns (None, None) (ambiguous/compound).
        - If text mentions no known skill -> returns (None, None) (unmapped).
        """
        if not catalog_skills and not skill_resolver:
            return None, None

        # 1. Exact match test: check if the entire fragment resolves directly
        if skill_resolver:
            try:
                resolved = skill_resolver(text)
                if resolved:
                    return resolved.id, resolved.canonical_name
            except Exception:
                # Ambiguous match in resolver -> remain unmapped
                return None, None

        if not catalog_skills:
            return None, None

        # 2. Scan catalog for skill mentions, recording match spans
        raw_spans: list[tuple[int, int, uuid.UUID, str, int]] = []

        for skill in catalog_skills:
            terms = [skill.canonical_name] + list(skill.aliases)
            for term in terms:
                if not term or not term.strip():
                    continue
                pattern = self._build_skill_pattern(term)
                for match in pattern.finditer(text):
                    raw_spans.append(
                        (
                            match.start(),
                            match.end(),
                            skill.id,
                            skill.canonical_name,
                            len(term.strip()),
                        )
                    )

        if not raw_spans:
            return None, None

        # 3. Filter out sub-spans: spans strictly contained within a longer matching span
        # e.g., 'React' within 'React Native', or 'Kafka' within 'Apache Kafka'
        filtered_spans: list[tuple[int, int, uuid.UUID, str, int]] = []
        for i, s1 in enumerate(raw_spans):
            contained = False
            for j, s2 in enumerate(raw_spans):
                if (
                    i != j
                    and s2[0] <= s1[0]
                    and s1[1] <= s2[1]
                    and (s2[1] - s2[0] > s1[1] - s1[0])
                ):
                    contained = True
                    break
            if not contained:
                filtered_spans.append(s1)

        # 4. Count distinct skill IDs remaining among independent matches
        distinct_skills: dict[uuid.UUID, str] = {
            span[2]: span[3] for span in filtered_spans
        }

        # If exactly one skill is unambiguously referenced
        if len(distinct_skills) == 1:
            skill_id, canonical_name = next(iter(distinct_skills.items()))
            return skill_id, canonical_name

        # If 0 or >1 distinct skills -> ambiguous/compound requirement, remains unmapped
        return None, None

    def parse(
        self,
        text: str | None,
        catalog_skills: list[SkillResponse] | None = None,
        skill_resolver: Callable[[str], SkillResponse | None] | None = None,
    ) -> list[RequirementPreviewItem]:
        """
        Extract requirements and map skills deterministically.
        """
        candidates = self.extract_candidates(text)
        preview_items: list[RequirementPreviewItem] = []

        for cand in candidates:
            skill_id, matched_name = self.match_skill(
                cand.text,
                catalog_skills=catalog_skills,
                skill_resolver=skill_resolver,
            )

            # If skill was unambiguously matched, ensure requirement_type is SKILL
            final_type = (
                RequirementType.SKILL if skill_id is not None else cand.requirement_type
            )

            preview_items.append(
                RequirementPreviewItem(
                    requirement_text=cand.text,
                    requirement_type=final_type,
                    importance=cand.importance,
                    source_type=cand.source_type,
                    skill_id=skill_id,
                    matched_skill_name=matched_name,
                )
            )

        return preview_items
