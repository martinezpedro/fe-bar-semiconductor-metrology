"""Train the contact-hole segmentation + defect classification model and register it in UC.

Training labels: masks in the curated Volume (labels/) and defect class from the
image metadata. In production, approved review decisions become the label source.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0])))

import mlflow
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient
from PIL import Image
from pyspark.sql import SparkSession

import fabs_ml as mm

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", required=True)
ap.add_argument("--epochs", type=int, default=6)
ap.add_argument("--max_labeled", type=int, default=600)
ap.add_argument("--batch_size", type=int, default=16)
ap.add_argument("--lr", type=float, default=2e-3)
ap.add_argument("--experiment", default="")
args, _ = ap.parse_known_args()

spark = SparkSession.builder.getOrCreate()
torch.set_num_threads(os.cpu_count())
torch.manual_seed(0)
rng = np.random.default_rng(0)

fq = f"{args.catalog}.{args.schema}"
label_dir = f"/Volumes/{args.catalog}/{args.schema}/curated/labels"
model_name = f"{fq}.contact_hole_model"
labeled = {f[: -len("_mask.png")] for f in os.listdir(label_dir) if f.endswith("_mask.png")}

rows = (
    spark.table(f"{fq}.image_catalog")
    .select("image_id", "file_path", "gt_defect_type", "gt_cd_nm", "tool_id", "pixel_size_nm", "expected_holes")
    .toPandas()
)
rows = rows[rows.image_id.isin(labeled)]
# keep every defect example, subsample the (dominant) good class
rows = pd.concat([rows[rows.gt_defect_type != "none"],
                  rows[rows.gt_defect_type == "none"].sample(frac=1, random_state=0)]).head(args.max_labeled)
rows = rows.reset_index(drop=True)
print(f"labeled images: {len(rows)}")

X, M, Y = [], [], []
for r in rows.itertuples():
    X.append(mm.preprocess(mm.load_image(r.file_path)))
    m = Image.open(f"{label_dir}/{r.image_id}_mask.png").resize((mm.MODEL_SIZE, mm.MODEL_SIZE), Image.NEAREST)
    M.append((np.asarray(m) > 127).astype(np.float32)[None])
    Y.append(mm.CLASSES.index(r.gt_defect_type))
X, M, Y = torch.tensor(np.stack(X)), torch.tensor(np.stack(M)), torch.tensor(Y)

perm = rng.permutation(len(rows))
n_val = max(1, int(0.15 * len(rows)))
val_idx, tr_idx = perm[:n_val], perm[n_val:]

# class weights: defects are rare
counts = torch.bincount(Y[tr_idx], minlength=len(mm.CLASSES)).float()
cls_w = (counts.sum() / (counts.clamp(min=1) * len(mm.CLASSES))).clamp(max=6.0)


def augment(x, m):
    k = int(rng.integers(0, 4))
    x, m = torch.rot90(x, k, (2, 3)), torch.rot90(m, k, (2, 3))
    if rng.random() < 0.5:
        x, m = torch.flip(x, (3,)), torch.flip(m, (3,))
    return x, m


def dice_loss(logit, target):
    p = torch.sigmoid(logit)
    inter = (p * target).sum((1, 2, 3))
    return (1 - (2 * inter + 1) / (p.sum((1, 2, 3)) + target.sum((1, 2, 3)) + 1)).mean()


net = mm.TinyUNet()
opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * (len(tr_idx) // args.batch_size + 1))

me = spark.sql("select current_user()").first()[0]
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(args.experiment or f"/Users/{me}/fabs-metrology-training")


def evaluate():
    net.eval()
    with torch.no_grad():
        seg, cls = [], []
        for i in range(0, n_val, 64):
            s, c = net(X[val_idx[i : i + 64]])
            seg.append(torch.sigmoid(s)), cls.append(c.argmax(1))
        seg, cls = torch.cat(seg), torch.cat(cls)
    pred = seg > 0.5
    gt = M[val_idx] > 0.5
    iou = ((pred & gt).sum() / (pred | gt).sum()).item()
    acc = (cls == Y[val_idx]).float().mean().item()
    per_cls = {}
    for k, name in enumerate(mm.CLASSES):
        tp = ((cls == k) & (Y[val_idx] == k)).sum().item()
        fp = ((cls == k) & (Y[val_idx] != k)).sum().item()
        fn = ((cls != k) & (Y[val_idx] == k)).sum().item()
        per_cls[f"f1_{name}"] = 2 * tp / max(1, 2 * tp + fp + fn)
    return {"val_mask_iou": iou, "val_class_acc": acc, **per_cls}, seg


with mlflow.start_run(run_name=f"tinyunet-{time.strftime('%Y%m%d-%H%M')}") as run:
    mlflow.log_params({**vars(args), "n_train": len(tr_idx), "n_val": n_val, "model_size": mm.MODEL_SIZE,
                       "params": sum(p.numel() for p in net.parameters())})
    t0 = time.time()
    for ep in range(args.epochs):
        net.train()
        order = rng.permutation(tr_idx)
        tot = 0.0
        for i in range(0, len(order), args.batch_size):
            b = order[i : i + args.batch_size]
            x, m = augment(X[b], M[b])
            seg, cls = net(x)
            loss = F.binary_cross_entropy_with_logits(seg, m) + dice_loss(seg, m) + 0.5 * F.cross_entropy(cls, Y[b], weight=cls_w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item() * len(b)
        metrics, _ = evaluate()
        mlflow.log_metrics({"train_loss": tot / len(tr_idx), **metrics}, step=ep)
        print(f"epoch {ep + 1}/{args.epochs} loss={tot / len(tr_idx):.4f} iou={metrics['val_mask_iou']:.3f} acc={metrics['val_class_acc']:.3f} ({time.time() - t0:.0f}s)")

    # measurement accuracy on the validation set at full resolution
    metrics, seg = evaluate()
    err = {"SEM-01": [], "SEM-02": []}
    for j, vi in enumerate(val_idx):
        r = rows.iloc[vi]
        full = mm.load_image(r.file_path)
        summ, _, _ = mm.measure(mm.upsample(seg[j, 0].numpy(), full.shape), r.pixel_size_nm, r.expected_holes)
        if summ["mean_cd_nm"] is not None and r.gt_defect_type == "none":
            err[r.tool_id].append(summ["mean_cd_nm"] - r.gt_cd_nm)
    for tool, e in err.items():
        if e:
            metrics[f"cd_bias_nm_{tool}"] = float(np.mean(e))
            metrics[f"cd_mae_nm_{tool}"] = float(np.mean(np.abs(e)))
    metrics["train_seconds"] = time.time() - t0
    mlflow.log_metrics(metrics)
    print(metrics)

    # keep the weights even if model logging fails
    ckpt_dir = f"/Volumes/{args.catalog}/{args.schema}/curated/models"
    os.makedirs(ckpt_dir, exist_ok=True)
    import io as _io
    buf = _io.BytesIO()
    torch.save(net.state_dict(), buf)
    with open(f"{ckpt_dir}/tinyunet_{run.info.run_id}.pt", "wb") as f:
        f.write(buf.getvalue())

    export = mm.FabsModel(net).eval()
    example = X[:2].numpy()
    with torch.no_grad():
        out = export(torch.tensor(example))
    sig = infer_signature(example, {"mask_prob": out[0].numpy(), "class_prob": out[1].numpy()})
    info = mlflow.pytorch.log_model(
        export,
        artifact_path="model",
        signature=sig,
        serialization_format="pickle",
        code_paths=[os.path.join(os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0])), "fabs_ml.py")],
        registered_model_name=model_name,
        pip_requirements=["torch", "numpy", "pillow", "scipy"],
    )
    version = info.registered_model_version
    client = MlflowClient()
    client.set_registered_model_alias(model_name, "champion", version)
    client.update_model_version(model_name, version, description=(
        f"TinyUNet multi-task. val IoU={metrics['val_mask_iou']:.3f}, class acc={metrics['val_class_acc']:.3f}"))
    print(f"registered {model_name} v{version} as @champion")
