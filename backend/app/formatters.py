from backend.app.db import ExcavationRecord


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def record_answer(record: ExcavationRecord, metric: str) -> str:
    if metric == "theoretical":
        return f"On {record.date}, pull was {_number(record.pull)}, theoretical excavation was {_number(record.theoretical_volume)}. Support class was {record.support_class}."
    if metric == "both":
        return f"On {record.date}, pull was {_number(record.pull)}, actual excavation was {_number(record.actual_volume)} and theoretical excavation was {_number(record.theoretical_volume)}. Support class was {record.support_class}."
    return f"On {record.date}, pull was {_number(record.pull)}, actual excavation was {_number(record.actual_volume)} and theoretical excavation was {_number(record.theoretical_volume)}. Support class was {record.support_class}."

