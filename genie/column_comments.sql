-- Column descriptions Genie reads from Unity Catalog. Re-apply after src/sql/gold_views.sql,
-- because CREATE OR REPLACE VIEW drops column comments.
USE CATALOG ws_azure_classic_eastus_pedro;

-- v_image_results: one row per processed SEM image
COMMENT ON COLUMN fabs_metrology.v_image_results.image_id IS 'Unique image identifier (file name stem)';
COMMENT ON COLUMN fabs_metrology.v_image_results.experiment_id IS 'Process experiment: EXP-ETCH-A (baseline etch), EXP-ETCH-B (new etch recipe), EXP-LITHO-C (litho split)';
COMMENT ON COLUMN fabs_metrology.v_image_results.lot_id IS 'Wafer lot; each lot belongs to one experiment';
COMMENT ON COLUMN fabs_metrology.v_image_results.wafer_id IS 'Wafer within the lot (W01..W25); unique only together with lot_id';
COMMENT ON COLUMN fabs_metrology.v_image_results.die_x IS 'Die column on the wafer map';
COMMENT ON COLUMN fabs_metrology.v_image_results.die_y IS 'Die row on the wafer map';
COMMENT ON COLUMN fabs_metrology.v_image_results.tool_id IS 'CD-SEM metrology tool that captured the image: SEM-01 or SEM-02';
COMMENT ON COLUMN fabs_metrology.v_image_results.layer IS 'Process layer; CH1 = first contact-hole layer';
COMMENT ON COLUMN fabs_metrology.v_image_results.capture_ts IS 'When the SEM captured the image';
COMMENT ON COLUMN fabs_metrology.v_image_results.capture_date IS 'Capture date (use for daily/weekly trends)';
COMMENT ON COLUMN fabs_metrology.v_image_results.submission_id IS 'App submission that uploaded the image; null for instrument drops';
COMMENT ON COLUMN fabs_metrology.v_image_results.predicted_class IS 'Model defect class: none, missing_contact, bridge (merged holes) or particle';
COMMENT ON COLUMN fabs_metrology.v_image_results.class_confidence IS 'Model probability for predicted_class, 0-1';
COMMENT ON COLUMN fabs_metrology.v_image_results.hole_count IS 'Contact holes the segmentation found in the image';
COMMENT ON COLUMN fabs_metrology.v_image_results.expected_holes IS 'Contact holes the layout says should be in the field of view';
COMMENT ON COLUMN fabs_metrology.v_image_results.missing_holes IS 'expected_holes minus holes found';
COMMENT ON COLUMN fabs_metrology.v_image_results.bridge_count IS 'Number of bridged (merged) hole pairs';
COMMENT ON COLUMN fabs_metrology.v_image_results.mean_cd_nm IS 'Critical dimension (CD): mean contact-hole diameter in nm. Spec target 60, LSL 54, USL 66. Null when no measurement';
COMMENT ON COLUMN fabs_metrology.v_image_results.std_cd_nm IS 'Within-image standard deviation of hole diameter, nm';
COMMENT ON COLUMN fabs_metrology.v_image_results.min_cd_nm IS 'Smallest hole diameter in the image, nm';
COMMENT ON COLUMN fabs_metrology.v_image_results.max_cd_nm IS 'Largest hole diameter in the image, nm';
COMMENT ON COLUMN fabs_metrology.v_image_results.cd_3sigma_nm IS 'Within-image CD uniformity (3 x std), nm';
COMMENT ON COLUMN fabs_metrology.v_image_results.cd_spec_status IS 'PASS, MARGINAL (within 1.5 nm of a limit), FAIL (outside 54-66 nm) or NO_MEASUREMENT';
COMMENT ON COLUMN fabs_metrology.v_image_results.disposition IS 'Model triage: FLAGGED (defect, CD fail or missing holes; needs review) or PASS';
COMMENT ON COLUMN fabs_metrology.v_image_results.model_version IS 'Registered model version that produced the result';
COMMENT ON COLUMN fabs_metrology.v_image_results.processed_ts IS 'When the model processed the image';
COMMENT ON COLUMN fabs_metrology.v_image_results.gt_defect_type IS 'Synthetic ground-truth defect (POC evaluation only; not available in production)';
COMMENT ON COLUMN fabs_metrology.v_image_results.gt_cd_nm IS 'Synthetic ground-truth CD (POC evaluation only; not available in production)';

-- v_lot_summary
COMMENT ON COLUMN fabs_metrology.v_lot_summary.images IS 'Images measured in the lot';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.mean_cd_nm IS 'Lot average of per-image mean CD, nm';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.lot_cd_sigma_nm IS 'Image-to-image CD standard deviation within the lot, nm';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.cd_fail_pct IS 'Percent of lot images outside the CD spec';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.flagged_pct IS 'Percent of lot images the model flagged for review';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.missing_contact_images IS 'Images classified missing_contact';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.bridge_images IS 'Images classified bridge';
COMMENT ON COLUMN fabs_metrology.v_lot_summary.particle_images IS 'Images classified particle';

-- v_daily_cd_trend (one row per date x experiment x tool)
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.images IS 'Measured images that day; weight averages by this when rolling up';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.mean_cd_nm IS 'Daily mean CD, nm';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.p05_cd_nm IS '5th percentile of per-image CD that day, nm';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.p95_cd_nm IS '95th percentile of per-image CD that day, nm';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.lsl_nm IS 'Lower spec limit, 54 nm';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.target_nm IS 'CD target, 60 nm';
COMMENT ON COLUMN fabs_metrology.v_daily_cd_trend.usl_nm IS 'Upper spec limit, 66 nm';

-- v_tool_matching
COMMENT ON COLUMN fabs_metrology.v_tool_matching.sem01_mean_cd_nm IS 'Mean CD measured by SEM-01 on defect-free images, nm';
COMMENT ON COLUMN fabs_metrology.v_tool_matching.sem02_mean_cd_nm IS 'Mean CD measured by SEM-02 on defect-free images, nm';
COMMENT ON COLUMN fabs_metrology.v_tool_matching.sem02_minus_sem01_nm IS 'Tool-to-tool CD offset, nm. |offset| > 1.0 nm is a tool-matching problem';
COMMENT ON COLUMN fabs_metrology.v_tool_matching.images IS 'Defect-free measured images behind the comparison';

-- fabs_review.v_review_items_current: engineering review queue (from the Lakebase app database)
COMMENT ON COLUMN fabs_review.v_review_items_current.state IS 'Review workflow state: PENDING_REVIEW, PENDING_APPROVAL, APPROVED_GOOD, REJECTED_BAD, NEEDS_REWORK';
COMMENT ON COLUMN fabs_review.v_review_items_current.priority IS 'Review priority: 1 = high (model-flagged), 2 = normal';
COMMENT ON COLUMN fabs_review.v_review_items_current.reviewer_verdict IS 'Reviewer decision: GOOD or BAD; null until reviewed';
COMMENT ON COLUMN fabs_review.v_review_items_current.assigned_reviewer IS 'Engineer assigned to review the image';
COMMENT ON COLUMN fabs_review.v_review_items_current.reviewed_by IS 'Engineer who recorded the verdict';
COMMENT ON COLUMN fabs_review.v_review_items_current.approved_by IS 'Approver (must differ from the reviewer: separation of duties)';
COMMENT ON COLUMN fabs_review.v_review_items_current.disposition IS 'Model triage at publish time: FLAGGED or PASS';
COMMENT ON COLUMN fabs_review.v_review_items_current._timestamp IS 'Replication timestamp from the Lakebase change feed; ignore for analysis';
