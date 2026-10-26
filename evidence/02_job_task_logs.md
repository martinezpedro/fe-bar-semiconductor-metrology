# Job task logs (stdout)

Captured stdout of every successful Python task: data generation, Lakebase setup, PyTorch training, batch inference and review publishing.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

## fabs-01-setup-seed-train / run 125757800162822 / task `generate_history`

Started 2026-10-20 03:14 UTC, 2.1 min.

```text
injected 3 corrupt and 3 duplicate files
rendered 1500 images in 34s
wrote 1500 images (4041 files) to /Volumes/ws_azure_classic_eastus_pedro/fabs_metrology/landing/instruments in 117s (batch HISTORY)
```

## fabs-01-setup-seed-train / run 125757800162822 / task `train`

Started 2026-10-20 03:18 UTC, 94.6 min.

```text
labeled images: 900


2026/10/20 03:25:51 INFO mlflow.tracking.fluent: Experiment with name '/Users/pedro.martinez@databricks.com/fabs-metrology-training' does not exist. Creating a new experiment.
If you are using MLflow Tracing, consider storing your traces in Unity Catalog for unlimited storage (no 100,000 trace limit), fine-grained access controls, and queryability from notebooks, SQL, and dashboards. Learn more: https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog


epoch 1/12 loss=1.8691 iou=0.778 acc=0.815 (447s)
epoch 2/12 loss=1.4743 iou=0.912 acc=0.067 (869s)
epoch 3/12 loss=1.1550 iou=0.961 acc=0.326 (1303s)
epoch 4/12 loss=0.7826 iou=0.934 acc=0.859 (1742s)
epoch 5/12 loss=0.6824 iou=0.943 acc=0.081 (2175s)
epoch 6/12 loss=0.6020 iou=0.977 acc=0.096 (2608s)
epoch 7/12 loss=0.4444 iou=0.916 acc=0.104 (3039s)
epoch 8/12 loss=0.3755 iou=0.951 acc=0.074 (3473s)
epoch 9/12 loss=0.2984 iou=0.948 acc=0.126 (3897s)
epoch 10/12 loss=0.2531 iou=0.955 acc=0.933 (4324s)
epoch 11/12 loss=0.2561 iou=0.956 acc=0.993 (4760s)
epoch 12/12 loss=0.2249 iou=0.952 acc=0.993 (5192s)
{'val_mask_iou': 0.9515047073364258, 'val_class_acc': 0.9925925731658936, 'f1_none': 0.9953051643192489, 'f1_missing_contact': 1.0, 'f1_bridge': 1.0, 'f1_particle': 0.9411764705882353, 'cd_bias_nm_SEM-01': 0.027691269360324584, 'cd_mae_nm_SEM-01': 0.5976076173177228, 'cd_bias_nm_SEM-02': 1.2332340797600971, 'cd_mae_nm_SEM-02': 1.2332340797600971, 'train_seconds': 5244.626183986664}


2026/10/20 04:53:21 WARNING mlflow.models.model: `artifact_path` is deprecated. Please use `name` instead.
🔗 View Logged Model at: https://adb-7405605954880111.11.azuredatabricks.net/ml/experiments/4153035828441046/models/m-85cb1fb3799f43a1aff9fd35a85793e2?o=7405605954880111
Successfully registered model 'ws_azure_classic_eastus_pedro.fabs_metrology.contact_hole_model'.
🔗 Created version '1' of model 'ws_azure_classic_eastus_pedro.fabs_metrology.contact_hole_model': https://adb-7405605954880111.11.azuredatabricks.net/explore/data/models/ws_azure_classic_eastus_pedro/fabs_metrology/contact_hole_model/version/1?o=7405605954880111


registered ws_azure_classic_eastus_pedro.fabs_metrology.contact_hole_model v1 as @champion
🏃 View run tinyunet-20261020-0325 at: https://adb-7405605954880111.11.azuredatabricks.net/ml/experiments/4153035828441046/runs/d6ef65af4493413690b3d54c1132f126
🧪 View experiment at: https://adb-7405605954880111.11.azuredatabricks.net/ml/experiments/4153035828441046
```

## fabs-01-setup-seed-train / run 125757800162822 / task `setup_lakebase`

Started 2026-10-20 03:15 UTC, 0.7 min.

```text
granted app role 3a630645-574e-499c-9b86-dc4e87e09fbb
app_users: 5
lakebase ready
```

## fabs-02-image-processing / run 246180842051957 / task `infer`

Started 2026-10-20 15:23 UTC, 21.1 min.

```text
model contact_hole_model/v1
images to process: 1500
  32/1500 (27s)
  64/1500 (53s)
  96/1500 (78s)
  128/1500 (102s)
  160/1500 (126s)
  192/1500 (148s)
  224/1500 (174s)
  256/1500 (196s)
  flushed 256 results
  288/1500 (243s)
  320/1500 (268s)
  352/1500 (288s)
  384/1500 (310s)
  416/1500 (331s)
  448/1500 (351s)
  480/1500 (373s)
  512/1500 (395s)
  flushed 256 results
  544/1500 (433s)
  576/1500 (460s)
  608/1500 (483s)
  640/1500 (506s)
  672/1500 (527s)
  704/1500 (547s)
  736/1500 (570s)
  768/1500 (593s)
  flushed 256 results
  800/1500 (629s)
  832/1500 (652s)
  864/1500 (674s)
  896/1500 (694s)
  928/1500 (716s)
  960/1500 (737s)
  992/1500 (756s)
  1024/1500 (777s)
  flushed 256 results
  1056/1500 (813s)
  1088/1500 (835s)
  1120/1500 (857s)
  1152/1500 (878s)
  1184/1500 (901s)
  1216/1500 (923s)
  1248/1500 (945s)
  1280/1500 (966s)
  flushed 256 results
  1312/1500 (998s)
  1344/1500 (1021s)
  1376/1500 (1046s)
  1408/1500 (1067s)
  1440/1500 (1087s)
  1472/1500 (1108s)
  1500/1500 (1126s)
  flushed 220 results
done: 1500 images in 1137s, run 12d69632-e7d2-44b1-8564-e31ea461891a
```

## fabs-02-image-processing / run 246180842051957 / task `publish_review`

Started 2026-10-20 15:44 UTC, 0.7 min.

```text
results to publish: 1500
published
```

## fabs-02-image-processing / run 350213818431519 / task `infer`

Started 2026-10-20 14:17 UTC, 5.1 min.

```text
model contact_hole_model/v1
images to process: 220
  32/220 (36s)
  64/220 (59s)
  96/220 (79s)
  128/220 (98s)
  160/220 (118s)
  192/220 (136s)
  220/220 (153s)
  flushed 220 results
done: 220 images in 170s, run aedc5d37-9638-4369-bc34-201e965827d0
```

## fabs-02-image-processing / run 350213818431519 / task `publish_review`

Started 2026-10-20 14:22 UTC, 0.5 min.

```text
results to publish: 220
published
```
