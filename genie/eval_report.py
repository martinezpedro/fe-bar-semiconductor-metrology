"""Write a text report of a Genie benchmark run: question, assessment, Genie's SQL and its result rows.

    python3 eval_report.py <eval_run_id>   ->  genie/evidence/benchmark_<run>.md
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sql_run import PROFILE, run

HERE = os.path.dirname(os.path.abspath(__file__))


def cli(*args):
    out = subprocess.run(["databricks", "genie", *args, "-p", PROFILE, "-o", "json"], capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stderr)
    return json.loads(out.stdout)


def table(cols, rows, limit=12):
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit]]
    if len(rows) > limit:
        md.append(f"\n_{len(rows) - limit} more rows_")
    return "\n".join(md)


if __name__ == "__main__":
    sid = open(os.path.join(HERE, "space_id.txt")).read().strip()
    rid = sys.argv[1]
    summary = cli("genie-get-eval-run", sid, rid)
    results = cli("genie-list-eval-results", sid, rid)["eval_results"]
    out = [f"# Genie benchmark run `{rid}`", "",
           f"Space `{sid}` (Metrology Process Analyst). Status {summary['eval_run_status']}: "
           f"**{summary['num_correct']}/{summary['num_questions']} GOOD**, "
           f"{summary.get('num_needs_review', 0)} need review.", "",
           "Each section: the benchmark question, Genie's assessment, the SQL Genie generated, and that SQL's "
           "result re-executed on the SQL warehouse.", ""]
    for i, r in enumerate(sorted(results, key=lambda x: x["question"]), 1):
        d = cli("genie-get-eval-result-details", sid, rid, r["result_id"])
        actual = (d.get("actual_response") or [{}])[0]
        sql = actual.get("response", "")
        out += [f"## {i}. {r['question']}", "", f"Assessment: **{d.get('assessment', 'n/a')}**", "",
                "Genie SQL:", "```sql", sql, "```", ""]
        if actual.get("response_type") == "SQL" and sql:
            try:
                cols, rows = run(sql)
                out += ["Result:", "", table(cols, rows), ""]
            except Exception as e:
                out += [f"Re-execution failed: {e}", ""]
        out += ["Benchmark (expected) SQL:", "```sql", r["benchmark_answer"], "```", ""]
    os.makedirs(os.path.join(HERE, "evidence"), exist_ok=True)
    path = os.path.join(HERE, "evidence", f"benchmark_{rid}.md")
    open(path, "w").write("\n".join(out))
    print(path, f"{summary['num_correct']}/{summary['num_questions']}")
