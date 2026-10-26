# Unity Catalog: data produced at each layer

Row counts and key results, queried live on the serverless SQL warehouse.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

### Row counts by layer

```sql
SELECT 'bronze_image_files' AS table_name, COUNT(*) AS rows FROM ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files UNION ALL
SELECT 'bronze_image_metadata', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata UNION ALL
SELECT 'image_catalog', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog UNION ALL
SELECT 'image_quarantine', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine UNION ALL
SELECT 'image_results', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.image_results UNION ALL
SELECT 'hole_measurements', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.hole_measurements UNION ALL
SELECT 'processing_runs', COUNT(*) FROM ws_azure_classic_eastus_pedro.fabs_metrology.processing_runs
```

| table_name | rows |
|---|---|
| image_catalog | 1500 |
| bronze_image_files | 1506 |
| bronze_image_metadata | 1506 |
| image_quarantine | 6 |
| image_results | 1500 |
| hole_measurements | 95740 |
| processing_runs | 2 |

_7 rows_

### Image catalog by experiment, tool and format

```sql
SELECT experiment_id, tool_id, file_ext, COUNT(*) AS images, ROUND(SUM(size_bytes) / 1e6, 1) AS mb
FROM ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog GROUP BY ALL ORDER BY ALL
```

| experiment_id | tool_id | file_ext | images | mb |
|---|---|---|---|---|
| EXP-ETCH-A | SEM-01 | jpg | 106 | 12.6 |
| EXP-ETCH-A | SEM-01 | tif | 187 | 93.6 |
| EXP-ETCH-A | SEM-02 | jpg | 104 | 12.3 |
| EXP-ETCH-A | SEM-02 | tif | 115 | 57.6 |
| EXP-ETCH-B | SEM-01 | jpg | 100 | 11.9 |
| EXP-ETCH-B | SEM-01 | tif | 166 | 83.3 |
| EXP-ETCH-B | SEM-02 | jpg | 96 | 11.6 |
| EXP-ETCH-B | SEM-02 | tif | 130 | 65.2 |
| EXP-LITHO-C | SEM-01 | jpg | 109 | 13.0 |
| EXP-LITHO-C | SEM-01 | tif | 172 | 86.0 |
| EXP-LITHO-C | SEM-02 | jpg | 84 | 10.0 |
| EXP-LITHO-C | SEM-02 | tif | 131 | 65.6 |

_12 rows_

### Processing runs (throughput)

```sql
SELECT processing_run_id, mode, model_version, images_processed, flagged, seconds, images_per_second,
       cpu_count, started_ts
FROM ws_azure_classic_eastus_pedro.fabs_metrology.processing_runs ORDER BY started_ts
```

| processing_run_id | mode | model_version | images_processed | flagged | seconds | images_per_second | cpu_count | started_ts |
|---|---|---|---|---|---|---|---|---|
| aedc5d37-9638-4369-bc34-201e965827d0 | incremental | contact_hole_model/v1 | 220 | 99 | 170.0 | 1.29 | 4 | 2026-10-20T14:19:37.886Z |
| 12d69632-e7d2-44b1-8564-e31ea461891a | reprocess | contact_hole_model/v1 | 1500 | 394 | 1136.8 | 1.32 | 4 | 2026-10-20T15:25:07.790Z |

_2 rows_

### Model predictions vs synthetic ground truth (confusion matrix)

```sql
SELECT gt_defect_type, predicted_class, images FROM ws_azure_classic_eastus_pedro.fabs_metrology.v_model_accuracy ORDER BY ALL
```

| gt_defect_type | predicted_class | images |
|---|---|---|
| bridge | bridge | 68 |
| bridge | none | 3 |
| missing_contact | missing_contact | 80 |
| none | none | 1276 |
| particle | none | 3 |
| particle | particle | 70 |

_6 rows_

### Disposition and CD spec status

```sql
SELECT disposition, cd_spec_status, COUNT(*) AS images FROM ws_azure_classic_eastus_pedro.fabs_metrology.v_image_results GROUP BY ALL ORDER BY ALL
```

| disposition | cd_spec_status | images |
|---|---|---|
| FLAGGED | FAIL | 193 |
| FLAGGED | MARGINAL | 10 |
| FLAGGED | PASS | 191 |
| PASS | MARGINAL | 132 |
| PASS | PASS | 974 |

_5 rows_

### Finding 1: SEM tool matching (SEM-02 minus SEM-01, defect-free images)

```sql
SELECT * FROM ws_azure_classic_eastus_pedro.fabs_metrology.v_tool_matching ORDER BY experiment_id
```

| experiment_id | sem01_mean_cd_nm | sem02_mean_cd_nm | sem02_minus_sem01_nm | images |
|---|---|---|---|---|
| EXP-ETCH-A | 60.05 | 61.19 | 1.14 | 488 |
| EXP-ETCH-B | 64.89 | 66.2 | 1.31 | 451 |
| EXP-LITHO-C | 59.26 | 60.39 | 1.12 | 343 |

_3 rows_

### Finding 2: EXP-ETCH-B CD drift, weekly

```sql
SELECT DATE_TRUNC('WEEK', capture_date) AS week,
       ROUND(SUM(mean_cd_nm * images) / SUM(images), 2) AS mean_cd_nm, SUM(images) AS images, 66.0 AS usl_nm
FROM ws_azure_classic_eastus_pedro.fabs_metrology.v_daily_cd_trend WHERE experiment_id = 'EXP-ETCH-B' GROUP BY ALL ORDER BY week
```

| week | mean_cd_nm | images | usl_nm |
|---|---|---|---|
| 2026-08-17T00:00:00.000Z | 63.34 | 23 | 66.0 |
| 2026-08-24T00:00:00.000Z | 63.5 | 59 | 66.0 |
| 2026-08-31T00:00:00.000Z | 64.16 | 50 | 66.0 |
| 2026-09-07T00:00:00.000Z | 64.7 | 64 | 66.0 |
| 2026-09-14T00:00:00.000Z | 65.2 | 53 | 66.0 |
| 2026-09-21T00:00:00.000Z | 65.89 | 50 | 66.0 |
| 2026-09-28T00:00:00.000Z | 66.16 | 67 | 66.0 |
| 2026-10-05T00:00:00.000Z | 66.96 | 52 | 66.0 |
| 2026-10-12T00:00:00.000Z | 67.66 | 60 | 66.0 |
| 2026-10-19T00:00:00.000Z | 68.14 | 14 | 66.0 |

_10 rows_

### Finding 3: lot defectivity

```sql
SELECT experiment_id, lot_id, images, mean_cd_nm, cd_fail_pct, flagged_pct,
       missing_contact_images, bridge_images, particle_images
FROM ws_azure_classic_eastus_pedro.fabs_metrology.v_lot_summary ORDER BY flagged_pct DESC
```

| experiment_id | lot_id | images | mean_cd_nm | cd_fail_pct | flagged_pct | missing_contact_images | bridge_images | particle_images |
|---|---|---|---|---|---|---|---|---|
| EXP-ETCH-B | L24206 | 82 | 66.97 | 68.3 | 73.2 | 3 | 3 | 2 |
| EXP-ETCH-B | L24201 | 94 | 66.14 | 54.3 | 56.4 | 1 | 0 | 3 |
| EXP-ETCH-B | L24205 | 84 | 65.94 | 50.0 | 56.0 | 6 | 3 | 3 |
| EXP-ETCH-B | L24203 | 84 | 65.78 | 41.7 | 46.4 | 1 | 4 | 3 |
| EXP-LITHO-C | L25305 | 89 | 58.53 | 0.0 | 36.0 | 11 | 11 | 10 |
| EXP-LITHO-C | L25303 | 90 | 60.07 | 0.0 | 34.4 | 13 | 10 | 8 |
| EXP-LITHO-C | L25302 | 80 | 59.91 | 0.0 | 33.8 | 7 | 13 | 7 |
| EXP-LITHO-C | L25304 | 81 | 61.15 | 0.0 | 33.3 | 8 | 10 | 9 |
| EXP-LITHO-C | L25301 | 91 | 58.91 | 0.0 | 23.1 | 7 | 6 | 8 |
| EXP-LITHO-C | L25306 | 65 | 60.16 | 0.0 | 23.1 | 7 | 2 | 6 |
| EXP-ETCH-B | L24204 | 84 | 63.88 | 8.3 | 16.7 | 5 | 1 | 1 |
| EXP-ETCH-A | L24101 | 79 | 59.95 | 0.0 | 7.6 | 1 | 1 | 4 |
| EXP-ETCH-A | L24104 | 94 | 60.56 | 0.0 | 7.4 | 5 | 0 | 2 |
| EXP-ETCH-B | L24202 | 64 | 63.92 | 3.1 | 6.3 | 2 | 0 | 0 |
| EXP-ETCH-A | L24106 | 88 | 60.18 | 0.0 | 4.5 | 2 | 0 | 2 |
| EXP-ETCH-A | L24103 | 81 | 60.59 | 0.0 | 3.7 | 1 | 1 | 1 |
| EXP-ETCH-A | L24102 | 85 | 60.57 | 0.0 | 2.4 | 0 | 2 | 0 |
| EXP-ETCH-A | L24105 | 85 | 61.32 | 0.0 | 2.4 | 0 | 1 | 1 |

_18 rows_

### Per-hole measurements sample

```sql
SELECT * FROM ws_azure_classic_eastus_pedro.fabs_metrology.hole_measurements LIMIT 10
```

| image_id | hole_idx | center_x_px | center_y_px | area_px | diameter_nm | is_bridge |
|---|---|---|---|---|---|---|
| IMG-20260821-b6150b8776 | 0 | 31.5625 | 32.017857142857146 | 672 | 58.50186233145162 | false |
| IMG-20260821-b6150b8776 | 1 | 96.75158227848101 | 31.832278481012658 | 632 | 56.73402479192263 | false |
| IMG-20260821-b6150b8776 | 2 | 160.04885496183206 | 31.531297709923663 | 655 | 57.75714334353913 | false |
| IMG-20260821-b6150b8776 | 3 | 223.97410071942446 | 32.105035971223025 | 695 | 59.49458743754555 | false |
| IMG-20260821-b6150b8776 | 4 | 287.9592145015106 | 32.22809667673716 | 662 | 58.06494910407406 | false |
| IMG-20260821-b6150b8776 | 5 | 351.9968701095462 | 32.009389671361504 | 639 | 57.04735117727269 | false |
| IMG-20260821-b6150b8776 | 6 | 415.65430267062317 | 32.3026706231454 | 674 | 58.58885399635325 | false |
| IMG-20260821-b6150b8776 | 7 | 480.62827988338194 | 31.760932944606413 | 686 | 59.10811543902653 | false |
| IMG-20260821-b6150b8776 | 8 | 224.01826484018264 | 94.96651445966515 | 657 | 57.84525497881402 | false |
| IMG-20260821-b6150b8776 | 9 | 32.38863287250384 | 96.85253456221199 | 651 | 57.58051558027562 | false |

_10 rows_
