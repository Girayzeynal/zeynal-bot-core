# -*- coding: utf-8 -*-
"""
FAZ-15 Preprocess Engine (Fly.io friendly + mimari uyum)

Mimari sözleşmesi:
- preprocess_image_bytes(img_bytes) -> bytes  (main / OCR pipeline bunu sever)
- faz15_preprocess(meta) -> dict              (status / meta işaretleme)
- Pillow yoksa NO-OP (hayalet FAZ olmaz, sadece "skipped" döner)
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional, Tuple

# Pillow opsiyonel
try:
    from PIL import Image, ImageOps, ImageEnhance
except Exception:
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    ImageEnhance = None  # type: ignore

FAZ15_ENABLED = os.getenv("FAZ15_ENABLED", "1").strip() == "1"
FAZ15_MAX_EDGE = int(os.getenv("FAZ15_MAX_EDGE", "1400"))
FAZ15_CONTRAST = float(os.getenv("FAZ15_CONTRAST", "1.25"))


def _resize_keep_aspect(w: int, h: int, max_edge: int) -> Tuple[int, int]:
    m = max(w, h)
    if m <= max_edge:
        return w, h
    s = max_edge / float(m)
    return max(1, int(w * s)), max(1, int(h * s))


def preprocess_image_bytes(
    img_bytes: bytes,
    max_edge: int = FAZ15_MAX_EDGE,
    contrast: float = FAZ15_CONTRAST,
) -> bytes:
    """
    Bytes -> bytes (PNG). Pillow yoksa veya disabled ise aynı bytes döner.
    """
    if (not FAZ15_ENABLED) or (Image is None):
        return img_bytes

    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        nw, nh = _resize_keep_aspect(im.size[0], im.size[1], max_edge)
        if (nw, nh) != im.size:
            im = im.resize((nw, nh))

        # OCR için basit, güvenli iyileştirme
        im = ImageOps.grayscale(im)  # type: ignore
        im = ImageOps.autocontrast(im)  # type: ignore

        if ImageEnhance is not None:
            im = ImageEnhance.Contrast(im).enhance(contrast)  # type: ignore

        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return img_bytes


def faz15_preprocess(meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Meta üstünden çalışır.
    Beklenen alan (mimari): meta["image_bytes"] = bytes
    Çıkış: status dict + meta["faz15"] iz bırakır.
    """
    if not FAZ15_ENABLED:
        return {"faz": "FAZ-15", "enabled": False, "status": "skipped", "reason": "disabled"}

    if not isinstance(meta, dict):
        return {"faz": "FAZ-15", "enabled": True, "status": "skipped", "reason": "no-meta"}

    img = meta.get("image_bytes")
    if not isinstance(img, (bytes, bytearray)):
        meta["faz15"] = {"applied": False, "reason": "no-image"}
        return {"faz": "FAZ-15", "enabled": True, "status": "skipped", "reason": "no-image"}

    before_len = len(img)
    processed = preprocess_image_bytes(bytes(img))
    meta["image_bytes"] = processed
    meta["faz15"] = {
        "applied": processed is not None,
        "bytes_in": before_len,
        "bytes_out": len(processed) if isinstance(processed, (bytes, bytearray)) else None,
        "pillow": Image is not None,
    }

    return {"faz": "FAZ-15", "enabled": True, "status": "ok", "applied": True}
