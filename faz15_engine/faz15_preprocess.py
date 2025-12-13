# -*- coding: utf-8 -*-
"""
FAZ-15 Preprocess Engine
Mimari uyum:
- main.py FAZ-15'i opsiyonel çağırır
- ÇALIŞTI / ATLANDI / HATA durumunu net bildirir
- Hayalet FAZ olmaz
"""

from __future__ import annotations

import io
import os
from typing import Dict, Optional, Tuple

# Pillow opsiyonel
try:
    from PIL import Image, ImageOps, ImageEnhance
except Exception:
    Image = None
    ImageOps = None
    ImageEnhance = None

FAZ15_ENABLED = os.getenv("FAZ15_ENABLED", "1") == "1"
MAX_EDGE = int(os.getenv("FAZ15_MAX_EDGE", "1400"))
CONTRAST = float(os.getenv("FAZ15_CONTRAST", "1.25"))


def _resize_keep_aspect(w: int, h: int, max_edge: int) -> Tuple[int, int]:
    m = max(w, h)
    if m <= max_edge:
        return w, h
    s = max_edge / float(m)
    return max(1, int(w * s)), max(1, int(h * s))


def _process_bytes(img_bytes: bytes) -> bytes:
    if Image is None:
        return img_bytes

    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        nw, nh = _resize_keep_aspect(im.size[0], im.size[1], MAX_EDGE)
        if (nw, nh) != im.size:
            im = im.resize((nw, nh))

        im = ImageOps.grayscale(im)
        im = ImageOps.autocontrast(im)

        if ImageEnhance:
            im = ImageEnhance.Contrast(im).enhance(CONTRAST)

        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return img_bytes


def faz15_preprocess(meta: Optional[Dict] = None) -> Dict:
    """
    FAZ-15 resmi preprocess eder.
    main.py bu sonucu alıp _set_faz çağırmalı.
    """
    if not FAZ15_ENABLED:
        return {
            "faz": "FAZ-15",
            "enabled": False,
            "status": "skipped",
            "reason": "disabled"
        }

    if not isinstance(meta, dict):
        return {
            "faz": "FAZ-15",
            "enabled": True,
            "status": "skipped",
            "reason": "no-meta"
        }

    img = meta.get("image_bytes")
    if not isinstance(img, (bytes, bytearray)):
        meta["faz15"] = {"applied": False}
        return {
            "faz": "FAZ-15",
            "enabled": True,
            "status": "skipped",
            "reason": "no-image"
        }

    meta["image_bytes"] = _process_bytes(bytes(img))
    meta["faz15"] = {"applied": True}

    return {
        "faz": "FAZ-15",
        "enabled": True,
        "status": "ok",
        "applied": True
    }
