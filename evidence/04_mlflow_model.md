# MLflow + Unity Catalog model registry

Registered versions, the @champion alias, and the logged metrics of the champion's training run.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

Model `ws_azure_classic_eastus_pedro.fabs_metrology.contact_hole_model`

Aliases: `@champion` -> v1

| version | status | created | run_id | source |
|---|---|---|---|---|
| 1 | READY | 2026-10-20 04:53 UTC | d6ef65af4493413690b3d54c1132f126 | models:/m-85cb1fb3799f43a1aff9fd35a85793e2 |

## v1: MLflow run `tinyunet-20261020-0325` (FINISHED)

Parameters:

| param | value |
|---|---|
| batch_size | 16 |
| catalog | ws_azure_classic_eastus_pedro |
| epochs | 12 |
| experiment |  |
| lr | 0.002 |
| max_labeled | 900 |
| model_size | 256 |
| n_train | 765 |
| n_val | 135 |
| params | 483669 |
| schema | fabs_metrology |

Final metrics:

| metric | value |
|---|---|
| cd_bias_nm_SEM-01 | 0.0277 |
| cd_bias_nm_SEM-02 | 1.2332 |
| cd_mae_nm_SEM-01 | 0.5976 |
| cd_mae_nm_SEM-02 | 1.2332 |
| f1_bridge | 1.0 |
| f1_missing_contact | 1.0 |
| f1_none | 0.9953 |
| f1_particle | 0.9412 |
| train_loss | 0.2249 |
| train_seconds | 5244.6262 |
| val_class_acc | 0.9926 |
| val_mask_iou | 0.9515 |
