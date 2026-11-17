import re

# Task 1: Deterministic Whitelist Router (runs FIRST, before any LLM call)
GREETING_REGEX = re.compile(
    r"^\s*(?:(?:hi+|hello+|hey+|hii+)(?:\s+there)?|namaste|good\s+(?:morning|afternoon|evening|night)|how\s+are\s+you|kaise\s+ho|thanks|thank\s+you|shukriya|bye|goodbye|who\s+are\s+you|what\s+can\s+you\s+do|tum\s+kaun\s+ho|aap\s+kaun\s+ho)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

DATA_WORDS = (
    "excavation", "excavated", "excavation_records", "pull", "support", "class", "chainage",
    "theoretical", "actual", "volume", "record", "records", "row", "rows",
    "database", "table", "data", "khudai", "खुदाई", "tarikh", "तारीख",
    "january", "february", "jan", "feb", "total", "average", "highest",
    "lowest", "difference", "compare", "chart"
)

DATE_REGEX = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b")
NUMBER_RANGE_REGEX = re.compile(r"(?<!\d)(\d{1,2})\s*(?:to|-|se|tak|and)\s*(\d{1,2})(?!\d)", re.IGNORECASE)

GREETING_REPLY = (
    "Hello! I'm Tunnel Excavation AI. You can ask me about dates, support class, chainage, "
    "or theoretical/actual excavation. "
    "For example: 'What was the actual excavation on 01-01-2025?'"
)

OUT_OF_SCOPE_REPLY = (
    "Sorry, main sirf tunnel excavation se related sawalon me madad kar sakta hu. "
    "Aap pooch sakte ho: '01-01-2025 ko actual excavation kitna tha?' ya 'Support class A me total excavation kitna hai?'"
)

MONTH_CLARIFICATION_REPLY = (
    "Kaunsa month? (1) January (2) February (3) Dono, ya table ke pehle 5 rows chahiye?"
)


def route(question: str, has_context: bool = False) -> str:
    """Deterministic router that runs FIRST, before any LLM call.
    Returns: 'chat' | 'data' | 'out_of_scope'
    """
    text = question.strip()
    if not text:
        return "out_of_scope"

    # 1. "chat": ONLY if the whole message matches a greeting regex
    if GREETING_REGEX.match(text):
        return "chat"

    text_lower = text.lower()

    # 2. "data":
    # - If the text contains any data word
    if any(re.search(rf"\b{re.escape(w)}\b", text_lower) if w.isascii() else w in text_lower for w in DATA_WORDS):
        return "data"

    # - Contains a date (DD-MM-YYYY / DD/MM/YYYY)
    if DATE_REGEX.search(text):
        return "data"

    # - Contains a number range ("1 to 5", "1to5", "1-5", "1 se 5")
    range_match = NUMBER_RANGE_REGEX.search(text)
    if range_match:
        d1, d2 = int(range_match.group(1)), int(range_match.group(2))
        if 1 <= d1 <= 31 and 1 <= d2 <= 31 and d1 <= d2:
            return "data"

    # - has_context is true and the message has <= 6 words
    words = text.split()
    if has_context and len(words) <= 6:
        return "data"

    # 3. "out_of_scope": everything else
    return "out_of_scope"
