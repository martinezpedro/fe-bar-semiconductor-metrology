-- Engineering analytics views over the image catalog and model results.
-- Parameterized by :catalog and :schema (SQL task parameters).
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);

CREATE OR REPLACE VIEW v_image_results
COMMENT 'One row per processed image: context metadata + model and measurement results'
AS SELECT
  c.image_id, c.experiment_id, c.lot_id, c.wafer_id, c.die_x, c.die_y, c.tool_id, c.layer,
  c.capture_ts, DATE(c.capture_ts) AS capture_date, c.file_ext, c.size_bytes, c.file_path,
  c.submission_id, c.batch_id,
  r.predicted_class, r.class_confidence, r.hole_count, r.expected_holes, r.missing_holes, r.bridge_count,
  r.mean_cd_nm, r.std_cd_nm, r.min_cd_nm, r.max_cd_nm, r.cd_3sigma_nm, r.cd_spec_status, r.disposition,
  r.overlay_path, r.mask_path, r.model_version, r.processed_ts,
  c.gt_defect_type, c.gt_cd_nm
FROM image_catalog c JOIN image_results r USING (image_id);

CREATE OR REPLACE VIEW v_lot_summary
COMMENT 'Lot-level CD statistics, spec yield and defect mix'
AS SELECT
  experiment_id, lot_id,
  COUNT(*) AS images,
  ROUND(AVG(mean_cd_nm), 2) AS mean_cd_nm,
  ROUND(STDDEV(mean_cd_nm), 2) AS lot_cd_sigma_nm,
  ROUND(AVG(CASE WHEN cd_spec_status = 'FAIL' THEN 1 ELSE 0 END) * 100, 1) AS cd_fail_pct,
  ROUND(AVG(CASE WHEN disposition = 'FLAGGED' THEN 1 ELSE 0 END) * 100, 1) AS flagged_pct,
  SUM(CASE WHEN predicted_class = 'missing_contact' THEN 1 ELSE 0 END) AS missing_contact_images,
  SUM(CASE WHEN predicted_class = 'bridge' THEN 1 ELSE 0 END) AS bridge_images,
  SUM(CASE WHEN predicted_class = 'particle' THEN 1 ELSE 0 END) AS particle_images,
  MIN(capture_ts) AS first_capture, MAX(capture_ts) AS last_capture
FROM v_image_results
GROUP BY experiment_id, lot_id;

CREATE OR REPLACE VIEW v_daily_cd_trend
COMMENT 'Daily CD trend by experiment and SEM tool, with spec limits'
AS SELECT
  capture_date, experiment_id, tool_id,
  COUNT(*) AS images,
  ROUND(AVG(mean_cd_nm), 2) AS mean_cd_nm,
  ROUND(PERCENTILE(mean_cd_nm, 0.05), 2) AS p05_cd_nm,
  ROUND(PERCENTILE(mean_cd_nm, 0.95), 2) AS p95_cd_nm,
  54.0 AS lsl_nm, 60.0 AS target_nm, 66.0 AS usl_nm
FROM v_image_results
WHERE mean_cd_nm IS NOT NULL
GROUP BY capture_date, experiment_id, tool_id;

CREATE OR REPLACE VIEW v_cd_outliers
COMMENT 'Images whose mean CD is >3 sigma from their experiment-and-tool population'
AS WITH s AS (
  SELECT *,
         AVG(mean_cd_nm) OVER (PARTITION BY experiment_id, tool_id) AS pop_mean,
         STDDEV(mean_cd_nm) OVER (PARTITION BY experiment_id, tool_id) AS pop_sigma
  FROM v_image_results WHERE mean_cd_nm IS NOT NULL
)
SELECT image_id, experiment_id, lot_id, wafer_id, tool_id, capture_ts, mean_cd_nm,
       ROUND(pop_mean, 2) AS population_mean_nm,
       ROUND((mean_cd_nm - pop_mean) / pop_sigma, 2) AS z_score,
       cd_spec_status, predicted_class, overlay_path
FROM s
WHERE ABS((mean_cd_nm - pop_mean) / pop_sigma) > 3;

CREATE OR REPLACE VIEW v_tool_matching
COMMENT 'SEM tool-to-tool CD offset per experiment (defect-free images only)'
AS SELECT
  experiment_id,
  ROUND(AVG(CASE WHEN tool_id = 'SEM-01' THEN mean_cd_nm END), 2) AS sem01_mean_cd_nm,
  ROUND(AVG(CASE WHEN tool_id = 'SEM-02' THEN mean_cd_nm END), 2) AS sem02_mean_cd_nm,
  ROUND(AVG(CASE WHEN tool_id = 'SEM-02' THEN mean_cd_nm END)
      - AVG(CASE WHEN tool_id = 'SEM-01' THEN mean_cd_nm END), 2) AS sem02_minus_sem01_nm,
  COUNT(*) AS images
FROM v_image_results
WHERE predicted_class = 'none' AND mean_cd_nm IS NOT NULL
GROUP BY experiment_id;

CREATE OR REPLACE VIEW v_model_accuracy
COMMENT 'Model class predictions vs synthetic ground truth (POC evaluation only)'
AS SELECT gt_defect_type, predicted_class, COUNT(*) AS images
FROM v_image_results GROUP BY gt_defect_type, predicted_class;

-- Review / audit analytics over the Lakebase CDF replica (fabs_review schema).
CREATE OR REPLACE VIEW fabs_review.v_review_items_current
COMMENT 'Current review state per image, rebuilt from the Lakebase change feed'
AS SELECT * EXCEPT (_pg_change_type, _pg_lsn, _pg_xid, _sort_by, rn) FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY image_id ORDER BY _sort_by DESC) AS rn
  FROM fabs_review.lb_review_items_history
  WHERE lower(_pg_change_type) NOT LIKE '%pre%'
) WHERE rn = 1 AND lower(_pg_change_type) NOT LIKE '%delete%';

CREATE OR REPLACE VIEW fabs_review.v_review_actions
COMMENT 'Append-only review workflow actions from Lakebase'
AS SELECT * EXCEPT (_pg_change_type, _pg_lsn, _pg_xid, _sort_by)
FROM fabs_review.lb_review_actions_history WHERE lower(_pg_change_type) LIKE '%insert%';

CREATE OR REPLACE VIEW fabs_review.v_audit_events
COMMENT 'Append-only application audit events from Lakebase'
AS SELECT * EXCEPT (_pg_change_type, _pg_lsn, _pg_xid, _sort_by)
FROM fabs_review.lb_audit_events_history WHERE lower(_pg_change_type) LIKE '%insert%';
