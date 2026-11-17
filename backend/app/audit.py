from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Optional

AUDIT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "audit.log"


def log_audit_event(
    client_ip: str,
    endpoint: str,
    question: Optional[str] = None,
    generated_query: Optional[str] = None,
    response_time_ms: float = 0.0,
    status: str = "success",
    violation_flag: bool = False,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Append a structured security & operational audit event to backend/data/audit.log."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": client_ip,
        "endpoint": endpoint,
        "question": question[:500] if question else None,
        "generated_query": generated_query,
        "response_time_ms": round(response_time_ms, 2),
        "status": status,
        "violation_flag": violation_flag,
        "metadata": metadata or {},
    }

    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:
        logging.error("Failed to write audit log: %s", exc)
