import csv
from datetime import datetime
import io
from typing import Any, BinaryIO, Tuple

import openpyxl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db import ExcavationRecord


def standardize_date(val: Any) -> str:
    """Normalize any date format (datetime, DD-MM-YYYY, YYYY-MM-DD, DD/MM/YYYY) into DD-MM-YYYY."""
    if isinstance(val, datetime):
        return val.strftime("%d-%m-%Y")
    text = str(val).strip()
    # Replace / with -
    text = text.replace("/", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y", "%m-%d-%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%d-%m-%Y")
        except ValueError:
            pass
    raise ValueError(f"Invalid date format: {val}. Expected DD-MM-YYYY or YYYY-MM-DD.")


def parse_rows(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Parse CSV or Excel file bytes into raw row dictionaries."""
    rows: list[dict[str, Any]] = []
    lower_fn = filename.lower()

    if lower_fn.endswith(".csv"):
        text_content = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text_content))
        for r in reader:
            rows.append({k.strip().lower(): v for k, v in r.items() if k})

    elif lower_fn.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        headers = [str(cell.value or "").strip().lower() for cell in sheet[1]]
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            row_dict = {}
            for h, v in zip(headers, row):
                if h:
                    row_dict[h] = v
            rows.append(row_dict)
    else:
        raise ValueError("Unsupported file format. Please upload a .csv or .xlsx file.")

    return rows


COLUMN_MAP = {
    "date": ["date", "tarikh", "dates"],
    "start_ch": ["start_ch", "start_chainage", "from_ch", "ch_start", "start"],
    "end_ch": ["end_ch", "end_chainage", "to_ch", "ch_end", "end"],
    "pull": ["pull", "pull_m", "pull_len", "length"],
    "support_class": ["support_class", "class", "support", "rock_class"],
    "theoretical_volume": ["theoretical_volume", "theoretical", "theo_vol", "theoretical_m3"],
    "actual_volume": ["actual_volume", "actual", "act_vol", "actual_m3"],
}


def find_val(row: dict[str, Any], col_name: str) -> Any:
    for alias in COLUMN_MAP.get(col_name, [col_name]):
        if alias in row and row[alias] is not None and str(row[alias]).strip() != "":
            return row[alias]
    raise ValueError(f"Missing required column for '{col_name}'.")


def import_excavation_data(
    file_bytes: bytes,
    filename: str,
    session: Session,
) -> dict[str, Any]:
    """Parse and upsert excavation records into database."""
    raw_rows = parse_rows(file_bytes, filename)
    if not raw_rows:
        raise ValueError("The uploaded file contains no data rows.")

    inserted = 0
    updated = 0
    errors: list[str] = []

    for idx, r in enumerate(raw_rows, start=2):
        try:
            date_str = standardize_date(find_val(r, "date"))
            start_ch = float(find_val(r, "start_ch"))
            end_ch = float(find_val(r, "end_ch"))
            pull = float(find_val(r, "pull"))
            support = str(find_val(r, "support_class")).strip().upper()
            if support not in {"A", "B", "C", "D", "E", "F"}:
                raise ValueError(f"Invalid support class '{support}'. Must be one of A-F.")
            theo = float(find_val(r, "theoretical_volume"))
            actual = float(find_val(r, "actual_volume"))

            existing = session.scalar(select(ExcavationRecord).where(ExcavationRecord.date == date_str))
            if existing:
                existing.start_ch = start_ch
                existing.end_ch = end_ch
                existing.pull = pull
                existing.support_class = support
                existing.theoretical_volume = theo
                existing.actual_volume = actual
                updated += 1
            else:
                new_rec = ExcavationRecord(
                    date=date_str,
                    start_ch=start_ch,
                    end_ch=end_ch,
                    pull=pull,
                    support_class=support,
                    theoretical_volume=theo,
                    actual_volume=actual,
                )
                session.add(new_rec)
                inserted += 1

        except Exception as exc:
            errors.append(f"Row {idx}: {exc}")

    session.commit()

    total_records = session.scalar(select(func.count(ExcavationRecord.id))) or 0

    return {
        "status": "success",
        "imported": inserted + updated,
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
        "total_records": total_records,
    }
