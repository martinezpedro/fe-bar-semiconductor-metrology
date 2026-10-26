"""Publish processed results into the Lakebase review queue.

New images become PENDING_REVIEW items. Reprocessed images (e.g. after
NEEDS_REWORK) get their result snapshot refreshed and return to PENDING_REVIEW,
with the transition recorded in review_actions. Submission status is updated.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0])), "..", "common"))

from pyspark.sql import SparkSession

import lakebase

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", required=True)
ap.add_argument("--processing_run_id", default="")
ap.add_argument("--submission_id", default="")
ap.add_argument("--job_run_id", default="")
ap.add_argument("--lakebase_endpoint", required=True)
ap.add_argument("--lakebase_host", required=True)
args, _ = ap.parse_known_args()

spark = SparkSession.builder.getOrCreate()
fq = f"{args.catalog}.{args.schema}"

rows = []
if args.processing_run_id:
    rows = spark.sql(f"""
        SELECT r.image_id, c.submission_id, c.uploaded_by, c.experiment_id, c.lot_id, c.wafer_id, c.tool_id,
               c.capture_ts, r.predicted_class, r.class_confidence, r.mean_cd_nm, r.cd_spec_status,
               r.disposition, r.overlay_path, r.model_version
        FROM {fq}.image_results r JOIN {fq}.image_catalog c USING (image_id)
        WHERE r.processing_run_id = :run_id
    """, args={"run_id": args.processing_run_id}).collect()
print(f"results to publish: {len(rows)}")

SYSTEM = "system:metrology-pipeline"
with lakebase.connect(args.lakebase_endpoint, args.lakebase_host) as conn, conn.cursor() as cur:
    # uploads register their submission from the app; scheduled drops have none
    for r in rows:
        cur.execute("SELECT state FROM review_items WHERE image_id = %s", (r.image_id,))
        prev = cur.fetchone()
        cur.execute(
            """
            INSERT INTO review_items (image_id, submission_id, submitted_by, experiment_id, lot_id, wafer_id, tool_id,
                capture_ts, predicted_class, class_confidence, mean_cd_nm, cd_spec_status, disposition, priority,
                overlay_path, model_version, state)
            VALUES (%s, (SELECT submission_id FROM submissions WHERE submission_id = %s), %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_REVIEW')
            ON CONFLICT (image_id) DO UPDATE SET
                predicted_class = EXCLUDED.predicted_class, class_confidence = EXCLUDED.class_confidence,
                mean_cd_nm = EXCLUDED.mean_cd_nm, cd_spec_status = EXCLUDED.cd_spec_status,
                disposition = EXCLUDED.disposition, priority = EXCLUDED.priority,
                overlay_path = EXCLUDED.overlay_path, model_version = EXCLUDED.model_version,
                state = 'PENDING_REVIEW', reviewer_verdict = NULL, reviewed_by = NULL, reviewed_at = NULL,
                approved_by = NULL, approved_at = NULL, updated_at = now()
            """,
            (r.image_id, r.submission_id, r.uploaded_by, r.experiment_id, r.lot_id, r.wafer_id, r.tool_id,
             r.capture_ts, r.predicted_class, r.class_confidence, r.mean_cd_nm, r.cd_spec_status, r.disposition,
             1 if r.disposition == "FLAGGED" else 2, r.overlay_path, r.model_version),
        )
        cur.execute(
            "INSERT INTO review_actions (image_id, actor_email, acting_role, action, from_state, to_state, comment) "
            "VALUES (%s, %s, 'system', %s, %s, 'PENDING_REVIEW', %s)",
            (r.image_id, SYSTEM, "REPROCESSED" if prev else "PUBLISHED", prev[0] if prev else None,
             f"model {r.model_version}, job run {args.job_run_id}"),
        )
    if args.submission_id:
        cur.execute(
            "UPDATE submissions SET status = 'PROCESSED', status_detail = %s, updated_at = now() WHERE submission_id = %s",
            (f"{len(rows)} image(s) processed", args.submission_id),
        )
    cur.execute(
        "INSERT INTO audit_events (actor_email, event_type, object_type, object_id, details) "
        "VALUES (%s, 'PIPELINE_PUBLISH', 'job_run', %s, jsonb_build_object('images', %s::int, 'submission_id', %s::text))",
        (SYSTEM, args.job_run_id, len(rows), args.submission_id or None),
    )
    conn.commit()
print("published")
