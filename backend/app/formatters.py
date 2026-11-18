from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db import ExcavationRecord
from backend.app.schemas import Intent

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


def format_num(val: float | int | None, force_sign: bool = False) -> str:
    """Format number to at most 2 decimal places, dropping trailing .0.
    Optionally prefix with sign (+ or -).
    """
    if val is None:
        return "0"
    v = round(float(val), 2)
    if abs(v) < 1e-9:
        v = 0.0
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    if force_sign and v > 0:
        return f"+{s}"
    return s


def _number(value: float | int | None) -> str:
    """Backwards-compatible alias for format_num."""
    return format_num(value)


def get_dataset_bounds(session: Session) -> tuple[str, str, int]:
    """Return (first_date, last_date, total_count) sorted chronologically."""
    records = session.query(ExcavationRecord.date).all()
    if not records:
        return "01-01-2025", "25-02-2025", 0
    dates = [r[0] for r in records if r[0]]

    def _to_tuple(d: str):
        parts = d.split("-")
        try:
            return (int(parts[2]), int(parts[1]), int(parts[0]))
        except (IndexError, ValueError):
            return (0, 0, 0)

    sorted_dates = sorted(dates, key=_to_tuple)
    return sorted_dates[0], sorted_dates[-1], len(dates)


def get_scope_description(
    intent: Intent, count: int, first_date: str, last_date: str
) -> tuple[str, str]:
    """Return (scope_prefix, scope_phrase) based on resolved intent filters."""
    rec_word = "record" if count == 1 else "records"
    count_str = f"({count} {rec_word})"

    # 1. Single date
    if intent.date:
        return f"On {intent.date}: ", f"on {intent.date}"

    # 2. Date range
    if intent.start_date and intent.end_date:
        if intent.support_class:
            cls = intent.support_class.upper()
            return (
                f"For support class {cls} from {intent.start_date} to {intent.end_date} {count_str}: ",
                f"for support class {cls} from {intent.start_date} to {intent.end_date} {count_str}",
            )
        return (
            f"From {intent.start_date} to {intent.end_date} {count_str}: ",
            f"from {intent.start_date} to {intent.end_date} {count_str}",
        )

    # 3. Month
    if intent.month:
        m_name = MONTH_NAMES.get(intent.month, f"Month {intent.month}")
        yr = intent.year or 2025
        if intent.support_class:
            cls = intent.support_class.upper()
            return (
                f"For support class {cls} in {m_name} {yr} {count_str}: ",
                f"for support class {cls} in {m_name} {yr} {count_str}",
            )
        return f"In {m_name} {yr} {count_str}: ", f"in {m_name} {yr} {count_str}"

    # 4. Support class alone
    if intent.support_class:
        cls = intent.support_class.upper()
        return f"For support class {cls} {count_str}: ", f"for support class {cls} {count_str}"

    # 5. Chainage range
    if intent.start_ch is not None or intent.end_ch is not None:
        c1 = format_num(intent.start_ch) if intent.start_ch is not None else "0"
        c2 = format_num(intent.end_ch) if intent.end_ch is not None else "max"
        return f"For chainage {c1} to {c2} {count_str}: ", f"for chainage {c1} to {c2} {count_str}"

    # 6. Day range (across all months)
    if intent.start_day is not None and intent.end_day is not None:
        return (
            f"For days {intent.start_day} to {intent.end_day} {count_str}: ",
            f"for days {intent.start_day} to {intent.end_day} {count_str}",
        )

    # 7. No filter (whole dataset)
    return (
        f"Across all records ({first_date} to {last_date}, {count} {rec_word}): ",
        f"across all records ({first_date} to {last_date}, {count} {rec_word})",
    )


def get_scope_target(intent: Intent) -> str:
    """Format scope target description for 0 matching records."""
    if intent.date:
        return f"date {intent.date}"
    if intent.start_date and intent.end_date:
        return f"dates {intent.start_date} to {intent.end_date}"
    if intent.month:
        m_name = MONTH_NAMES.get(intent.month, f"Month {intent.month}")
        yr = intent.year or 2025
        return f"{m_name} {yr}"
    if intent.support_class:
        return f"support class {intent.support_class.upper()}"
    if intent.start_ch is not None or intent.end_ch is not None:
        c1 = format_num(intent.start_ch) if intent.start_ch is not None else "0"
        c2 = format_num(intent.end_ch) if intent.end_ch is not None else "max"
        return f"chainage {c1} to {c2}"
    return "the specified query"


def format_difference_answer(
    scope_prefix: str,
    theoretical: float,
    actual: float,
    records_count: int,
) -> str:
    """Requirement 2: 'Theoretical: X, Actual: Y, Difference (actual - theoretical): Z.'
    Show sign (+ or -) and '(actual is higher)' / '(actual is lower)' when Z != 0.
    """
    diff = round(actual - theoretical, 2)
    diff_str = format_num(diff, force_sign=True)
    if diff > 0:
        hl = " (actual is higher)"
    elif diff < 0:
        hl = " (actual is lower)"
    else:
        hl = ""
    return f"{scope_prefix}Theoretical: {format_num(theoretical)}, Actual: {format_num(actual)}, Difference (actual - theoretical): {diff_str}{hl}."


def format_aggregate_answer(
    intent: Intent,
    scope_prefix: str,
    val_actual: float | None,
    val_theo: float | None = None,
    extreme_record: Optional[ExcavationRecord] = None,
) -> str:
    """Requirement 1 & 6: Starts with scope prefix, says metric and aggregate type in words.
    For min/max/highest: include where it happened: '(on DD-MM-YYYY, support class X)'.
    """
    agg_label = {
        "sum": "Total",
        "avg": "Average",
        "min": "Minimum",
        "max": "Maximum",
    }.get(intent.aggregate or "sum", "Total")

    extra_loc = ""
    if extreme_record and (intent.aggregate in ("min", "max")):
        extra_loc = f" (on {extreme_record.date}, support class {extreme_record.support_class})"

    if intent.metric == "both" and val_actual is not None and val_theo is not None:
        return (
            f"{scope_prefix}{agg_label} actual excavation: {format_num(val_actual)}{extra_loc}. "
            f"{agg_label} theoretical excavation: {format_num(val_theo)}."
        )
    elif intent.metric == "theoretical" and val_theo is not None:
        return f"{scope_prefix}{agg_label} theoretical excavation: {format_num(val_theo)}{extra_loc}."
    else:
        v = val_actual if val_actual is not None else val_theo
        return f"{scope_prefix}{agg_label} actual excavation: {format_num(v)}{extra_loc}."


def record_answer(record: ExcavationRecord, metric: str | None = None) -> str:
    pull_str = format_num(record.pull)
    act_str = format_num(record.actual_volume)
    theo_str = format_num(record.theoretical_volume)
    if metric == "theoretical":
        return f"On {record.date}: Pull was {pull_str}, theoretical excavation was {theo_str}. Support class was {record.support_class}."
    if metric == "actual":
        return f"On {record.date}: Pull was {pull_str}, actual excavation was {act_str}. Support class was {record.support_class}."
    return f"On {record.date}: Pull was {pull_str}, actual excavation was {act_str} and theoretical excavation was {theo_str}. Support class was {record.support_class}."


def build_result_table(
    records: list[ExcavationRecord],
    is_difference: bool = False,
    max_display: int = 20,
) -> tuple[list[list[str]], list[list[str]], bool]:
    """Build table for frontend rendering.
    Returns:
        (display_table, all_table, is_truncated)
    display_table is capped at max_display data rows (default 20).
    all_table holds all records for complete CSV export.
    """
    if is_difference:
        headers = ["Date", "Pull", "Support Class", "Theoretical", "Actual", "Difference"]
        raw_rows = []
        total_theo = 0.0
        total_act = 0.0
        for r in records:
            total_theo += r.theoretical_volume
            total_act += r.actual_volume
            d = r.actual_volume - r.theoretical_volume
            raw_rows.append([
                r.date,
                format_num(r.pull),
                r.support_class,
                format_num(r.theoretical_volume),
                format_num(r.actual_volume),
                format_num(d, force_sign=True),
            ])
        total_diff = total_act - total_theo
        total_row = [
            "Total",
            "-",
            "-",
            format_num(total_theo),
            format_num(total_act),
            format_num(total_diff, force_sign=True),
        ]
        all_table = [headers] + raw_rows + [total_row]
        is_truncated = len(records) > max_display
        display_table = [headers] + raw_rows[:max_display] + [total_row] if is_truncated else all_table
        return display_table, all_table, is_truncated
    else:
        headers = ["Date", "Pull", "Support Class", "Theoretical", "Actual"]
        raw_rows = [
            [
                r.date,
                format_num(r.pull),
                r.support_class,
                format_num(r.theoretical_volume),
                format_num(r.actual_volume),
            ]
            for r in records
        ]
        all_table = [headers] + raw_rows
        is_truncated = len(records) > max_display
        display_table = [headers] + raw_rows[:max_display] if is_truncated else all_table
        return display_table, all_table, is_truncated
