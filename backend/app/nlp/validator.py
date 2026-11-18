import re
from typing import List, Optional, Tuple

VALID_CLASSES = {"A", "B", "C", "D", "E", "F"}
VALID_MONTHS = {1, 2}  # January and February
VALID_YEAR = 2025

# Dates known to exist in the 2-month dataset (01-01-2025 to 31-01-2025 and 01-02-2025 to 25-02-2025)
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
        return 1 <= d <= 25
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


def make_clarify_reply(corrected_question: Optional[str]) -> str:
    """Reply 'Did you mean: <corrected_question>?' with 2-3 example questions."""
    cq = corrected_question or "What was the actual excavation on 01-01-2025?"
    examples = "\n".join(f"- {q}" for q in EXAMPLE_QUESTIONS)
    return f"Did you mean: '{cq}'?\n\nYou can ask:\n{examples}"


def validate_intent_answerability(intent_data: dict) -> Tuple[bool, str, Optional[str]]:
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

    # 3. Out of scope with confidence >= 0.7
    if op == "out_of_scope":
        if confidence >= 0.7:
            return True, "refuse", OUT_OF_SCOPE_REPLY
        else:
            return False, "clarify", make_clarify_reply(corrected)

    # 4. Low confidence or explicit clarify operation
    if confidence < 0.5 or op == "clarify":
        return False, "clarify", make_clarify_reply(corrected)

    # 5. Check database boundaries per operation
    if op == "record":
        date_val = intent_data.get("date")
        if not date_val or not is_valid_date(date_val):
            return False, "clarify", make_clarify_reply(f"What was the excavation on 01-01-2025?")

    elif op == "range_records":
        s_date = intent_data.get("start_date")
        e_date = intent_data.get("end_date")
        if not s_date or not e_date or not is_valid_date(s_date) or not is_valid_date(e_date):
            return False, "clarify", make_clarify_reply(f"excavation from 01-01-2025 to 05-01-2025")

    elif op == "aggregate":
        # Check month if provided
        m = intent_data.get("month")
        if m is not None and m not in VALID_MONTHS:
            return False, "clarify", make_clarify_reply(f"total excavation in January")
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
