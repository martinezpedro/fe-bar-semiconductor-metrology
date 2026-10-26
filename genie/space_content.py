"""Content for the metrology Genie space: tables, instructions, curated SQL, benchmarks.

Kept as plain Python so it is reviewable in git; build_space.py turns it into the
serialized_space payload the Genie API expects.
"""

CATALOG = "ws_azure_classic_eastus_pedro"
SCHEMA = "fabs_metrology"
REVIEW_SCHEMA = "fabs_review"
M = f"{CATALOG}.{SCHEMA}"
R = f"{CATALOG}.{REVIEW_SCHEMA}"

TITLE = "Metrology Process Analyst (CH1 contact holes)"
DESCRIPTION = (
    "Ask about SEM metrology results for the CH1 contact-hole layer: critical dimension (CD) "
    "trends and spec compliance, SEM tool matching, lot and experiment defectivity, "
    "and the engineering review queue. Data is synthetic POC data."
)

# Curated views only (best practice: a few purpose-built, documented objects, not raw bronze).
TABLES = [
    f"{M}.v_image_results",
    f"{M}.v_lot_summary",
    f"{M}.v_daily_cd_trend",
    f"{M}.v_tool_matching",
    f"{R}.v_review_items_current",
]

TEXT_INSTRUCTIONS = f"""
You are a metrology and process-engineering analyst for a semiconductor memory fab. The data covers
top-down SEM images of the CH1 contact-hole layer, processed by a PyTorch segmentation/classification
model. Answer in engineering terms and keep numbers in nanometres (nm) rounded to 2 decimals.

Domain definitions
- CD = critical dimension = contact-hole diameter in nm. Per-image CD is mean_cd_nm.
- CH1 spec: target 60.0 nm, LSL 54.0 nm, USL 66.0 nm. MARGINAL means within 1.5 nm of a limit
  (below 55.5 or above 64.5). cd_spec_status is PASS, MARGINAL, FAIL or NO_MEASUREMENT.
- "Out of spec" = cd_spec_status = 'FAIL'. "Spec yield" = share of measured images that are not FAIL.
- Defect classes (predicted_class): none, missing_contact, bridge, particle. "Defective" = predicted_class <> 'none'.
- disposition is the model's triage: FLAGGED (needs engineer attention) or PASS.
- Tools: SEM-01 and SEM-02 are CD-SEM metrology tools. "Tool offset" / "tool matching" = SEM-02 mean CD minus
  SEM-01 mean CD on defect-free images; use v_tool_matching. An offset above 1.0 nm in absolute value is a
  tool-matching problem worth escalating.
- Experiments: EXP-ETCH-A (baseline etch), EXP-ETCH-B (new etch recipe), EXP-LITHO-C (litho split).
  Lots belong to one experiment; wafers belong to lots.
- "Drift" = change in daily mean CD over time for an experiment; use v_daily_cd_trend and compare the first
  and last 7 days of data, or fit the slope with regr_slope(mean_cd_nm, datediff(capture_date, min date)).
- "Near the limit" / "at risk" = cd_spec_status = 'MARGINAL'; report MARGINAL and FAIL together when asked about spec risk.

Query rules
- Exclude rows where mean_cd_nm IS NULL (cd_spec_status = 'NO_MEASUREMENT') from CD averages, but count them
  when the question is about missing measurements or defects.
- Do not use gt_defect_type or gt_cd_nm (synthetic ground truth) unless the user explicitly asks about
  model accuracy or ground truth.
- For review workflow questions (pending review, approvals, who reviewed) use v_review_items_current.
  Review states: PENDING_REVIEW, PENDING_APPROVAL, APPROVED_GOOD, REJECTED_BAD, NEEDS_REWORK.
- "Recent" with no date means the last 7 days of available data (relative to MAX(capture_date)), not today,
  because the data is a fixed synthetic history.
- When ranking, return the top 10 unless the user says otherwise. "Top N" means exactly N rows:
  ORDER BY the metric DESC, break ties by the image count DESC and then the identifier, then LIMIT N
  (no RANK, so ties do not add rows).
- Always include the count of images behind an average or a percentage so engineers can judge confidence.
- Always show context identifiers with results: a lot with its experiment_id; a wafer with its lot_id and
  experiment_id.
- Round nm values to 2 decimals and percentages to 1 decimal.
- For counts of a status or class per group ("how many marginal or failing per experiment"), keep every
  group: count each status with SUM(CASE WHEN ...) over all measured images, and do not filter rows to that
  status in WHERE (which drops groups with zero and breaks percentages).
- If a question is outside metrology/review data (yield $, cost, personnel), say the space does not hold it.
""".strip()

# Join between model results and the review queue (both keyed by image_id).
JOINS = [
    (f"{M}.v_image_results", f"{R}.v_review_items_current",
     "v_image_results.image_id = v_review_items_current.image_id",
     "Model result to its engineering review item", "ONE_TO_ONE"),
]

# Categorical columns: turn on value dictionaries so "etch B" or "sem 2" resolve to real values.
ENTITY_COLUMNS = {
    "v_image_results": ["experiment_id", "lot_id", "tool_id", "predicted_class", "cd_spec_status", "disposition", "layer"],
    "v_lot_summary": ["experiment_id", "lot_id"],
    "v_daily_cd_trend": ["experiment_id", "tool_id"],
    "v_tool_matching": ["experiment_id"],
    "v_review_items_current": ["experiment_id", "lot_id", "tool_id", "predicted_class", "cd_spec_status", "disposition", "state", "reviewer_verdict"],
}
# Columns Genie should not use for business answers.
HIDDEN_COLUMNS = {"v_review_items_current": ["_timestamp"]}

# Reusable business logic (SQL expressions/measures/filters).
SNIPPETS = {
    "measures": [
        ("spec_yield_pct", "Spec yield %",
         "ROUND(100 * AVG(CASE WHEN v_image_results.cd_spec_status <> 'FAIL' THEN 1.0 ELSE 0 END), 1)",
         "Share of measured images not failing the CD spec"),
        ("flagged_pct", "Flagged %",
         "ROUND(100 * AVG(CASE WHEN v_image_results.disposition = 'FLAGGED' THEN 1.0 ELSE 0 END), 1)",
         "Share of images the model flagged for engineer review"),
        ("defect_rate_pct", "Defect rate %",
         "ROUND(100 * AVG(CASE WHEN v_image_results.predicted_class <> 'none' THEN 1.0 ELSE 0 END), 1)",
         "Share of images with a predicted defect"),
    ],
    "filters": [
        ("measured_only", "Measured images only", "v_image_results.mean_cd_nm IS NOT NULL",
         "Exclude images with no CD measurement"),
        ("defect_free", "Defect-free images", "v_image_results.predicted_class = 'none'",
         "Images with no predicted defect (use for tool matching)"),
    ],
}

# Example question -> SQL pairs for patterns Genie would otherwise guess at.
EXAMPLES = [
    ("Which experiment is drifting toward the upper spec limit?",
     f"""WITH d AS (
  SELECT experiment_id, capture_date, SUM(mean_cd_nm * images) / SUM(images) AS daily_cd
  FROM {M}.v_daily_cd_trend GROUP BY experiment_id, capture_date
), b AS (SELECT experiment_id, MIN(capture_date) AS d0 FROM d GROUP BY experiment_id)
SELECT d.experiment_id,
       ROUND(regr_slope(daily_cd, datediff(capture_date, d0)) * 30, 2) AS cd_change_nm_per_30_days,
       ROUND(MAX_BY(daily_cd, capture_date), 2) AS latest_daily_cd_nm,
       66.0 AS usl_nm
FROM d JOIN b USING (experiment_id)
GROUP BY d.experiment_id
ORDER BY cd_change_nm_per_30_days DESC"""),
    ("Is there a CD offset between the SEM tools?",
     f"""SELECT experiment_id, sem01_mean_cd_nm, sem02_mean_cd_nm, sem02_minus_sem01_nm, images
FROM {M}.v_tool_matching ORDER BY experiment_id"""),
    ("Weekly mean CD by tool for EXP-ETCH-B",
     f"""SELECT DATE_TRUNC('WEEK', capture_date) AS week, tool_id,
       ROUND(SUM(mean_cd_nm * images) / SUM(images), 2) AS mean_cd_nm, SUM(images) AS images
FROM {M}.v_daily_cd_trend WHERE experiment_id = 'EXP-ETCH-B'
GROUP BY ALL ORDER BY week, tool_id"""),
    ("How many images are waiting for review or approval, by experiment?",
     f"""SELECT experiment_id, state, COUNT(*) AS images
FROM {R}.v_review_items_current
WHERE state IN ('PENDING_REVIEW', 'PENDING_APPROVAL')
GROUP BY ALL ORDER BY experiment_id, state"""),
]

SAMPLE_QUESTIONS = [
    "Which experiment is drifting toward the upper spec limit?",
    "Is there a CD offset between SEM-01 and SEM-02?",
    "Which lots have the highest defect rate?",
    "Show the daily mean CD trend for EXP-ETCH-B by tool",
    "How many images are pending review?",
]

# Benchmarks: natural-language question + ground-truth SQL. Cover the space's core intents
# (drift, tool matching, spec compliance, defectivity, review workflow) and phrasing variants.
BENCHMARKS = [
    ("What is the overall spec yield for CD across all measured images?",
     f"""SELECT ROUND(100 * AVG(CASE WHEN cd_spec_status <> 'FAIL' THEN 1.0 ELSE 0 END), 1) AS spec_yield_pct,
       COUNT(*) AS measured_images
FROM {M}.v_image_results WHERE mean_cd_nm IS NOT NULL"""),
    ("What is the SEM-02 minus SEM-01 CD offset for each experiment?",
     f"""SELECT experiment_id, sem02_minus_sem01_nm FROM {M}.v_tool_matching ORDER BY experiment_id"""),
    ("Which experiment has the highest share of images failing the CD spec?",
     f"""SELECT experiment_id,
       ROUND(100 * AVG(CASE WHEN cd_spec_status = 'FAIL' THEN 1.0 ELSE 0 END), 1) AS cd_fail_pct,
       COUNT(*) AS images
FROM {M}.v_image_results WHERE mean_cd_nm IS NOT NULL
GROUP BY experiment_id ORDER BY cd_fail_pct DESC LIMIT 1"""),
    ("Top 5 lots by defect rate",
     f"""SELECT experiment_id, lot_id,
       ROUND(100 * AVG(CASE WHEN predicted_class <> 'none' THEN 1.0 ELSE 0 END), 1) AS defect_rate_pct,
       COUNT(*) AS images
FROM {M}.v_image_results GROUP BY experiment_id, lot_id
ORDER BY defect_rate_pct DESC, images DESC, lot_id LIMIT 5"""),
    ("How many images did the model flag, broken down by predicted defect class?",
     f"""SELECT predicted_class, COUNT(*) AS images
FROM {M}.v_image_results WHERE disposition = 'FLAGGED'
GROUP BY predicted_class ORDER BY images DESC"""),
    ("What is the mean CD for each experiment and tool?",
     f"""SELECT experiment_id, tool_id, ROUND(AVG(mean_cd_nm), 2) AS mean_cd_nm, COUNT(*) AS images
FROM {M}.v_image_results WHERE mean_cd_nm IS NOT NULL
GROUP BY experiment_id, tool_id ORDER BY experiment_id, tool_id"""),
    ("How many images are marginal or failing the CD spec in each experiment?",
     f"""SELECT experiment_id,
       SUM(CASE WHEN cd_spec_status = 'MARGINAL' THEN 1 ELSE 0 END) AS marginal_images,
       SUM(CASE WHEN cd_spec_status = 'FAIL' THEN 1 ELSE 0 END) AS fail_images,
       COUNT(*) AS images
FROM {M}.v_image_results WHERE mean_cd_nm IS NOT NULL
GROUP BY experiment_id ORDER BY experiment_id"""),
    ("For EXP-ETCH-B, how much did the daily mean CD change between the first and last week of data?",
     f"""WITH d AS (
  SELECT capture_date, SUM(mean_cd_nm * images) / SUM(images) AS daily_cd, SUM(images) AS images
  FROM {M}.v_daily_cd_trend WHERE experiment_id = 'EXP-ETCH-B' GROUP BY capture_date
), lim AS (SELECT MIN(capture_date) AS d0, MAX(capture_date) AS d1 FROM d)
SELECT ROUND(SUM(CASE WHEN capture_date <= date_add(d0, 6) THEN daily_cd * images END)
           / SUM(CASE WHEN capture_date <= date_add(d0, 6) THEN images END), 2) AS first_week_cd_nm,
       ROUND(SUM(CASE WHEN capture_date >= date_sub(d1, 6) THEN daily_cd * images END)
           / SUM(CASE WHEN capture_date >= date_sub(d1, 6) THEN images END), 2) AS last_week_cd_nm,
       ROUND(SUM(CASE WHEN capture_date >= date_sub(d1, 6) THEN daily_cd * images END)
           / SUM(CASE WHEN capture_date >= date_sub(d1, 6) THEN images END)
           - SUM(CASE WHEN capture_date <= date_add(d0, 6) THEN daily_cd * images END)
           / SUM(CASE WHEN capture_date <= date_add(d0, 6) THEN images END), 2) AS change_nm
FROM d CROSS JOIN lim"""),
    ("Which wafers have more than one image with missing contacts?",
     f"""SELECT experiment_id, lot_id, wafer_id, COUNT(*) AS missing_contact_images
FROM {M}.v_image_results WHERE predicted_class = 'missing_contact'
GROUP BY experiment_id, lot_id, wafer_id HAVING COUNT(*) > 1
ORDER BY missing_contact_images DESC"""),
    ("How many images are in each review state?",
     f"""SELECT state, COUNT(*) AS images FROM {R}.v_review_items_current
GROUP BY state ORDER BY images DESC"""),
    ("Which lot has the lowest mean CD in EXP-LITHO-C?",
     f"""SELECT lot_id, mean_cd_nm, images FROM {M}.v_lot_summary
WHERE experiment_id = 'EXP-LITHO-C' ORDER BY mean_cd_nm ASC LIMIT 1"""),
    ("How many high-priority flagged images are still pending review?",
     f"""SELECT COUNT(*) AS images FROM {R}.v_review_items_current
WHERE state = 'PENDING_REVIEW' AND disposition = 'FLAGGED' AND priority = 1"""),
]
