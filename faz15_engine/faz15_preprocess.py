# -*- coding: utf-8 -*-
"""
FAZ-15 Preprocess (Fly.io friendly)
Amaç:
- OCR/visual pipeline öncesi görüntüyü hafifçe temizlemek (opsiyonel)
- Opencv (cv2) YOKSA bile import patlatmayacak → "hayalet" FAZ olmasın.
- main.py `faz15_preprocess(meta)` veya `faz15_preprocess()` çağırabilir → toleranslı.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional, Tuple

# Pillow opsiyonel: varsa kullan, yoksa no-op
try:
    from PIL import Image, ImageOps, ImageEnhance
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    ImageEnhance = None  # type: ignore

FAZ15_ENABLED = os.getenv("FAZ15_ENABLED", "1").strip() == "1"

# Çok agresif ayar yapma: Fly.io + farklı görseller → stabil kal
DEFAULT_MAX_EDGE = int(os.getenv("FAZ15_MAX_EDGE", "1400"))
DEFAULT_CONTRAST = float(os.getenv("FAZ15_CONTRAST", "1.25"))


def _resize_keep_aspect(w: int, h: int, max_edge: int) -> Tuple[int, int]:
    m = max(w, h)
    if m <= max_edge:
        return w, h
    scale = max_edge / float(m)
    return max(1, int(w * scale)), max(1, int(h * scale))


def preprocess_image_bytes(
    img_bytes: bytes,
    max_edge: int = DEFAULT_MAX_EDGE,
    contrast: float = DEFAULT_CONTRAST,
) -> bytes:
    """
    Bytes -> bytes (PNG).
    Pillow yoksa input'u aynen döndürür.
    """
    if not FAZ15_ENABLED:
        return img_bytes

    if Image is None:
        # Pillow yok → hiç dokunma
        return img_bytes

    try:
        im = Image.open(io.BytesIO(img_bytes))
        im = im.convert("RGB")

        # Boyut indir (OCR hız/ram)
        nw, nh = _resize_keep_aspect(im.size[0], im.size[1], max_edge=max_edge)
        if (nw, nh) != im.size:
            im = im.resize((nw, nh))

        # Gri + oto-contrast
        im = ImageOps.grayscale(im)
        im = ImageOps.autocontrast(im)

        # hafif kontrast
        if ImageEnhance is not None:
            im = ImageEnhance.Contrast(im).enhance(contrast)

        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        # preprocess patlarsa görüntüyü bozmayalım, aynen dön
        return img_bytes


def faz15_preprocess(meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    main.py bunu şimdilik meta ile çağırıyor:
      - faz15_preprocess(meta)
      - faz15_preprocess()
    Bu fonksiyon meta üzerinde "hazır" bayrağı bırakır.
    Görsel bytes burada yoksa bile FAZ-15 yeşil tik verir.
    """
    if not FAZ15_ENABLED:
        return {"ok": True, "enabled": False}

    if not isinstance(meta, dict):
        return {"ok": True, "enabled": True, "note": "no meta"}

    # Eğer ileride main.py meta içine image_bytes koyarsa (örn: meta["image_bytes"])
    # burada preprocess yapıp meta["image_bytes"]'i güncelleyebilirsin.
    img_bytes = meta.get("image_bytes")
    if isinstance(img_bytes, (bytes, bytearray)):
        meta["image_bytes"] = preprocess_image_bytes(bytes(img_bytes))
        meta["faz15"] = {"preprocessed": True}
        return {"ok": True, "enabled": True, "preprocessed": True}

    meta["faz15"] = {"preprocessed": False}
    return {"ok": True, "enabled": True, "preprocessed": False}
