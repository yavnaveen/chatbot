from typing import Any, Dict, Optional, Tuple

from backend.app.nlp.extractor import extract_entities
from backend.app.nlp.llm import classify_with_llm, deterministic_classify
from backend.app.nlp.normalize import normalize_question
from backend.app.nlp.validator import validate_intent_answerability


async def process_question(
    raw_question: str,
    context: Optional[Dict[str, Any]] = None,
    mock: bool = False,
) -> Tuple[Dict[str, Any], bool, str, Optional[str]]:
    """Full NLP pipeline:
    1. Normalizer (lowercases, collapses whitespace, fixes spelling of known vocab, normalizes dates)
    2. Entity extractor in code (dates, month, year, support_class, chainage, days, metric, aggregate)
    3. LLM classifier (with code entity override)
    4. Validator (checks DB answerability, confidence, out_of_scope refusal, or clarification)

    Returns:
        (intent_dict, is_valid, behavior, message)
        behavior in {"answer", "clarify", "refuse"}
    """
    # 1. Normalize
    normalized = normalize_question(raw_question)

    # 2. Extract entities in code
    entities = extract_entities(normalized)

    # 3. Classify with LLM (or mock)
    intent_data = await classify_with_llm(
        raw_question=raw_question,
        normalized=normalized,
        entities=entities,
        context=context,
        mock=mock,
    )

    # 4. Strict Code Override: Extracted entities always override LLM entities
    for key in (
        "date",
        "start_date",
        "end_date",
        "month",
        "year",
        "support_class",
        "start_ch",
        "end_ch",
        "day",
        "start_day",
        "end_day",
    ):
        if entities.get(key) is not None:
            intent_data[key] = entities[key]
    if entities.get("metric") and entities["metric"] != "actual":
        intent_data["metric"] = entities["metric"]
    if entities.get("aggregate"):
        intent_data["aggregate"] = entities["aggregate"]

    # 5. Validator
    is_valid, behavior, message = validate_intent_answerability(intent_data)

    return intent_data, is_valid, behavior, message
