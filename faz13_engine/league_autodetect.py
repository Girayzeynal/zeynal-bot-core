import re
from typing import Any, Optional, Tuple

# ===============================================================
# GLOBAL FAMILY HARİTASI
# ===============================================================

FAMILY_KEYWORDS = {
    # Kuzey Amerika
    "NBA": ["nba"],
    "WNBA": ["wnba"],
    "GLEAGUE": ["g league", "gleague", "g-league"],

    # Avrupa üst seviye
    "EUROLEAGUE": ["euroleague", "euro league"],
    "EUROCUP": ["eurocup"],
    "BCL": ["bcl", "champions league", "basketball champions league"],

    # Yerel ligler
    "TURKISH_BSL": ["bsl", "turkey", "türkiye", "super lig", "süper lig"],
    "ACB_SPAIN": ["acb", "endesa", "liga acb"],
    "GERMANY_BBL": ["bbl", "germany", "easycredit"],
    "FRANCE_PROA": ["pro a", "lnb", "france"],
    "ITALY_SERIEA": ["serie a", "lega", "italy", "italia"],
    "GREECE_ESAKE": ["esake", "greek", "greece"],
    "ABA_ADRIATIC": ["aba", "adriatic"],

    # Diğer global ligler
    "AUSTRALIA_NBL": ["nbl", "australia"],
    "JAPAN_BLEAGUE": ["b.league", "bleague", "japan"],
    "KOREA_KBL": ["kbl", "korea"],
    "CHINA_CBA": ["cba", "china"],
    "PHILIPPINES_PBA": ["pba", "philippines"],

    # Milli takım / FIBA
    "FIBA_NATIONAL": ["fiba", "eurobasket", "olympic", "world cup"],
}

# ===============================================================
# ÜLKE / TAKIM İSMİ → FAMILY HINT
# ===============================================================

COUNTRY_FAMILY = {
    "turkey": "TURKISH_BSL",
    "türkiye": "TURKISH_BSL",
    "spain": "ACB_SPAIN",
    "germany": "GERMANY_BBL",
    "france": "FRANCE_PROA",
    "italy": "ITALY_SERIEA",
    "italia": "ITALY_SERIEA",
    "greece": "GREECE_ESAKE",
    "serbia": "ABA_ADRIATIC",
    "croatia": "ABA_ADRIATIC",
    "slovenia": "ABA_ADRIATIC",
    "bosnia": "ABA_ADRIATIC",
    "montenegro": "ABA_ADRIATIC",
    "usa": "NBA",
    "united states": "NBA",
    "canada": "NBA",
    "australia": "AUSTRALIA_NBL",
    "japan": "JAPAN_BLEAGUE",
    "korea": "KOREA_KBL",
    "china": "CHINA_CBA",
    "philippines": "PHILIPPINES_PBA",
}

# ===============================================================
# INPUT NORMALİZASYON
# ===============================================================

def _norm(x: Any) -> str:
    """None / tuple / list → güvenli string."""
    if x is None:
        return ""
    if isinstance(x, (tuple, list)):
        return " ".join(str(i) for i in x if i is not None)
    return str(x)

# ===============================================================
# MAIN DETECTOR (ANA ALGORİTMA)
# ===============================================================

def guess_league(home: str, away: str, league_hint: Any) -> Tuple[Optional[str], str]:
    """
    Lig tahmini üretir.
    Her zaman (league_string, reason) tuple döndürür.
    """
    h = _norm(home).lower()
    a = _norm(away).lower()
    l = _norm(league_hint).lower()

    # 1) Direkt lig isminde family keyword var mı?
    for fam, keys in FAMILY_KEYWORDS.items():
        for kw in keys:
            if kw in l:
                return fam, f"match by league keyword: {kw}"

    # 2) Takım isimlerinden ülke çıkarma
    for name in [h, a]:
        for c, fam in COUNTRY_FAMILY.items():
            if c in name:
                return fam, f"match by team-country: {c}"

    # 3) Lig adında ülke/lig ipucu var mı?
    for c, fam in COUNTRY_FAMILY.items():
        if c in l:
            return fam, f"match by league-country: {c}"

    # 4) FIBA / milli takımlar kontrolü
    if any(k in l for k in ["fiba", "national", "world cup", "olympic"]):
        return "FIBA_NATIONAL", "match by fiba keywords"

    # 5) NCAA / kolej tahmini
    if any(k in l for k in ["ncaa", "college"]):
        return "GENERIC_HIGH", "match by ncaa/college hint"

    # 6) Bulunamadı → default family
    return "GENERIC_MID", "default fallback"
