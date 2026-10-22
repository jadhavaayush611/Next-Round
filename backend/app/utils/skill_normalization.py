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
