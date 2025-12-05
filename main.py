import os
import io
import time
import json
import hashlib
import logging
from typing import Any, Dict, List, Tuple, Optional

from PIL import Image

log = logging.getLogger("ultra-ocr-v3")

# ================================================================
# 🔧 CONFIG
# ================================================================
OCR_ENGINE_ORDER = os.getenv("OCR_ENGINE_ORDER", "TESSERACT,EASYOCR,VISION")
OCR_ENGINE_ORDER = [e.strip().upper() for e in OCR_ENGINE_ORDER.split(",") if e.strip()]

GPU_MODE = os.getenv("GPU_MODE", "AUTO").upper()  # AUTO / FORCE / OFF
OCR_CACHE_TTL = int(os.getenv("OCR_CACHE_TTL", "900"))  # saniye
OCR_DEBUG = os.getenv("OCR_DEBUG", "OFF").upper() == "ON"

# Vision ile ilgili env'ler (isteğe bağlı, yoksa fallback)
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "NONE").upper()  # OPENAI / NONE
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ================================================================
# 🔧 OPTIONAL IMPORTS
# ================================================================
try:
    import pytesseract  # type: ignore
except Exception:
    pytesseract = None  # type: ignore

try:
    import easyocr  # type: ignore
except Exception:
    easyocr = None  # type: ignore

# OpenAI Vision opsiyonel
try:
    if VISION_PROVIDER == "OPENAI" and OPENAI_API_KEY:
        from openai import OpenAI  # type: ignore

        _vision_client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        _vision_client = None
except Exception:
    _vision_client = None


# ================================================================
# 🔧 GLOBAL OCR CACHE
# ================================================================
_OCR_CACHE: Dict[str, Dict[str, Any]] = {}
_OCR_CACHE_TS: Dict[str, float] = {}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    ts = _OCR_CACHE_TS.get(key)
    if ts is None:
        return None
    if (time.time() - ts) > OCR_CACHE_TTL:
        # TTL dolmuş, sil
        _OCR_CACHE.pop(key, None)
        _OCR_CACHE_TS.pop(key, None)
        return None
    return _OCR_CACHE.get(key)


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    _OCR_CACHE[key] = value
    _OCR_CACHE_TS[key] = time.time()


# ================================================================
# 🔧 UTIL
# ================================================================
def _pil_from_bytes(img_bytes: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = img.convert("RGB")
        return img
    except Exception as e:
        log.error("PIL image açılırken hata: %s", e, exc_info=True)
        return None


def _normalize_text(text: str) -> str:
    # Basit normalizasyon; istersen burayı ileride genişletebiliriz.
    if not text:
        return ""
    # Çok satırlı çıktıyı temizle
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def _debug_meta(tag: str, meta: Dict[str, Any]) -> None:
    if not OCR_DEBUG:
        return
    try:
        log.info("[OCR-DEBUG] %s -> %s", tag, json.dumps(meta, ensure_ascii=False))
    except Exception:
        log.info("[OCR-DEBUG] %s -> %s", tag, meta)


# ================================================================
# 🔍 TESSERACT BACKEND
# ================================================================
def _run_tesseract(img: Image.Image) -> Optional[Dict[str, Any]]:
    if pytesseract is None:
        return None
    try:
        # Basic config; burada dil ayarı vs. ileride eklenebilir.
        raw = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        texts: List[str] = []
        confs: List[float] = []

        n = len(raw.get("text", []))
        for i in range(n):
            txt = (raw["text"][i] or "").strip()
            if not txt:
                continue
            try:
                c = float(raw.get("conf", [0] * n)[i])
            except Exception:
                c = 0.0
            # -1 veya 0 olanlar genelde çöp
            if c <= 0:
                continue
            texts.append(txt)
            confs.append(c)

        if not texts:
            return None

        text = _normalize_text(" ".join(texts))
        if not text:
            return None

        avg_conf = sum(confs) / max(len(confs), 1)
        prob = max(0.0, min(avg_conf / 100.0, 1.0))

        meta = {
            "engine": "TESSERACT",
            "classifier": "TESSERACT_RAW",
            "prob_score": float(prob),
        }
        _debug_meta("TESSERACT", meta)

        return {"text": text, "meta": meta}
    except Exception as e:
        log.error("Tesseract OCR hata: %s", e, exc_info=True)
        return None


# ================================================================
# 🔍 EASYOCR BACKEND
# ================================================================
_easyocr_reader = None


def _get_easyocr_reader() -> Optional[Any]:
    global _easyocr_reader
    if easyocr is None:
        return None

    if _easyocr_reader is not None:
        return _easyocr_reader

    try:
        # easyocr Reader init: Türkçe + İngilizce çok mantıklı
        # GPU_MODE: AUTO/FORCE/OFF
        if GPU_MODE == "OFF":
            use_gpu = False
        elif GPU_MODE == "FORCE":
            use_gpu = True
        else:
            # AUTO -> easyocr kendisi karar versin
            use_gpu = True

        _easyocr_reader = easyocr.Reader(
            ["en", "tr"],
            gpu=use_gpu,
            verbose=False,
        )
        return _easyocr_reader
    except Exception as e:
        log.error("EasyOCR reader init hata: %s", e, exc_info=True)
        _easyocr_reader = None
        return None


def _run_easyocr(img: Image.Image) -> Optional[Dict[str, Any]]:
    reader = _get_easyocr_reader()
    if reader is None:
        return None
    try:
        # EasyOCR doğrudan path veya numpy array alıyor
        import numpy as np  # type: ignore

        arr = np.array(img)
        res = reader.readtext(arr)

        if not res:
            return None

        texts: List[str] = []
        confs: List[float] = []

        for box, txt, conf in res:
            txt = (txt or "").strip()
            if not txt:
                continue
            texts.append(txt)
            try:
                c = float(conf)
            except Exception:
                c = 0.0
            confs.append(c)

        if not texts:
            return None

        text = _normalize_text(" ".join(texts))
        if not text:
            return None

        avg_conf = sum(confs) / max(len(confs), 1)
        prob = max(0.0, min(avg_conf, 1.0))

        meta = {
            "engine": "EASYOCR",
            "classifier": "EASYOCR_RAW",
            "prob_score": float(prob),
        }
        _debug_meta("EASYOCR", meta)

        return {"text": text, "meta": meta}
    except Exception as e:
        log.error("EasyOCR hata: %s", e, exc_info=True)
        return None


# ================================================================
# 🔍 VISION BACKEND (OPSİYONEL)
# ================================================================
def _run_vision_openai(img_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Basit OpenAI Vision entegrasyonu.
    Eğer ortamda yoksa sessizce None döner.
    """
    if _vision_client is None:
        return None

    try:
        # Çok detaylı prompt'a gerek yok, scoreboard/maç bilgisi için serbest format.
        prompt = (
            "Bu görsel basketbol maçına ait istatistik/barem/maç bilgileri içeriyor. "
            "Tüm yazıları, takım isimlerini, lig ve barem bilgilerini düz metin olarak çıkar."
        )

        # OpenAI Vision API isteği
        completion = _vision_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + img_bytes.hex(),
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=800,
        )

        text = completion.choices[0].message.content or ""
        text = _normalize_text(text)
        if not text:
            return None

        meta = {
            "engine": "VISION_OPENAI",
            "classifier": "GPT_VISION",
            "prob_score": 0.85,  # Heuristik; gerçek confidence yok.
        }
        _debug_meta("VISION_OPENAI", meta)

        return {"text": text, "meta": meta}
    except Exception as e:
        log.error("Vision(OpenAI) hata: %s", e, exc_info=True)
        return None


def _run_vision(img_bytes: bytes) -> Optional[Dict[str, Any]]:
    if VISION_PROVIDER == "OPENAI":
        return _run_vision_openai(img_bytes)
    return None


# ================================================================
# 🔎 CANDIDATE SEÇİMİ
# ================================================================
def _choose_best(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    # Prob_score'a göre sırala, en yüksek ilk olsun
    ranked = sorted(
        candidates,
        key=lambda c: float((c.get("meta") or {}).get("prob_score", 0.0)),
        reverse=True,
    )
    best = ranked[0]
    return best


# ================================================================
# 🚀 PUBLIC ENTRYPOINT
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes) -> Dict[str, Any]:
    """
    FAZ-13 Ultra OCR Engine v3 (C MODE FULL POWER - Fly.io safe)

    Geri dönüş formatı:
    {
      "text": "....",
      "meta": {
         "engine": "EASYOCR / TESSERACT / VISION_...",
         "classifier": "....",
         "prob_score": float
      }
    }
    """
    # 1) Cache kontrol
    cache_key = _hash_bytes(img_bytes)
    cached = _cache_get(cache_key)
    if cached is not None:
        _debug_meta("CACHE_HIT", cached.get("meta", {}))
        return cached

    # 2) Görseli PIL ile aç
    img = _pil_from_bytes(img_bytes)
    if img is None:
        # Görsel parse edilemediyse hard fallback
        result = {
            "text": "",
            "meta": {
                "engine": "NONE",
                "classifier": "INVALID_IMAGE",
                "prob_score": 0.0,
            },
        }
        _cache_set(cache_key, result)
        return result

    candidates: List[Dict[str, Any]] = []

    for engine in OCR_ENGINE_ORDER:
        if engine == "TESSERACT":
            res = _run_tesseract(img)
        elif engine == "EASYOCR":
            res = _run_easyocr(img)
        elif engine == "VISION":
            res = _run_vision(img_bytes)
        else:
            continue

        if not res:
            continue

        text = _normalize_text(res.get("text") or "")
        if not text:
            continue

        # meta zorunlu alanları doldur
        meta = res.get("meta") or {}
        meta.setdefault("engine", engine)
        meta.setdefault("classifier", f"{engine}_RAW")
        meta.setdefault("prob_score", 0.5)

        candidates.append({"text": text, "meta": meta})

    best = _choose_best(candidates)
    if best is None:
        # Hiçbir engine düzgün bir şey çıkaramadı → yumuşak fallback
        result = {
            "text": "",
            "meta": {
                "engine": "NONE",
                "classifier": "NO_ENGINE_SUCCESS",
                "prob_score": 0.0,
            },
        }
        _cache_set(cache_key, result)
        return result

    _cache_set(cache_key, best)
    return best
    
    # force-include 
