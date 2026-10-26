# Lakeflow Declarative Pipeline: fabs-image-ingest

Auto Loader intake from the landing Volume, validation and quarantine. Updates and per-flow output rows from the pipeline event log.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

## Updates

| update_id | state | cause | created | full_refresh |
|---|---|---|---|---|
| 38dd77fa-9227-449f-89f9-d6efd6c7a59b | COMPLETED | JOB_TASK | 2026-10-20 15:21 UTC | False |
| ccd63a01-38a8-47e6-b96b-de441743a6fe | COMPLETED | JOB_TASK | 2026-10-20 13:33 UTC | False |
| 7a2d494d-469e-4915-8604-9c5e64ed36a8 | COMPLETED | JOB_TASK | 2026-10-20 03:17 UTC | True |

### Flow progress (event log)

```sql
SELECT timestamp, origin.flow_name, details:flow_progress:status AS status,
       details:flow_progress:metrics:num_output_rows AS rows_out,
       details:flow_progress:data_quality:dropped_records AS dropped_by_expectations,
       origin.update_id
FROM event_log('98b54615-7439-4c06-af8f-6f558b7277d1')
WHERE event_type = 'flow_progress' AND details:flow_progress:status = 'COMPLETED'
ORDER BY timestamp DESC
```

| timestamp | flow_name | status | rows_out | dropped_by_expectations | update_id |
|---|---|---|---|---|---|
| 2026-10-20T15:22:47.514Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine | COMPLETED | 6 | 0 | 38dd77fa-9227-449f-89f9-d6efd6c7a59b |
| 2026-10-20T15:22:47.414Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | COMPLETED | 1500 | 6 | 38dd77fa-9227-449f-89f9-d6efd6c7a59b |
| 2026-10-20T15:22:39.731Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata | COMPLETED |  |  | 38dd77fa-9227-449f-89f9-d6efd6c7a59b |
| 2026-10-20T15:22:39.717Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files | COMPLETED |  |  | 38dd77fa-9227-449f-89f9-d6efd6c7a59b |
| 2026-10-20T13:34:11.599Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine | COMPLETED | 6 | 0 | ccd63a01-38a8-47e6-b96b-de441743a6fe |
| 2026-10-20T13:34:11.568Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | COMPLETED | 1500 | 6 | ccd63a01-38a8-47e6-b96b-de441743a6fe |
| 2026-10-20T13:34:03.382Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files | COMPLETED |  |  | ccd63a01-38a8-47e6-b96b-de441743a6fe |
| 2026-10-20T13:34:03.366Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata | COMPLETED |  |  | ccd63a01-38a8-47e6-b96b-de441743a6fe |
| 2026-10-20T03:18:44.843Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_catalog | COMPLETED | 1500 | 6 | 7a2d494d-469e-4915-8604-9c5e64ed36a8 |
| 2026-10-20T03:18:44.184Z | ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine | COMPLETED | 6 | 0 | 7a2d494d-469e-4915-8604-9c5e64ed36a8 |
| 2026-10-20T03:18:38.682Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_files | COMPLETED |  |  | 7a2d494d-469e-4915-8604-9c5e64ed36a8 |
| 2026-10-20T03:18:31.887Z | ws_azure_classic_eastus_pedro.fabs_metrology.bronze_image_metadata | COMPLETED |  |  | 7a2d494d-469e-4915-8604-9c5e64ed36a8 |

_12 rows_

### Quarantined files and reasons

Three truncated TIFFs and three byte-identical duplicates were planted on purpose.

```sql
SELECT * FROM ws_azure_classic_eastus_pedro.fabs_metrology.image_quarantine ORDER BY 1
```

| file_path | image_id | file_ext | size_bytes | sha256 | reject_reason | ingested_ts |
|---|---|---|---|---|---|---|
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-ETCH-A/L24103/W08/IMG-20261004-fb884c6fa1-TRUNC.jpg | IMG-20261004-fb884c6fa1-TRUNC | jpg | 2048 | 263d27ccf4c7b3cee90d862a5255b6a63ccb63c8a63a361c3fa163bb1d276d6a | corrupt: image file is truncated (23 bytes not processed) | 2026-10-20T03:18:16.083Z |
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-ETCH-A/L24103/W08/IMG-20261004-fb884c6fa1.jpg | IMG-20261004-fb884c6fa1 | jpg | 112170 | 74621016963ef8b33b6f9583f485d1a18a7229b8e8039a7163e65f6f152bb4b0 | duplicate_content | 2026-10-20T03:18:16.083Z |
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-LITHO-C/L25303/W20/IMG-20260905-ba33387995-TRUNC.jpg | IMG-20260905-ba33387995-TRUNC | jpg | 2048 | b8b7155bacb794294f5c6fb934c186b9229923345c51e5b191b42b65fc22e052 | corrupt: image file is truncated (24 bytes not processed) | 2026-10-20T03:18:17.077Z |
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-LITHO-C/L25303/W20/IMG-20260905-ba33387995.jpg | IMG-20260905-ba33387995 | jpg | 127238 | dd5c639d49c1cdb7a85afbe7306c52e4294b47a139d2877b1a508d014de0184b | duplicate_content | 2026-10-20T03:18:17.077Z |
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-LITHO-C/L25305/W02/IMG-20260925-d084e89a7f-TRUNC.tif | IMG-20260925-d084e89a7f-TRUNC | tif | 2048 | 8707838a3b33859b33bf10ae58dc19a21fb0f149e4acb81026247aa336fd92b4 | corrupt: cannot identify image file | 2026-10-20T03:18:17.077Z |
| /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments/EXP-LITHO-C/L25305/W02/IMG-20260925-d084e89a7f.tif | IMG-20260925-d084e89a7f | tif | 503538 | fa76d4ad920e3bb3123cf3c78ca84bbc40f74b664a4ec7c0a97a227d98ee253d | duplicate_content | 2026-10-20T03:18:17.077Z |

_6 rows_
