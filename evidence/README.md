# Execution evidence

Text records of the build running in workspace fe-vm (Azure). Everything here was pulled from the workspace
by `collect_evidence.py`: job run history and task stdout, pipeline event logs, MLflow and the model
registry, live query results, the Lakebase replica, and app/dashboard status. Genie benchmark runs are in
`../genie/evidence/`. All data is synthetic.

Regenerate with `python3 -I evidence/collect_evidence.py` (Databricks CLI profile `fe-vm-azure`).

| Stage | File | What it shows |
|---|---|---|
| Lakeflow (orchestration) | `01_jobs_run_history.md` | Every run of the 3 jobs with per-task results, including the failed and cancelled attempts during the build (an out-of-memory inference task was retried and passed; training was relaunched after classic-VM quota failures) |
| ML | `02_job_task_logs.md` | Task stdout: per-epoch training loss/IoU/accuracy, the final metrics dict, model registration as `@champion`, batch-inference progress for 1,500 images, Lakebase setup, publish to the review queue |
| Lakeflow (ingest) | `03_lakeflow_pipeline.md` | Pipeline updates and event-log flow metrics: 1,506 files in, 1,500 cataloged, 6 quarantined (3 truncated, 3 duplicates) with the reject reason for each |
| ML | `04_mlflow_model.md` | UC registered model versions, the `@champion` alias, and params/metrics of both MLflow runs (v1 vs v2) |
| Unity Catalog (data) | `05_unity_catalog_data.md` | Row counts per layer, catalog breakdown, processing-run throughput, confusion matrix, and the three engineering findings |
| Unity Catalog (governance) | `06_unity_catalog_governance.md` | Securables with comments, least-privilege grants for the app service principal, and table lineage from bronze to the analytics views |
| Lakebase | `07_lakebase.md` | Lakebase project config, the Delta replica tables fed by the change data feed, review-queue state, append-only review actions, audit events |
| App / BI / Genie | `08_app_dashboard_genie.md` | App running with its 6 bound resources, deployment history, AI/BI dashboard, and Genie space |
| Genie | `../genie/evidence/` | Benchmark runs on the final data (11 GOOD + 1 manually verified of 12), each with Genie's SQL and its result |

## Headline numbers (from the files above)

- **Ingest:** 1,506 files landed, 1,500 cataloged, 6 quarantined with reasons (3 truncated, 3 byte-identical
  duplicates). 95,740 individual contact holes measured.
- **Model (`contact_hole_model@champion`, 12 epochs on 900 labeled images, 87 min on serverless CPU):**
  - validation mask IoU 0.952, class accuracy 99.3%
  - F1: missing_contact 1.00, bridge 1.00, particle 0.94
  - 1,494 of 1,500 images correct on the full set (3 bridges and 3 particles called "none")
- **Measurement:** SEM-01 CD bias +0.03 nm (MAE 0.60 nm). SEM-02 reads +1.23 nm high, which recovers the
  injected tool offset.
- **Processing:**
  - The clean full run processed 1,500 images in 19 minutes (1.3 images/s on 4-vCPU serverless) and flagged
    394 for review: 193 CD out of spec, 201 defects, missing contacts or marginal CD.
  - An earlier incremental run ran out of memory and was retried automatically (see `01`). The inference
    loop now frees memory after each batch, and the full rerun completed without a retry.
- **Engineering findings:**
  - **CD drift:** EXP-ETCH-B weekly mean CD rose from 63.3 nm to 68.1 nm over 10 weeks. It crossed the
    66 nm USL in the week of 2026-09-28, and lot L24206 now fails spec on 68% of images.
  - **Tool matching:** SEM-02 minus SEM-01 is +1.12 to +1.31 nm in every experiment, which points to a
    systematic tool-matching issue.
  - **Defectivity:** EXP-LITHO-C lots run 23-36% defective (missing contacts, bridges, particles) while
    staying in CD spec.
