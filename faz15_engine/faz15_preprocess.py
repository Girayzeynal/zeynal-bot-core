# -*- coding: utf-8 -*-
"""
FAZ-15 Preprocess Engine (Fly.io safe + FAZ architecture compliant)

Architectural contract:
- preprocess_image_bytes(img_bytes) -> bytes
- faz15_preprocess(meta) -> dict
- NO destructive side-effects
- Pillow optional, deterministic NO-OP when unavailable
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional, Tuple

# Pillow optional
try:
    from PIL import Image, ImageOps, ImageEnhance
except Exception:
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    ImageEnhance = None  # type: ignore


FAZ15_ENABLED = os.getenv("FAZ15_ENABLED", "1").strip() == "1"
FAZ15_MAX_EDGE = int(os.getenv("FAZ15_MAX_EDGE", "1400"))
FAZ15_CONTRAST = float(os.getenv("FAZ15_CONTRAST", "1.25"))


# =====================================================
# INTERNAL HELPERS
# =====================================================

def _resize_keep_aspect(w: int, h: int, max_edge: int) -> Tuple[int, int]:
    m = max(w, h)
    if m <= max_edge:
        return w, h
    s = max_edge / float(m)
    return max(1, int(w * s)), max(1, int(h * s))


# =====================================================
# CORE IMAGE PREPROCESS
# =====================================================

def preprocess_image_bytes(
    img_bytes: bytes,
    max_edge: int = FAZ15_MAX_EDGE,
    contrast: float = FAZ15_CONTRAST,
) -> bytes:
    """
    Bytes -> bytes (PNG).
    Deterministic NO-OP if FAZ-15 disabled or Pillow unavailable.
    """
    if (not FAZ15_ENABLED) or Image is None:
        return img_bytes

    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        nw, nh = _resize_keep_aspect(im.size[0], im.size[1], max_edge)
        if (nw, nh) != im.size:
            im = im.resize((nw, nh))

        # Safe OCR-friendly normalization
        if ImageOps is not None:
            im = ImageOps.grayscale(im)
            im = ImageOps.autocontrast(im)

        if ImageEnhance is not None:
            im = ImageEnhance.Contrast(im).enhance(contrast)

        out = io.BytesIO()
        # optimize=False → Fly / CI safe
        im.save(out, format="PNG", optimize=False)
        return out.getvalue()

    except Exception:
        # Hard guarantee: never break pipeline
        return img_bytes


# =====================================================
# FAZ-15 META HOOK
# =====================================================

def faz15_preprocess(meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    FAZ-15 metadata processor.

    Expected:
      meta["image_bytes"] -> bytes

    Behavior:
    - NEVER overwrites original bytes in-place
    - Writes output to meta["faz15"]["processed_bytes"]
    - Leaves decision to downstream engines
    """

    if not FAZ15_ENABLED:
        return {
            "faz": "FAZ-15",
            "enabled": False,
            "status": "skipped",
            "reason": "disabled",
        }

    if not isinstance(meta, dict):
        return {
            "faz": "FAZ-15",
            "enabled": True,
            "status": "skipped",
            "reason": "no-meta",
        }

    img = meta.get("image_bytes")
    if not isinstance(img, (bytes, bytearray)):
        meta["faz15"] = {
            "applied": False,
            "reason": "no-image",
        }
        return {
            "faz": "FAZ-15",
            "enabled": True,
            "status": "skipped",
            "reason": "no-image",
        }

    before_len = len(img)
    processed = preprocess_image_bytes(bytes(img))

    # FAZ-compliant: non-destructive write
    meta["faz15"] = {
        "applied": processed != img,
        "bytes_in": before_len,
        "bytes_out": len(processed),
        "pillow": Image is not None,
        "stored_in": "faz15.processed_bytes",
    }
    meta["faz15"]["processed_bytes"] = processed

    return {
        "faz": "FAZ-15",
        "enabled": True,
        "status": "ok",
        "applied": meta["faz15"]["applied"],
    }
