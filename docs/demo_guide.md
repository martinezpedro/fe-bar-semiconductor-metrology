# Semiconductor metrology POC on Databricks: demo guide and design notes

Audience: SemiConductor Customer metrology/process engineering team (demo), plus internal prep.
Data is synthetic. Images are generated to look like top-down SEM contact-hole arrays,
with known process effects injected so the analysis has something real to find.

## 1. What the demo shows (mapped to the POC success criteria)

| POC success criterion (from the discovery doc) | Where it shows up |
|---|---|
| Image goes from ingestion to processed result without workstation intervention | Drop files into `landing/instruments/` (simulator job) or upload in the app → processing job → result in the review queue |
| Existing or minimally adapted PyTorch runs on Databricks | `src/ml/fabs_ml.py`: plain PyTorch module; the team's model swaps in at `TinyUNet` / `preprocess()` |
| Results traceable to the source image | `image_results` keyed by `image_id` + `sha256`, linked to `image_catalog` (path, lot, wafer, tool, capture time) and to the model version and job run |
| Engineers ask questions in natural language | App → Ask Genie (Genie space over the curated views and review queue; answers show their SQL; questions are audited) |
| Authorized user submits a job and reviews output in the app | App → Submit images → Job status → Review queue |
| App records who accessed, reviewed, approved, rejected, commented | Lakebase `audit_events` (access, page views, uploads, job submits, AI use, role changes) and append-only `review_actions` |
| Review/approval status persisted and visible | Lakebase `review_items` (state machine), replicated to Delta in `fabs_review` for reporting |
| Workflow can be monitored and rerun | Lakeflow Jobs run history, retries, queueing; reprocess-by-image from the app |
| Initial sizing estimate | Section 5 below (measured on this POC) |
| Migration and security assumptions documented | Sections 4 and 6 |

## 2. Demo script (about 20 minutes)

1. **Context (2 min).** The workstation problem: data split across OneDrive and local disk, one machine hosting the app and compute, manual steps, no review audit trail.
2. **Governed landing (3 min).** Catalog Explorer → `fabs_metrology`: Volumes keep the familiar experiment/lot/wafer folder layout. Show `image_catalog` (one row per unique image with metadata), and `image_quarantine` (truncated TIFFs and byte-identical duplicates caught at intake). Show lineage from the Volume through to the views.
3. **Processing (3 min).** Jobs → `fabs-02-image-processing`: ingest → infer (PyTorch on CPU) → publish to review / refresh analytics. The file-arrival trigger on `landing/instruments/` handles instrument drops; the app triggers the same job for uploads. MLflow experiment and the UC-registered model with the `@champion` alias.
4. **App: submit (3 min).** Submit images → generate 4 synthetic EXP-ETCH-B images on SEM-02 → watch the run in Job status.
5. **App: review and approve (5 min).** Review queue (flagged first) → original next to the segmentation overlay, measurements, contact-diameter histogram → AI review assistant summary (stored with token counts) → record a verdict with a reason code. Approvals → second person approves or declines. Show the separation-of-duties message, then demo mode (flagged `sod_override` in the audit trail).
6. **Engineering analysis (3 min).** Analytics tab or the AI/BI dashboard: EXP-ETCH-B CD drifting toward the USL, the SEM-02 vs SEM-01 offset (~+1.1 nm measured, a tool-matching issue), and EXP-LITHO-C defectivity by lot. (`v_cd_outliers` is empty on the current data: the largest deviation is 2.8σ.) Then open **Ask Genie** in the app and ask the same things in plain English ("Is there a CD offset between the SEM tools?"). Genie answers from the same governed views and shows its SQL. From a review item, *Ask Genie how lot … compares* opens the same page with the question filled in, so engineers can go from one flagged image to its lot context. Every question is logged to the Lakebase audit trail (`GENIE_QUESTION`).
7. **Audit (1 min).** Audit trail page with CSV export; the same data as Delta in `fabs_review` for long-term retention and reporting.

## 3. Architecture

```
 Instruments / OneDrive / workstation             Users (SSO, any network allowed by policy)
          │ bulk migration + incremental                     │
          ▼                                                  ▼
 UC Volume: landing/  ──Auto Loader──►  Lakeflow pipeline    Databricks App (Streamlit)
  (GCS in production)                   bronze → image_catalog ◄── upload / submit / review / approve
          │                             + quarantine            │            │
          │                                   │                 │ run_now    │ read/write state
          ▼                                   ▼                 ▼            ▼
 curated/ (labels, preprocessed)   Lakeflow Job: infer on CPU/GPU ──► Lakebase (Postgres)
 results/ (masks, overlays)  ◄──── PyTorch model @champion (UC)       users/roles, submissions,
                                   │                                   review_items, review_actions,
                                   ▼                                   audit_events, ai_summaries
                     Delta: image_results, hole_measurements,                │ change data feed
                     processing_runs → v_* analytics views                   ▼
                                   │                           Delta: fabs_review.* (history)
                                   └──────────► AI/BI dashboard ◄────────────┘
 AI Gateway (serving endpoint, OpenAI-compatible) ◄── app review assistant
```

## 4. How this maps to the GCP production target

| Demo (fe-vm, Azure) | Production (SemiConductor Customer GCP) | Notes |
|---|---|---|
| UC managed Volume on ADLS | UC external Volume on GCS bucket(s), raw/curated/results | Keeps the folder structure; access is governed by UC, not bucket ACLs |
| Synthetic generator | OneDrive/SharePoint bulk copy, then incremental ingestion | Bulk: Storage Transfer Service or an approved transfer tool into GCS; incremental: Lakeflow Connect SharePoint connector or the instrument writing straight to GCS. Confirm the M365 region / Multi-Geo and the GCP region first (data residency) |
| Serverless jobs with a `torch` environment (CPU) | Serverless CPU for daily inference; classic GPU job clusters (L4/A100) for training or heavy inference, or serverless GPU where available in region | The task code is identical; only the task's compute block changes. fe-vm's eastus subscription hit core quota / SKU stockouts on classic VMs, which is itself a point for serverless |
| Lakebase Autoscaling (Azure eastus) | Lakebase on GCP, if available in the approved region | **Check Lakebase availability in the target GCP region before committing.** The design only needs Postgres semantics |
| AI Gateway → `databricks-claude-sonnet-5-5` | AI Gateway in the GCP workspace, or an external-model endpoint in front of Portkey/OpenAI | Keeps LLM traffic, rate limits and usage logging inside the workspace; cross-cloud routing (GCP Singapore ↔ AWS US) needs a security/latency review |
| Apps SSO, demo personas | Entra ID/SSO groups mapped to app roles; external/vendor users only after SemiConductor Customer security approval | `app_users.user_type = 'external'` already blocks review/approval |

## 5. Measured on the POC (fe-vm, synthetic data, Oct 2026)

| Step | Result |
|---|---|
| Synthetic history | 1,500 images (901 TIFF 16-bit, 599 JPEG; 512×512, ~0.25–0.5 MB each) + 3 truncated + 3 duplicate test files |
| Intake (Lakeflow pipeline, serverless) | ~1–2 min per run; 1,500 cataloged; all 6 bad files quarantined with reasons |
| Training (serverless CPU, 4 vCPU) | 12 epochs on 900 labeled images: ~90 min. 6 epochs / 600 images: ~33 min |
| Model v2 (`@champion`) | Mask IoU 0.953; class accuracy 98.5% (validation); 1,497 / 1,500 correct vs ground truth on the full set (3 particles missed) |
| CD measurement | SEM-01 bias +0.01 nm, MAE 0.64 nm; SEM-02 reads +1.0 to +1.2 nm high (the injected tool offset) |
| Batch inference (serverless CPU) | ~1.5 images/s including preprocessing, mask/overlay writes and measurement; 1,500 images in ~17 min |
| Per-run overhead | ~4 min serverless environment setup (PyTorch install) + ~1 min pipeline + ~1 min publish/views |
| Review queue | 1,500 items in Lakebase; 284 (19%) flagged by the model; replicated to Delta via CDF |

**Sizing read-across (indicative only):** at ~1.5 images/s per 4-vCPU serverless task, a daily
batch of a few thousand images is well under an hour on CPU. The open question for the real
workload is image size (real SEM TIFFs are often 2–20 MB, 1–4k px) and model size; both scale
CPU time roughly linearly, which is where GPU job clusters for inference start to pay off.
The 25 TB backfill is a storage/migration exercise first; reprocessing all of it is a
separate, schedulable GPU batch decision.

Issues hit while building, worth knowing for production:
- fe-vm's Azure subscription ran out of regional cores and then hit VM stockouts for classic clusters, so the demo uses serverless for every task. In production, reserve capacity for GPU pools, or use serverless where it covers the workload.
- Writing TIFFs straight to a Volume's FUSE mount fails (libtiff needs a seekable file); encode in memory, then write.
- Small-file writes to Volumes are slow one at a time; render locally and copy in parallel (32 threads took 1,500 images × 3 files from ~60 min to ~3 min).

## 6. Assumptions, limits, open items

- Synthetic data. Real image sizes, the TIFF bit depth mix, file counts and metadata fields are still in the sizing-input list from discovery.
- The model is a small stand-in. The team's PyTorch code and weights replace it; plumbing stays the same.
- Ground truth in sidecars is only for POC evaluation (`v_model_accuracy`); the pipeline doesn't use it.
- Lakebase change data feed to Delta is Beta.
- Separation-of-duties demo mode exists so one presenter can play every role; it is admin-only and audited.
- Not covered: the real M365 → GCS migration, network design (Private Service Connect, egress), and Portkey/LangGraph integration beyond the OpenAI-compatible call.
