import re
from typing import List, Optional, Tuple

VALID_CLASSES = {"A", "B", "C", "D", "E", "F"}
VALID_MONTHS = {1, 2}  # January and February
VALID_YEAR = 2025
MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

# Dates known to exist in the 2-month dataset (01-01-2025 to 28-02-2025)
def is_valid_date(date_str: Optional[str]) -> bool:
    if not date_str:
        return False
    parts = date_str.split("-")
    if len(parts) != 3:
        return False
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return False
    if y != VALID_YEAR:
        return False
    if m == 1:
        return 1 <= d <= 31
    if m == 2:
        return 1 <= d <= 28
    return False


EXAMPLE_QUESTIONS = [
    "What was the actual excavation on 01-01-2025?",
    "Total theoretical excavation in February",
    "Support class B total excavation",
]

OUT_OF_SCOPE_REPLY = (
    "Sorry, I can only answer questions related to the tunnel excavation database. "
    "You can ask: 'What was the actual excavation on 01-01-2025?' or 'What is the total excavation for support class A?'"
)

GREETING_REPLY = (
    "Hello! I'm Tunnel Excavation AI. You can ask me about dates, support class, chainage, "
    "or theoretical/actual excavation. "
    "For example: 'What was the actual excavation on 01-01-2025?'"
)

MUTATION_REFUSAL_REPLY = (
    "I'm sorry, but I am a read-only assistant and cannot delete, modify, or change data in the database. "
    "If you need help with tunnel excavation data, feel free to ask!"
)


TOPIC_KEYWORDS = (
    "excavation",
    "excavated",
    "pull",
    "support",
    "class",
    "classes",
    "chainage",
    "theoretical",
    "actual",
    "volume",
    "record",
    "records",
    "row",
    "rows",
    "data",
    "database",
    "table",
    "date",
    "dates",
    "khudai",
    "खुदाई",
    "tarikh",
    "तारीख",
    "vastavik",
    "sidhantik",
)


def has_topic_evidence(
    question: str = "",
    normalized: str = "",
    intent_or_entities: Optional[dict] = None,
) -> bool:
    """Check if the question contains topic evidence:
    Evidence = a date, month, year, support class letter, chainage numbers, a day range,
    or a whole-word topic word: excavation, pull, support, class, chainage, theoretical, actual,
    volume, record(s), row(s), data, database, table, date.
    Operation words (min, max, minimum, maximum, total, sum, average, avg, highest, lowest, difference,
    compare, count) are NOT evidence on their own.
    """
    q_norm = (normalized or "").lower()
    q_raw = (question or "").lower()
    data = intent_or_entities or {}

    # 1. Date
    if data.get("date") or data.get("start_date") or data.get("end_date"):
        return True
    if re.search(r"\b\d{2}-\d{2}-\d{4}\b", q_norm):
        return True

    # 2. Explicit Month
    month_regex = r"\b(?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|october|oct|november|nov|december|dec)\b"
    if re.search(month_regex, q_norm) or re.search(month_regex, q_raw):
        return True

    # 3. Explicit Year (typed by user, e.g. 2025)
    if re.search(r"\b20\d{2}\b", q_raw) or re.search(r"\b20\d{2}\b", q_norm):
        return True

    # 4. Support Class letter
    if data.get("support_class"):
        return True
    if re.search(r"\b(?:support\s*class|class)\s*[:=]?\s*([a-f])\b|\b([a-f])\s*(?:class|support)\b", q_norm):
        return True

    # 5. Chainage numbers
    if data.get("start_ch") is not None or data.get("end_ch") is not None:
        return True
    if re.search(r"\b(?:chainage|ch)\b", q_norm):
        return True

    # 6. Day range or day numbers
    if data.get("has_day_range") or data.get("start_day") is not None:
        return True
    if re.search(r"\b\d{1,2}\s*(?:to|-|se|tak|and)\s*\d{1,2}\b", q_norm):
        return True

    # 7. Whole-word topic word
    for word in TOPIC_KEYWORDS:
        if re.search(rf"\b{re.escape(word)}\b", q_norm) or re.search(rf"\b{re.escape(word)}\b", q_raw):
            return True

    return False


def make_clarify_reply(corrected_question: Optional[str]) -> str:
    """Reply 'Did you mean: <corrected_question>?' with 2-3 example questions."""
    cq = corrected_question or "What was the actual excavation on 01-01-2025?"
    examples = "\n".join(f"- {q}" for q in EXAMPLE_QUESTIONS)
    return f"Did you mean: '{cq}'?\n\nYou can ask:\n{examples}"


def validate_intent_answerability(
    intent_data: dict,
    raw_question: str = "",
    normalized: str = "",
) -> Tuple[bool, str, Optional[str]]:
    """Validate whether the classified intent is answerable from the DB.
    Returns:
        (is_answerable, behavior, reason_or_message)
        behavior in {"answer", "clarify", "refuse"}
    """
    op = intent_data.get("operation")
    confidence = float(intent_data.get("confidence", 1.0))
    corrected = intent_data.get("corrected_question") or ""

    # 1. Greetings
    if op == "chat":
        return True, "answer", GREETING_REPLY

    # 2. Mutation refusal
    if op == "mutation_refusal":
        return True, "refuse", MUTATION_REFUSAL_REPLY

    # 3. Topic evidence check (Requirement 3 & 4)
    has_evidence = has_topic_evidence(raw_question, normalized, intent_data)
    if not has_evidence:
        # Never query DB without topic evidence!
        if op == "out_of_scope" or confidence >= 0.7:
            return True, "refuse", OUT_OF_SCOPE_REPLY
        agg = intent_data.get("aggregate")
        suggested = f"{agg} actual excavation" if agg else "What was the actual excavation on 01-01-2025?"
        return False, "clarify", make_clarify_reply(corrected or suggested)

    # 4. Out of scope with confidence >= 0.7
    if op == "out_of_scope":
        if confidence >= 0.7:
            return True, "refuse", OUT_OF_SCOPE_REPLY
        else:
            return False, "clarify", make_clarify_reply(corrected)

    # 5. Low confidence or explicit clarify operation
    if confidence < 0.5 or op == "clarify":
        return False, "clarify", make_clarify_reply(corrected)

    # 5. Check if named month or date is out of available data range (Requirement 9)
    m = intent_data.get("month")
    y = intent_data.get("year") or 2025
    if m is not None and m not in VALID_MONTHS:
        m_name = MONTH_NAMES.get(m, f"Month {m}")
        return False, "clarify", f"No records found for {m_name} {y}. Available data: 01-01-2025 to 28-02-2025."

    date_val = intent_data.get("date")
    if date_val and not is_valid_date(date_val):
        return False, "clarify", f"No records found for {date_val}. Available data: 01-01-2025 to 28-02-2025."

    s_date = intent_data.get("start_date")
    e_date = intent_data.get("end_date")
    if (s_date or e_date) and (not is_valid_date(s_date) or not is_valid_date(e_date)):
        scope_d = f"{s_date} to {e_date}" if (s_date and e_date) else (s_date or e_date or "specified range")
        return False, "clarify", f"No records found for {scope_d}. Available data: 01-01-2025 to 28-02-2025."

    # 6. Check database boundaries per operation
    if op == "record":
        if not date_val:
            return False, "clarify", make_clarify_reply(f"What was the excavation on 01-01-2025?")

    elif op == "range_records":
        pass

    elif op == "aggregate":
        # Check support class if provided
        sc = intent_data.get("support_class")
        if sc and sc.upper() not in VALID_CLASSES:
            return False, "clarify", make_clarify_reply(f"total excavation for support class B")
        # Check chainage if provided
        start_ch = intent_data.get("start_ch")
        end_ch = intent_data.get("end_ch")
        if start_ch is not None and end_ch is not None:
            if start_ch < 0 or end_ch > 180 or start_ch > end_ch:
                return False, "clarify", make_clarify_reply(f"total excavation for chainage 30 to 60")

    elif op == "day_range":
        # Ambiguous day range without month requires clarification
        if not intent_data.get("month"):
            d1 = intent_data.get("start_day") or 1
            d2 = intent_data.get("end_day") or 5
            return False, "clarify", make_clarify_reply(f"give me data {d1} to {d2} january")

    elif op == "day_records":
        day = intent_data.get("day")
        if day is None or not (1 <= day <= 31):
            return False, "clarify", make_clarify_reply("pull on day 5 of January")

    return True, "answer", None
