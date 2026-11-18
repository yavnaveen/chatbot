from datetime import datetime

from sqlalchemy import Integer, Select, and_, func, select

from backend.app.db import ExcavationRecord
from backend.app.schemas import Intent


def _date(value: str | None) -> str | None:
    if not value:
        return None
    datetime.strptime(value, "%d-%m-%Y")
    return value


def get_intent_filters(intent: Intent):
    date = _date(intent.date)
    start_date = _date(intent.start_date)
    end_date = _date(intent.end_date)
    filters = []
    if date:
        filters.append(ExcavationRecord.date == date)
    sortable_date = (
        func.substr(ExcavationRecord.date, 7, 4)
        .concat(func.substr(ExcavationRecord.date, 4, 2))
        .concat(func.substr(ExcavationRecord.date, 1, 2))
    )
    if start_date:
        filters.append(sortable_date >= start_date[6:] + start_date[3:5] + start_date[:2])
    if end_date:
        filters.append(sortable_date <= end_date[6:] + end_date[3:5] + end_date[:2])
    if intent.month:
        filters.append(func.substr(ExcavationRecord.date, 4, 2) == f"{intent.month:02d}")
    if intent.year:
        filters.append(func.substr(ExcavationRecord.date, 7, 4) == str(intent.year))
    if intent.day:
        if not 1 <= intent.day <= 31:
            raise ValueError("Day must be between 1 and 31")
        filters.append(func.substr(ExcavationRecord.date, 1, 2) == f"{intent.day:02d}")
    if intent.support_class:
        support = intent.support_class.upper()
        if support not in {"A", "B", "C", "D", "E", "F"}:
            raise ValueError("Unknown support class")
        filters.append(ExcavationRecord.support_class == support)
    if intent.start_ch is not None:
        filters.append(ExcavationRecord.start_ch >= intent.start_ch)
    if intent.end_ch is not None:
        filters.append(ExcavationRecord.end_ch <= intent.end_ch)
    if intent.operation == "day_range":
        s_day = intent.start_day or 1
        e_day = intent.end_day or 31
        day_expr = func.cast(func.substr(ExcavationRecord.date, 1, 2), Integer)
        filters.append(and_(day_expr >= s_day, day_expr <= e_day))
    return filters, sortable_date


def build_records_query(intent: Intent) -> Select:
    """Build a SELECT statement returning ExcavationRecord objects matching the intent filters."""
    filters, sortable_date = get_intent_filters(intent)
    stmt = select(ExcavationRecord)
    if filters:
        stmt = stmt.where(and_(*filters))
    return stmt.order_by(sortable_date)


def build_query(intent: Intent) -> Select:
    """Build only pre-defined SQLAlchemy statements; model text never becomes SQL."""
    filters, sortable_date = get_intent_filters(intent)
    where = and_(*filters) if filters else None

    def filtered(statement: Select) -> Select:
        return statement.where(where) if where is not None else statement

    if intent.operation == "row_count":
        return filtered(select(func.count(ExcavationRecord.id)))
    if intent.operation == "record":
        return filtered(select(ExcavationRecord)).order_by(sortable_date)
    if intent.operation == "range_records":
        return filtered(select(ExcavationRecord)).order_by(sortable_date)
    if intent.operation == "day_records":
        return filtered(select(ExcavationRecord)).order_by(sortable_date)
    if intent.operation == "day_range":
        return filtered(select(ExcavationRecord)).order_by(sortable_date)
    if intent.operation == "highest":
        return filtered(select(ExcavationRecord)).order_by(ExcavationRecord.actual_volume.desc(), sortable_date).limit(1)
    if intent.operation == "lowest":
        return filtered(select(ExcavationRecord)).order_by(ExcavationRecord.actual_volume.asc(), sortable_date).limit(1)
    if intent.operation == "group_by_support":
        if intent.metric == "both":
            statement = select(
                ExcavationRecord.support_class,
                func.sum(ExcavationRecord.theoretical_volume),
                func.sum(ExcavationRecord.actual_volume),
            )
        else:
            column = ExcavationRecord.theoretical_volume if intent.metric == "theoretical" else ExcavationRecord.actual_volume
            statement = select(ExcavationRecord.support_class, func.sum(column))
        return filtered(statement).group_by(ExcavationRecord.support_class).order_by(ExcavationRecord.support_class)
    if intent.operation == "difference":
        return filtered(select(func.sum(ExcavationRecord.theoretical_volume), func.sum(ExcavationRecord.actual_volume)))

    aggregate = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}.get(intent.aggregate or "sum")
    if aggregate is None:
        raise ValueError("Unsupported aggregate")
    if intent.metric == "both":
        return filtered(select(aggregate(ExcavationRecord.theoretical_volume), aggregate(ExcavationRecord.actual_volume)))
    column = ExcavationRecord.theoretical_volume if intent.metric == "theoretical" else ExcavationRecord.actual_volume
    return filtered(select(aggregate(column)))
    return filtered(select(aggregate(column)))

