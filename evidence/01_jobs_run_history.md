# Lakeflow Jobs: run history

Every run of the three bundle jobs, with per-task results. Failures are kept: they show the retries and fixes during the build.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

## fabs-01-setup-seed-train (job 819210393520691)

| run_id | started | minutes | result | tasks (enabled) |
|---|---|---|---|---|
| 125757800162822 | 2026-10-20 03:14 UTC | 98.6 | SUCCESS | generate_history=SUCCESS, train=SUCCESS, setup_lakebase=FAILED, setup_lakebase=SUCCESS, ingest=SUCCESS |

## fabs-02-image-processing (job 554610143105938)

| run_id | started | minutes | result | tasks (enabled) |
|---|---|---|---|---|
| 246180842051957 | 2026-10-20 15:21 UTC | 23.2 | SUCCESS | ingest=SUCCESS, refresh_analytics=SUCCESS, infer=SUCCESS, publish_review=SUCCESS |
| 350213818431519 | 2026-10-20 13:33 UTC | 50.0 | SUCCESS | ingest=SUCCESS, refresh_analytics=SUCCESS, infer=FAILED, infer=SUCCESS, publish_review=SUCCESS |

## fabs-03-simulate-instrument-drop (job 588470458864664)

No runs (job is scheduled but paused).
