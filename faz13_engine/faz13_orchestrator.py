# faz13_engine/faz13_orchestrator.py
from typing import Dict, Any, Optional
import re

# ================================================================
# 🔧 Basit yardımcılar
# ================================================================
def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


# ================================================================
# 📝 MANUAL NORMALIZER (FAZ-13 CORE)
# ================================================================
def normalize_manual_text(raw: str, default_league: str = "NBA") -> Dict[str, Any]:
    if not raw:
        return {
            "source": "manual",
            "raw": "",
            "league": default_league,
            "home": "UNKNOWN",
            "away": "UNKNOWN",
            "market": "FT TOTAL",
            "line": None,
            "direction": None,
            "odds": None,
        }

    # "/mac ..." prefix kırp
    txt = raw.strip()
    if txt.startswith("/"):
        spl = txt.split(maxsplit=1)
        txt = spl[1] if len(spl) > 1 else ""

    tokens = [t for t in txt.replace("\n", " ").split(" ") if t.strip()]

    # Float indexleri bul
    floats_idx = [i for i, t in enumerate(tokens) if _safe_float(t) is not None]

    line = None
    odds = None
    direction = None

    if floats_idx:
        if len(floats_idx) >= 2:
            line = _safe_float(tokens[floats_idx[-2]])
            odds = _safe_float(tokens[floats_idx[-1]])
        else:
            line = _safe_float(tokens[floats_idx[-1]])

        pos = floats_idx[-2] if len(floats_idx) >= 2 else floats_idx[-1]

        # direction
        if pos + 1 < len(tokens):
            d = tokens[pos + 1].upper()
            if d in ("U", "UNDER", "ALT"):
                direction = "U"
            elif d in ("O", "OVER", "ÜST", "UST"):
                direction = "O"

        if not direction and pos - 1 >= 0:
            d = tokens[pos - 1].upper()
            if d in ("U", "UNDER", "ALT"):
                direction = "U"
            elif d in ("O", "OVER", "ÜST", "UST"):
                direction = "O"

        first_num_idx = floats_idx[0]
    else:
        first_num_idx = len(tokens)

    teams = tokens[:first_num_idx]
    if len(teams) >= 2:
        mid = len(teams) // 2
        home = " ".join(teams[:mid])
        away = " ".join(teams[mid:])
    elif len(teams) == 1:
        home = teams[0]
        away = "UNKNOWN"
    else:
        home = "UNKNOWN"
        away = "UNKNOWN"

    return {
        "source": "manual",
        "raw": raw,
        "league": default_league,
        "home": home.upper(),
        "away": away.upper(),
        "market": "FT TOTAL",
        "line": line,
        "direction": direction,
        "odds": odds,
    }


# ================================================================
# 📸 VISUAL META NORMALIZER (FAZ-13 CORE)
# ================================================================
def normalize_visual_meta(ocr_text: str) -> Dict[str, Any]:
    if not ocr_text:
        return {
            "source": "visual",
            "raw": "",
            "league": "NBA",
            "home": "TEAM1",
            "away": "TEAM2",
            "market": "FT TOTAL",
            "line": None,
            "direction": None,
            "odds": None,
        }

    text = ocr_text.upper().replace("\n", " ")
    words = [w for w in text.split(" ") if w.strip()]

    # takım isimleri
    home = words[0] if len(words) > 0 else "TEAM1"
    away = words[1] if len(words) > 1 else "TEAM2"

    # line yakala
    nums = re.findall(r"(\d{2,3}[.,]?\d*)", text)
    line = _safe_float(nums[-1]) if nums else None

    direction = None
    if " ALT" in text or "UNDER" in text:
        direction = "U"
    elif " ÜST" in text or "OVER" in text or "UST" in text:
        direction = "O"

    return {
        "source": "visual",
        "raw": ocr_text,
        "league": "NBA",
        "home": home,
        "away": away,
        "market": "FT TOTAL",
        "line": line,
        "direction": direction,
        "odds": None,
    }


# ================================================================
# 🧠 FAZ-13 CORE PIPELINE
# ================================================================
def run_faz13_auto_pipeline(source: str, fusion: Dict[str, Any]) -> Dict[str, Any]:
    """
    Orchestrator çekirdeği:
    - Normalize edilmiş fusion verisini alır
    - GOD-LAYER veya üst fazlara teslim edilmek üzere paketi hazırlayıp döner
    """
    return {
        "status": "OK",
        "source": source,
        "fusion": fusion,
    }


# ================================================================
# 🧾 KUPO﻿N MOTORLARI — Basit Skeleton
# ================================================================
def faz13_daily_coupon(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coupon_type": "DAILY",
        "status": "READY",
        "msg": "FAZ-13 DAILY coupon motoru aktif (basic)."
    }


def faz13_upcoming_coupon(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coupon_type": "UPCOMING",
        "status": "READY",
        "msg": "FAZ-13 UPCOMING coupon motoru aktif (basic)."
    }


def faz13_league_coupon(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coupon_type": "LEAGUE",
        "status": "READY",
        "msg": "FAZ-13 LEAGUE coupon motoru aktif (basic)."
    }


def faz13_live_coupon(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coupon_type": "LIVE",
        "status": "READY",
        "msg": "FAZ-13 LIVE coupon motoru aktif (basic)."
      }
