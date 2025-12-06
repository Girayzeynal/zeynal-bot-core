# ================================================================
#   FAZ-13 ORCHESTRATOR (FULL REBUILD - STABLE VERSION)
# ================================================================

from typing import Dict, Any, List, Optional

# --------------------------------------------------------------
# MANUAL INPUT NORMALIZER
# --------------------------------------------------------------
def normalize_manual_text(raw: str) -> Dict[str, Any]:
    """
    Manuel giriş formatını FAZ-13 GOD-LAYER'ın anlayacağı fusion forma çevirir.
    """
    if not raw:
        return {
            "league": None,
            "match": None,
            "home": None,
            "away": None,
            "date": None,
            "tokens": [],
            "raw": "",
        }

    text = raw.strip()
    tokens = text.split()

    league = None
    date = None
    home = None
    away = None

    # Format 1 — Euroleague | 2025-12-05 | Team - Team
    if "|" in text and "-" in text:
        parts = [p.strip() for p in text.split("|")]
        if len(parts) >= 3:
            league = parts[0]
            date = parts[1]

            if "-" in parts[2]:
                t = parts[2].split("-")
                home = t[0].strip()
                away = t[1].strip()

    # Format 2 — BOS ORL 220.5 U 1.46
    if home is None and away is None and len(tokens) >= 2:
        home = tokens[0]
        away = tokens[1]

    match = None
    if home and away:
        match = f"{home} - {away}"

    return {
        "league": league,
        "match": match,
        "home": home,
        "away": away,
        "date": date,
        "tokens": tokens,
        "raw": text,
    }


# --------------------------------------------------------------
# VISUAL INPUT NORMALIZER
# --------------------------------------------------------------
def normalize_visual_meta(text: str) -> Dict[str, Any]:
    """
    OCR'den gelen metni FAZ-13 fusion formatına çevirir.
    """
    if not text:
        return {
            "league": None,
            "match": None,
            "home": None,
            "away": None,
            "date": None,
            "raw": "",
        }

    lines = text.strip().split("\n")
    tokens = text.replace("\n", " ").split()

    home = None
    away = None
    league = None
    date = None

    # İlkel takım çıkarma (görseller için çoğu zaman yeterli)
    if len(tokens) >= 2:
        home = tokens[0]
        away = tokens[1]

    match = None
    if home and away:
        match = f"{home} - {away}"

    return {
        "league": league,
        "match": match,
        "home": home,
        "away": away,
        "date": date,
        "raw": text,
    }


# --------------------------------------------------------------
# API / PROVIDER DATA NORMALIZER
# --------------------------------------------------------------
def normalize_api_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-23'ten veya başka canlı kaynaklardan gelen veriyi FAZ-13 formatına çevirir.
    """
    if not isinstance(data, dict):
        return {
            "league": None,
            "match": None,
            "home": None,
            "away": None,
            "date": None,
            "raw": data,
        }

    league = data.get("league") or data.get("competition")
    date = data.get("date")
    home = data.get("home_team") or data.get("home")
    away = data.get("away_team") or data.get("away")

    match = None
    if home and away:
        match = f"{home} - {away}"

    return {
        "league": league,
        "date": date,
        "home": home,
        "away": away,
        "match": match,
        "raw": data,
    }


# --------------------------------------------------------------
# FAZ-13 ANA FÜZYON PIPELINE
# --------------------------------------------------------------
def _fake_model_score(home: str, away: str) -> List[int]:
    """
    Placeholder: gerçek ML/deep model yoksa bile skor vektörü döndürür.
    """
    base = (len(home) * 7 + len(away) * 11) % 40
    return [base + 70, base + 75, base + 80]


def run_faz13_auto_pipeline(
    league: Optional[str],
    date: Optional[str],
    home_team: Optional[str],
    away_team: Optional[str],
    full_output: bool = True,
    match_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    FAZ-13 otomatik tahmin pipeline'ı.
    """
    if not home_team or not away_team:
        raise ValueError("home_team veya away_team eksik")

    match = f"{home_team} - {away_team}"

    # Skor vektörü (fake model)
    score_vec = _fake_model_score(home_team, away_team)

    # Fusion karar
    if score_vec[-1] >= 150:
        fusion_call = "ÜST"
    else:
        fusion_call = "ALT"

    debug_reasons = [
        f"Takım uzunluğu modeli: {score_vec}",
        "Lig ağırlığı: STABLE-MODE (placeholder)",
        "Meta veri füzyonu: NORMAL",
    ]

    return {
        "league": league,
        "date": date,
        "match": match,
        "fusion_total_call": fusion_call,
        "internal_score_vector": score_vec,
        "news_summary": "NEWS DISABLED (OCR/Opsiyonel modüller kapalı)",
        "debug_reasons": debug_reasons,
    } 
