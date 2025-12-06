# ultra_ocr_v3.py — SAFE / NO-TORCH MODE (Fly.io 512MB uyumlu)

def ultra_ocr_engine_v3(img_bytes: bytes):
    """
    Torch / EasyOCR devre dışı.
    Sadece güvenli fallback döner.
    """
    return {
        "text": "",
        "meta": {
            "engine": "SAFE_MODE",
            "classifier": "NONE",
            "prob_score": 0.0,
        },
    }
