# -*- coding: utf-8 -*-
"""
FAZ-13 + FAZ-23 Orchestrator

Bu dosya:
- /mac komutundan gelen lig / tarih / takım bilgisini alır
- Basit ama stabil bir total tahmini üretir
- FAZ-13 çekirdeği için: total, band, vector, period skorları, takım skorları, analiz yapısı
- FAZ-23 katmanı için: meta23 blok (model_over / model_under / primary_total / flags)
döndürür.

ÇIKTI FORMATİ, main.py içindeki fmt_faz13_message() ile birebir uyumludur.
"""

import math
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Tuple


# ================================================================
# DATA MODELLERİ (FAZ-13 ÇEKİRDEK)
# ================================================================

@dataclass
class Faz13Input:
    source: str                    # "manual" / "api" / "visual" / "hybrid"
    league: str
    date_str: str
    home: str
    away: str

    prematch_total_hint: Optional[float] = None
    recent_points_avg: Optional[float] = None

    manual_text: Optional[str] = None
    api_data: Optional[Dict[str, Any]] = None
    visual_meta: Optional[Dict[str, Any]] = None
    market_data: Optional[Dict[str, Any]] = None
    profile: Optional[Dict[str, Any]] = None


# ================================================================
# NORMALİZASYON FONKSİYONLARI
# ================================================================

def normalize_manual_text(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = " ".join(text.split())
    lowered = cleaned.lower()
    return {
        "raw": text,
        "cleaned": cleaned,
        "tokens": cleaned.split(),
        "has_overtime": "ot" in lowered or "uzatma" in lowered,
    }


def normalize_api_data(api_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not api_data:
        return None
    out = dict(api_data)
    if "pace" in out:
        try:
            out["pace"] = float(out["pace"])
        except Exception:
            pass

    if "off_rating_home" in out and "off_rating_away" in out:
        try:
            out["off_rating_diff"] = (
                float(out["off_rating_home"]) - float(out["off_rating_away"])
            )
        except Exception:
            pass
    return out


def normalize_visual_meta(visual_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not visual_meta:
        return None
    out = dict(visual_meta)
    # İleride scoreboard / periyot skorları vs. buraya entegre edilir.
    return out


# ================================================================
# LİG / FAMILY / BASELINE YARDIMCILARI
# ================================================================

def _detect_league_family(league: str) -> Tuple[str, float]:
    """
    Lig ismine göre family + kaba baseline çıkarır.
    Burayı istersen takım bazlı / API bazlı hale genişletebiliriz.
    """
    l = (league or "").lower()

    # NBA yüksek tempo
    if "nba" in l:
        return "NBA", 230.0

    # Euroleague / Eurocup
    if "euroleague" in l or "euro league" in l:
        return "EUROLEAGUE", 165.0
    if "eurocup" in l:
        return "EUROCUP", 162.0

    # Türkiye ve benzeri orta tempolu ligler
    if "bsl" in l or "türkiye" in l or "turkey" in l:
        return "EURO_MID", 160.0

    # Milli takım / FIBA tipleri
    if "fiba" in l or "world cup" in l or "eurobasket" in l:
        return "NATIONAL", 162.0

    # Varsayılan: orta tempo
    return "GENERICMID", 165.0


def _split_periods(total: float) -> Tuple[float, float, float, float]:
    """
    Toplam skoru 4 çeyreğe dağıtır.
    NBA / Euro parametrelerini çok bozmadan basit ağırlıklarla böler.
    """
    # hafifçe 2. çeyreği yüksek tutan dağılım
    weights = [0.24, 0.26, 0.25, 0.25]
    q1 = round(total * weights[0], 1)
    q2 = round(total * weights[1], 1)
    q3 = round(total * weights[2], 1)
    q4 = round(total * weights[3], 1)
    return q1, q2, q3, q4


# ================================================================
# ANA TOTAL TAHMİNİ (BASİS)
# ================================================================

def _estimate_total_points(data: Faz13Input) -> float:
    """
    FAZ-13 çekirdeği için ana total tahmini.
    Sıralama:
    1) prematch_total_hint varsa onu merkez al
    2) recent_points_avg varsa league baseline ile harmanla
    3) hiçbir şey yoksa sadece league baseline
    İleride: API-SPORT / balldontlie / ODDS verisi bu fonksiyona eklenecek.
    """
    family, league_baseline = _detect_league_family(data.league)

    total = league_baseline

    # 1) prematch barem ipucu
    if data.prematch_total_hint is not None:
        try:
            hint = float(data.prematch_total_hint)
            total = hint
        except Exception:
            pass

    # 2) Son maç ortalamaları (takım bazlı besleme yeri)
    if data.recent_points_avg is not None:
        try:
            r = float(data.recent_points_avg)
            # league baseline ile son maç ortalamasını harmanla
            total = (league_baseline * 0.5) + (r * 0.5)
        except Exception:
            pass

    # İleride: data.api_data / market_data / profile burada devreye girecek.
    return round(total, 1)


# ================================================================
# FAZ-23 META ÖZETİ (BASİT)
# ================================================================

def _build_faz23_meta(total: float, market_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    FAZ-23 için basit meta:
    - primary_total: mümkünse market çizgisi, yoksa model total
    - model_over / model_under: markete göre eğilim
    Şu an placeholder; ODDS API ve datahub bağlanınca sertleştirilecek.
    """
    main_total = None
    if market_data and "main_total" in market_data:
        try:
            main_total = float(market_data["main_total"])
        except Exception:
            main_total = None

    primary_total = main_total if main_total is not None else float(total)

    if main_total is None:
        model_over = 0.500
        model_under = 0.500
    else:
        diff = float(total) - main_total
        # model total > market total → over eğilimi
        if diff > 3:
            model_over = 0.62
            model_under = 0.38
        elif diff > 1.5:
            model_over = 0.56
            model_under = 0.44
        elif diff < -3:
            model_over = 0.38
            model_under = 0.62
        elif diff < -1.5:
            model_over = 0.44
            model_under = 0.56
        else:
            model_over = 0.50
            model_under = 0.50

    flags: List[str] = []

    if main_total is None:
        flags.append("NO_MARKET_DATA")
    else:
        if abs(float(total) - primary_total) <= 2.0:
            flags.append("SAFEBaseline")
        else:
            flags.append("DRIFT")

    return {
        "primary_total": float(primary_total),
        "model_over": float(model_over),
        "model_under": float(model_under),
        "flags": flags,
    }


# ================================================================
# FAZ-13 ANA PIPELINE (main.py ile UYUMLU)
# ================================================================

def run_faz13_auto_pipeline(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    prematch_total_hint: Optional[float] = None,
    recent_points_avg: Optional[float] = None,
    # İleri kullanım için ekstra parametreler:
    source: str = "manual",
    manual_text: Optional[str] = None,
    api_data: Optional[Dict[str, Any]] = None,
    visual_meta: Optional[Dict[str, Any]] = None,
    market_data: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    **_: Any,  # gelecekte eklenebilecek keyword arg'lar için sigortadır
) -> Dict[str, Any]:
    """
    main.py içinden şu şekilde çağrılır:

        result = run_faz13_auto_pipeline(
            league=league,
            date_str=date_str,
            home=home,
            away=away,
            prematch_total_hint=None,
            recent_points_avg=None,
        )

    Dönen sözlük fmt_faz13_message() fonksiyonu ile birebir uyumlu:
        - total
        - band  (min,max)
        - vector (lo, mid, hi)
        - periods (q1,q2,q3,q4)
        - team_scores (home_pts, away_pts)
        - analysis {...}
        - meta23 {...}
        - live_ctx {...}
        - family
    """

    # INPUT nesnesi
    data = Faz13Input(
        source=source,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        prematch_total_hint=prematch_total_hint,
        recent_points_avg=recent_points_avg,
        manual_text=manual_text,
        api_data=api_data,
        visual_meta=visual_meta,
        market_data=market_data,
        profile=profile,
    )

    # Lig family + league baseline
    family, league_baseline = _detect_league_family(league)

    # Ana total tahmini
    total = _estimate_total_points(data)

    # Dar bant + skor vektörü
    band_delta = 6.0  # ±6 sayı → 12 sayılık bant
    band = (round(total - band_delta, 1), round(total + band_delta, 1))

    vec_lo = round(total - 4.0, 1)
    vec_mid = round(total, 1)
    vec_hi = round(total + 4.0, 1)
    vector = (vec_lo, vec_mid, vec_hi)

    # Periyot skorları
    q1, q2, q3, q4 = _split_periods(total)
    periods = (q1, q2, q3, q4)

    # Takım skor tahmini (basit home-boost)
    home_boost = 2.0
    home_pts = round(total / 2.0 + home_boost, 1)
    away_pts = round(total / 2.0 - home_boost, 1)
    team_scores = (home_pts, away_pts)

    # Analiz bloğu
    match_type = "CLUB"
    l_lower = league.lower()
    if "fiba" in l_lower or "world cup" in l_lower or "eurobasket" in l_lower or "national" in l_lower:
        match_type = "NATIONAL"

    analysis: Dict[str, Any] = {
        "league_baseline": float(league_baseline),
        "tempo_style": "MID",
        "volatility": 0.10,   # şimdilik sabit; ileride varyans motoru gelir
        "def": 0.00,
        "match_type": match_type,
        "news_range": "TOTAL: NEUTRAL",
        "home_boost": float(home_boost),
    }

    # Normalizasyon çıktıları (debug / ileride kullanılacak)
    norm_manual = normalize_manual_text(manual_text)
    norm_api = normalize_api_data(api_data)
    norm_visual = normalize_visual_meta(visual_meta)

    # FAZ-23 meta bloğu
    meta23 = _build_faz23_meta(total, market_data or {})

    # Canlı veri yok → false sabit
    live_ctx = {
        "is_live": False,
        "live_total": None,
        "pace_delta": None,
        "provider": None,
    }

    # ANA SONUÇ (fmt_faz13_message bu yapıyı kullanıyor)
    result: Dict[str, Any] = {
        "family": family,
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "total": float(total),
        "band": band,
        "vector": vector,
        "periods": periods,
        "team_scores": team_scores,
        "analysis": analysis,
        "meta23": meta23,
        "live_ctx": live_ctx,
        "raw": {
            "input": asdict(data),
            "norm_manual": norm_manual,
            "norm_api": norm_api,
            "norm_visual": norm_visual,
        },
    }

    return result


# ================================================================
# FAZ-23 KLASİK EK FONKSİYONLAR (Şimdilik main.py kullanmıyor ama dursun)
# ================================================================

def build_faz23_safe_coupon(faz23_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-23 çıktılarına göre kupon filtresi.
    Şu an sadece örnek politika döndürüyor.
    """
    filter_mode = faz23_result.get("filter_mode")
    alignment = faz23_result.get("market_alignment", 70.0)
    sharpened_conf = faz23_result.get("sharpened_confidence", 70)

    legs: List[Dict[str, Any]] = []

    if filter_mode == "AGGRESSIVE_SAFE" and sharpened_conf >= 80:
        legs.append({
            "market": "Toplam Sayı (dar bant)",
            "pick": "MODEL_BAND",
            "line": "model band ±2",
            "risk_tag": "FAZ23_A",
        })
    elif filter_mode == "ULTRA_CONSERVATIVE":
        legs.append({
            "market": "Toplam Sayı (geniş bant)",
            "pick": "SAFE_ZONE",
            "line": "model band ±10",
            "risk_tag": "FAZ23_SAFE",
        })
    else:
        legs.append({
            "market": "Toplam Sayı",
            "pick": "BASE",
            "line": "model total",
            "risk_tag": "FAZ23_BASE",
        })

    return {"legs": legs}
