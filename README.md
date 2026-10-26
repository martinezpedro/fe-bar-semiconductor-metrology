# Semiconductor metrology image processing on Databricks (POC demo)

Synthetic stand-in for SemiConductor Customer's metrology team's SEM image workflow: images land in a UC Volume,
a Lakeflow pipeline validates and catalogs them, PyTorch segments and classifies them on
CPU, measurements land in Delta, and a Streamlit Databricks App drives review, approval
and audit with Lakebase as the operational store. An LLM review assistant runs through
the Databricks AI Gateway.

Workspace: fe-vm (Azure, profile `fe-vm-azure`). The customer target is GCP; everything
above the storage layer is the same there (UC Volume on GCS instead of ADLS).

## Layout

| Path | What |
|---|---|
| `src/generate_images.py` | Synthetic SEM contact-hole images + JSON sidecars + label masks (also copied to `app/lib/`) |
| `src/pipeline/ingest_images.py` | Lakeflow Declarative Pipeline: Auto Loader intake, decode/format/metadata/duplicate checks, quarantine |
| `src/ml/fabs_ml.py` | TinyUNet (segmentation + classification heads), preprocessing, measurement, overlays |
| `src/ml/train.py` | Train on the labeled subset, log to MLflow, register `contact_hole_model@champion` in UC |
| `src/ml/infer.py` | Batch inference → masks/overlays in Volumes, `image_results` / `hole_measurements` / `processing_runs` in Delta |
| `src/jobs/publish_review.py` | Push new results into the Lakebase review queue |
| `src/jobs/setup_lakebase.py`, `src/lakebase/schema.sql` | Lakebase schema (roles, submissions, review items, append-only actions/audit, AI summaries) |
| `src/sql/gold_views.sql` | Analytics views: trend, lot summary, outliers, tool matching, model accuracy |
| `app/` | Streamlit Databricks App. `app/lib/genie.py` backs the **Ask Genie** page (Genie Conversation API), linked from the review detail and the analytics page |
| `scripts/build_dashboard.py` | Generates the AI/BI dashboard JSON |
| `genie/` | Genie space as code: instructions, curated SQL, 12 benchmarks, UC column comments, benchmark evidence |
| `resources/` | Bundle resources (pipeline, 3 jobs, app, dashboard) |

## Unity Catalog objects

- `ws_azure_classic_eastus_pedro.fabs_metrology`: Volumes `landing` (instruments/, uploads/), `curated` (labels/, preprocessed/), `results` (masks/, overlays/); tables `bronze_image_files`, `bronze_image_metadata`, `image_catalog`, `image_quarantine`, `image_results`, `hole_measurements`, `processing_runs`; `v_*` views; model `contact_hole_model`
- `ws_azure_classic_eastus_pedro.fabs_review`: Delta replica of the Lakebase `fabs` schema (Lakebase change data feed, Beta)
- Lakebase Autoscaling project `fabs-metrology`, branch `production`, database `databricks_postgres`, schema `fabs`

## Deploy / rebuild

```bash
databricks bundle deploy                       # pipeline, jobs, app, dashboard
databricks bundle run fabs_setup            # Lakebase DDL, 1,500 synthetic images, ingest, train
databricks bundle run fabs_processing       # first full inference + review queue + views
databricks bundle run fabs_review           # deploy and start the app
```

After the app exists, grant its service principal (client id from `databricks apps get fabs-metrology-review`):

- UC: `USE CATALOG` on the catalog, `USE SCHEMA, SELECT, READ VOLUME` on `fabs_metrology`
- Lakebase: rerun `fabs_setup` task `setup_lakebase` with `--app_sp_client_id=<id>` (bundle var `app_sp_client_id`)

## Jobs

| Job | Compute | Trigger |
|---|---|---|
| `fabs-01-setup-seed-train` | serverless (torch env for training) | manual |
| `fabs-02-image-processing` | serverless pipeline + serverless (torch env) + SQL warehouse | file arrival on `landing/instruments/` (paused), app `run_now` with `submission_id` / `image_ids` |
| `fabs-03-simulate-instrument-drop` | serverless | daily 06:00 PT (paused) |

PyTorch tasks run on serverless (torch installed per environment). A single-node ML-runtime cluster
is defined in jobs.yml but fe-vm eastus hit core quota and SKU stockouts.
