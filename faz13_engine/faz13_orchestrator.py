from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .league_autodetect import guess_league
from .faz13_news_scraper import MatchMeta, get_match_news, encode_news_features

log = logging.getLogger(__name__)

# ================================================================
# GLOBAL LİG AİLESİ KONFİGÜRASYONU
# ================================================================

FAMILY_CONFIG: Dict[str, Dict[str, Any]] = {
    # Kuzey Amerika
    "NBA": {
        "base_total": 230.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.12,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
    },
    "WNBA": {
        "base_total": 165.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.10,
        "home_adv": 2.5,
    },
    "GLEAGUE": {
        "base_total": 225.0,
        "q_dist": [0.25, 0.25, 0.25, 0.25],
        "pace_volatility": 0.13,
        "defense_volatility": 0.11,
        "home_adv": 2.5,
    },

    # Avrupa üst seviye
    "EUROLEAGUE": {
        "base_total": 165.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.10,
        "defense_volatility": 0.11,
        "home_adv": 3.5,
    },
    "EUROCUP": {
        "base_total": 162.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.10,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "BCL": {
        "base_total": 159.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },

    # Milli takım / FIBA
    "FIBA_NATIONAL": {
        "base_total": 155.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.09,
        "defense_volatility": 0.11,
        "home_adv": 2.5,
    },

    # Yerel lig aileleri (örnekler)
    "TURKISH_BSL": {
        "base_total": 160.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.5,
    },
    "ACB_SPAIN": {
        "base_total": 162.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "GERMANY_BBL": {
        "base_total": 164.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "FRANCE_PROA": {
        "base_total": 161.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "ITALY_SERIEA": {
        "base_total": 160.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "GREECE_ESAKE": {
        "base_total": 158.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.10,
        "defense_volatility": 0.11,
        "home_adv": 3.5,
    },
    "ABA_ADRIATIC": {
        "base_total": 162.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },

    # Diğer global lig aileleri
    "AUSTRALIA_NBL": {
        "base_total": 171.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
    },
    "JAPAN_BLEAGUE": {
        "base_total": 178.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.12,
        "defense_volatility": 0.10,
        "home_adv": 2.5,
    },
    "KOREA_KBL": {
        "base_total": 176.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.12,
        "defense_volatility": 0.10,
        "home_adv": 2.5,
    },
    "CHINA_CBA": {
        "base_total": 184.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.13,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
    },
    "PHILIPPINES_PBA": {
        "base_total": 182.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.12,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
    },

    # Genel default family
    "GENERIC_HIGH": {
        "base_total": 175.0,
        "q_dist": [0.24, 0.26, 0.25, 0.25],
        "pace_volatility": 0.11,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
    },
    "GENERIC_MID": {
        "base_total": 165.0,
        "q_dist": [0.23, 0.27, 0.25, 0.25],
        "pace_volatility": 0.10,
        "defense_volatility": 0.11,
        "home_adv": 3.0,
    },
    "GENERIC_LOW": {
        "base_total": 155.0,
        "q_dist": [0.22, 0.28, 0.25, 0.25],
        "pace_volatility": 0.09,
        "defense_volatility": 0.12,
        "home_adv": 3.0,
    },
}


def _league_family(league: Any) -> str:
    """
    Lig stringinden global family ismini çıkar.
    Tuple / list / None / vs. hepsi güvenli.
    """
    if not league:
        return "GENERIC_MID"

    if isinstance(league, (tuple, list)):
        league = " ".join(str(x) for x in league if x is not None)

    l = str(league).lower()

    # Kuzey Amerika
    if "wnba" in l:
        return "WNBA"
    if "g-league" in l or "gleague" in l or "g league" in l:
        return "GLEAGUE"
    if "nba" in l:
        return "NBA"

    # Avrupa üst seviye
    if "euroleague" in l or "euro league" in l:
        return "EUROLEAGUE"
    if "eurocup" in l:
        return "EUROCUP"
    if "bcl" in l or "basketball champions league" in l:
        return "BCL"

    # FIBA / milli takımlar
    if "fiba" in l or "eurobasket" in l or "world cup" in l or "olympic" in l:
        return "FIBA_NATIONAL"

    # Yerel ligler
    if "türkiye" in l or "turkey" in l or "bsl" in l or "tbl" in l or "türkiye süper ligi" in l:
        return "TURKISH_BSL"
    if "acb" in l or "endesa" in l or "liga acb" in l:
        return "ACB_SPAIN"
    if "bbl" in l and "germany" in l:
        return "GERMANY_BBL"
    if "pro a" in l or "lnb" in l:
        return "FRANCE_PROA"
    if "lega" in l or "serie a" in l:
        return "ITALY_SERIEA"
    if "esake" in l or "greek" in l:
        return "GREECE_ESAKE"
    if "aba" in l or "adriatic" in l:
        return "ABA_ADRIATIC"

    # Diğer global lig
    if "nbl" in l:
        return "AUSTRALIA_NBL"
    if "b.league" in l or "bleague" in l:
        return "JAPAN_BLEAGUE"
    if "kbl" in l:
        return "KOREA_KBL"
    if "cba" in l:
        return "CHINA_CBA"
    if "pba" in l:
        return "PHILIPPINES_PBA"

    # Skor seviyesi heuristiği
    if any(k in l for k in ["ncaa", "college"]):
        return "GENERIC_HIGH"

    return "GENERIC_MID"


# ================================================================
# Yardımcı fonksiyonlar
# ================================================================


def _safe_float(x: Any) -> Optional[float]:
    """String/number karışık değerleri güvenli şekilde floata çevirmeye çalış."""
    try:
        if isinstance(x, str):
            x = x.replace(",", ".")
        return float(x)
    except Exception:
        return None


def _detect_match_from_text(text: str) -> str:
    """
    Basit eşleşme: 'A - B' veya 'A vs B' yakalamaya çalışır.
    Bulamazsa raw text'in ilk 40 karakterini döner.
    """
    if not text:
        return ""

    t = text.replace("VS", "vs").replace("Vs", "vs")

    for sep in [" - ", "-", " vs ", " vs. "]:
        if sep in t:
            parts = t.split(sep)
            if len(parts) >= 2:
                left = parts[0].strip()
                right = parts[1].strip()
                if left and right:
                    return f"{left} - {right}"

    return text.strip()[:40]


def _baseline_total_for_league(league: Any) -> float:
    """
    Lig tipine göre kaba total baseline.
    AĞIR istatistik yok; sadece lig tipi heuristiği.

    🔥 TUPLE / HER TÜRLÜ INPUT FIX:
    - guess_league tuple döndürse bile burada güvenle işlenir.
    """
    if not league:
        return 200.0

    family = _league_family(league)
    fam_cfg = FAMILY_CONFIG.get(family)
    if fam_cfg:
        return float(fam_cfg.get("base_total", 200.0))

    # Eski fallback mantığı (güvenlik için)
    if isinstance(league, (tuple, list)):
        league = " ".join(str(part) for part in league if part is not None)

    l = str(league).lower()

    if "nba" in l:
        return 230.0
    if "euroleague" in l:
        return 165.0
    if "türkiye" in l or "bsl" in l or "turkey" in l:
        return 160.0
    if "fiba" in l or "world cup" in l or "eurobasket" in l:
        return 155.0

    # default: kulüp ligi gibi davran
    return 170.0


def _national_match_flag(home: str, away: str, league: str) -> bool:
    """Milli takım maçı mı? Çok kaba bayrak."""
    league_l = (league or "").lower()
    if any(k in league_l for k in ["fiba", "eurobasket", "world cup", "olympic"]):
        return True

    # Ülkeler arası maç gibi görünen çok basit durumlar
    def is_country(name: str) -> bool:
        n = name.strip().lower()
        return n in {
            "turkey",
            "türkiye",
            "france",
            "spain",
            "serbia",
            "germany",
            "greece",
            "slovenia",
            "lithuania",
            "latvia",
            "usa",
            "canada",
            "italy",
            "croatia",
            "bosnia",
            "belgium",
            "poland",
            "russia",
        }

    return is_country(home) and is_country(away)

def _compute_team_total_shares(
    home_team: str,
    away_team: str,
    league_family: str,
    nf: Dict[str, Any],
) -> (float, float, List[str]):
    """
    Profesyonel FAZ-23 TEAM STRENGTH modeli (lite versiyon).

    ÇIKTI:
        home_share, away_share, debug_list
    """
    debug: List[str] = []

    home_strength = 1.0
    away_strength = 1.0

    from .faz13_config import FAMILY_CONFIG  # eğer global değilse

    fam_cfg = FAMILY_CONFIG.get(league_family, FAMILY_CONFIG["GENERIC_MID"])
    home_adv_pts = float(fam_cfg.get("home_adv", 3.0))

    ha_boost = home_adv_pts * 0.03
    home_strength += ha_boost
    debug.append(f"Home advantage boost ~ +{ha_boost:.2f}")

    if nf.get("news_spread_home_flag", 0) > 0:
        home_strength += 0.30
        debug.append("Spread: HOME slight favorite (+0.30)")

    if nf.get("news_spread_away_flag", 0) > 0:
        away_strength += 0.30
        debug.append("Spread: AWAY slight favorite (+0.30)")

    inj_h = float(nf.get("news_inj_impact_home", 0.0))
    inj_a = float(nf.get("news_inj_impact_away", 0.0))

    if inj_h > 0:
        d = inj_h * 0.8
        home_strength -= d
        debug.append(f"Injuries hurt HOME: -{d:.2f}")

    if inj_a > 0:
        d = inj_a * 0.8
        away_strength -= d
        debug.append(f"Injuries hurt AWAY: -{d:.2f}")

    fatigue_diff = float(nf.get("news_fatigue_diff", 0.0))

    if fatigue_diff > 0.0:
        d = fatigue_diff * 0.3
        home_strength -= d
        away_strength += d * 0.5
        debug.append(f"Fatigue: HOME more tired (diff={fatigue_diff:.2f})")

    elif fatigue_diff < 0.0:
        d = (-fatigue_diff) * 0.3
        away_strength -= d
        home_strength += d * 0.5
        debug.append(f"Fatigue: AWAY more tired (diff={fatigue_diff:.2f})")

    home_strength = max(0.2, home_strength)
    away_strength = max(0.2, away_strength)

    total = home_strength + away_strength
    if total <= 0:
        return 0.5, 0.5, debug + ["Strength total <= 0 fallback"]

    H = home_strength / total
    A = away_strength / total

    debug.append(
        f"Final strength H:{home_strength:.2f} A:{away_strength:.2f} "
        f"→ shares H:{H:.3f} A:{A:.3f}"
    )

    return H, A, debug
    
# ================================================================
# normalize_manual_text
# ================================================================


def normalize_manual_text(raw: str) -> Dict[str, Any]:
    """
    /mac13 ve /live13 için manuel girilen metni tek şemaya çevirir.

    Örnek argümanlar:
      "BOS ORL 220.5 U 1.46"
      "Fenerbahçe Efes 162.5 ÜST 1.70"
    """
    text = (raw or "").strip()

    fusion: Dict[str, Any] = {
        "engine": "FAZ-13",
        "raw": text,
        "match": "",
        "home_team": "",
        "away_team": "",
        "total": None,
        "pick": None,
        "odds": None,
        "score_low": None,
        "score_high": None,
    }

    if not text:
        return fusion

    parts = text.split()

    if len(parts) >= 2:
        home = parts[0].upper()
        away = parts[1].upper()
        fusion["home_team"] = home
        fusion["away_team"] = away
        fusion["match"] = f"{home} - {away}"

    total = None
    pick = None
    odds = None

    for token in parts[2:]:
        # Total arıyoruz
        val = _safe_float(token)
        if val is not None:
            if total is None:
                total = val
            elif odds is None:
                odds = val
            continue

        up = token.upper()
        if up in {"U", "ALT", "UNDER"} and pick is None:
            pick = "UNDER"
        elif up in {"O", "ÜST", "OVER"} and pick is None:
            pick = "OVER"

    if total is not None:
        fusion["total"] = total
        fusion["score_low"] = total - 6.0
        fusion["score_high"] = total + 6.0

    if pick is not None:
        fusion["pick"] = pick

    if odds is not None:
        fusion["odds"] = odds

    return fusion


# ================================================================
# normalize_visual_meta
# ================================================================


def normalize_visual_meta(ocr_text: str) -> Dict[str, Any]:
    """
    Ultra OCR v3'ten gelen raw metni basit bir fusion şemasına çevirir.
    Burada ağır analiz yok; sadece God Layer'ın okuyacağı alanlar doldurulur.
    """
    text = (ocr_text or "").strip()

    fusion: Dict[str, Any] = {
        "engine": "FAZ-13-VISUAL",
        "raw_text": text,
        "match": "",
        "home_team": "",
        "away_team": "",
        "league": "",
        "debug": [],
    }

    if not text:
        return fusion

    match_str = _detect_match_from_text(text)
    fusion["match"] = match_str

    # Çok kaba: "A - B" formatı bulduysak home/away böl
    if " - " in match_str:
        left, right = match_str.split(" - ", 1)
        fusion["home_team"] = left.strip()
        fusion["away_team"] = right.strip()

    fusion["debug"].append("visual_meta_normalized_v1")
    return fusion


# ================================================================
# normalize_api_data
# ================================================================


def normalize_api_data(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    İleride canlı API (Flashscore, kendi live provider'ların vb.)
    ile birleşmek için hook. Şimdilik pass-through.
    """
    if data is None:
        return {}
    out = dict(data)
    out.setdefault("engine", "FAZ-13-API")
    return out


# ================================================================
# FAZ-23 FUSION TAVSİYE MOTORU
# ================================================================

def _faz23_recommendation(
    base_total: float,
    nf: Dict[str, Any],
    per_period_projection: Dict[str, Any],
    news_summary: Dict[str, Any],
    league_family: str,
) -> Dict[str, Any]:
    """
    FAZ-23 için:
      - Maç total
      - İlk yarı total
      - Çeyrek total
      - Yön (OVER/UNDER/PASS)
      - Confidence
    üretir.
    """
    total_bias = 0.0
    if nf.get("news_total_over_flag"):
        total_bias += 1.0
    if nf.get("news_total_under_flag"):
        total_bias -= 1.0

    pace_bias = 0.0
    if nf.get("news_pace_high_flag"):
        pace_bias += 1.0
    if nf.get("news_pace_low_flag"):
        pace_bias -= 1.0

    # haber confidence
    news_conf = float(nf.get("news_confidence", 0.0))
    if news_conf <= 0:
        # summary içinden confidence varsa onu kullan
        conf = float(news_summary.get("confidence", 0.0)) if isinstance(news_summary, dict) else 0.0
    else:
        conf = news_conf

    # min / max clamp
    if conf <= 0:
        conf = 0.55  # çıplak lig + barem zekâsı
    conf = max(0.5, min(conf, 0.95))

    # final line
    main_line = round(base_total * 2) / 2.0

    if total_bias > 0.25:
        main_dir = "OVER"
    elif total_bias < -0.25:
        main_dir = "UNDER"
    else:
        main_dir = "PASS"

    # yarı / çeyrek çizgileri
    q1 = per_period_projection.get("q1_total")
    q2 = per_period_projection.get("q2_total")
    q3 = per_period_projection.get("q3_total")
    q4 = per_period_projection.get("q4_total")
    h1 = per_period_projection.get("h1_total")
    h2 = per_period_projection.get("h2_total")

    def _mk_ob(total_val: Any) -> Optional[Dict[str, Any]]:
        try:
            v = float(total_val)
        except Exception:
            return None
        return {
            "line": round(v * 2) / 2.0,
            "band": [round(v - 4.0, 1), round(v + 4.0, 1)],
        }

    rec = {
        "engine": "FAZ-23",
        "league_family": league_family,
        "main_total": {
            "line": main_line,
            "direction": main_dir,
            "band": [round(base_total - 8.0, 1), round(base_total + 8.0, 1)],
            "confidence": conf,
        },
        "h1_total": _mk_ob(h1),
        "h2_total": _mk_ob(h2),
        "q1_total": _mk_ob(q1),
        "q2_total": _mk_ob(q2),
        "q3_total": _mk_ob(q3),
        "q4_total": _mk_ob(q4),
        "raw_bias": {
            "total_bias": total_bias,
            "pace_bias": pace_bias,
        },
    }

    return rec


# ================================================================
# run_faz13_auto_pipeline
# ================================================================


def run_faz13_auto_pipeline(
    league: Any,
    date: str,
    home_team: str,
    away_team: str,
    full_output: bool = True,
    match_key: Optional[str] = None,
    meta_hint: Optional[Dict[str, Any]] = None,
    api_data: Optional[Dict[str, Any]] = None,
    visual_meta: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    FAZ-13 ana tahmin pipeline iskeleti + FAZ-23 fusion.

    HEDEF:
    - Lig / tarih / takım bilgisine göre hafif bir tahmin üretmek
    - FAZ-23 için gerekli internal_meta alanlarını doldurmak
    - Haber motorundan gelen sinyalleri base total üzerine bindirmek
    - Periyot / yarı projeksiyon + FAZ-23 tavsiyesi üretmek

    AĞIR MODEL YOK → Fly.io 512 MB free ile uyumlu.
    Esneklik için fazladan gelen tüm keyword argümanlar **kwargs ile
    sessizce yutulur (eski komutlar bozulmasın).
    """
    # kwargs içinden gelebilecek override'lar
    if meta_hint is None:
        meta_hint = kwargs.get("meta_hint")
    if api_data is None:
        api_data = kwargs.get("api_data")
    if visual_meta is None:
        visual_meta = kwargs.get("visual_meta")

    home_team = (home_team or "").strip()
    away_team = (away_team or "").strip()
    date = (date or "").strip()

    # 🔥 LİG INPUT NORMALİZASYONU (tuple fix)
    raw_league = league
    if isinstance(raw_league, (tuple, list)):
        league_hint = " ".join(str(x) for x in raw_league if x is not None)
    else:
        league_hint = (str(raw_league or "")).strip()

    # 1) Lig oto tespit
    detected_league_raw = guess_league(home_team, away_team, league_hint)
    league_detect_reason: Optional[str] = None

    # guess_league bazen tuple döndürebilir: (league_str, açıklama)
    if isinstance(detected_league_raw, tuple):
        if len(detected_league_raw) >= 1:
            detected_league = detected_league_raw[0]
        else:
            detected_league = None
        if len(detected_league_raw) >= 2:
            league_detect_reason = str(detected_league_raw[1])
    else:
        detected_league = detected_league_raw

    final_league = (detected_league or league_hint or "Unknown League")
    league_family = _league_family(final_league)
    fam_cfg = FAMILY_CONFIG.get(league_family, FAMILY_CONFIG["GENERIC_MID"])

    # 2) MatchMeta + haber motoru
    match_meta = MatchMeta(
        league=final_league,
        date=date or "1970-01-01",
        home_team=home_team or "HOME",
        away_team=away_team or "AWAY",
    )

    try:
        news_summary, news_features = get_match_news(match_meta, use_cache=True)
    except Exception as e:
        log.warning("get_match_news hata verdi: %s", e)

        # Haber gelmezse boş summary/features üret
        class Dummy:
            def __init__(self) -> None:
                self.match_key = match_meta.match_key
                self.home_team = match_meta.home_team
                self.away_team = match_meta.away_team
                self.injuries = {}
                self.fatigue = {}
                self.tempo = {}
                self.total_view = {}
                self.spread_view = {}
                self.soft_score_range = {}
                self.flags = []
                self.confidence = 0.0
                self.key_quotes = []
                self.sources_used = []

        news_summary = Dummy()
        news_features = {}

    # 3) Lig baseline + haber bias → base_total
    base = _baseline_total_for_league(final_league)
    nf = news_features or {}

    total_bias = 0.0
    if nf.get("news_total_over_flag"):
        total_bias += 1.0
    if nf.get("news_total_under_flag"):
        total_bias -= 1.0

    pace_bias = 0.0
    if nf.get("news_pace_high_flag"):
        pace_bias += 1.0
    if nf.get("news_pace_low_flag"):
        pace_bias -= 1.0

    # 1 puan bias ≈ 3 sayı etki gibi düşün
    base_total = base + total_bias * 3.0 + pace_bias * 2.0

    # Eğer haber içinde avg_line varsa, hafifçe ona yaklaş
    avg_line = nf.get("news_total_avg_line") or 0.0
    if avg_line > 0:
        base_total = (base_total * 0.6) + (avg_line * 0.4)

    # Skor bandı
    low = base_total - 8.0
    high = base_total + 8.0
    internal_score_vector = [
        round(low, 1),
        round(base_total, 1),
        round(high, 1),
    ]

    # 4) Periyot ve yarı projeksiyonları (family config'ten)
    q_dist = fam_cfg.get("q_dist", [0.24, 0.26, 0.25, 0.25])
    if len(q_dist) != 4:
        q_dist = [0.24, 0.26, 0.25, 0.25]

    q1_total = base_total * q_dist[0]
    q2_total = base_total * q_dist[1]
    q3_total = base_total * q_dist[2]
    q4_total = base_total * q_dist[3]

    h1_total = q1_total + q2_total
    h2_total = q3_total + q4_total

    per_period_projection = {
        "family": league_family,
        "q1_total": round(q1_total, 1),
        "q2_total": round(q2_total, 1),
        "q3_total": round(q3_total, 1),
        "q4_total": round(q4_total, 1),
        "h1_total": round(h1_total, 1),
        "h2_total": round(h2_total, 1),
        "game_total": round(base_total, 1),
    }

    # 5) Fusion total call (insani çıktı)
    # Tek bir "line" üretelim (0.5'e yuvarlanmış)
    line = round(base_total * 2) / 2.0

    if total_bias > 0.25:
        direction = "OVER"
    elif total_bias < -0.25:
        direction = "UNDER"
        # nötr tarafta PASS; FAZ-23 rec içinde tutuluyor
    else:
        direction = "NEUTRAL"

    fusion_total_call = (
        f"{final_league} | {home_team} - {away_team} | "
        f"TOTAL {line:.1f} band ({low:.1f}-{high:.1f}) [{direction}]"
    )

    # 6) News summary + debug
    if hasattr(news_summary, "__dataclass_fields__"):
        ns_dict = asdict(news_summary)  # type: ignore[arg-type]
    else:
        ns_dict = getattr(news_summary, "__dict__", {}) or {}

    total_view = ns_dict.get("total_view") or {}
    tempo_view = ns_dict.get("tempo") or {}
    injuries_view = ns_dict.get("injuries") or {}
    spread_view = ns_dict.get("spread_view") or {}
    soft_range = ns_dict.get("soft_score_range") or {}

    flags = ns_dict.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]

    news_summary_text = (
        f"TOTAL: {total_view.get('consensus', 'NEUTRAL')}, "
        f"tempo: {tempo_view.get('pace_hint', 'MID')}, "
        f"flags: {','.join(flags)}"
    )

    debug_reasons: List[str] = []
    debug_reasons.append(f"League baseline ~ {base:.1f}")
    debug_reasons.append(f"League family ~ {league_family}")

    if league_detect_reason:
        debug_reasons.append(f"League detect: {league_detect_reason}")

    if avg_line:
        debug_reasons.append(f"News avg_line ~ {avg_line:.1f}")
    if nf.get("news_total_over_flag"):
        debug_reasons.append("News consensus: OVER")
    if nf.get("news_total_under_flag"):
        debug_reasons.append("News consensus: UNDER")
    if nf.get("news_pace_high_flag"):
        debug_reasons.append("Tempo: HIGH pace hint")
    if nf.get("news_pace_low_flag"):
        debug_reasons.append("Tempo: LOW pace hint")
    if injuries_view.get("impact_home") or injuries_view.get("impact_away"):
        debug_reasons.append(
            f"Injury impact H:{injuries_view.get('impact_home', 0)} "
            f"A:{injuries_view.get('impact_away', 0)}"
        )
    if soft_range:
        debug_reasons.append(
            f"Soft range from news: {soft_range.get('low')} - "
            f"{soft_range.get('high')}"
        )
    if not debug_reasons:
        debug_reasons.append(
            "No strong news signal; using league baseline only."
        )

    # 7) FAZ-23 için internal_meta
    national_flag = _national_match_flag(home_team, away_team, final_league)

    internal_meta: Dict[str, Any] = {
        "league": final_league,
        "league_family": league_family,
        "date": date,
        "home_team": home_team,
        "away_team": away_team,
        "match": f"{home_team} - {away_team}",
        "match_type": "NATIONAL" if national_flag else "CLUB",
        "stage": "",
        "start_ts": None,
        # FAZ-23 çekirdek parametreler:
        "base_total": float(round(base_total, 1)),
        "tempo_factor": 1.0 + (pace_bias * 0.05),  # hafif çarpan
        "defense_factor": 1.0 - (pace_bias * 0.03),
        "pace_volatility": float(fam_cfg.get("pace_volatility", 0.10)),
        "defense_volatility": float(fam_cfg.get("defense_volatility", 0.10)),
        "home_adv": float(fam_cfg.get("home_adv", 3.0)),
        "h2h_factor": 0.0,
        "hot_shooting_risk": 0.3 if total_bias > 0.25 else 0.1,
        "clutch_factor": 0.0,
        "national_bonus": 0.15 if national_flag else 0.0,
        "schedule_fatigue": float(nf.get("news_fatigue_diff", 0.0)),
        "style_pace": tempo_view.get("pace_hint", "MID"),
        # Haber & features debug
        "news_features": news_features,
        "news_flags": flags,
        "league_detect_reason": league_detect_reason,
        # Periyot projeksiyonu
        "per_period_projection": per_period_projection,
    }

    # 8) FAZ-23 Fusion tavsiyesi
    faz23_rec = _faz23_recommendation(
        base_total=base_total,
        nf=nf,
        per_period_projection=per_period_projection,
        news_summary=ns_dict,
        league_family=league_family,
    )

    result: Dict[str, Any] = {
        "engine": "FAZ-13",
        "league": final_league,
        "league_family": league_family,
        "date": date,
        "match": f"{home_team} - {away_team}",
        "fusion_total_call": fusion_total_call,
        "internal_score_vector": internal_score_vector,
        "per_period_projection": per_period_projection,
        "news_summary": news_summary_text,
        "debug_reasons": debug_reasons,
        "internal_meta": internal_meta,
        "faz23_recommendation": faz23_rec,
    }

    if full_output:
        # İleride istersen buraya daha fazla debug / ham veri ekleyebilirsin.
        result["raw_news_summary"] = ns_dict

    return result


# ================================================================
# Basit kupon fonksiyonları (şimdilik iskelet)
# ================================================================


def faz13_daily_coupon(*args, **kwargs) -> Dict[str, Any]:
    """
    Şimdilik placeholder.
    İleride günün maçlarını alıp run_faz13_auto_pipeline ile
    batch kupon üretebilirsin.
    """
    return {
        "engine": "FAZ-13",
        "status": "NOT_IMPLEMENTED",
        "message": "faz13_daily_coupon iskelet halinde; sadece interface için mevcut.",
    }


def faz13_upcoming_coupon(*args, **kwargs) -> Dict[str, Any]:
    return {
        "engine": "FAZ-13",
        "status": "NOT_IMPLEMENTED",
        "message": "faz13_upcoming_coupon iskelet halinde; sadece interface için mevcut.",
    }


def faz13_league_coupon(*args, **kwargs) -> Dict[str, Any]:
    return {
        "engine": "FAZ-13",
        "status": "NOT_IMPLEMENTED",
        "message": "faz13_league_coupon iskelet halinde; sadece interface için mevcut.",
    }


def faz13_live_coupon(*args, **kwargs) -> Dict[str, Any]:
    return {
        "engine": "FAZ-13",
        "status": "NOT_IMPLEMENTED",
        "message": "faz13_live_coupon iskelet halinde; sadece interface için mevcut.",
    }
