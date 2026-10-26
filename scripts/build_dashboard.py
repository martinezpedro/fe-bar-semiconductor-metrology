"""Generate the AI/BI (Lakeview) dashboard definition for the metrology POC.

Writes resources/fabs_metrology.lvdash.json. Colors follow the app:
experiments and tools keep fixed hues; spec limits are muted reference lines.
Run: python3 scripts/build_dashboard.py
"""
import json
import os

FQ = "ws_azure_classic_eastus_pedro.fabs_metrology"
EXP = {"EXP-ETCH-A": "#2a78d6", "EXP-ETCH-B": "#eb6834", "EXP-LITHO-C": "#1baf7a"}
TOOL = {"SEM-01": "#2a78d6", "SEM-02": "#eb6834"}
RV = "ws_azure_classic_eastus_pedro.fabs_review"
STATE = {"Pending review": "#fab219", "Pending approval": "#898781", "Approved / Good": "#0ca30c",
         "Rejected / Bad": "#d03b3b", "Needs rework": "#ec835a"}
DEFECT = {"missing_contact": "#eda100", "bridge": "#e87ba4", "particle": "#4a3aa7"}

datasets = [
    ("kpis", f"""SELECT count(*) AS images,
       avg(CASE WHEN disposition = 'FLAGGED' THEN 1 ELSE 0 END) AS flagged_rate,
       avg(CASE WHEN cd_spec_status = 'FAIL' THEN 1 ELSE 0 END) AS cd_fail_rate,
       count(DISTINCT lot_id) AS lots
FROM {FQ}.v_image_results"""),
    ("trend", f"""SELECT capture_date, experiment_id, sum(mean_cd_nm * images) / sum(images) AS mean_cd_nm, sum(images) AS images
FROM {FQ}.v_daily_cd_trend GROUP BY ALL"""),
    ("tool_trend", f"""SELECT capture_date, tool_id, sum(mean_cd_nm * images) / sum(images) AS mean_cd_nm, sum(images) AS images
FROM {FQ}.v_daily_cd_trend GROUP BY ALL"""),
    ("tool_matching", f"SELECT * FROM {FQ}.v_tool_matching"),
    ("lots", f"SELECT * FROM {FQ}.v_lot_summary"),
    ("defects", f"""SELECT experiment_id, predicted_class, count(*) AS images
FROM {FQ}.v_image_results WHERE predicted_class <> 'none' GROUP BY ALL"""),
    ("outliers", f"SELECT * FROM {FQ}.v_cd_outliers"),
    ("runs", f"SELECT * FROM {FQ}.processing_runs"),
    ("quarantine", f"SELECT reject_reason, count(*) AS files FROM {FQ}.image_quarantine GROUP BY ALL"),
    ("review_state", f"""SELECT CASE state WHEN 'PENDING_REVIEW' THEN 'Pending review' WHEN 'PENDING_APPROVAL' THEN 'Pending approval'
  WHEN 'APPROVED_GOOD' THEN 'Approved / Good' WHEN 'REJECTED_BAD' THEN 'Rejected / Bad' ELSE 'Needs rework' END AS state,
  count(*) AS images FROM {RV}.v_review_items_current GROUP BY ALL"""),
    ("agreement", f"""SELECT disposition AS model_disposition, coalesce(reviewer_verdict, 'NOT YET') AS reviewer_verdict, count(*) AS images
FROM {RV}.v_review_items_current WHERE reviewed_at IS NOT NULL OR approved_at IS NOT NULL GROUP BY ALL"""),
    ("actions", f"""SELECT date(action_ts) AS day, action, count(*) AS actions
FROM {RV}.v_review_actions WHERE acting_role <> 'system' GROUP BY ALL"""),
    ("action_log", f"""SELECT action_ts, image_id, actor_email, acting_role, action, from_state, to_state, reason_code, comment, sod_override
FROM {RV}.v_review_actions WHERE acting_role <> 'system'"""),
]


def ds(name, q):
    return {"name": name, "displayName": name, "queryLines": [l + "\n" for l in q.split("\n")]}


def q(dataset, fields, disagg=True):
    return [{"name": "main_query", "query": {"datasetName": dataset, "disaggregated": disagg,
                                             "fields": [{"name": n, "expression": e} for n, e in fields]}}]


def counter(name, dataset, field, title, fmt=None):
    enc = {"fieldName": field, "displayName": title}
    if fmt:
        enc["format"] = fmt
    return {"name": name, "queries": q(dataset, [(field, f"`{field}`")]),
            "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": enc},
                     "frame": {"showTitle": True, "title": title}}}


def line(name, dataset, x, y, color, title, colors):
    return {"name": name, "queries": q(dataset, [(x, f"`{x}`"), (y, f"`{y}`"), (color, f"`{color}`")]),
            "spec": {"version": 3, "widgetType": "line", "frame": {"showTitle": True, "title": title},
                     "encodings": {
                         "x": {"fieldName": x, "scale": {"type": "temporal"}, "displayName": "Capture date"},
                         "y": {"fieldName": y, "scale": {"type": "quantitative", "domain": {"min": 52, "max": 68}},
                               "displayName": "Mean CD (nm)"},
                         "color": {"fieldName": color, "scale": {"type": "categorical", "mappings": [
                             {"value": k, "color": v} for k, v in colors.items()]}, "displayName": color}}}}


def bar(name, dataset, x, y, color, title, colors=None, stacked=True):
    enc = {"x": {"fieldName": x, "scale": {"type": "categorical"}, "displayName": x},
           "y": {"fieldName": y, "scale": {"type": "quantitative"}, "displayName": y}}
    if color:
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color}
        if colors:
            enc["color"]["scale"]["mappings"] = [{"value": k, "color": v} for k, v in colors.items()]
    return {"name": name, "queries": q(dataset, [(f, f"`{f}`") for f in [x, y] + ([color] if color else [])]),
            "spec": {"version": 3, "widgetType": "bar", "encodings": enc,
                     "frame": {"showTitle": True, "title": title}}}


def table(name, dataset, cols, title):
    return {"name": name, "queries": q(dataset, [(c, f"`{c}`") for c in cols]),
            "spec": {"version": 1, "widgetType": "table", "frame": {"showTitle": True, "title": title},
                     "encodings": {"columns": [{"fieldName": c, "displayName": c} for c in cols]}}}


def text(name, md):
    return {"name": name, "multilineTextboxSpec": {"lines": [md]}}


def place(widget, x, y, w, h):
    return {"widget": widget, "position": {"x": x, "y": y, "width": w, "height": h}}


page1 = [
    place(text("hdr", "## Metrology — CH1 contact holes\nSpec 60 ± 6 nm (LSL 54 / USL 66). Synthetic POC data."), 0, 0, 6, 2),
    place(counter("k_img", "kpis", "images", "Images processed"), 0, 2, 2, 3),
    place(counter("k_flag", "kpis", "flagged_rate", "Flagged by model", {"type": "number-percent", "decimalPlaces": {"type": "exact", "places": 1}}), 2, 2, 2, 3),
    place(counter("k_fail", "kpis", "cd_fail_rate", "CD out of spec", {"type": "number-percent", "decimalPlaces": {"type": "exact", "places": 1}}), 4, 2, 2, 3),
    place(line("trend", "trend", "capture_date", "mean_cd_nm", "experiment_id", "Daily mean CD by experiment", EXP), 0, 5, 6, 7),
    place(line("tool_trend", "tool_trend", "capture_date", "mean_cd_nm", "tool_id", "Daily mean CD by SEM tool (all experiments)", TOOL), 0, 12, 3, 7),
    place(table("tool_tbl", "tool_matching", ["experiment_id", "sem01_mean_cd_nm", "sem02_mean_cd_nm", "sem02_minus_sem01_nm", "images"], "SEM tool matching"), 3, 12, 3, 7),
    place(bar("defects", "defects", "experiment_id", "images", "predicted_class", "Defect images by experiment", DEFECT), 0, 19, 3, 7),
    place(table("lots", "lots", ["experiment_id", "lot_id", "images", "mean_cd_nm", "lot_cd_sigma_nm", "cd_fail_pct", "flagged_pct",
                                 "missing_contact_images", "bridge_images", "particle_images"], "Lot summary"), 3, 19, 3, 7),
    place(table("outliers", "outliers", ["image_id", "experiment_id", "lot_id", "tool_id", "capture_ts", "mean_cd_nm", "z_score",
                                         "cd_spec_status", "predicted_class"], "CD outliers (|z| > 3 within experiment and tool)"), 0, 26, 6, 7),
]
page2 = [
    place(text("hdr2", "## Pipeline operations\nProcessing runs, throughput and intake validation."), 0, 0, 6, 2),
    place(table("runs", "runs", ["ended_ts", "mode", "images_processed", "flagged", "seconds", "images_per_second", "model_version", "job_run_id"],
                "Processing runs"), 0, 2, 4, 7),
    place(bar("quar", "quarantine", "reject_reason", "files", None, "Files rejected at intake"), 4, 2, 2, 7),
]

page3 = [
    place(text("hdr3", "## Review & audit\nReplicated from Lakebase to Delta via change data feed. Every action is attributable to an SSO identity."), 0, 0, 6, 2),
    place(bar("states", "review_state", "state", "images", "state", "Images by review state", STATE), 0, 2, 3, 7),
    place(bar("agree", "agreement", "model_disposition", "images", "reviewer_verdict", "Model disposition vs reviewer verdict",
              {"GOOD": "#2a78d6", "BAD": "#eb6834", "NOT YET": "#898781"}), 3, 2, 3, 7),
    place(bar("acts", "actions", "day", "actions", "action", "Review actions per day"), 0, 9, 6, 6),
    place(table("alog", "action_log", ["action_ts", "image_id", "actor_email", "acting_role", "action", "from_state", "to_state",
                                       "reason_code", "comment", "sod_override"], "Review action log"), 0, 15, 6, 8),
]

dash = {
    "datasets": [ds(n, s) for n, s in datasets],
    "pages": [
        {"name": "process", "displayName": "Process & metrology", "layout": page1, "pageType": "PAGE_TYPE_CANVAS"},
        {"name": "review", "displayName": "Review & audit", "layout": page3, "pageType": "PAGE_TYPE_CANVAS"},
        {"name": "ops", "displayName": "Pipeline operations", "layout": page2, "pageType": "PAGE_TYPE_CANVAS"},
    ],
}
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resources", "fabs_metrology.lvdash.json")
with open(out, "w") as f:
    json.dump(dash, f, indent=1)
print("wrote", out)
