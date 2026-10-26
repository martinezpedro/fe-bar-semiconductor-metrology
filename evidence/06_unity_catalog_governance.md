# Unity Catalog governance

Securables, grants, and lineage for the metrology schema.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

### Tables, views and volumes

```sql
SELECT table_name AS name, table_type AS type, comment FROM ws_azure_classic_eastus_pedro.information_schema.tables
WHERE table_schema = 'fabs_metrology'
UNION ALL
SELECT volume_name, CONCAT('VOLUME ', volume_type), comment FROM ws_azure_classic_eastus_pedro.information_schema.volumes
WHERE volume_schema = 'fabs_metrology' ORDER BY 2, 1
```

| name | type | comment |
|---|---|---|
| __materialization_mat_98b54615_7439_4c06_af8f_6f558b7277d1_bronze_image_files_1 | MANAGED | Raw image file facts from the landing Volume (no image bytes). |
| __materialization_mat_98b54615_7439_4c06_af8f_6f558b7277d1_bronze_image_metadata_1 | MANAGED | Raw sidecar metadata (one JSON per image). |
| __materialization_mat_98b54615_7439_4c06_af8f_6f558b7277d1_image_catalog_1 | MANAGED | Governed catalog of valid, unique metrology images with context metadata. |
| __materialization_mat_98b54615_7439_4c06_af8f_6f558b7277d1_image_quarantine_1 | MANAGED | Files rejected by intake validation, with reason. |
| event_log_98b54615_7439_4c06_af8f_6f558b7277d1 | MANAGED |  |
| hole_measurements | MANAGED | Per-contact measurements from the segmentation mask |
| image_results | MANAGED | Model + measurement result per image (latest) |
| processing_runs | MANAGED |  |
| image_catalog | MATERIALIZED_VIEW | Governed catalog of valid, unique metrology images with context metadata. |
| image_quarantine | MATERIALIZED_VIEW | Files rejected by intake validation, with reason. |
| bronze_image_files | STREAMING_TABLE | Raw image file facts from the landing Volume (no image bytes). |
| bronze_image_metadata | STREAMING_TABLE | Raw sidecar metadata (one JSON per image). |
| v_cd_outliers | VIEW | Images whose mean CD is >3 sigma from their experiment-and-tool population |
| v_daily_cd_trend | VIEW | Daily CD trend by experiment and SEM tool, with spec limits |
| v_image_results | VIEW | One row per processed image: context metadata + model and measurement results |
| v_lot_summary | VIEW | Lot-level CD statistics, spec yield and defect mix |
| v_model_accuracy | VIEW | Model class predictions vs synthetic ground truth (POC evaluation only) |
| v_tool_matching | VIEW | SEM tool-to-tool CD offset per experiment (defect-free images only) |
| curated | VOLUME MANAGED |  |
| landing | VOLUME MANAGED |  |
| results | VOLUME MANAGED |  |

_21 rows_

### Grants on the schema and its objects

The app service principal gets only what it needs: read on the curated layer, write on the landing Volume (uploads), read on results (overlays).

```sql
SELECT 'SCHEMA' AS level, grantee, privilege_type, NULL AS object FROM ws_azure_classic_eastus_pedro.information_schema.schema_privileges
WHERE schema_name = 'fabs_metrology'
UNION ALL
SELECT 'VOLUME', grantee, privilege_type, volume_name FROM ws_azure_classic_eastus_pedro.information_schema.volume_privileges
WHERE volume_schema = 'fabs_metrology'
ORDER BY 1, 2, 3
```

| level | grantee | privilege_type | object |
|---|---|---|---|
| SCHEMA | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME |  |
| SCHEMA | 3a630645-574e-499c-9b86-dc4e87e09fbb | SELECT |  |
| SCHEMA | 3a630645-574e-499c-9b86-dc4e87e09fbb | USE_SCHEMA |  |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME | results |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME | landing |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME | curated |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME | results |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | READ_VOLUME | landing |
| VOLUME | 3a630645-574e-499c-9b86-dc4e87e09fbb | WRITE_VOLUME | landing |

_9 rows_

### Table lineage (system.access.table_lineage)

```sql
SELECT source_table_full_name, target_table_full_name,
       array_join(sort_array(collect_set(entity_type)), ', ') AS recorded_by
FROM system.access.table_lineage
WHERE target_table_catalog = 'ws_azure_classic_eastus_pedro' AND target_table_schema IN ('fabs_metrology', 'fabs_review')
  AND source_table_full_name IS NOT NULL
GROUP BY 1, 2 ORDER BY 2, 1
```

| source_table_full_name | target_table_full_name | recorded_by |
|---|---|---|
| ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files | ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | PIPELINE |
| ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata | ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | PIPELINE |
| ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files | ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine | PIPELINE |
| ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata | ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine | PIPELINE |
| ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_cd_outliers | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_daily_cd_trend | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_lot_summary | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_model_accuracy | JOB |
| ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results | ws_azure_classic_eastus_pedro.fabs_metrology.v_tool_matching | JOB |
| ws_azure_classic_eastus_pedro.fabs_review.lb_audit_events_history | ws_azure_classic_eastus_pedro.fabs_review.v_audit_events | JOB |
| ws_azure_classic_eastus_pedro.fabs_review.lb_review_actions_history | ws_azure_classic_eastus_pedro.fabs_review.v_review_actions | JOB |
| ws_azure_classic_eastus_pedro.fabs_review.lb_review_items_history | ws_azure_classic_eastus_pedro.fabs_review.v_review_items_current | JOB |

_14 rows_
