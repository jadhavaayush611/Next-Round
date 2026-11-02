import re
import unicodedata


def normalize_text(raw_text: str) -> str:
    """
    Normalizes extracted document text deterministically:
    1. Performs NFKC Unicode normalization.
    2. Strips zero-width and invisible control characters.
    3. Normalizes exotic whitespace characters to standard spaces.
    4. Unifies line terminators (CRLF, CR -> LF).
    5. Strips line-level trailing whitespace and collapses multiple horizontal spaces/tabs.
    6. Collapses 3+ consecutive newlines to at most 2 newlines (preserving paragraph structure).
    7. Preserves technical tokens (C++, C#, .NET, Node.js, SQL, URLs, email addresses).
    """
    if not raw_text:
        return ""

    # 1. Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", raw_text)

    # 2. Remove invisible formatting characters (soft hyphen, zero-width space/joiner, BOM)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\xad]", "", text)

    # 3. Normalize non-breaking and exotic whitespace to standard space
    text = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", text)

    # 4. Normalize line breaks: CRLF and CR -> LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 5. Process per-line: collapse internal horizontal whitespace and strip ends
    lines: list[str] = []
    for line in text.split("\n"):
        cleaned_line = re.sub(r"[^\S\n]+", " ", line).strip()
        lines.append(cleaned_line)
    text = "\n".join(lines)

    # 6. Collapse excessive blank lines (3 or more consecutive \n -> 2 \n)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. Strip surrounding blank lines
    return text.strip()
