import re


def normalize_skill_name(name: str | None) -> str:
    """
    Deterministic normalization for skill matching, lookup, and collision detection.
    Strips surrounding whitespace, collapses internal whitespace sequences to single spaces,
    and lowercases the string.

    Preserves essential technical characters (e.g. '+', '#', '.', '-', '/').
    Examples:
      - '  PostgreSQL  ' -> 'postgresql'
      - 'Node.js' -> 'node.js'
      - 'C++' -> 'c++'
      - 'Ruby   on   Rails' -> 'ruby on rails'
    """
    if not name:
        return ""
    return " ".join(name.strip().split()).lower()


def clean_aliases(
    aliases: list[str] | None, canonical_name: str | None = None
) -> list[str]:
    """
    Cleans and deduplicates a list of aliases for persistence:
    - Strips leading/trailing whitespace and collapses internal whitespace.
    - Drops empty strings.
    - Deduplicates aliases case-insensitively while preserving initial display casing.
    - Excludes aliases that match the canonical name case-insensitively.
    """
    if not aliases:
        return []

    canonical_norm = normalize_skill_name(canonical_name) if canonical_name else ""
    cleaned: list[str] = []
    seen: set[str] = set()

    if canonical_norm:
        seen.add(canonical_norm)

    for alias in aliases:
        if not isinstance(alias, str):
            continue
        collapsed = " ".join(alias.strip().split())
        norm = collapsed.lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(collapsed)

    return cleaned


def build_skill_pattern(term: str) -> re.Pattern[str]:
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
    if term_clean.lower() == "react":
        right = r"(?![a-zA-Z0-9_])(?!\s+native\b)"
    elif term_clean.endswith("++"):
        right = r"(?!\+)"
    elif term_clean.endswith("#"):
        right = r"(?!#)"
    elif term_clean and re.match(r"[a-zA-Z0-9_]", term_clean[-1]):
        if len(term_clean) == 1 and term_clean.isalpha():
            right = r"(?![a-zA-Z0-9_+#])"
        else:
            right = r"(?![a-zA-Z0-9_])"
    else:
        right = r"(?![a-zA-Z0-9_+#])"

    return re.compile(left + escaped_term + right, re.IGNORECASE)
