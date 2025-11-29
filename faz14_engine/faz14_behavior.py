
# faz14_engine/faz14_behavior.py

from typing import Any, Dict


# ================================================================
# 🔧 INTERNAL SAFE FLOAT
# ================================================================
def _safe_float(val: Any):
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


# ================================================================
# 🔎 MATCH TYPE DETECT
# ================================================================
def _detect_match_type(meta: Dict[str, Any]) -> str:
    """
    Maçın tipini tahmin eder:
      - NATIONAL (milli takım)
      - PLAYOFF
      - CUP
      - FRIENDLY
      - CLUB (default)
    """
    league = (meta.get("league") or "").upper()
    event_name = (meta.get("event_name") or "").upper()
    home = (meta.get("home") or "").upper()
    away = (meta.get("away") or "").upper()

    text_blob = " ".join([league, event_name, home, away])

    # Milli takım patternleri (WC, EURO, FIBA vs)
    national_keys = [
        "WORLD CUP",
        "WORLD CHAMP",
        "FIBA",
        "EUROBASKET",
        "EURO BASKET",
        "QUALIFICATION",
        "QUALIFIER",
        "EUROPEAN CHAMP",
        "OLYMPIC",
        "OLYMPIK",
        "OLİMPİYAT",
    ]
    for k in national_keys:
        if k in text_blob:
            return "NATIONAL"

    # Friendly pattern
    friendly_keys = ["FRIENDLY", "HAZIRLIK", "PRESEASON", "PRE-SEASON"]
    for k in friendly_keys:
        if k in text_blob:
            return "FRIENDLY"

    # Playoff pattern
    playoff_keys = ["PLAYOFF", "PLAY-OFF", "PLAY OFF", "FINALS", "QUARTERFINAL", "SEMIFINAL"]
    for k in playoff_keys:
        if k in text_blob:
            return "PLAYOFF"

    # Cup pattern
    cup_keys = ["CUP", "KUPA"]
    for k in cup_keys:
        if k in league or k in event_name:
            return "CUP"

    # Default
    return "CLUB"


# ================================================================
# 🧮 LİG PROFİLİ (PACE & VOLATILITY)
# ================================================================
def _league_profile(league: str) -> Dict[str, float]:
    """
    Lig bazlı tempo (pace) ve volatilite profili.
    0.0 - 1.0 arası normalize değerler.
    """
    lu = (league or "").upper()

    # Bazı yaygın ligler
    profiles = {
        "NBA":        {"pace": 0.75, "volatility": 0.65},
        "EUROLEAGUE": {"pace": 0.55, "volatility": 0.55},
        "EL":         {"pace": 0.55, "volatility": 0.55},
        "BSL":        {"pace": 0.60, "volatility": 0.60},
        "TBL":        {"pace": 0.58, "volatility": 0.58},
    }

    # Lig adının içinde geçen patternlere göre de yakala
    if "NBA" in lu:
        return profiles["NBA"]
    if "EUROLEAGUE" in lu or "EURO LEAGUE" in lu or "EUROLEAG" in lu or lu == "EL":
        return profiles["EUROLEAGUE"]
    if "BSL" in lu:
        return profiles["BSL"]
    if "TBL" in lu:
        return profiles["TBL"]

    # Bilinmeyen ligler için orta değer
    return {"pace": 0.60, "volatility": 0.60}


# ================================================================
# 🧪 MATCH-TYPE ADJUST
# ================================================================
def _apply_match_type_adjust(base: Dict[str, float], match_type: str) -> Dict[str, float]:
    """
    Match type'a göre pace/volatility üzerinde küçük ayarlar.
    """
    pace = base["pace"]
    vol = base["volatility"]

    mt = (match_type or "CLUB").upper()

    if mt == "NATIONAL":
        # Milli maçlarda genelde volatilite daha yüksek,
        # tempo turnuvaya göre biraz düşebilir veya kararsız olabilir.
        pace -= 0.02
        vol += 0.05
    elif mt == "PLAYOFF":
        # Playoff maçları: pace hafif düşer, savunma artar, volatilite orta-yüksek
        pace -= 0.03
        vol += 0.02
    elif mt == "CUP":
        # Kupa maçlarında sürpriz çoktur, volatilite artar
        vol += 0.04
    elif mt == "FRIENDLY":
        # Hazırlık maçları: tempo yüksek olabilir ama ciddiyet düşük, volatilite yüksek
        pace += 0.03
        vol += 0.06
    else:
        # CLUB → base değerleri bırak
        pass

    # Clamp
    pace = max(0.30, min(0.90, pace))
    vol = max(0.30, min(0.90, vol))

    return {"pace": round(pace, 3), "volatility": round(vol, 3)}


# ================================================================
# 📆 GÜN MODU / DAY PROFILE
# ================================================================
def _detect_day_profile(feedback_snapshot: Dict[str, Any] | None) -> str:
    """
    FAZ-11 feedback verisine göre gün modunu belirler.
    Şimdilik çok basit:
      - recent_hit_rate >= 0.65 → "HOT"
      - recent_hit_rate <= 0.45 → "CHAOS"
      - aksi → "NORMAL"

    Eğer feedback yoksa → "NORMAL".
    """
    if not feedback_snapshot:
        return "NORMAL"

    try:
        recent_hit_rate = float(feedback_snapshot.get("recent_hit_rate", 0.55))
    except Exception:
        recent_hit_rate = 0.55

    if recent_hit_rate >= 0.65:
        return "HOT"
    if recent_hit_rate <= 0.45:
        return "CHAOS"
    return "NORMAL"


# ================================================================
# 🧠 PUBLIC API: FAZ-14 BEHAVIOR ENRICHER
# ================================================================
def faz14_enrich_behavior(
    meta: Dict[str, Any],
    feedback_snapshot: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    FAZ-14 ana fonksiyon:
      - Lig bilgisinden pace/volatility çıkar
      - Match type tahmin et
      - FAZ-11 feedback'e göre day_profile çıkar
      - Tüm bu bilgileri meta'ya ekler

    Dönen meta:
      {
        ...,
        "match_type": "NATIONAL" | "CLUB" | "CUP" | "PLAYOFF" | "FRIENDLY",
        "pace_score": float,
        "volatility": float,
        "day_profile": "NORMAL" | "HOT" | "CHAOS",
      }
    """
    meta = dict(meta or {})
    league = meta.get("league") or "UNKNOWN"

    # 1) Maç tipi
    match_type = _detect_match_type(meta)

    # 2) Lig profili
    base_prof = _league_profile(league)

    # 3) Match-type adjust
    adj = _apply_match_type_adjust(base_prof, match_type)

    # 4) Gün modu (feedback snapshot ile)
    day_profile = _detect_day_profile(feedback_snapshot)

    # 5) Meta'ya yaz
    meta["match_type"] = match_type
    meta["pace_score"] = adj["pace"]
    meta["volatility"] = adj["volatility"]
    meta["day_profile"] = day_profile

    return meta
