"""Collect execution evidence from fe-vm into readable text files under evidence/.

Pulls job run history and task logs, Lakeflow pipeline event-log metrics, MLflow / UC model
registry state, query results over every layer, the Lakebase review replica, and app status.

    python3 -I evidence/collect_evidence.py
"""
import datetime as dt
import re
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "genie"))
from sql_run import PROFILE, run  # noqa: E402

CAT = "ws_azure_classic_eastus_pedro"
M = f"{CAT}.fabs_metrology"
R = f"{CAT}.fabs_review"


def _bundle_resources():
    # Resource ids come from the deployed bundle, so the collector follows redeploys.
    root = os.path.join(HERE, "..")
    out = subprocess.run(["databricks", "bundle", "summary", "-o", "json"], cwd=root, capture_output=True, text=True)
    return json.loads(out.stdout)["resources"]


_RES = _bundle_resources()
JOBS = {j["name"]: int(j["id"]) for j in sorted(_RES["jobs"].values(), key=lambda j: j["name"])}
PIPELINE = next(iter(_RES["pipelines"].values()))["id"]
APP = next(iter(_RES["apps"].values()))["name"]
DASHBOARD = next(iter(_RES["dashboards"].values()))["id"]
MODEL = f"{M}.contact_hole_model"
GENIE_SPACE = open(os.path.join(HERE, "..", "genie", "space_id.txt")).read().strip()


def cli(*args):
    out = subprocess.run(["databricks", *args, "-p", PROFILE, "-o", "json"], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout) if out.stdout.strip() else {}


def ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ms else ""


def md_table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v).replace("|", "\\|") for v in r) + " |" for r in rows]
    return "\n".join(out)


def query_section(title, sql, note=""):
    lines = [f"### {title}", ""]
    if note:
        lines += [note, ""]
    lines += ["```sql", sql.strip(), "```", ""]
    try:
        cols, rows = run(sql)
        lines += [md_table(cols, rows), "", f"_{len(rows)} rows_", ""]
    except Exception as e:  # keep going; a failed query is itself worth recording
        lines += [f"Query failed: `{e}`", ""]
    return lines


def write(name, lines):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print("wrote", os.path.relpath(path, os.path.join(HERE, "..")))


def header(title, what):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return [f"# {title}", "", what, "", f"Collected {now} from workspace fe-vm (Azure, "
            f"adb-7405605954880111) by `evidence/collect_evidence.py`.", ""]


# ------------------------------------------------------------------ 1. jobs: run history + task logs
def jobs():
    lines = header("Lakeflow Jobs: run history", "Every run of the three bundle jobs, with per-task results. "
                   "Failures are kept: they show the retries and fixes during the build.")
    logs = []
    for name, jid in JOBS.items():
        runs = cli("jobs", "list-runs", "--job-id", str(jid), "--limit", "25")
        runs = runs if isinstance(runs, list) else runs.get("runs", [])
        lines += [f"## {name} (job {jid})", ""]
        if not runs:
            lines += ["No runs (job is scheduled but paused).", ""]
            continue
        rows = []
        for r in runs:
            d = cli("jobs", "get-run", str(r["run_id"]))
            st = d.get("state", {})
            tasks = [t for t in d.get("tasks", []) if t.get("state", {}).get("result_state") != "DISABLED"]
            rows.append([r["run_id"], ts(r.get("start_time")), round((d.get("run_duration") or 0) / 60000, 1),
                         st.get("result_state") or st.get("life_cycle_state"),
                         ", ".join(f"{t['task_key']}={t.get('state', {}).get('result_state')}" for t in tasks)])
            if st.get("result_state") == "SUCCESS":
                for t in tasks:
                    if "spark_python_task" not in t:
                        continue
                    try:
                        o = cli("jobs", "get-run-output", str(t["run_id"]))
                    except RuntimeError:
                        continue
                    if o.get("logs"):
                        logs.append((name, r["run_id"], t["task_key"], ts(t.get("start_time")),
                                     round((t.get("execution_duration") or 0) / 60000, 1), o["logs"]))
        lines += [md_table(["run_id", "started", "minutes", "result", "tasks (enabled)"], rows), ""]
    write("01_jobs_run_history.md", lines)

    out = header("Job task logs (stdout)", "Captured stdout of every successful Python task: data generation, "
                 "Lakebase setup, PyTorch training, batch inference and review publishing.")
    for name, rid, key, start, mins, log in logs:
        out += [f"## {name} / run {rid} / task `{key}`", "", f"Started {start}, {mins} min.", "", "```text",
                re.sub(r"\x1b\[[0-9;]*m", "", log).strip(), "```", ""]
    write("02_job_task_logs.md", out)


# ------------------------------------------------------------------ 2. Lakeflow pipeline
def pipeline():
    lines = header("Lakeflow Declarative Pipeline: fabs-image-ingest",
                   "Auto Loader intake from the landing Volume, validation and quarantine. "
                   "Updates and per-flow output rows from the pipeline event log.")
    ups = cli("pipelines", "list-updates", PIPELINE).get("updates", [])
    lines += ["## Updates", "", md_table(["update_id", "state", "cause", "created", "full_refresh"],
              [[u["update_id"], u.get("state"), u.get("cause"), ts(u.get("creation_time")), u.get("full_refresh")]
               for u in ups]), ""]
    lines += query_section("Flow progress (event log)", f"""
SELECT timestamp, origin.flow_name, details:flow_progress:status AS status,
       details:flow_progress:metrics:num_output_rows AS rows_out,
       details:flow_progress:data_quality:dropped_records AS dropped_by_expectations,
       origin.update_id
FROM event_log('{PIPELINE}')
WHERE event_type = 'flow_progress' AND details:flow_progress:status = 'COMPLETED'
ORDER BY timestamp DESC""")
    lines += query_section("Quarantined files and reasons", f"""
SELECT * FROM {M}.image_quarantine ORDER BY 1""",
                           "Three truncated TIFFs and three byte-identical duplicates were planted on purpose.")
    write("03_lakeflow_pipeline.md", lines)


# ------------------------------------------------------------------ 3. MLflow / UC model registry
def model():
    lines = header("MLflow + Unity Catalog model registry", "Registered versions, the @champion alias, and the "
                   "logged metrics of the champion's training run.")
    info = cli("api", "get", f"/api/2.1/unity-catalog/models/{MODEL}?include_aliases=true")
    lines += [f"Model `{MODEL}`", "", "Aliases: " + ", ".join(f"`@{a['alias_name']}` -> v{a['version_num']}"
                                                              for a in info.get("aliases", [])), ""]
    vers = cli("api", "get", f"/api/2.1/unity-catalog/models/{MODEL}/versions").get("model_versions", [])
    lines += [md_table(["version", "status", "created", "run_id", "source"],
                       [[v["version"], v.get("status"), ts(v.get("created_at")), v.get("run_id"),
                         v.get("source", "")[:90]] for v in sorted(vers, key=lambda v: v["version"])]), ""]
    for v in sorted(vers, key=lambda v: v["version"]):
        if not v.get("run_id"):
            continue
        r = cli("api", "get", f"/api/2.0/mlflow/runs/get?run_id={v['run_id']}")["run"]
        metrics = sorted((m["key"], round(m["value"], 4)) for m in r["data"].get("metrics", []))
        params = sorted((p["key"], p["value"]) for p in r["data"].get("params", []))
        lines += [f"## v{v['version']}: MLflow run `{r['info'].get('run_name')}` ({r['info']['status']})", "",
                  "Parameters:", "", md_table(["param", "value"], params), "",
                  "Final metrics:", "", md_table(["metric", "value"], metrics), ""]
    write("04_mlflow_model.md", lines)


# ------------------------------------------------------------------ 4. Unity Catalog data, every layer
def data():
    lines = header("Unity Catalog: data produced at each layer", "Row counts and key results, queried live on "
                   "the serverless SQL warehouse.")
    lines += query_section("Row counts by layer", f"""
SELECT 'bronze_image_files' AS table_name, COUNT(*) AS rows FROM {M}.bronze_image_files UNION ALL
SELECT 'bronze_image_metadata', COUNT(*) FROM {M}.bronze_image_metadata UNION ALL
SELECT 'image_catalog', COUNT(*) FROM {M}.image_catalog UNION ALL
SELECT 'image_quarantine', COUNT(*) FROM {M}.image_quarantine UNION ALL
SELECT 'image_results', COUNT(*) FROM {M}.image_results UNION ALL
SELECT 'hole_measurements', COUNT(*) FROM {M}.hole_measurements UNION ALL
SELECT 'processing_runs', COUNT(*) FROM {M}.processing_runs""")
    lines += query_section("Image catalog by experiment, tool and format", f"""
SELECT experiment_id, tool_id, file_ext, COUNT(*) AS images, ROUND(SUM(size_bytes) / 1e6, 1) AS mb
FROM {M}.image_catalog GROUP BY ALL ORDER BY ALL""")
    lines += query_section("Processing runs (throughput)", f"""
SELECT processing_run_id, mode, model_version, images_processed, flagged, seconds, images_per_second,
       cpu_count, started_ts
FROM {M}.processing_runs ORDER BY started_ts""")
    lines += query_section("Model predictions vs synthetic ground truth (confusion matrix)", f"""
SELECT gt_defect_type, predicted_class, images FROM {M}.v_model_accuracy ORDER BY ALL""")
    lines += query_section("Disposition and CD spec status", f"""
SELECT disposition, cd_spec_status, COUNT(*) AS images FROM {M}.v_image_results GROUP BY ALL ORDER BY ALL""")
    lines += query_section("Finding 1: SEM tool matching (SEM-02 minus SEM-01, defect-free images)",
                           f"SELECT * FROM {M}.v_tool_matching ORDER BY experiment_id")
    lines += query_section("Finding 2: EXP-ETCH-B CD drift, weekly", f"""
SELECT DATE_TRUNC('WEEK', capture_date) AS week,
       ROUND(SUM(mean_cd_nm * images) / SUM(images), 2) AS mean_cd_nm, SUM(images) AS images, 66.0 AS usl_nm
FROM {M}.v_daily_cd_trend WHERE experiment_id = 'EXP-ETCH-B' GROUP BY ALL ORDER BY week""")
    lines += query_section("Finding 3: lot defectivity", f"""
SELECT experiment_id, lot_id, images, mean_cd_nm, cd_fail_pct, flagged_pct,
       missing_contact_images, bridge_images, particle_images
FROM {M}.v_lot_summary ORDER BY flagged_pct DESC""")
    lines += query_section("Per-hole measurements sample", f"SELECT * FROM {M}.hole_measurements LIMIT 10")
    write("05_unity_catalog_data.md", lines)


# ------------------------------------------------------------------ 5. governance
def governance():
    lines = header("Unity Catalog governance", "Securables, grants, and lineage for the metrology schema.")
    lines += query_section("Tables, views and volumes", f"""
SELECT table_name AS name, table_type AS type, comment FROM {CAT}.information_schema.tables
WHERE table_schema = 'fabs_metrology'
UNION ALL
SELECT volume_name, CONCAT('VOLUME ', volume_type), comment FROM {CAT}.information_schema.volumes
WHERE volume_schema = 'fabs_metrology' ORDER BY 2, 1""")
    lines += query_section("Grants on the schema and its objects", f"""
SELECT 'SCHEMA' AS level, grantee, privilege_type, NULL AS object FROM {CAT}.information_schema.schema_privileges
WHERE schema_name = 'fabs_metrology'
UNION ALL
SELECT 'VOLUME', grantee, privilege_type, volume_name FROM {CAT}.information_schema.volume_privileges
WHERE volume_schema = 'fabs_metrology'
ORDER BY 1, 2, 3""", "The app service principal gets only what it needs: read on the curated layer, write on "
                       "the landing Volume (uploads), read on results (overlays).")
    lines += query_section("Table lineage (system.access.table_lineage)", f"""
SELECT source_table_full_name, target_table_full_name,
       array_join(sort_array(collect_set(entity_type)), ', ') AS recorded_by
FROM system.access.table_lineage
WHERE target_table_catalog = '{CAT}' AND target_table_schema IN ('fabs_metrology', 'fabs_review')
  AND source_table_full_name IS NOT NULL
GROUP BY 1, 2 ORDER BY 2, 1""")
    write("06_unity_catalog_governance.md", lines)


# ------------------------------------------------------------------ 6. Lakebase (via its Delta replica)
def lakebase():
    lines = header("Lakebase operational store", "The app's live state lives in Lakebase Postgres (project "
                   "`fabs-metrology`, schema `fabs`). The change data feed replicates it to Delta in "
                   "`fabs_review`; these queries read that replica.")
    try:
        p = cli("api", "get", "/api/2.0/postgres/projects/fabs-metrology")
        lines += ["Lakebase project:", "", "```json", json.dumps(p, indent=2)[:1500], "```", ""]
    except RuntimeError as e:
        lines += [f"(Lakebase project API not readable from the CLI: {e.splitlines()[0][:150]})", ""]
    lines += query_section("Replicated tables", f"""
SELECT table_name, table_type FROM {CAT}.information_schema.tables
WHERE table_schema = 'fabs_review' ORDER BY 1""")
    lines += query_section("Review queue by state, disposition and priority", f"""
SELECT state, disposition, priority, COUNT(*) AS items FROM {R}.v_review_items_current
GROUP BY ALL ORDER BY ALL""")
    lines += query_section("Review actions (append-only)", f"""
SELECT action, acting_role, COUNT(*) AS actions FROM {R}.v_review_actions GROUP BY ALL ORDER BY ALL""")
    lines += query_section("Audit events by type", f"""
SELECT event_type, COUNT(*) AS events, MIN(event_ts) AS first_event, MAX(event_ts) AS last_event
FROM {R}.v_audit_events GROUP BY ALL ORDER BY events DESC""")
    write("07_lakebase.md", lines)


# ------------------------------------------------------------------ 7. app, dashboard, Genie
def surfaces():
    lines = header("Databricks App, AI/BI dashboard and Genie space", "Deployment status of the business-facing "
                   "surfaces.")
    a = cli("apps", "get", APP)
    lines += [f"## App `{APP}`", "", f"URL: {a.get('url')}", "",
              md_table(["field", "value"], [
                  ["app_status", a.get("app_status", {}).get("state")],
                  ["compute_status", a.get("compute_status", {}).get("state")],
                  ["active deployment", a.get("active_deployment", {}).get("deployment_id")],
                  ["deployment status", a.get("active_deployment", {}).get("status", {}).get("message")],
                  ["deployed at", a.get("active_deployment", {}).get("create_time")],
                  ["service principal client id", a.get("service_principal_client_id")],
                  ["resources", ", ".join(r["name"] for r in a.get("resources", []))]]), ""]
    try:
        deps = cli("apps", "list-deployments", APP)
        deps = deps if isinstance(deps, list) else deps.get("app_deployments", [])
        lines += ["Deployments:", "", md_table(["deployment_id", "created", "status"],
                  [[d.get("deployment_id"), d.get("create_time"), d.get("status", {}).get("state")] for d in deps]), ""]
    except RuntimeError:
        pass
    d = cli("lakeview", "get", DASHBOARD)
    lines += [f"## AI/BI dashboard `{d.get('display_name')}`", "", md_table(["field", "value"], [
        ["dashboard_id", DASHBOARD], ["lifecycle", d.get("lifecycle_state")], ["warehouse", d.get("warehouse_id")],
        ["updated", d.get("update_time")],
        ["datasets", len(json.loads(d.get("serialized_dashboard", "{}")).get("datasets", []))]]), ""]
    g = cli("api", "get", f"/api/2.0/genie/spaces/{GENIE_SPACE}")
    lines += [f"## Genie space `{g.get('title')}`", "", f"Space id `{GENIE_SPACE}`, warehouse {g.get('warehouse_id')}. "
              "Benchmark runs with Genie's SQL and results are in `genie/evidence/`.", ""]
    write("08_app_dashboard_genie.md", lines)


if __name__ == "__main__":
    for step in (jobs, pipeline, model, data, governance, lakebase, surfaces):
        try:
            step()
        except Exception as e:
            print(f"{step.__name__} failed: {e}")
