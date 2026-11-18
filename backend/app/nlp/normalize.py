import re
from typing import Optional
from rapidfuzz import fuzz, process

OPERATION_WORDS = {
    "min",
    "max",
    "minimum",
    "maximum",
    "total",
    "sum",
    "average",
    "avg",
    "highest",
    "lowest",
    "difference",
    "compare",
    "count",
}

TOPIC_WORDS = {
    "excavation",
    "theoretical",
    "actual",
    "support",
    "class",
    "chainage",
    "pull",
    "volume",
    "record",
    "records",
    "row",
    "rows",
    "date",
    "which",
    "under",
}

KNOWN_VOCAB = tuple(sorted(list(TOPIC_WORDS | OPERATION_WORDS | {"between"})))

COMMON_TYPOS = {
    "minimun": "minimum",
    "maximun": "maximum",
}

MONTH_MAP = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

FULL_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def fix_typo_month(word: str) -> Optional[str]:
    """Match typo month names like 'januray' or 'febuary' to standard month names."""
    if len(word) < 3:
        return None
    cleaned = word.lower().strip()
    if cleaned in MONTH_MAP:
        return cleaned
    if len(cleaned) >= 4:
        match = process.extractOne(cleaned, FULL_MONTH_NAMES, scorer=fuzz.ratio, score_cutoff=75)
        if match:
            return match[0]
    return None


def normalize_spelling(text: str) -> str:
    """Fix spelling of known vocabulary using rapidfuzz.
    Rules:
    - Tokens shorter than 5 letters are NOT fuzzy-corrected.
    - Never map a token to an operation word unless the score is >= 88.
    - Topic words require score >= 78.
    """
    tokens = re.split(r"(\w+)", text)
    result = []
    for token in tokens:
        if token.isalpha():
            token_lower = token.lower()
            # 1. Exact match in known vocab or months -> preserve
            if token_lower in KNOWN_VOCAB or token_lower in MONTH_MAP:
                result.append(token_lower)
                continue

            # 2. Common direct typos
            if token_lower in COMMON_TYPOS:
                result.append(COMMON_TYPOS[token_lower])
                continue

            # 3. Check typo month
            if len(token_lower) >= 4:
                month_match = fix_typo_month(token_lower)
                if month_match and month_match in ("january", "february"):
                    result.append(month_match)
                    continue

            # 4. Tokens shorter than 5 letters are NOT fuzzy-corrected
            if len(token_lower) < 5:
                result.append(token)
                continue

            # 5. Fuzzy match against known vocabulary
            match = process.extractOne(token_lower, KNOWN_VOCAB, scorer=fuzz.ratio)
            if match:
                matched_word, score, _ = match
                # Operation words require score >= 88
                if matched_word in OPERATION_WORDS:
                    if score >= 88:
                        result.append(matched_word)
                    else:
                        result.append(token)
                else:
                    # Topic words require score >= 78
                    if score >= 78:
                        result.append(matched_word)
                    else:
                        result.append(token)
            else:
                result.append(token)
        else:
            result.append(token)
    return "".join(result)


def normalize_dates(text: str, default_year: int = 2025) -> str:
    """Normalize dates in text to DD-MM-YYYY format.
    Handles:
      - '5 jan', '5th january 2025', 'jan 5', 'january 5th'
      - '05/01/25', '05/01/2025', '5-1-2025', '5/1/25'
      - '1 to 5 jan', '1 to 5 january'
    """
    month_regex = r"(?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|october|oct|november|nov|december|dec)"

    # 1. Date ranges with explicit month, e.g. "1 to 5 jan", "1-5 january 2025"
    def _replace_date_range(m: re.Match) -> str:
        d1 = int(m.group(1))
        sep = m.group(2)
        d2 = int(m.group(3))
        m_str = m.group(4).lower()
        yr_str = m.group(5)
        m_name = fix_typo_month(m_str) or m_str
        m_num = MONTH_MAP.get(m_name, 1)
        yr = int(yr_str) if yr_str else default_year
        if yr < 100:
            yr += 2000
        return f"{d1:02d}-{m_num:02d}-{yr} {sep} {d2:02d}-{m_num:02d}-{yr}"

    range_pat = rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(to|-|se|tak|and)\s*(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+({month_regex})\b(?:\s+(\d{{2,4}}))?"
    text = re.sub(range_pat, _replace_date_range, text, flags=re.IGNORECASE)

    # 1b. Date ranges with month first, e.g. "february 20 to 25", "january 1-5"
    def _replace_month_first_range(m: re.Match) -> str:
        m_str = m.group(1).lower()
        d1 = int(m.group(2))
        sep = m.group(3)
        d2 = int(m.group(4))
        yr_str = m.group(5)
        m_name = fix_typo_month(m_str) or m_str
        m_num = MONTH_MAP.get(m_name, 1)
        yr = int(yr_str) if yr_str else default_year
        if yr < 100:
            yr += 2000
        return f"{d1:02d}-{m_num:02d}-{yr} {sep} {d2:02d}-{m_num:02d}-{yr} "

    month_first_range_pat = rf"\b({month_regex})\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(to|-|se|tak|and)\s*(\d{{1,2}})\s*(?:st|nd|rd|th)?\b(?:\s+(\d{{2,4}}))?"
    text = re.sub(month_first_range_pat, _replace_month_first_range, text, flags=re.IGNORECASE)

    # 2. Pattern: "5 jan 2025", "5th january 2025", "5 jan", "5th january"
    def _replace_day_month_year(m: re.Match) -> str:
        day = int(m.group(1))
        m_str = m.group(2).lower()
        yr_str = m.group(3)
        m_name = fix_typo_month(m_str) or m_str
        m_num = MONTH_MAP.get(m_name, 1)
        yr = int(yr_str) if yr_str else default_year
        if yr < 100:
            yr += 2000
        return f"{day:02d}-{m_num:02d}-{yr}"

    dmy_pat = rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+({month_regex})\b(?:\s+(\d{{2,4}}))?"
    text = re.sub(dmy_pat, _replace_day_month_year, text, flags=re.IGNORECASE)

    # 3. Pattern: "jan 5", "january 5th", "jan 5 2025", "january 5th, 2025"
    def _replace_month_day_year(m: re.Match) -> str:
        m_str = m.group(1).lower()
        day = int(m.group(2))
        yr_str = m.group(3)
        m_name = fix_typo_month(m_str) or m_str
        m_num = MONTH_MAP.get(m_name, 1)
        yr = int(yr_str) if yr_str else default_year
        if yr < 100:
            yr += 2000
        return f"{day:02d}-{m_num:02d}-{yr}"

    mdy_pat = rf"\b({month_regex})\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\b(?:\s*,?\s*(\d{{2,4}}))?"
    text = re.sub(mdy_pat, _replace_month_day_year, text, flags=re.IGNORECASE)

    # 4. Pattern: numeric dates like 05/01/25, 5-1-2025, 05/01/2025, 5-1-25
    def _replace_numeric_date(m: re.Match) -> str:
        d = int(m.group(1))
        mon = int(m.group(2))
        yr_str = m.group(3)
        if not (1 <= d <= 31 and 1 <= mon <= 12):
            return m.group(0)
        yr = int(yr_str)
        if yr < 100:
            yr += 2000
        return f"{d:02d}-{mon:02d}-{yr}"

    num_date_pat = r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b"
    text = re.sub(num_date_pat, _replace_numeric_date, text)

    return text


def normalize_question(text: str) -> str:
    """Full normalization pipeline:
    1. Lowercase and collapse whitespace.
    2. Fix spelling of known vocabulary and typo months with rapidfuzz.
    3. Normalize date expressions to DD-MM-YYYY.
    """
    if not text:
        return ""
    # 1. Lowercase and collapse whitespace
    collapsed = re.sub(r"\s+", " ", text.lower()).strip()

    # 2. Fix spelling of known vocabulary
    spelling_fixed = normalize_spelling(collapsed)

    # 3. Normalize dates
    date_normalized = normalize_dates(spelling_fixed)

    return re.sub(r"\s+", " ", date_normalized).strip()
