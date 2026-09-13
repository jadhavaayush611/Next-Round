import re

from app.schemas.canonical_resume import DateInfo

MONTH_NAMES: dict[str, str] = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}

PRESENT_KEYWORDS = {
    "present",
    "current",
    "now",
    "ongoing",
    "till date",
    "to date",
    "continuing",
}

RANGE_SEPARATORS_PATTERN = r"(?:\s*(?:–|—|-|to|until|through|\.\.|--)\s*)"

# Regex components
MONTH_NAME_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
YEAR_RE = r"(?:19\d{2}|20\d{2})"
MONTH_NUM_RE = r"(?:0?[1-9]|1[0-2])"
DAY_NUM_RE = r"(?:0?[1-9]|[12]\d|3[01])"


def _normalize_single_token(token: str) -> tuple[str | None, bool]:
    """
    Normalizes a single date token into (normalized_string, is_ambiguous).
    Supported formats:
    - 'Present' / 'Current' -> ('Present', False)
    - 'January 2024' / 'Jan 2024' -> ('01/2024', False)
    - '01/2024' or '01-2024' (Month/Year) -> ('01/2024', False)
    - '2024/01' or '2024-01' (Year/Month) -> ('01/2024', False)
    - '2024' (Year only) -> ('2024', False) [DO NOT fabricate month]
    - '15/01/2024' (Unambiguous Day/Month/Year since 15 > 12) -> ('01/2024', False)
    - '03/04/2024' (Ambiguous DD/MM vs MM/DD since 03 <= 12 and 04 <= 12) -> (None, True)
    """
    clean = token.strip().rstrip(".,")
    if not clean:
        return None, False

    clean_lower = clean.lower()
    if clean_lower in PRESENT_KEYWORDS:
        return "Present", False

    # 1. Year only (e.g. 2024) -> preserve year granularity
    if re.fullmatch(YEAR_RE, clean):
        return clean, False

    # 2. Month name + Year (e.g. "January 2024", "Jan 2024", "Jan. 2024", "January, 2024")
    m_name_year = re.fullmatch(
        rf"({MONTH_NAME_RE})\.?,?\s*({YEAR_RE})", clean, re.IGNORECASE
    )
    if m_name_year:
        m_name = m_name_year.group(1).lower().rstrip(".")
        year = m_name_year.group(2)
        month_num = MONTH_NAMES.get(m_name)
        if month_num:
            return f"{month_num}/{year}", False

    # 3. Day + Month name + Year (e.g. "15 January 2024", "Jan 15, 2024")
    d_m_y = re.fullmatch(
        rf"{DAY_NUM_RE}(?:st|nd|rd|th)?\s+({MONTH_NAME_RE})\.?,?\s*({YEAR_RE})",
        clean,
        re.IGNORECASE,
    )
    if d_m_y:
        m_name = d_m_y.group(1).lower().rstrip(".")
        year = d_m_y.group(2)
        month_num = MONTH_NAMES.get(m_name)
        if month_num:
            return f"{month_num}/{year}", False

    m_d_y = re.fullmatch(
        rf"({MONTH_NAME_RE})\.?\s+{DAY_NUM_RE}(?:st|nd|rd|th)?,?\s*({YEAR_RE})",
        clean,
        re.IGNORECASE,
    )
    if m_d_y:
        m_name = m_d_y.group(1).lower().rstrip(".")
        year = m_d_y.group(2)
        month_num = MONTH_NAMES.get(m_name)
        if month_num:
            return f"{month_num}/{year}", False

    # 4. YYYY-MM or YYYY/MM
    y_m = re.fullmatch(rf"({YEAR_RE})[/-]({MONTH_NUM_RE})", clean)
    if y_m:
        year = y_m.group(1)
        month = y_m.group(2).zfill(2)
        return f"{month}/{year}", False

    # 5. MM/YYYY or MM-YYYY
    m_y = re.fullmatch(rf"({MONTH_NUM_RE})[/-]({YEAR_RE})", clean)
    if m_y:
        month = m_y.group(1).zfill(2)
        year = m_y.group(2)
        return f"{month}/{year}", False

    # 6. Three numeric components: XX/YY/YYYY or XX-YY-YYYY
    three_parts = re.fullmatch(rf"(\d{{1,2}})[/-](\d{{1,2}})[/-]({YEAR_RE})", clean)
    if three_parts:
        num1 = int(three_parts.group(1))
        num2 = int(three_parts.group(2))
        year = three_parts.group(3)

        # Ambiguous case: both <= 12 (e.g. 03/04/2024) -> Cannot reliably determine month vs day
        if num1 <= 12 and num2 <= 12:
            return None, True

        # Unambiguous: one is clearly day (> 12) and other is month (<= 12)
        if num1 > 12 and num2 <= 12:
            # DD/MM/YYYY
            return f"{str(num2).zfill(2)}/{year}", False
        elif num1 <= 12 and num2 > 12:
            # MM/DD/YYYY
            return f"{str(num1).zfill(2)}/{year}", False
        else:
            # Invalid date numbers (e.g. 15/15/2024)
            return None, True

    return None, False


def parse_date_string(date_str: str) -> DateInfo | None:
    """
    Parses a candidate date string into a structured DateInfo.
    Adheres strictly to invariants:
    - Preserves original raw text.
    - Normalizes unambiguous dates into MM/YYYY or MM/YYYY – MM/YYYY or MM/YYYY – Present.
    - Partial dates (e.g. '2024') preserve year granularity.
    - Ambiguous dates (e.g. '03/04/2024') normalize to None with original preserved.
    """
    if not date_str:
        return None

    raw = date_str.strip().strip("()[]{}")
    if not raw:
        return None

    # Split potential range
    split_parts = re.split(RANGE_SEPARATORS_PATTERN, raw, maxsplit=1)

    if len(split_parts) == 2:
        part1, part2 = split_parts[0].strip(), split_parts[1].strip()
        norm1, ambig1 = _normalize_single_token(part1)
        norm2, ambig2 = _normalize_single_token(part2)

        if ambig1 or ambig2:
            # Date is ambiguous -> cannot normalize reliably
            return DateInfo(
                original=raw,
                normalized=None,
                start_date=None,
                end_date=None,
                is_present=False,
            )

        if norm1 and norm2:
            is_pres = norm2 == "Present"
            normalized_val = f"{norm1} – {norm2}"
            return DateInfo(
                original=raw,
                normalized=normalized_val,
                start_date=norm1,
                end_date=norm2,
                is_present=is_pres,
            )

    # Single date token
    norm, ambig = _normalize_single_token(raw)
    if ambig:
        return DateInfo(
            original=raw,
            normalized=None,
            start_date=None,
            end_date=None,
            is_present=False,
        )

    if norm:
        is_pres = norm == "Present"
        return DateInfo(
            original=raw,
            normalized=norm,
            start_date=norm if not is_pres else None,
            end_date=norm if is_pres else None,
            is_present=is_pres,
        )

    # If could not normalize, still preserve original
    return DateInfo(
        original=raw,
        normalized=None,
        start_date=None,
        end_date=None,
        is_present=False,
    )


# Combined date extraction regex for scanning lines
DATE_PATTERN_REGEX = re.compile(
    rf"(?:(?:\b(?:{MONTH_NAME_RE}\.?,?\s+)?{YEAR_RE}|\b{MONTH_NUM_RE}[/-]{YEAR_RE}|\b\d{{1,2}}[/-]\d{{1,2}}[/-]{YEAR_RE})\s*(?:–|—|-|to|until|through|\.\.|--)\s*(?:(?:{MONTH_NAME_RE}\.?,?\s+)?{YEAR_RE}|{MONTH_NUM_RE}[/-]{YEAR_RE}|\d{{1,2}}[/-]\d{{1,2}}[/-]{YEAR_RE}|Present|Current|Ongoing|Now|Till date)\b|\b(?:{MONTH_NAME_RE}\.?,?\s+{DAY_NUM_RE}(?:st|nd|rd|th)?,?\s*{YEAR_RE}|{MONTH_NAME_RE}\.?,?\s+{YEAR_RE}|{MONTH_NUM_RE}[/-]{YEAR_RE}|\d{{1,2}}[/-]\d{{1,2}}[/-]{YEAR_RE}|{YEAR_RE})\b)",
    re.IGNORECASE,
)


def extract_date_from_text(text: str) -> tuple[DateInfo | None, str]:
    """
    Extracts date string match from a text line and returns (DateInfo, cleaned_text_without_date).
    """
    if not text:
        return None, text

    matches = list(DATE_PATTERN_REGEX.finditer(text))
    if not matches:
        return None, text

    # Select the most plausible date match (usually the last date range on a header line)
    # Prefer ranges over single years if multiple
    chosen_match = None
    for match in reversed(matches):
        match_str = match.group(0).strip()
        # Avoid treating simple numbers as years if they look like quantities (e.g. "top 100")
        if re.fullmatch(r"\d{1,3}", match_str):
            continue
        # Verify it can be parsed
        parsed = parse_date_string(match_str)
        if parsed and (
            parsed.normalized
            or "–" in match_str
            or "-" in match_str
            or re.search(YEAR_RE, match_str)
        ):
            chosen_match = match
            break

    if not chosen_match:
        return None, text

    raw_date_str = chosen_match.group(0).strip()
    date_info = parse_date_string(raw_date_str)

    # Strip the date from text
    start, end = chosen_match.span()
    cleaned = (text[:start] + text[end:]).strip()
    # Clean up dangling separators like '|', '-', ',', '()'
    cleaned = re.sub(r"\s*[|•·,]\s*$", "", cleaned)
    cleaned = re.sub(r"^\s*[|•·,]\s*", "", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned).strip()

    return date_info, cleaned
