import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.app.nlp.pipeline import process_question


def is_typo_question(q: str) -> bool:
    typo_signals = (
        "excvation", "theoretcal", "actul", "januray", "febuary", "suport",
        "clas", "chanage", "totl", "averge", "higest", "lowst", "diffrence",
        "reocrd", "volum", "wich", "presidnt", "pythn", "frnce", "1to5",
        "10to15", "data base"
    )
    q_low = q.lower()
    return any(t in q_low for t in typo_signals)


def categorize_question(op: str, behavior: str) -> str:
    if behavior == "refuse":
        if op == "mutation_refusal":
            return "Security / Destructive"
        return "Out of Scope / Refusal"
    if behavior == "clarify":
        return "Clarifications / Boundary"
    if op == "chat":
        return "Greetings"
    if op == "record":
        return "Date Record"
    if op == "aggregate":
        return "Aggregate (Month/Class/Ch)"
    if op == "range_records":
        return "Date Range"
    if op in ("highest", "lowest"):
        return "Highest / Lowest"
    if op == "difference":
        return "Difference / Compare"
    if op in ("count_rows", "row_count"):
        return "Row Count"
    if op == "group_by_support":
        return "Support Class Grouping"
    return "Other"


async def evaluate_set(set_name: str, mock: bool = False) -> Tuple[float, float, Dict[str, Tuple[int, int]], List[Dict[str, Any]], str]:
    csv_path = Path("tests/golden") / f"{set_name}.csv"
    if not csv_path.exists():
        csv_path = Path("d:/Softwares/chatbot/tests/golden") / f"{set_name}.csv"

    if not csv_path.exists():
        print(f"Error: {csv_path} does not exist.")
        sys.exit(1)

    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    total = len(rows)
    correct = 0
    typo_total = 0
    typo_correct = 0
    cat_stats: Dict[str, List[int]] = {}  # cat -> [correct, total]
    failures = []

    for row in rows:
        q = row["question"]
        exp_op = row["expected_operation"]
        exp_metric = row.get("expected_metric") or None
        exp_date = row.get("expected_date") or None
        exp_month = int(row["expected_month"]) if row.get("expected_month") else None
        exp_class = row.get("expected_class") or None
        exp_start_ch = float(row["expected_start_ch"]) if row.get("expected_start_ch") else None
        exp_end_ch = float(row["expected_end_ch"]) if row.get("expected_end_ch") else None
        exp_behavior = row["expected_behavior"]

        category = categorize_question(exp_op, exp_behavior)
        if category not in cat_stats:
            cat_stats[category] = [0, 0]
        cat_stats[category][1] += 1

        is_typo = is_typo_question(q)
        if is_typo:
            typo_total += 1

        # Run pipeline
        intent, is_valid, behavior, message = await process_question(q, mock=mock)

        got_op = intent.get("operation")
        # Accept alias count_rows / row_count
        op_match = (got_op == exp_op) or (got_op in ("count_rows", "row_count") and exp_op in ("count_rows", "row_count"))
        behavior_match = (behavior == exp_behavior)

        metric_match = True
        if exp_metric and exp_behavior == "answer":
            got_m = intent.get("metric")
            if exp_metric == "both":
                metric_match = (got_m in ("both", "actual")) if exp_op == "range_records" else (got_m == "both")
            else:
                metric_match = (got_m == exp_metric)

        date_match = True
        if exp_date and exp_behavior == "answer":
            date_match = (intent.get("date") == exp_date or intent.get("start_date") == exp_date)

        month_match = True
        if exp_month and exp_behavior == "answer":
            month_match = (intent.get("month") == exp_month)

        class_match = True
        if exp_class and exp_behavior == "answer":
            class_match = (intent.get("support_class") == exp_class)

        ch_match = True
        if exp_start_ch is not None and exp_behavior == "answer":
            ch_match = (intent.get("start_ch") == exp_start_ch and intent.get("end_ch") == exp_end_ch)

        passed = op_match and behavior_match and metric_match and date_match and month_match and class_match and ch_match

        if passed:
            correct += 1
            cat_stats[category][0] += 1
            if is_typo:
                typo_correct += 1
        else:
            failures.append({
                "question": q,
                "expected": f"op={exp_op}, behavior={exp_behavior}, metric={exp_metric or '-'}, date={exp_date or '-'}",
                "got": f"op={got_op}, behavior={behavior}, metric={intent.get('metric') or '-'}, date={intent.get('date') or intent.get('start_date') or '-'}",
                "category": category,
            })

    accuracy = (correct / total) * 100 if total else 0.0
    typo_accuracy = (typo_correct / typo_total) * 100 if typo_total else 0.0

    # Build markdown report
    report_lines = [
        f"# Evaluation Report: `{set_name}.csv`",
        "",
        f"- **Mode**: {'Mocked Deterministic' if mock else 'Live Ollama'}",
        f"- **Total Questions**: {total}",
        f"- **Passed**: {correct} / {total}",
        f"- **Overall Accuracy**: **{accuracy:.1f}%**",
        f"- **Typo Accuracy**: **{typo_accuracy:.1f}%** ({typo_correct}/{typo_total})",
        "",
        "## Accuracy Per Category",
        "",
        "| Category | Passed | Total | Accuracy |",
        "| :--- | :---: | :---: | :---: |",
    ]

    for cat, (c_cnt, t_cnt) in sorted(cat_stats.items()):
        cat_pct = (c_cnt / t_cnt) * 100 if t_cnt else 0.0
        report_lines.append(f"| {cat} | {c_cnt} | {t_cnt} | {cat_pct:.1f}% |")

    if failures:
        report_lines.extend([
            "",
            f"## Failures ({len(failures)})",
            "",
            "| Question | Expected | Got | Category |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for f in failures:
            report_lines.append(f"| `{f['question']}` | {f['expected']} | {f['got']} | {f['category']} |")
    else:
        report_lines.extend(["", "## Failures", "", "🎉 Zero failures! All questions passed."])

    report_content = "\n".join(report_lines)
    return accuracy, typo_accuracy, cat_stats, failures, report_content


def main():
    parser = argparse.ArgumentParser(description="Tunnel Excavation AI Evaluation Harness")
    parser.add_argument("--set", choices=["dev", "holdout"], default="dev", help="Dataset to evaluate (dev or holdout)")
    parser.add_argument("--mock", action="store_true", default=False, help="Mock Ollama with deterministic code classifier")
    args = parser.parse_args()

    print(f"\n========================================================")
    print(f" Running Evaluation on '{args.set}.csv' (Mock={args.mock})")
    print(f"========================================================\n")

    accuracy, typo_accuracy, cat_stats, failures, report_content = asyncio.run(
        evaluate_set(args.set, mock=args.mock)
    )

    print(f"Overall Accuracy: {accuracy:.1f}%")
    print(f"Typo Accuracy:    {typo_accuracy:.1f}%\n")
    print("Category Breakdown:")
    for cat, (c_cnt, t_cnt) in sorted(cat_stats.items()):
        pct = (c_cnt / t_cnt) * 100 if t_cnt else 0.0
        print(f"  - {cat:<26}: {c_cnt}/{t_cnt} ({pct:.1f}%)")

    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures[:15]:
            print(f"  [Q]: {f['question']}")
            print(f"       Expected: {f['expected']}")
            print(f"       Got:      {f['got']}")
        if len(failures) > 15:
            print(f"  ... and {len(failures) - 15} more failures.")

    # Write report to eval_report.md
    report_path = Path("eval_report.md")
    report_path.write_text(report_content, encoding="utf-8")
    print(f"\nReport written to: {report_path.resolve()}\n")

    if accuracy < 95.0:
        print(f"❌ FAILED: Accuracy {accuracy:.1f}% is below the required 95.0% threshold.")
        sys.exit(1)
    else:
        print(f"✅ PASSED: Accuracy {accuracy:.1f}% meets the >= 95.0% threshold!")
        sys.exit(0)


if __name__ == "__main__":
    main()
