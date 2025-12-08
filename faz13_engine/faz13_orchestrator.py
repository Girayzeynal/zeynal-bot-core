from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .league_autodetect import guess_league
from .faz13_news_scraper import MatchMeta, get_match_news, encode_news_features

log = logging.getLogger(__name__)

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

    # tuple / list / diğer tipler → stringe indir
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
    FAZ-13 ana tahmin pipeline iskeleti.

    HEDEF:
    - Lig / tarih / takım bilgisine göre hafif bir tahmin üretmek
    - FAZ-23 için gerekli internal_meta alanlarını doldurmak
    - Haber motorundan gelen sinyalleri base total üzerine bindirmek

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

    # 4) Fusion total call (insani çıktı)
    # Tek bir "line" üretelim (0.5'e yuvarlanmış)
    line = round(base_total * 2) / 2.0

    if total_bias > 0.25:
        direction = "OVER"
    elif total_bias < -0.25:
        direction = "UNDER"
    else:
        direction = "NEUTRAL"

    fusion_total_call = (
        f"{final_league} | {home_team} - {away_team} | "
        f"TOTAL {line:.1f} band ({low:.1f}-{high:.1f}) [{direction}]"
    )

    # 5) News summary + debug
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

    # 6) FAZ-23 için internal_meta
    national_flag = _national_match_flag(home_team, away_team, final_league)

    internal_meta: Dict[str, Any] = {
        "league": final_league,
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
        "pace_volatility": 0.10,
        "defense_volatility": 0.10,
        "home_adv": 3.0,
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
    }

    result: Dict[str, Any] = {
        "engine": "FAZ-13",
        "league": final_league,
        "date": date,
        "match": f"{home_team} - {away_team}",
        "fusion_total_call": fusion_total_call,
        "internal_score_vector": internal_score_vector,
        "news_summary": news_summary_text,
        "debug_reasons": debug_reasons,
        "internal_meta": internal_meta,
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
