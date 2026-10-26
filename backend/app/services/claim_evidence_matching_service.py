import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimType
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import EvidenceSource, EvidenceSourceStatus
from app.models.user import User
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.repositories.skill import SkillRepository
from app.schemas.claim_evidence_match import (
    ClaimEvidenceMatchResponse,
    ClaimMatchStatus,
    EvidenceMatchItem,
    MatchingBasis,
)
from app.utils.skill_normalization import (
    build_skill_pattern,
    normalize_skill_name,
)

# Common filler words to ignore when extracting project keywords from claims
PROJECT_STOP_WORDS = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "about",
    "against",
    "between",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "to",
    "from",
    "up",
    "down",
    "and",
    "or",
    "as",
    "of",
    "built",
    "developed",
    "created",
    "designed",
    "implemented",
    "managed",
    "worked",
    "working",
    "maintained",
    "contributed",
    "assisted",
    "my",
    "our",
}

# Generic software development tokens that alone cannot identify a distinct project
GENERIC_PROJECT_WORDS = {
    "web",
    "application",
    "app",
    "project",
    "system",
    "platform",
    "tool",
    "service",
    "software",
    "website",
    "frontend",
    "backend",
    "fullstack",
    "mobile",
    "api",
    "dashboard",
    "portal",
    "code",
    "database",
    "program",
    "solution",
    "server",
    "client",
    "site",
    "online",
    "framework",
    "library",
    "utility",
    "component",
    "module",
    "package",
    "interface",
    "engine",
}

MATCH_PRIORITY: dict[MatchingBasis, int] = {
    MatchingBasis.REPOSITORY_NAME: 5,
    MatchingBasis.CANONICAL_SKILL_NAME: 4,
    MatchingBasis.SKILL_ALIAS: 3,
    MatchingBasis.REPOSITORY_DESCRIPTION: 2,
    MatchingBasis.DOCUMENTATION_KEYWORD: 1,
}


class ClaimEvidenceMatchingService:
    """
    Dedicated deterministic read-only service for discovering potentially relevant
    candidate-owned evidence items for a given CandidateClaim.

    Core Invariants:
    1. Read-Only: Never creates, mutates, or deletes CandidateClaim, EvidenceItem,
       CandidateSkillEvidence, or VerificationResult records.
    2. Candidate Isolation: Only inspects evidence sources and items owned by the same candidate.
    3. Relevance vs. Verification: Matches indicate relevance / thematic overlap only;
       they do NOT establish authenticity, authorship, employment, or skill proficiency.
    4. Conservative Rules:
       - SKILL: exact canonical and alias matching across metadata and documentation.
       - PROJECT: repository name and description correspondence.
       - EXPERIENCE: identifies relevant project/technology overlap without inferring employment,
         job title, duration, or professional responsibility.
       - EDUCATION & CERTIFICATION: always returns NOT_APPLICABLE.
       - OTHER: always returns NOT_APPLICABLE.
    """

    def __init__(self, db: Session):
        self.db = db
        self.claim_repo = CandidateClaimRepository(db)
        self.source_repo = EvidenceSourceRepository(db)
        self.item_repo = EvidenceItemRepository(db)
        self.skill_repo = SkillRepository(db)

    def find_evidence_matches(
        self, user: User, claim_id: uuid.UUID, limit: int = 20
    ) -> ClaimEvidenceMatchResponse:
        """
        Evaluate a candidate claim against candidate-owned evidence items to discover
        potentially relevant observations.
        """
        claim = self.claim_repo.get_by_id(claim_id)
        if not claim or claim.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate claim not found.",
            )

        # 1. Non-applicable claim types: EDUCATION, CERTIFICATION, OTHER
        if claim.claim_type in (ClaimType.EDUCATION, ClaimType.CERTIFICATION):
            return self._build_not_applicable_response(
                claim,
                summary=(
                    "Repository and code evidence cannot verify education or certification claims. "
                    "Evidence matching is not applicable for this claim type."
                ),
            )

        if claim.claim_type == ClaimType.OTHER:
            return self._build_not_applicable_response(
                claim,
                summary="Evidence matching is not supported for claims classified as OTHER.",
            )

        # 2. Inspect candidate evidence sources and items
        sources = list(self.source_repo.list_by_user(user.id))
        sources_summary = {st.value: 0 for st in EvidenceSourceStatus}
        for s in sources:
            sources_summary[s.access_status.value] += 1

        items = list(self.item_repo.list_by_user(user.id))

        available_sources = [
            s for s in sources if s.access_status == EvidenceSourceStatus.AVAILABLE
        ]
        available_source_ids = {s.id for s in available_sources}
        non_available_sources = [
            s for s in sources if s.access_status != EvidenceSourceStatus.AVAILABLE
        ]

        available_items = [
            i for i in items if i.evidence_source_id in available_source_ids
        ]
        unavailable_items = [
            i for i in items if i.evidence_source_id not in available_source_ids
        ]

        if not sources or not available_items:
            limitation_note = ""
            if unavailable_items:
                limitation_note = (
                    f" Note: {len(unavailable_items)} observation(s) from {len(non_available_sources)} "
                    f"non-available (revoked, inaccessible, or errored) source(s) were excluded from active matching."
                )
            return self._build_response(
                claim=claim,
                status=ClaimMatchStatus.INSUFFICIENT_DATA,
                summary=(
                    "Insufficient active evidence: no observations from currently AVAILABLE evidence sources "
                    f"are available to evaluate for this claim.{limitation_note}"
                ),
                matches=[],
                total_matches=0,
                sources_inspected=len(sources),
                items_inspected=0,
                sources_summary=sources_summary,
            )

        # Map available sources by ID for fast lookup
        sources_by_id = {s.id: s for s in available_sources}

        # 3. Deterministic matching per claim type against available items only
        raw_matches: list[EvidenceMatchItem] = []
        if claim.claim_type == ClaimType.SKILL:
            raw_matches = self._match_skill_claim(claim, available_items, sources_by_id)
        elif claim.claim_type == ClaimType.PROJECT:
            raw_matches = self._match_project_claim(
                claim, available_items, sources_by_id
            )
        elif claim.claim_type == ClaimType.EXPERIENCE:
            raw_matches = self._match_experience_claim(
                claim, available_items, sources_by_id
            )

        # 4. Deduplicate per evidence_item_id, picking highest-priority match
        best_matches_by_item: dict[uuid.UUID, EvidenceMatchItem] = {}
        for m in raw_matches:
            existing = best_matches_by_item.get(m.evidence_item_id)
            if (
                not existing
                or MATCH_PRIORITY[m.matching_basis]
                > MATCH_PRIORITY[existing.matching_basis]
            ):
                best_matches_by_item[m.evidence_item_id] = m

        # 5. Deterministic sorting: priority desc, then item ID asc
        sorted_matches = sorted(
            best_matches_by_item.values(),
            key=lambda m: (-MATCH_PRIORITY[m.matching_basis], str(m.evidence_item_id)),
        )

        bounded_matches = sorted_matches[:limit]
        total_matches = len(sorted_matches)

        limitation_note = ""
        if unavailable_items:
            limitation_note = (
                f" Note: {len(unavailable_items)} observation(s) from {len(non_available_sources)} "
                f"non-available (revoked, inaccessible, or errored) source(s) were excluded from active matching."
            )

        if total_matches > 0:
            match_status = ClaimMatchStatus.POTENTIAL_MATCH
            summary = (
                f"Identified {total_matches} potential evidence match(es) across {len(available_items)} "
                f"available observation(s). Relevance indicates keyword presence only; authenticity, authorship, "
                f"and proficiency remain unverified.{limitation_note}"
            )
        else:
            match_status = ClaimMatchStatus.NO_MATCH
            summary = (
                f"No matching evidence items found across {len(available_items)} available collected "
                f"observation(s) for this claim.{limitation_note}"
            )

        return self._build_response(
            claim=claim,
            status=match_status,
            summary=summary,
            matches=bounded_matches,
            total_matches=total_matches,
            sources_inspected=len(sources),
            items_inspected=len(available_items),
            sources_summary=sources_summary,
        )

    # -------------------------------------------------------------------------
    # Matching Subroutines
    # -------------------------------------------------------------------------

    def _match_skill_claim(
        self,
        claim: CandidateClaim,
        items: list[EvidenceItem],
        sources_by_id: dict[uuid.UUID, EvidenceSource],
    ) -> list[EvidenceMatchItem]:
        """Match SKILL claims using canonical skill names and registered aliases."""
        target_skills = self._resolve_target_skills(claim.claim_text)
        matches: list[EvidenceMatchItem] = []

        for item in items:
            source = sources_by_id.get(item.evidence_source_id)
            if not source or source.access_status != EvidenceSourceStatus.AVAILABLE:
                continue

            observed = item.observed_data or {}
            locator = item.source_locator or (
                "README.md"
                if item.evidence_type == EvidenceType.DOCUMENTATION
                else "repository_metadata"
            )

            for term, is_canonical in target_skills:
                term_clean = term.strip()
                if not term_clean:
                    continue

                basis = (
                    MatchingBasis.CANONICAL_SKILL_NAME
                    if is_canonical
                    else MatchingBasis.SKILL_ALIAS
                )

                if item.evidence_type == EvidenceType.REPOSITORY_METADATA:
                    primary_lang = str(observed.get("primary_language") or "").strip()
                    topics = [
                        str(t).strip() for t in (observed.get("topics") or []) if t
                    ]
                    desc = str(observed.get("description") or "").strip()

                    # 1. Primary language match
                    if normalize_skill_name(primary_lang) == normalize_skill_name(
                        term_clean
                    ):
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=basis,
                                matched_term=primary_lang,
                                explanation=(
                                    f"Repository primary language '{primary_lang}' matches skill '{term_clean}'. "
                                    f"Relevance indicates keyword presence only; authorship and proficiency remain unverified."
                                ),
                            )
                        )
                        continue

                    # 2. Topic match
                    topic_match = next(
                        (
                            t
                            for t in topics
                            if normalize_skill_name(t)
                            == normalize_skill_name(term_clean)
                        ),
                        None,
                    )
                    if topic_match:
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=basis,
                                matched_term=topic_match,
                                explanation=(
                                    f"Repository topic '{topic_match}' matches skill '{term_clean}'. "
                                    f"Relevance indicates keyword presence only; authorship and proficiency remain unverified."
                                ),
                            )
                        )
                        continue

                    # 3. Description match
                    pattern = build_skill_pattern(term_clean)
                    if desc and pattern.search(desc):
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=MatchingBasis.REPOSITORY_DESCRIPTION,
                                matched_term=term_clean,
                                explanation=(
                                    f"Skill '{term_clean}' referenced in repository description. "
                                    f"Relevance indicates keyword presence only; authorship and proficiency remain unverified."
                                ),
                            )
                        )
                        continue

                elif item.evidence_type == EvidenceType.DOCUMENTATION:
                    content = str(observed.get("content") or "")
                    pattern = build_skill_pattern(term_clean)
                    if content and pattern.search(content):
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=MatchingBasis.DOCUMENTATION_KEYWORD,
                                matched_term=term_clean,
                                explanation=(
                                    f"Skill '{term_clean}' referenced in documentation ({locator}). "
                                    f"Relevance indicates keyword presence only; authorship and proficiency remain unverified."
                                ),
                            )
                        )
                        continue

        return matches

    def _match_project_claim(
        self,
        claim: CandidateClaim,
        items: list[EvidenceItem],
        sources_by_id: dict[uuid.UUID, EvidenceSource],
    ) -> list[EvidenceMatchItem]:
        """Match PROJECT claims using repository name, description, and documentation."""
        matches: list[EvidenceMatchItem] = []
        claim_text_norm = claim.claim_text.strip().lower()

        # Extract tokens from claim: filter stop words and categorize distinctiveness
        all_tokens = [
            w
            for w in re.findall(r"[a-zA-Z0-9_-]+", claim_text_norm)
            if len(w) >= 3 and w not in PROJECT_STOP_WORDS
        ]
        distinctive_tokens = [w for w in all_tokens if w not in GENERIC_PROJECT_WORDS]

        for item in items:
            source = sources_by_id.get(item.evidence_source_id)
            if not source or source.access_status != EvidenceSourceStatus.AVAILABLE:
                continue

            observed = item.observed_data or {}
            locator = item.source_locator or (
                "README.md"
                if item.evidence_type == EvidenceType.DOCUMENTATION
                else "repository_metadata"
            )

            if item.evidence_type == EvidenceType.REPOSITORY_METADATA:
                full_name = str(observed.get("full_name") or "").strip()
                repo_name = full_name.split("/")[-1] if "/" in full_name else full_name
                repo_desc = str(observed.get("description") or "").strip()

                repo_name_norm = repo_name.lower()
                repo_name_spaced = repo_name_norm.replace("-", " ").replace("_", " ")

                repo_tokens = re.findall(r"[a-zA-Z0-9]+", repo_name_norm)
                is_repo_generic = bool(
                    repo_tokens
                    and all(
                        tok in GENERIC_PROJECT_WORDS or tok in PROJECT_STOP_WORDS
                        for tok in repo_tokens
                    )
                )

                # 1. Repository name match:
                # - Exact match is always accepted
                # - Substring match requires the repository name to have distinctive tokens (not purely generic words)
                repo_matched = False
                if (
                    repo_name_norm == claim_text_norm
                    or repo_name_spaced == claim_text_norm
                ):
                    repo_matched = True
                elif not is_repo_generic:
                    if re.search(
                        r"\b" + re.escape(repo_name_norm) + r"\b", claim_text_norm
                    ):
                        repo_matched = True
                    elif len(repo_name_spaced) >= 4 and re.search(
                        r"\b" + re.escape(repo_name_spaced) + r"\b", claim_text_norm
                    ):
                        repo_matched = True

                if repo_matched:
                    matches.append(
                        EvidenceMatchItem(
                            evidence_item_id=item.id,
                            evidence_source_id=item.evidence_source_id,
                            evidence_type=item.evidence_type,
                            source_locator=locator,
                            matching_basis=MatchingBasis.REPOSITORY_NAME,
                            matched_term=repo_name,
                            explanation=(
                                f"Repository name '{repo_name}' matches project claim text. "
                                f"Relevance indicates name correspondence only; authorship and contribution scope remain unverified."
                            ),
                        )
                    )
                    continue

                # 2. Significant description overlap:
                # Generic tokens alone (e.g. 'web', 'app', 'application') NEVER match.
                # Requires distinctive tokens in the claim matching words in repository description.
                if repo_desc and distinctive_tokens:
                    matching_tokens = [
                        w
                        for w in distinctive_tokens
                        if re.search(r"\b" + re.escape(w) + r"\b", repo_desc.lower())
                    ]
                    # Accept if:
                    # - At least 2 distinctive tokens match
                    # - Or 1 distinctive token matches and it is substantive (length >= 4)
                    if len(matching_tokens) >= 2 or (
                        len(matching_tokens) == 1 and len(matching_tokens[0]) >= 4
                    ):
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=MatchingBasis.REPOSITORY_DESCRIPTION,
                                matched_term=", ".join(matching_tokens[:3]),
                                explanation=(
                                    f"Repository description contains keywords ({', '.join(matching_tokens[:3])}) "
                                    f"matching project claim. Relevance only; authorship and contribution scope remain unverified."
                                ),
                            )
                        )
                        continue

            elif item.evidence_type == EvidenceType.DOCUMENTATION:
                # Check if repo name corresponds to project claim
                parent_meta = next(
                    (
                        i
                        for i in items
                        if i.evidence_source_id == item.evidence_source_id
                        and i.evidence_type == EvidenceType.REPOSITORY_METADATA
                    ),
                    None,
                )
                repo_name = ""
                if parent_meta and parent_meta.observed_data:
                    full_name = str(parent_meta.observed_data.get("full_name") or "")
                    repo_name = (
                        full_name.split("/")[-1] if "/" in full_name else full_name
                    )

                repo_name_norm = repo_name.lower() if repo_name else ""
                repo_name_spaced = (
                    repo_name_norm.replace("-", " ").replace("_", " ")
                    if repo_name_norm
                    else ""
                )

                repo_tokens = (
                    re.findall(r"[a-zA-Z0-9]+", repo_name_norm)
                    if repo_name_norm
                    else []
                )
                is_repo_generic = bool(
                    repo_tokens
                    and all(
                        tok in GENERIC_PROJECT_WORDS or tok in PROJECT_STOP_WORDS
                        for tok in repo_tokens
                    )
                )

                matched_doc = False
                if repo_name_norm:
                    if (
                        repo_name_norm == claim_text_norm
                        or repo_name_spaced == claim_text_norm
                    ):
                        matched_doc = True
                    elif not is_repo_generic:
                        if re.search(
                            r"\b" + re.escape(repo_name_norm) + r"\b", claim_text_norm
                        ):
                            matched_doc = True
                        elif len(repo_name_spaced) >= 4 and re.search(
                            r"\b" + re.escape(repo_name_spaced) + r"\b",
                            claim_text_norm,
                        ):
                            matched_doc = True

                if matched_doc:
                    matches.append(
                        EvidenceMatchItem(
                            evidence_item_id=item.id,
                            evidence_source_id=item.evidence_source_id,
                            evidence_type=item.evidence_type,
                            source_locator=locator,
                            matching_basis=MatchingBasis.DOCUMENTATION_KEYWORD,
                            matched_term=repo_name,
                            explanation=(
                                f"Documentation ({locator}) in repository '{repo_name}' corresponds to project claim. "
                                f"Relevance only; authorship and contribution scope remain unverified."
                            ),
                        )
                    )

        return matches

        return matches

    def _match_experience_claim(
        self,
        claim: CandidateClaim,
        items: list[EvidenceItem],
        sources_by_id: dict[uuid.UUID, EvidenceSource],
    ) -> list[EvidenceMatchItem]:
        """
        Match EXPERIENCE claims by identifying potentially relevant technologies or projects.
        Strictly preserves disclaimer: never infers employment, job title, duration, or responsibility.
        """
        target_skills = self._resolve_target_skills(claim.claim_text)
        matches: list[EvidenceMatchItem] = []

        for item in items:
            source = sources_by_id.get(item.evidence_source_id)
            if not source or source.access_status != EvidenceSourceStatus.AVAILABLE:
                continue

            observed = item.observed_data or {}
            locator = item.source_locator or (
                "README.md"
                if item.evidence_type == EvidenceType.DOCUMENTATION
                else "repository_metadata"
            )

            for term, is_canonical in target_skills:
                term_clean = term.strip()
                if not term_clean or len(term_clean) < 2:
                    continue

                pattern = build_skill_pattern(term_clean)

                if item.evidence_type == EvidenceType.REPOSITORY_METADATA:
                    primary_lang = str(observed.get("primary_language") or "").strip()
                    topics = [
                        str(t).strip() for t in (observed.get("topics") or []) if t
                    ]
                    desc = str(observed.get("description") or "").strip()

                    matched = False
                    if normalize_skill_name(primary_lang) == normalize_skill_name(
                        term_clean
                    ):
                        matched = True
                    elif any(
                        normalize_skill_name(t) == normalize_skill_name(term_clean)
                        for t in topics
                    ):
                        matched = True
                    elif desc and pattern.search(desc):
                        matched = True

                    if matched:
                        basis = (
                            MatchingBasis.CANONICAL_SKILL_NAME
                            if is_canonical
                            else MatchingBasis.SKILL_ALIAS
                        )
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=basis,
                                matched_term=term_clean,
                                explanation=(
                                    f"Technology '{term_clean}' from experience claim identified in repository metadata. "
                                    f"Does NOT verify employment, employer, job title, duration, or professional responsibility."
                                ),
                            )
                        )
                        continue

                elif item.evidence_type == EvidenceType.DOCUMENTATION:
                    content = str(observed.get("content") or "")
                    if content and pattern.search(content):
                        matches.append(
                            EvidenceMatchItem(
                                evidence_item_id=item.id,
                                evidence_source_id=item.evidence_source_id,
                                evidence_type=item.evidence_type,
                                source_locator=locator,
                                matching_basis=MatchingBasis.DOCUMENTATION_KEYWORD,
                                matched_term=term_clean,
                                explanation=(
                                    f"Technology '{term_clean}' from experience claim referenced in documentation ({locator}). "
                                    f"Does NOT verify employment, employer, job title, duration, or professional responsibility."
                                ),
                            )
                        )
                        continue

        return matches

    # -------------------------------------------------------------------------
    # Skill Resolution Helper
    # -------------------------------------------------------------------------

    def _resolve_target_skills(self, claim_text: str) -> list[tuple[str, bool]]:
        """
        Identify target skills and registered aliases referenced in claim text.
        Returns list of (term, is_canonical).
        """
        catalog = list(self.skill_repo.list_all())
        norm_claim = normalize_skill_name(claim_text)
        terms: list[tuple[str, bool]] = []
        matched_canonical_names: set[str] = set()

        # 1. Direct match: claim text matches a canonical skill or alias exactly
        for skill in catalog:
            if normalize_skill_name(skill.canonical_name) == norm_claim:
                matched_canonical_names.add(skill.canonical_name)
                terms.append((skill.canonical_name, True))
                for a in skill.aliases or []:
                    terms.append((a, False))
                return terms

            for alias in skill.aliases or []:
                if normalize_skill_name(alias) == norm_claim:
                    matched_canonical_names.add(skill.canonical_name)
                    terms.append((skill.canonical_name, True))
                    for a in skill.aliases or []:
                        terms.append((a, False))
                    return terms

        # 2. Pattern scan across catalog for mentions within claim text
        # Sort catalog skills by length descending so longer/more specific terms are scanned first
        sorted_catalog = sorted(
            catalog,
            key=lambda s: max(
                len(s.canonical_name),
                max((len(a) for a in (s.aliases or [])), default=0),
            ),
            reverse=True,
        )
        for skill in sorted_catalog:
            if skill.canonical_name in matched_canonical_names:
                continue

            all_skill_terms = [(skill.canonical_name, True)] + [
                (a, False) for a in (skill.aliases or [])
            ]
            for term, _is_canonical in all_skill_terms:
                if not term or not term.strip():
                    continue
                pattern = build_skill_pattern(term)
                if pattern.search(claim_text):
                    matched_canonical_names.add(skill.canonical_name)
                    terms.append((skill.canonical_name, True))
                    for a in skill.aliases or []:
                        terms.append((a, False))
                    break

        # 3. Fallback: if no catalog skills detected, treat short non-empty claim text as a term
        if not terms and claim_text.strip():
            cleaned = claim_text.strip()
            # Only use if not excessively long
            if len(cleaned) <= 60 and len(cleaned.split()) <= 5:
                terms.append((cleaned, True))

        return terms

    # -------------------------------------------------------------------------
    # Response Construction Helpers
    # -------------------------------------------------------------------------

    def _build_not_applicable_response(
        self, claim: CandidateClaim, summary: str
    ) -> ClaimEvidenceMatchResponse:
        return self._build_response(
            claim=claim,
            status=ClaimMatchStatus.NOT_APPLICABLE,
            summary=summary,
            matches=[],
            sources_inspected=0,
            items_inspected=0,
            sources_summary={},
        )

    def _build_response(
        self,
        claim: CandidateClaim,
        status: ClaimMatchStatus,
        summary: str,
        matches: list[EvidenceMatchItem],
        sources_inspected: int,
        items_inspected: int,
        sources_summary: dict[str, int],
        total_matches: int | None = None,
    ) -> ClaimEvidenceMatchResponse:
        return ClaimEvidenceMatchResponse(
            claim_id=claim.id,
            claim_type=claim.claim_type,
            claim_text=claim.claim_text,
            origin=claim.origin,
            canonical_path=claim.canonical_path,
            resume_parse_id=claim.resume_parse_id,
            status=status,
            summary=summary,
            matches=matches,
            total_matches=len(matches) if total_matches is None else total_matches,
            sources_inspected=sources_inspected,
            items_inspected=items_inspected,
            sources_summary=sources_summary,
        )
