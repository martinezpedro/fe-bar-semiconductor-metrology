# Genie benchmark evidence

Benchmark runs on space `01f1cc30d4d910538989cd372e3f44c1` (Metrology Process Analyst), scored by Genie's
built-in evaluator. Each file has, for every question: Genie's assessment, the SQL Genie generated, that SQL's
result re-executed on the warehouse, and the benchmark (expected) SQL.

| Run | Score | Notes |
|---|---|---|
| `benchmark_01f1cc9572f61894818cb45a5b5df87c.md` | 11/12 GOOD | First run on the final `fabs_metrology` data. #6 (top 5 lots) marked BAD because two lots tie at 23.1% for 5th place and the expected SQL broke the tie arbitrarily. Genie's answer was correct. The answer key was fixed to break ties by image count. |
| `benchmark_01f1cc9d39021816a0a5f6e24cb280f1.md` | **11/12 GOOD, 1 NEEDS_REVIEW** | Final. #1 (EXP-ETCH-B first vs last week) is NEEDS_REVIEW only because Genie returned extra image-count columns. On manual review it uses the same 7-day windows (`< min+7` = `<= min+6`) and the same weighted mean, and gives 63.42 to 67.78 nm (+4.36 nm). It is correct. |

## How the space was tuned (earlier runs, same 12 questions, previous build of the same data)

1. **9/12:**
   - Genie filtered to MARGINAL/FAIL before counting per experiment, which dropped experiments with zero.
   - A RANK tie returned 6 rows for "top 5".
   - A percentage came back unrounded.
2. **11/12:** after adding general rules to the instructions:
   - Top N means exactly N rows.
   - When counting statuses, keep every group, using conditional SUMs rather than a WHERE filter.
   - Round % to 1 decimal.
3. **12/12:** after one more rule: always show a lot with its experiment, and a wafer with its lot.

No benchmark SQL was copied into the space's example queries. Every fix is a general instruction.
