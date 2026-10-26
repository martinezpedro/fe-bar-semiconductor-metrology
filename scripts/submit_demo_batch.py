"""Submit a synthetic batch through the same path as an app upload, with chosen defect scenarios.

Writes images + sidecars to landing/uploads/<submission_id>/, registers the submission in Lakebase,
audits it, and starts the processing job for that submission, exactly as the app's Submit page does.
Used to stage a demo review set (the app's own generator picks defects at random).

Run as a one-off serverless job (needs psycopg + pillow), e.g. from scripts/submit_demo_batch.sh.
"""
import argparse
import io
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image
from psycopg.types.json import Json

HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "src", "common"))
import generate_images as gen  # noqa: E402
import lakebase  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", required=True)
ap.add_argument("--lakebase_endpoint", required=True)
ap.add_argument("--lakebase_host", required=True)
ap.add_argument("--processing_job_id", type=int, required=True)
ap.add_argument("--experiment", default="EXP-ETCH-A")
ap.add_argument("--lot", default="L24107")
ap.add_argument("--tool", default="SEM-01")
ap.add_argument("--scenarios", default="bridge,bridge,particle,particle,missing_contact,none,none")
args, _ = ap.parse_known_args()

w = WorkspaceClient()
user = w.current_user.me().user_name
now = datetime.now(timezone.utc)
sid = f"SUB-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
folder = f"/Volumes/{args.catalog}/{args.schema}/landing/uploads/{sid}"
os.makedirs(folder, exist_ok=True)

base, drift, _, _ = gen.EXPERIMENTS[args.experiment]
rng = np.random.default_rng(int(now.timestamp()))
scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
written = []
for i, defect in enumerate(scenarios):
    ts = now - timedelta(minutes=5 * (len(scenarios) - i))
    true_cd = gen.TARGET_CD_NM + base + drift * (ts - gen.DRIFT_EPOCH).total_seconds() / 86400 + gen._lot_bias(args.lot)
    img, _mask, _opened = gen._draw_holes(rng, true_cd + gen.TOOLS[args.tool], defect)
    img = gen._sem_artifacts(rng, img)
    image_id = f"IMG-U-{uuid.uuid4().hex[:12]}"
    ext = "tif" if i % 2 == 0 else "jpg"
    buf = io.BytesIO()  # encode in memory: libtiff needs a seekable file, Volume FUSE writes are not
    if ext == "tif":
        Image.fromarray((img * 65535).astype(np.uint16)).save(buf, format="TIFF", compression="tiff_deflate")
    else:
        Image.fromarray((img * 255).astype(np.uint8)).save(buf, format="JPEG", quality=92)
    with open(f"{folder}/{image_id}.{ext}", "wb") as f:
        f.write(buf.getvalue())
    meta = {"image_id": image_id, "file_name": f"{image_id}.{ext}", "original_file_name": f"demo_{defect}_{i + 1}.{ext}",
            "experiment_id": args.experiment, "lot_id": args.lot, "wafer_id": f"W{i + 1:02d}", "die_x": 0, "die_y": 0,
            "tool_id": args.tool, "layer": "CH1", "feature_type": "contact_hole_array", "pixel_size_nm": gen.PIXEL_NM,
            "target_cd_nm": gen.TARGET_CD_NM, "expected_holes": gen.GRID * gen.GRID, "capture_ts": ts.isoformat(),
            "operator": user, "batch_id": sid, "submission_id": sid, "uploaded_by": user}
    with open(f"{folder}/{image_id}.json", "w") as f:
        json.dump(meta, f)
    written.append((image_id, defect))
    print(f"wrote {image_id}.{ext}  scenario={defect}  true_cd={true_cd:.2f} nm")

desc = "Scripted demo batch: " + ", ".join(f"{scenarios.count(s)} {s}" for s in dict.fromkeys(scenarios))
with lakebase.connect(args.lakebase_endpoint, args.lakebase_host) as conn, conn.cursor() as cur:
    cur.execute("INSERT INTO submissions (submission_id, submitted_by, description, experiment_id, lot_id, file_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)", (sid, user, desc, args.experiment, args.lot, len(written)))
    cur.execute("INSERT INTO audit_events (actor_email, event_type, object_type, object_id, details) VALUES (%s, %s, %s, %s, %s)",
                (user, "UPLOAD", "submission", sid, Json({"files": len(written), "experiment": args.experiment,
                                                            "lot": args.lot, "source": "scripts/submit_demo_batch.py"})))
    conn.commit()
    run_id = w.jobs.run_now(job_id=args.processing_job_id,
                            job_parameters={"submission_id": sid, "image_ids": "", "reprocess_all": "false"}).run_id
    cur.execute("UPDATE submissions SET job_run_id = %s, status = 'RUNNING', updated_at = now() WHERE submission_id = %s",
                (run_id, sid))
    cur.execute("INSERT INTO audit_events (actor_email, event_type, object_type, object_id, details) VALUES (%s, %s, %s, %s, %s)",
                (user, "JOB_SUBMIT", "job_run", str(run_id), Json({"submission_id": sid})))
    conn.commit()
print(f"submission {sid}: {len(written)} images, processing run {run_id}")
