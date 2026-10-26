"""Shared PyTorch model, preprocessing and measurement logic.

The model is a small multi-task U-Net: a segmentation head (contact-hole mask)
and a classification head (good / missing_contact / bridge / particle) on the
encoder bottleneck. This mirrors the team's split between segmentation and
classification while keeping one artifact to version and serve.

The team's existing PyTorch code would replace TinyUNet / preprocess() here;
the job, measurement and review plumbing around it stay the same.
"""
import io

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

CLASSES = ["none", "missing_contact", "bridge", "particle"]
MODEL_SIZE = 256  # model input resolution

# Specification for the CH1 contact-hole layer
TARGET_CD_NM = 60.0
LSL_NM = 54.0
USL_NM = 66.0
MARGIN_NM = 1.5


# --------------------------------------------------------------------------- preprocessing
def load_image(path_or_bytes):
    """Read JPEG / 8- or 16-bit TIFF into float32 [0, 1], shape (H, W)."""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    with Image.open(src) as im:
        arr = np.asarray(im)
    if arr.ndim == 3:
        arr = arr[..., :3].mean(axis=2)
    if arr.dtype == np.uint16 or arr.max() > 255:
        arr = arr.astype(np.float32) / 65535.0
    else:
        arr = arr.astype(np.float32) / 255.0
    return arr


def preprocess(arr):
    """Resize to model resolution and standardize. Returns (1, S, S) float32."""
    im = Image.fromarray((arr * 255).astype(np.uint8)).resize((MODEL_SIZE, MODEL_SIZE), Image.BILINEAR)
    x = np.asarray(im).astype(np.float32) / 255.0
    x = (x - x.mean()) / (x.std() + 1e-6)
    return x[None, ...]


# --------------------------------------------------------------------------- model
def _block(cin, cout):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
    )


class TinyUNet(nn.Module):
    def __init__(self, base=16, n_classes=len(CLASSES)):
        super().__init__()
        c = [base, base * 2, base * 4, base * 8]
        self.e1, self.e2, self.e3, self.e4 = _block(1, c[0]), _block(c[0], c[1]), _block(c[1], c[2]), _block(c[2], c[3])
        self.pool = nn.MaxPool2d(2)
        self.u3, self.d3 = nn.ConvTranspose2d(c[3], c[2], 2, 2), _block(c[3], c[2])
        self.u2, self.d2 = nn.ConvTranspose2d(c[2], c[1], 2, 2), _block(c[2], c[1])
        self.u1, self.d1 = nn.ConvTranspose2d(c[1], c[0], 2, 2), _block(c[1], c[0])
        self.seg = nn.Conv2d(c[0], 1, 1)
        self.cls = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(c[3], n_classes))

    def forward(self, x):
        e1 = self.e1(x)
        e2 = self.e2(self.pool(e1))
        e3 = self.e3(self.pool(e2))
        e4 = self.e4(self.pool(e3))
        d3 = self.d3(torch.cat([self.u3(e4), e3], 1))
        d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
        d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
        return self.seg(d1), self.cls(e4)


class FabsModel(nn.Module):
    """Export wrapper: returns (mask probability, class probabilities)."""

    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, x):
        seg, cls = self.net(x)
        return torch.sigmoid(seg), torch.softmax(cls, dim=1)


# --------------------------------------------------------------------------- measurement
def measure(prob_full, pixel_nm, expected_holes):
    """Turn a full-resolution hole probability map into engineering measurements.

    Returns (summary dict, per-hole list, labeled bridge mask).
    """
    from scipy import ndimage

    mask = prob_full > 0.5
    lab, n = ndimage.label(mask)
    if n == 0:
        return _empty(expected_holes), [], np.zeros_like(mask)
    idx = np.arange(1, n + 1)
    areas = ndimage.sum(mask, lab, idx)
    centers = ndimage.center_of_mass(mask, lab, idx)
    keep = areas >= 20  # drop speckle
    idx, areas, centers = idx[keep], areas[keep], [c for c, k in zip(centers, keep) if k]
    if len(idx) == 0:
        return _empty(expected_holes), [], np.zeros_like(mask)

    med = float(np.median(areas))
    is_bridge = areas > 1.6 * med
    holes, bridge_mask = [], np.isin(lab, idx[is_bridge])
    for i, (a, (cy, cx), b) in enumerate(zip(areas, centers, is_bridge)):
        holes.append({
            "hole_idx": i,
            "center_x_px": float(cx),
            "center_y_px": float(cy),
            "area_px": int(a),
            "diameter_nm": None if b else float(2 * np.sqrt(a / np.pi) * pixel_nm),
            "is_bridge": bool(b),
        })
    d = np.array([h["diameter_nm"] for h in holes if not h["is_bridge"]])
    n_bridge = int(is_bridge.sum())
    count = int(len(d) + 2 * n_bridge)
    mean_cd = float(d.mean()) if len(d) else None
    out = {
        "hole_count": count,
        "expected_holes": int(expected_holes),
        "missing_holes": max(0, int(expected_holes) - count),
        "bridge_count": n_bridge,
        "mean_cd_nm": mean_cd,
        "std_cd_nm": float(d.std()) if len(d) else None,
        "min_cd_nm": float(d.min()) if len(d) else None,
        "max_cd_nm": float(d.max()) if len(d) else None,
        "cd_3sigma_nm": float(3 * d.std()) if len(d) else None,
        "cd_spec_status": spec_status(mean_cd),
    }
    return out, holes, bridge_mask


def spec_status(mean_cd):
    if mean_cd is None:
        return "NO_MEASUREMENT"
    if mean_cd < LSL_NM or mean_cd > USL_NM:
        return "FAIL"
    if mean_cd < LSL_NM + MARGIN_NM or mean_cd > USL_NM - MARGIN_NM:
        return "MARGINAL"
    return "PASS"


def _empty(expected):
    return {
        "hole_count": 0, "expected_holes": int(expected), "missing_holes": int(expected), "bridge_count": 0,
        "mean_cd_nm": None, "std_cd_nm": None, "min_cd_nm": None, "max_cd_nm": None, "cd_3sigma_nm": None,
        "cd_spec_status": "NO_MEASUREMENT",
    }


def overlay(arr, mask, bridge_mask):
    """RGB overlay: hole contours green, bridges red. Returns PNG bytes."""
    from scipy import ndimage

    g = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    rgb = np.stack([g, g, g], axis=-1)
    edge = mask & ~ndimage.binary_erosion(mask, iterations=1)
    rgb[edge & ~bridge_mask] = (40, 220, 90)
    rgb[bridge_mask] = (0.5 * rgb[bridge_mask] + 0.5 * np.array([230, 40, 40])).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def upsample(prob_small, size):
    t = torch.as_tensor(prob_small)[None, None]
    return F.interpolate(t, size=size, mode="bilinear", align_corners=False)[0, 0].numpy()
