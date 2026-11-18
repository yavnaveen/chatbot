# Evaluation Report: `holdout.csv`

- **Mode**: Mocked Deterministic
- **Total Questions**: 52
- **Passed**: 51 / 52
- **Overall Accuracy**: **98.1%**
- **Typo Accuracy**: **100.0%** (25/25)

## Accuracy Per Category

| Category | Passed | Total | Accuracy |
| :--- | :---: | :---: | :---: |
| Aggregate (Month/Class/Ch) | 13 | 13 | 100.0% |
| Clarifications / Boundary | 7 | 7 | 100.0% |
| Date Range | 4 | 4 | 100.0% |
| Date Record | 8 | 8 | 100.0% |
| Difference / Compare | 2 | 2 | 100.0% |
| Greetings | 1 | 2 | 50.0% |
| Highest / Lowest | 2 | 2 | 100.0% |
| Out of Scope / Refusal | 7 | 7 | 100.0% |
| Row Count | 2 | 2 | 100.0% |
| Security / Destructive | 3 | 3 | 100.0% |
| Support Class Grouping | 2 | 2 | 100.0% |

## Failures (1)

| Question | Expected | Got | Category |
| :--- | :--- | :--- | :--- |
| `hello there` | op=chat, behavior=answer, metric=actual, date=- | op=out_of_scope, behavior=refuse, metric=actual, date=- | Greetings |