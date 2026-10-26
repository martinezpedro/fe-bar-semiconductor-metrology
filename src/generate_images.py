"""Synthetic SEM-style contact-hole metrology images.

Stands in for the metrology team's instrument / OneDrive image drops. Each image is a
top-down view of an 8x8 contact-hole array with realistic SEM artifacts
(blur, shot noise, charging gradient, scan-line noise). Known process effects
are injected so the downstream analytics have something real to find:

  * EXP-ETCH-B: new etch recipe, CD grows slowly over the date range
  * EXP-LITHO-C: higher defect rate (missing contacts, bridges)
  * SEM-02: +1.5 nm measurement offset vs SEM-01 (tool-matching issue)
  * Lot-to-lot CD bias

Output layout (mirrors the source folder structure):
  <out_root>/<experiment>/<lot>/<wafer>/<image_id>.(tif|jpg)
  <out_root>/<experiment>/<lot>/<wafer>/<image_id>.json      sidecar metadata
  <label_root>/<image_id>_mask.png                            ground truth (labeled subset only)

Runs on Databricks serverless (numpy + Pillow only) or locally.
"""
import argparse
import io
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image, ImageFilter

IMG = 512
PIXEL_NM = 2.0  # nm per pixel -> 1024 nm field of view
GRID = 8
PITCH_PX = 64
OFFSET_PX = 32
TARGET_CD_NM = 60.0

DRIFT_EPOCH = datetime(2026, 8, 1, tzinfo=timezone.utc)
EXPERIMENTS = {
    # name: (base CD bias nm, CD drift nm/day since DRIFT_EPOCH, defect prob, lot prefix)
    "EXP-ETCH-A": (0.0, 0.0, 0.06, "L241"),
    "EXP-ETCH-B": (0.5, 0.09, 0.08, "L242"),
    "EXP-LITHO-C": (-1.5, 0.0, 0.30, "L253"),
}
TOOLS = {"SEM-01": 0.0, "SEM-02": 1.5}
DEFECTS = ["missing_contact", "bridge", "particle"]


def _draw_holes(rng, cd_nm, defect):
    """Return (image float32 0..1, gt mask uint8, hole count actually opened)."""
    yy, xx = np.mgrid[0:IMG, 0:IMG].astype(np.float32)
    mask = np.zeros((IMG, IMG), dtype=bool)
    rim = np.zeros((IMG, IMG), dtype=np.float32)

    missing = set()
    if defect == "missing_contact":
        n = rng.integers(1, 4)
        missing = {tuple(rng.integers(0, GRID, size=2)) for _ in range(n)}

    win = int(np.ceil(cd_nm / PIXEL_NM)) + 8  # half-window around each hole
    for gy in range(GRID):
        for gx in range(GRID):
            if (gy, gx) in missing:
                continue
            cy = OFFSET_PX + gy * PITCH_PX + rng.normal(0, 0.6)
            cx = OFFSET_PX + gx * PITCH_PX + rng.normal(0, 0.6)
            d_nm = cd_nm + rng.normal(0, 1.2)
            r = d_nm / PIXEL_NM / 2.0
            ell = 1.0 + rng.normal(0, 0.03)
            y0, y1 = max(0, int(cy) - win), min(IMG, int(cy) + win)
            x0, x1 = max(0, int(cx) - win), min(IMG, int(cx) + win)
            wy, wx = yy[y0:y1, x0:x1], xx[y0:y1, x0:x1]
            dist = np.sqrt(((wx - cx) * ell) ** 2 + ((wy - cy) / ell) ** 2)
            mask[y0:y1, x0:x1] |= dist <= r
            rim[y0:y1, x0:x1] += np.exp(-((dist - r) ** 2) / 4.0)

    if defect == "bridge":
        for _ in range(rng.integers(1, 3)):
            gy, gx = rng.integers(0, GRID), rng.integers(0, GRID - 1)
            cy = OFFSET_PX + gy * PITCH_PX
            x0 = OFFSET_PX + gx * PITCH_PX
            half = rng.uniform(5, 9)
            band = (np.abs(yy - cy) <= half) & (xx >= x0) & (xx <= x0 + PITCH_PX)
            mask |= band

    img = np.full((IMG, IMG), 0.62, dtype=np.float32)
    img[mask] = 0.12
    img += 0.35 * np.clip(rim, 0, 1) * (~mask)

    if defect == "particle":
        for _ in range(rng.integers(1, 3)):
            py, px = rng.uniform(40, IMG - 40, size=2)
            pr = rng.uniform(10, 22)
            blob = np.exp(-(((xx - px) ** 2 + (yy - py) ** 2) / (2 * pr**2)))
            img = img + 0.55 * blob  # bright charging particle, not a hole

    return img, mask.astype(np.uint8), GRID * GRID - len(missing)


def _lot_bias(lot):
    """Stable per-lot CD offset (nm) so a lot looks the same across drops."""
    return float(np.random.default_rng(int(lot[1:])).normal(0, 1.0))


def _sem_artifacts(rng, img):
    pil = Image.fromarray(np.clip(img * 255, 0, 255).astype(np.uint8))
    pil = pil.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.6)))
    arr = np.asarray(pil).astype(np.float32) / 255.0
    gy, gx = np.mgrid[0:IMG, 0:IMG].astype(np.float32) / IMG
    arr += rng.uniform(-0.06, 0.06) * gx + rng.uniform(-0.06, 0.06) * gy  # charging
    arr += rng.normal(0, 0.012, size=(IMG, 1))  # scan-line noise
    arr += rng.normal(0, rng.uniform(0.03, 0.06), size=arr.shape)  # shot noise
    return np.clip(arr, 0, 1)


def generate(out_root, label_root, n, seed, start, days, label_fraction, batch_id, submission_id=None):
    rng = np.random.default_rng(seed)
    os.makedirs(out_root, exist_ok=True)
    if label_root:
        os.makedirs(label_root, exist_ok=True)

    exps = list(EXPERIMENTS)
    written = 0
    for i in range(n):
        exp = exps[i % len(exps)] if rng.random() < 0.85 else exps[rng.integers(0, len(exps))]
        base, drift, p_def, prefix = EXPERIMENTS[exp]
        ts = start + timedelta(days=rng.random() * days)
        lot = f"{prefix}{rng.integers(1, 7):02d}"
        wafer = f"W{rng.integers(1, 26):02d}"
        tool = next(iter(TOOLS)) if len(TOOLS) == 1 else ("SEM-01" if rng.random() < 0.55 else "SEM-02")

        age_days = (ts - DRIFT_EPOCH).total_seconds() / 86400
        true_cd = TARGET_CD_NM + base + drift * age_days + _lot_bias(lot)
        # tool offset shows up in the *image* (calibration error), not the true CD
        imaged_cd = true_cd + TOOLS[tool]
        defect = DEFECTS[rng.integers(0, 3)] if rng.random() < p_def else "none"

        img, mask, opened = _draw_holes(rng, imaged_cd, defect)
        img = _sem_artifacts(rng, img)

        image_id = f"IMG-{ts:%Y%m%d}-{rng.bytes(5).hex()}"
        folder = os.path.join(out_root, exp, lot, wafer)
        os.makedirs(folder, exist_ok=True)
        fmt = "tif" if rng.random() < 0.6 else "jpg"
        path = os.path.join(folder, f"{image_id}.{fmt}")
        # encode in memory: libtiff needs a seekable file, which Volume FUSE writes are not
        buf = io.BytesIO()
        if fmt == "tif":
            Image.fromarray((img * 65535).astype(np.uint16)).save(buf, format="TIFF", compression="tiff_deflate")
        else:
            Image.fromarray((img * 255).astype(np.uint8)).save(buf, format="JPEG", quality=92)
        with open(path, "wb") as f:
            f.write(buf.getvalue())

        meta = {
            "image_id": image_id,
            "file_name": os.path.basename(path),
            "experiment_id": exp,
            "lot_id": lot,
            "wafer_id": wafer,
            "die_x": int(rng.integers(-6, 7)),
            "die_y": int(rng.integers(-6, 7)),
            "tool_id": tool,
            "layer": "CH1",
            "feature_type": "contact_hole_array",
            "pixel_size_nm": PIXEL_NM,
            "target_cd_nm": TARGET_CD_NM,
            "expected_holes": GRID * GRID,
            "capture_ts": ts.isoformat(),
            "operator": f"op{rng.integers(1, 7):02d}",
            "batch_id": batch_id,
            "submission_id": submission_id,
            # ground truth kept in the sidecar for model evaluation only; the
            # pipeline never uses these fields for inference
            "gt_defect_type": defect,
            "gt_cd_nm": round(true_cd, 3),
        }
        with open(os.path.join(folder, f"{image_id}.json"), "w") as f:
            json.dump(meta, f)

        if label_root and rng.random() < label_fraction:
            buf = io.BytesIO()
            Image.fromarray(mask * 255).save(buf, format="PNG")
            with open(os.path.join(label_root, f"{image_id}_mask.png"), "wb") as f:
                f.write(buf.getvalue())
        written += 1
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_root", required=True)
    ap.add_argument("--label_root", default="")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--days", type=float, default=60)
    ap.add_argument("--end_date", default="", help="YYYY-MM-DD; default today")
    ap.add_argument("--label_fraction", type=float, default=0.0)
    ap.add_argument("--batch_id", default="")
    ap.add_argument("--inject_bad", type=int, default=0, help="also write N corrupt + N duplicate files")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args, _ = ap.parse_known_args()

    end = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.end_date else datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    seed = args.seed or int(datetime.now().timestamp())
    batch = args.batch_id or f"BATCH-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    import shutil
    import tempfile
    import time
    from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

    # render on local disk, then copy to the Volume in parallel (per-file FUSE writes are slow)
    t0 = time.time()
    tmp = tempfile.mkdtemp()
    tmp_out, tmp_lab = os.path.join(tmp, "out"), os.path.join(tmp, "labels")
    k = max(1, min(args.workers, args.n))
    sizes = [args.n // k + (1 if i < args.n % k else 0) for i in range(k)]
    with ProcessPoolExecutor(k) as ex:
        futs = [ex.submit(generate, tmp_out, tmp_lab if args.label_root else None, sz, seed + i, start, args.days,
                          args.label_fraction, batch) for i, sz in enumerate(sizes) if sz]
        n = sum(f.result() for f in futs)
    if args.inject_bad:
        inject_bad(tmp_out, args.inject_bad, seed)
    print(f"rendered {n} images in {time.time() - t0:.0f}s")

    jobs = []
    for src_root, dst_root in ((tmp_out, args.out_root), (tmp_lab, args.label_root)):
        if not dst_root or not os.path.isdir(src_root):
            continue
        for r, _, fs in os.walk(src_root):
            rel = os.path.relpath(r, src_root)
            os.makedirs(os.path.join(dst_root, rel), exist_ok=True)
            # images before sidecars so a reader never sees metadata without its file
            for f in sorted(fs, key=lambda x: x.endswith(".json")):
                jobs.append((os.path.join(r, f), os.path.join(dst_root, rel, f)))
    with ThreadPoolExecutor(32) as ex:
        list(ex.map(lambda sd: shutil.copyfile(*sd), jobs))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {n} images ({len(jobs)} files) to {args.out_root} in {time.time() - t0:.0f}s (batch {batch})")


def inject_bad(out_root, n, seed):
    """Write intake test cases: truncated (corrupt) images and byte-identical duplicates."""
    import shutil

    rng = np.random.default_rng(seed + 999)
    imgs = sorted(os.path.join(r, f) for r, _, fs in os.walk(out_root) for f in fs if f.endswith((".tif", ".jpg")))
    for i in range(n):
        src = imgs[rng.integers(0, len(imgs))]
        base, ext = os.path.splitext(src)
        meta = json.load(open(base + ".json"))
        # corrupt: first 2 KB of a real file
        bad_id = f"{meta['image_id']}-TRUNC"
        with open(src, "rb") as f:
            head = f.read(2048)
        with open(os.path.join(os.path.dirname(src), bad_id + ext), "wb") as f:
            f.write(head)
        json.dump({**meta, "image_id": bad_id, "file_name": bad_id + ext}, open(os.path.join(os.path.dirname(src), bad_id + ".json"), "w"))
        # duplicate: same bytes re-exported under a new name
        dup_id = f"{meta['image_id']}-COPY"
        shutil.copyfile(src, os.path.join(os.path.dirname(src), dup_id + ext))
        json.dump({**meta, "image_id": dup_id, "file_name": dup_id + ext}, open(os.path.join(os.path.dirname(src), dup_id + ".json"), "w"))
    print(f"injected {n} corrupt and {n} duplicate files")


if __name__ == "__main__":
    main()
