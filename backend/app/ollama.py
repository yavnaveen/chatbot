import json
import logging
import os
import re

import httpx

from backend.app.schemas import Intent

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OUT_OF_SCOPE_REPLY = "Sorry, I can only help with tunnel excavation questions. You can ask: 'What was the actual excavation on 01-01-2025?' or 'What is the total excavation for support class A?'"

SYSTEM_PROMPT = """You are a router for a Tunnel Excavation assistant. Return JSON only with exactly these keys: operation, metric, date, start_date, end_date, month, year, support_class, start_ch, end_ch, aggregate, day.
Return operation chat only for greetings, thanks, goodbye, how are you, who are you, or what can you do. For anything not about the tunnel database, return operation out_of_scope and set every other key to null. For database questions operation is record, aggregate, group_by_support, range_records, difference, highest, or day_records. Use record only for a complete specific date. Never invent values; unknown fields are null. Dates are DD-MM-YYYY, month/year are numbers, and never output SQL or explanations. If the message is a short follow-up (e.g. "aur theoretical?", "ab class B ke liye"), reuse the previous intent from context and change only what the user mentions.

Examples: Good morning -> {"operation":"chat","metric":null,"date":null,"start_date":null,"end_date":null,"month":null,"year":null,"support_class":null,"start_ch":null,"end_ch":null,"aggregate":null,"day":null}; who is PM of india? -> {"operation":"out_of_scope","metric":null,"date":null,"start_date":null,"end_date":null,"month":null,"year":null,"support_class":null,"start_ch":null,"end_ch":null,"aggregate":null,"day":null}; write hello world in html -> {"operation":"out_of_scope","metric":null,"date":null,"start_date":null,"end_date":null,"month":null,"year":null,"support_class":null,"start_ch":null,"end_ch":null,"aggregate":null,"day":null}; bikaner se delhi train -> {"operation":"out_of_scope","metric":null,"date":null,"start_date":null,"end_date":null,"month":null,"year":null,"support_class":null,"start_ch":null,"end_ch":null,"aggregate":null,"day":null}; 01-01-2025 ko actual excavation kitna tha -> {"operation":"record","metric":"actual","date":"01-01-2025","start_date":null,"end_date":null,"month":null,"year":null,"support_class":null,"start_ch":null,"end_ch":null,"aggregate":null,"day":null}; support class A me total excavation kitna hai -> {"operation":"aggregate","metric":"actual","date":null,"start_date":null,"end_date":null,"month":null,"year":null,"support_class":"A","start_ch":null,"end_ch":null,"aggregate":"sum","day":null}.
""" # old prompt removed
'''"""You classify tunnel excavation questions into JSON only.
Return exactly one object with keys: operation, metric, date, start_date, end_date, month, year,
support_class, start_ch, end_ch, aggregate.
operation is one of record, aggregate, group_by_support, range_records, difference, highest.
metric is actual, theoretical, or both. Use actual when the question explicitly says actual;
theoretical when explicitly says theoretical; both only for comparisons/difference.
aggregate is sum, avg, min, or max for aggregate operations, otherwise null.
Dates must be DD-MM-YYYY. Resolve January/February 2025. Never output SQL.
Use highest when asking which date had the highest excavation; use actual unless theoretical is explicit.
Use group_by_support when the question asks “under which support class” or asks excavation for every support class.
"""'''

CHAT_PROMPT = """You are Tunnel Excavation AI. Always reply in English. Handle only greetings, thanks, goodbye, how are you, who are you, and what can you do. Reply in 1-2 sentences, then offer help with tunnel excavation data. Never answer other topics or invent excavation numbers.
\n/no_think"""

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def fallback_intent(question: str, previous_intent: Intent | None = None) -> Intent | None:
    """Safely classify common supported questions if model JSON is malformed."""
    text = question.casefold()
    if re.fullmatch(r"\s*(?:hi|hello|hey|namaste|good\s+(?:morning|evening|afternoon|night)|how\s+are\s+you|kaise\s+ho|thanks|thank\s+you|bye|goodbye|see\s+you|who\s+are\s+you|what\s+can\s+you\s+do)\s*[!.?]*\s*", text):
        return Intent(operation="chat")
    off_topic_keywords = ("prime minister", "pm of", "president", "capital of", "train", "weather", "news", "cricket", "movie", "joke", "html", "python", "javascript", "code", "recipe", "stock", "price", "pradhan mantri", "mausam")
    data_words = ("excavation", "pull", "support", "class", "chainage", "theoretical", "actual", "khudai", "tarikh", "date")
    if any(keyword in text for keyword in off_topic_keywords) and not any(word in text for word in data_words):
        return Intent(operation="out_of_scope")
    if previous_intent:
        metric_match = re.search(r"\b(actual|theoretical|both|dono)\b", text)
        support_match = re.search(r"(?:support\s*class|class)\s*([a-f])\b", text)
        remainder = re.sub(r"\b(?:actual|theoretical|both|dono|aur|ab|support|class|ke|liye|please|plz|me|mein|for|the)\b", "", text)
        remainder = re.sub(r"[a-f]", "", remainder)
        remainder = re.sub(r"[\s?.!,]+", "", remainder)
        if metric_match and not remainder:
            metric = "both" if metric_match.group(1) == "dono" else metric_match.group(1)
            return previous_intent.model_copy(update={"metric": metric})
        if support_match and not remainder:
            return previous_intent.model_copy(update={"support_class": support_match.group(1).upper()})
    metric = "theoretical" if "theoretical" in text or "सैद्धांतिक" in text else "actual" if "actual" in text or "वास्तविक" in text else "both"
    dates = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", text)
    dates = [re.sub(r"/", "-", item) for item in dates]
    support_match = re.search(r"(?:support\s*class|class)\s*([a-f])\b|\b([a-f])\s*class\b", text)
    support_class = (support_match.group(1) or support_match.group(2)).upper() if support_match else None
    day_match = re.search(r"\b(\d{1,2})\s*(?:ko|date|tarikh|तारीख)\b", text)
    if day_match and ("pull" in text or "support" in text or "class" in text):
        return Intent(operation="day_records", metric="both", day=int(day_match.group(1)))

    if "under which support class" in text or "support class wise" in text or "every support class" in text or "each support class" in text or ("support class" in text and ("how much" in text or "kitna" in text or "कितना" in text) and not support_class):
        return Intent(operation="group_by_support", metric=metric)
    if "difference" in text or "अंतर" in text or "farq" in text or ("theoretical" in text and "actual" in text and ("compare" in text or "versus" in text)):
        return Intent(operation="difference", metric="both")
    if "highest" in text or "maximum" in text or "max" in text or "सबसे अधिक" in text or "अधिकतम" in text or ("which date" in text and "excavation" in text):
        return Intent(operation="highest", metric="theoretical" if metric == "theoretical" else "actual")

    chainage = re.search(r"(?:chainage|ch)\s*(?:between|from)?\s*(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)", text)
    if chainage:
        return Intent(
            operation="aggregate",
            metric=metric,
            aggregate="sum",
            start_ch=float(chainage.group(1)),
            end_ch=float(chainage.group(2)),
        )
    if len(dates) >= 2 and ("between" in text or "from" in text):
        return Intent(operation="range_records", metric=metric, start_date=dates[0], end_date=dates[1])
    if dates:
        return Intent(operation="record", metric=metric, date=dates[0])

    month = next((number for name, number in MONTHS.items() if name in text), None)
    year_match = re.search(r"\b20\d{2}\b", text)
    year = int(year_match.group()) if year_match else None
    data_words = ("excavation", "pull", "support", "class", "chainage", "theoretical", "actual", "khudai", "खुदाई", "date", "tarikh", "तारीख")
    if (month or any(word in text for word in ("total", "sum", "average", "avg", "औसत", "minimum", "maximum", "max", "kitna", "कितना", "कुल"))) and any(word in text for word in data_words):
        aggregate = "avg" if "average" in text or "avg" in text or "औसत" in text else "min" if "minimum" in text else "max" if "maximum" in text or "max" in text else "sum"
        if support_class:
            return Intent(operation="aggregate", metric=metric, aggregate=aggregate, support_class=support_class)
        return Intent(operation="aggregate", metric=metric, aggregate=aggregate, month=month, year=year)
    return None


def apply_question_constraints(intent: Intent, question: str) -> Intent:
    """Prevent a valid-but-wrong model intent from bypassing obvious query constraints."""
    text = question.casefold()
    metric = "theoretical" if "theoretical" in text else "actual" if "actual" in text else "both"
    support_match = re.search(r"(?:support\s*class|class)\s*([a-f])\b|\b([a-f])\s*class\b", text)
    if support_match and ("kitna" in text or "how much" in text or "total" in text or "excavation" in text):
        return intent.model_copy(update={
            "operation": "aggregate",
            "aggregate": "sum",
            "support_class": (support_match.group(1) or support_match.group(2)).upper(),
            "metric": metric,
            "date": None,
            "start_date": None,
            "end_date": None,
            "month": None,
            "year": None,
            "start_ch": None,
            "end_ch": None,
        })
    chainage = re.search(r"(?:chainage|ch)\s*(?:between|from)?\s*(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)", text)
    if chainage:
        return intent.model_copy(update={
            "operation": "aggregate",
            "aggregate": "sum",
            "metric": metric,
            "start_ch": float(chainage.group(1)),
            "end_ch": float(chainage.group(2)),
        })
    if "under which support class" in text or "support class wise" in text or "every support class" in text or "each support class" in text:
        return intent.model_copy(update={"operation": "group_by_support", "support_class": None, "metric": metric})
    if intent.operation in {"aggregate", "group_by_support", "range_records"} and metric == "both":
        return intent.model_copy(update={"metric": "both"})
    return intent


async def classify_question(
    question: str,
    previous_intent: Intent | None = None,
    recent_messages: list[dict[str, str]] | None = None,
) -> Intent:
    local_intent = fallback_intent(question, previous_intent)
    if local_intent is not None:
        return local_intent
    if not re.search(r"excavation|pull|support|class|chainage|theoretical|actual|khudai|खुदाई|date|tarikh|तारीख|\d{1,2}[-/]\d{1,2}[-/]\d{4}", question.casefold()):
        return Intent(operation="out_of_scope")
    context_lines = [f"Previous intent: {previous_intent.model_dump_json() if previous_intent else 'none'}"]
    if recent_messages:
        context_lines.append("Recent messages:")
        context_lines.extend(f"{item['role']}: {item['content'][:1000]}" for item in recent_messages[-4:])
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "system": SYSTEM_PROMPT,
        "prompt": "Context:\n" + "\n".join(context_lines) + "\n\nCurrent message:\n" + question,
        "think": False,
        "options": {"temperature": 0, "num_predict": 256},
    }
    try:
        logging.info("Calling Ollama model: %s", OLLAMA_MODEL)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
            raw = body.get("response", "")
            parsed = json.loads(raw)
            # Small local normalization layer: compact models sometimes emit the
            # literal string "null" and may copy wording into support_class.
            for key, value in list(parsed.items()):
                if isinstance(value, str) and value.strip().lower() in {"null", "none", "n/a", "na"}:
                    parsed[key] = None
            month = parsed.get("month")
            if isinstance(month, str):
                parsed["month"] = MONTHS.get(month.strip().lower(), month)
            support = parsed.get("support_class")
            if isinstance(support, str) and support.upper() not in {"A", "B", "C", "D", "E", "F"}:
                parsed["support_class"] = None
            question_lower = question.lower()
            if "under which support class" in question_lower or "each support class" in question_lower or "every support class" in question_lower:
                parsed["operation"] = "group_by_support"
                parsed["support_class"] = None
            intent = apply_question_constraints(Intent.model_validate(parsed), question)
            if intent.operation == "record" and not intent.date:
                return Intent(operation="chat")
            return intent
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        raise RuntimeError("Ollama did not respond in time. Check that Ollama is running and the model is loaded.") from exc
    except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError):
        recovered = fallback_intent(question, previous_intent)
        if recovered is not None:
            return recovered
        return Intent(operation="chat")


async def chat_reply(question: str, history: list[dict[str, str]] | None = None) -> str:
    filtered_history = [
        item for item in (history or [])
        if not (
            item.get("role") == "assistant"
            and (
                item.get("content", "").casefold().startswith("okay, the user")
                or "<think>" in item.get("content", "").casefold()
                or "let me think" in item.get("content", "").casefold()
            )
        )
    ]
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": CHAT_PROMPT},
            *[{"role": item["role"], "content": item["content"][:1000]} for item in filtered_history],
            {"role": "user", "content": question},
        ],
        "think": False,
        "options": {"temperature": 0.7, "num_predict": 400},
    }
    try:
        logging.info("Calling Ollama model: %s", OLLAMA_MODEL)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            text = response.json().get("message", {}).get("content", "") or ""
            cleaned = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.DOTALL).strip()
            if cleaned.casefold().startswith("okay, the user"):
                return "Sorry, I had trouble answering that question. Please try again."
            return cleaned or "Sorry, I had trouble answering that question. Please try again."
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        raise RuntimeError("Ollama did not respond in time. Check that Ollama is running and the model is loaded.") from exc

