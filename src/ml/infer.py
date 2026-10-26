"""Batch inference: preprocess -> segment/classify -> measure -> persist results.

Selects images from image_catalog that have no result yet (or the images of one
submission / an explicit reprocess list), runs the @champion model, and writes:
  curated/preprocessed/<image_id>.png    model-resolution input
  results/masks/<image_id>.png           full-resolution hole mask
  results/overlays/<image_id>.png        review overlay
  image_results, hole_measurements       Delta (MERGE, idempotent per image)
  processing_runs                        one row per task run
"""
import argparse
import ctypes
import gc
import io
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0])))

import mlflow
import numpy as np
import pandas as pd
import torch
from mlflow.tracking import MlflowClient
from PIL import Image
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

import fabs_ml as mm

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", required=True)
ap.add_argument("--submission_id", default="")
ap.add_argument("--image_ids", default="", help="comma-separated ids to (re)process")
ap.add_argument("--job_run_id", default="")
ap.add_argument("--max_images", type=int, default=5000)
ap.add_argument("--reprocess_all", default="false", help="true = rerun every cataloged image (e.g. new champion model)")
args, _ = ap.parse_known_args()

spark = SparkSession.builder.getOrCreate()
torch.set_num_threads(os.cpu_count())
fq = f"{args.catalog}.{args.schema}"
vol = f"/Volumes/{args.catalog}/{args.schema}"
for d in ("curated/preprocessed", "results/masks", "results/overlays"):
    os.makedirs(f"{vol}/{d}", exist_ok=True)

mlflow.set_registry_uri("databricks-uc")
model_name = f"{fq}.contact_hole_model"
mv = MlflowClient().get_model_version_by_alias(model_name, "champion")
model = mlflow.pytorch.load_model(f"models:/{model_name}@champion", map_location="cpu").eval()
model_version = f"{model_name.split('.')[-1]}/v{mv.version}"
print(f"model {model_version}")

cat = spark.table(f"{fq}.image_catalog")
if args.image_ids.strip():
    todo = cat.where(F.col("image_id").isin([i.strip() for i in args.image_ids.split(",") if i.strip()]))
elif args.submission_id.strip():
    todo = cat.where(F.col("submission_id") == args.submission_id.strip())
else:
    todo = cat
    if args.reprocess_all.lower() != "true" and spark.catalog.tableExists(f"{fq}.image_results"):
        todo = cat.join(spark.table(f"{fq}.image_results").select("image_id"), "image_id", "left_anti")
todo = todo.orderBy("capture_ts").limit(args.max_images).toPandas()
print(f"images to process: {len(todo)}")

def _save_png(arr, path):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    with open(path, "wb") as f:
        f.write(buf.getvalue())


run_uuid = str(uuid.uuid4())
started = datetime.now(timezone.utc)
results, holes = [], []
n_done = n_flagged = 0
FLUSH_EVERY = 256  # bound driver memory; also keeps partial progress if a run dies


def _to_table(pdf, table, comment):
    df = spark.createDataFrame(pdf)
    if spark.catalog.tableExists(table):
        # align types with the table (a chunk can have an all-null column)
        df = df.select([F.col(f.name).cast(f.dataType) for f in spark.table(table).schema])
    else:
        df.limit(0).write.saveAsTable(table, comment=comment)
    return df


def flush():
    global results, holes
    if not results:
        return
    res = _to_table(pd.DataFrame(results), f"{fq}.image_results", "Model + measurement result per image (latest)")
    spark.sql(f"ALTER TABLE {fq}.image_results SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    res.createOrReplaceTempView("new_results")
    spark.sql(f"MERGE INTO {fq}.image_results t USING new_results s ON t.image_id = s.image_id "
              "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")
    ids = ",".join(f"'{r['image_id']}'" for r in results)
    if holes:
        hdf = _to_table(pd.DataFrame(holes), f"{fq}.hole_measurements", "Per-contact measurements from the segmentation mask")
        spark.sql(f"DELETE FROM {fq}.hole_measurements WHERE image_id IN ({ids})")
        hdf.write.mode("append").saveAsTable(f"{fq}.hole_measurements")
    print(f"  flushed {len(results)} results")
    results, holes = [], []


try:  # glibc only; returns freed heap pages to the OS so RSS tracks live data
    _malloc_trim = ctypes.CDLL("libc.so.6").malloc_trim
except (OSError, AttributeError):
    _malloc_trim = None


def release_memory():
    # Long CPU runs grew RSS until the serverless task ran out of memory (decoded images, PIL buffers).
    gc.collect()
    if _malloc_trim:
        _malloc_trim(0)


t0 = time.time()
BATCH = 32
for start in range(0, len(todo), BATCH):
    chunk = todo.iloc[start : start + BATCH]
    fulls = [mm.load_image(p) for p in chunk.file_path]
    xs = np.stack([mm.preprocess(a) for a in fulls])
    with torch.no_grad():
        prob, cls = model(torch.tensor(xs))
    prob, cls = prob.numpy(), cls.numpy()
    for j, r in enumerate(chunk.itertuples()):
        full = fulls[j]
        _save_png(((xs[j, 0] - xs[j, 0].min()) / (np.ptp(xs[j, 0]) + 1e-6) * 255).astype(np.uint8),
                  f"{vol}/curated/preprocessed/{r.image_id}.png")
        pf = mm.upsample(prob[j, 0], full.shape)
        summ, hl, bridge = mm.measure(pf, r.pixel_size_nm, r.expected_holes)
        _save_png(((pf > 0.5) * 255).astype(np.uint8), f"{vol}/results/masks/{r.image_id}.png")
        with open(f"{vol}/results/overlays/{r.image_id}.png", "wb") as f:
            f.write(mm.overlay(full, pf > 0.5, bridge))
        k = int(cls[j].argmax())
        predicted = mm.CLASSES[k]
        flagged = predicted != "none" or summ["cd_spec_status"] in ("FAIL", "NO_MEASUREMENT") or summ["missing_holes"] > 0
        n_done += 1
        n_flagged += int(flagged)
        results.append({
            "image_id": r.image_id,
            "sha256": r.sha256,
            "predicted_class": predicted,
            "class_confidence": float(cls[j, k]),
            **{f"p_{c}": float(cls[j, i]) for i, c in enumerate(mm.CLASSES)},
            **summ,
            "disposition": "FLAGGED" if flagged else "PASS",
            "mask_path": f"{vol}/results/masks/{r.image_id}.png",
            "overlay_path": f"{vol}/results/overlays/{r.image_id}.png",
            "preprocessed_path": f"{vol}/curated/preprocessed/{r.image_id}.png",
            "model_name": model_name,
            "model_version": model_version,
            "processing_run_id": run_uuid,
            "job_run_id": args.job_run_id,
            "processed_ts": datetime.now(timezone.utc),
        })
        for h in hl:
            holes.append({"image_id": r.image_id, **h})
    del fulls, xs, prob, cls
    release_memory()
    print(f"  {min(start + BATCH, len(todo))}/{len(todo)} ({time.time() - t0:.0f}s)")
    if len(results) >= FLUSH_EVERY:
        flush()
flush()

elapsed = time.time() - t0

run_row = {
    "processing_run_id": run_uuid,
    "job_run_id": args.job_run_id,
    "submission_id": args.submission_id or None,
    "mode": "reprocess" if args.image_ids or args.reprocess_all.lower() == "true" else ("submission" if args.submission_id else "incremental"),
    "model_version": model_version,
    "images_processed": n_done,
    "flagged": n_flagged,
    "seconds": float(round(elapsed, 1)),
    "images_per_second": float(round(n_done / elapsed, 2)) if elapsed and n_done else None,
    "cpu_count": int(os.cpu_count()),
    "started_ts": started,
    "ended_ts": datetime.now(timezone.utc),
}
RUN_SCHEMA = ("processing_run_id string, job_run_id string, submission_id string, mode string, model_version string, "
              "images_processed long, flagged long, seconds double, images_per_second double, cpu_count long, "
              "started_ts timestamp, ended_ts timestamp")
spark.createDataFrame([tuple(run_row.values())], schema=RUN_SCHEMA).write.mode("append").saveAsTable(
    f"{fq}.processing_runs")

# hand the processed ids to the publish task
try:
    from databricks.sdk.runtime import dbutils

    dbutils.jobs.taskValues.set("processing_run_id", run_uuid)
    dbutils.jobs.taskValues.set("images_processed", n_done)
except Exception as e:
    print(f"task values not set: {e}")
print(f"done: {n_done} images in {elapsed:.0f}s, run {run_uuid}")
