"""In-app synthetic SEM images for demo submissions (reuses the pipeline generator)."""
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from . import generate_images as gen

_lock = threading.Lock()  # generate() reads module globals


def synth_images(n, experiment, tool):
    """Return [(image_id, ext, bytes, original_name)] for n fresh images of one experiment/tool."""
    _lock.acquire()
    saved = gen.EXPERIMENTS, gen.TOOLS
    gen.EXPERIMENTS = {experiment: saved[0][experiment]}
    gen.TOOLS = {tool: saved[1][tool]}
    out = []
    d = tempfile.mkdtemp()
    try:
        now = datetime.now(timezone.utc)
        gen.generate(d, None, n, seed=int(now.timestamp()), start=now - timedelta(hours=1), days=1 / 24,
                     label_fraction=0, batch_id="APP")
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith((".tif", ".jpg")):
                    with open(os.path.join(root, f), "rb") as fh:
                        image_id, ext = f.rsplit(".", 1)
                        out.append((image_id, ext, fh.read(), f))
    finally:
        gen.EXPERIMENTS, gen.TOOLS = saved
        shutil.rmtree(d, ignore_errors=True)
        _lock.release()
    return out
