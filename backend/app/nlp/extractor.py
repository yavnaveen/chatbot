import re
from typing import Any, Dict, List, Optional
from backend.app.nlp.normalize import MONTH_MAP, fix_typo_month

DATE_REGEX = re.compile(r"\b\d{2}-\d{2}-\d{4}\b")
CHAINAGE_REGEX = re.compile(
    r"(?:chainage|ch)\s*(?:between|from)?\s*(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)|(?:between|from)?\s*(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)\s*(?:m|meter|meters)?\s*(?:chainage|ch)",
    re.IGNORECASE,
)
DAY_RANGE_REGEX = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:to|-|se|tak|and)\s*(\d{1,2})(?![\d.])(?!\s*-\s*\d{4})",
    re.IGNORECASE,
)
SINGLE_DAY_REGEX = re.compile(
    r"\b(?:day|tarikh|तारीख|date)?\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:ko|tarikh|तारीख|date)?\b",
    re.IGNORECASE,
)


def extract_entities(text: str) -> Dict[str, Any]:
    """Extract domain entities directly in code:
    - dates, start_date, end_date
    - month, year
    - support_class (A-F)
    - start_ch, end_ch
    - day, start_day, end_day
    - metric (actual, theoretical, both, vastavik, sidhantik)
    - aggregate (sum, avg, min, max)
    """
    text_lower = text.lower()
    entities: Dict[str, Any] = {
        "dates": [],
        "date": None,
        "start_date": None,
        "end_date": None,
        "month": None,
        "year": None,
        "support_class": None,
        "start_ch": None,
        "end_ch": None,
        "day": None,
        "start_day": None,
        "end_day": None,
        "metric": None,
        "aggregate": None,
        "has_day_range": False,
    }

    # 1. Dates
    found_dates = DATE_REGEX.findall(text)
    entities["dates"] = found_dates
    if len(found_dates) == 1:
        entities["date"] = found_dates[0]
        # Infer month and year from single date
        entities["month"] = int(found_dates[0][3:5])
        entities["year"] = int(found_dates[0][6:10])
    elif len(found_dates) >= 2:
        entities["start_date"] = found_dates[0]
        entities["end_date"] = found_dates[1]
        entities["month"] = int(found_dates[0][3:5])
        entities["year"] = int(found_dates[0][6:10])

    # 2. Month (if explicitly mentioned in text)
    explicit_month = None
    for m_name, m_num in MONTH_MAP.items():
        if re.search(rf"\b{m_name}\b", text_lower):
            explicit_month = m_num
            break
    if explicit_month is None:
        # Check typo months
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text_lower)
        for w in words:
            matched = fix_typo_month(w)
            if matched and matched in MONTH_MAP:
                explicit_month = MONTH_MAP[matched]
                break

    if explicit_month is not None:
        entities["month"] = explicit_month
        entities["year"] = 2025

    # Year (default 2025 if year is 2025 or mentioned)
    year_match = re.search(r"\b(20\d{2})\b", text)
    if year_match:
        entities["year"] = int(year_match.group(1))
    elif entities["month"] is not None or entities["date"] is not None:
        entities["year"] = 2025

    # 3. Support Class (A-Z)
    sc_match = re.search(r"\b(?:support\s*class|class|support)\s*[:=]?\s*([a-z])\b|\b([a-z])\s*(?:class|support)\b", text_lower)
    if sc_match:
        sc = (sc_match.group(1) or sc_match.group(2)).upper()
        entities["support_class"] = sc

    # 4. Chainage numbers
    ch_match = CHAINAGE_REGEX.search(text_lower)
    if ch_match:
        s1, e1, s2, e2 = ch_match.groups()
        s_ch = float(s1 if s1 is not None else s2)
        e_ch = float(e1 if e1 is not None else e2)
        entities["start_ch"] = s_ch
        entities["end_ch"] = e_ch

    # 5. Day numbers / ranges (only if not full dates and not chainage)
    if not entities["dates"] and entities["start_ch"] is None:
        range_match = DAY_RANGE_REGEX.search(text_lower)
        if range_match:
            d1, d2 = int(range_match.group(1)), int(range_match.group(2))
            if 1 <= d1 <= 31 and 1 <= d2 <= 31 and d1 <= d2:
                entities["start_day"] = d1
                entities["end_day"] = d2
                entities["has_day_range"] = True

        single_day_match = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:ko|date|tarikh|तारीख)\b", text_lower)
        if single_day_match and not entities["has_day_range"]:
            d_val = int(single_day_match.group(1))
            if 1 <= d_val <= 31:
                entities["day"] = d_val

    # 6. Metric (whole-word matching only)
    def _match_any(words: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", text_lower) for w in words)

    has_actual = _match_any(("actual", "vastavik", "vaastavik", "vastvik", "वास्तविक"))
    has_theo = _match_any(("theoretical", "sidhantik", "saiddhantik", "sidhhantik", "सैद्धांतिक"))
    has_both = _match_any(("both", "dono", "difference", "compare", "versus", "vs", "farq", "antar"))
    has_pull_and_volume = bool(re.search(r"\bpull\b", text_lower) and re.search(r"\bvolume\b", text_lower))

    if has_both or (has_actual and has_theo) or has_pull_and_volume:
        entities["metric"] = "both"
    elif has_theo:
        entities["metric"] = "theoretical"
    elif has_actual:
        entities["metric"] = "actual"
    else:
        entities["metric"] = "actual"  # default metric

    # 7. Aggregate (whole-word matching only: 'min' and 'max' must never match inside other words)
    if _match_any(("average", "avg", "mean", "ausat", "औसत")):
        entities["aggregate"] = "avg"
    elif _match_any(("minimum", "min", "lowest", "least", "kam", "chhota", "sabse kam")):
        entities["aggregate"] = "min"
    elif _match_any(("maximum", "max", "highest", "peak", "most", "adhik", "jyada", "sabse jyada", "sabse adhik")):
        entities["aggregate"] = "max"
    elif _match_any(("total", "sum", "kul", "कुल", "kitna", "pura")):
        entities["aggregate"] = "sum"

    return entities
