# Genie space: Metrology Process Analyst

Natural-language access to the metrology results and the review queue, for process and metrology
engineers. Space id is in `space_id.txt` (fe-vm, serverless warehouse `d508a88f62d6950a`).

| File | What |
|---|---|
| `space_content.py` | Everything the space knows: tables, instructions, SQL measures/filters, join, example SQL, sample questions, benchmarks |
| `build_space.py` | Builds `space.json` (the serialized space) and creates (`--create`) or updates (`--update`) the space |
| `column_comments.sql` | UC column descriptions on the five views. Re-apply after `src/sql/gold_views.sql`, since `CREATE OR REPLACE VIEW` drops them |
| `eval_report.py` | Turns a benchmark run into `evidence/benchmark_<run>.md`: assessment, Genie's SQL, and its result |
| `sql_run.py` | Small Statement Execution API helper used by the scripts |

## How it follows Genie best practice

- **Small and focused scope.** One subject (CH1 contact-hole metrology plus its review workflow) and five curated
  views. No bronze tables, no file paths. `v_cd_outliers` and `v_model_accuracy` are left out on purpose: the
  first is empty on this data and the second uses synthetic ground truth.
- **Metadata in Unity Catalog.** Table comments plus 55 column descriptions, including units, spec limits and
  the allowed values of every status column.
- **Value dictionaries** (entity matching) on categorical columns, so "etch B" or "sem 2" resolve to
  `EXP-ETCH-B` and `SEM-02`. The Lakebase replication timestamp is hidden.
- **Instructions written as a glossary plus query rules:** CD, LSL/USL, MARGINAL, spec yield, tool offset,
  drift and the review states. Rules: leave unmeasured images out of CD averages, keep ground-truth columns
  out of answers, read "recent" as the last 7 days of data, Top N means exactly N, and keep every group when
  counting statuses.
- **Reusable SQL** for the KPIs (spec yield %, flagged %, defect rate %) and common filters, so every answer
  uses the same definition.
- **A join spec** (image result to review item on `image_id`) instead of leaving Genie to guess.
- **Example SQL only for patterns that are hard to get right:** drift slope, tool offset, weighted weekly
  roll-up, and the review backlog.
- **Benchmarks.** 12 questions with ground-truth SQL across drift, tool matching, spec compliance,
  defectivity, and the review workflow. Runs are scored and kept in `evidence/`, and instructions are tuned
  from the failures rather than by copying benchmark SQL into the examples.
