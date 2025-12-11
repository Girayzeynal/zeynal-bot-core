# -*- coding: utf-8 -*-
"""
FAZ-13 Orchestrator (FULL AUTO FETCH)
- Hybrid Baseline Engine
- Live Providers fusion (prematch+live)
- FAZ-23 Meta layer (lightweight)
Bu dosya, /mac komutu çağrıldığında PREMATCH ise prematch; LIVE ise live shift uygular.
Mevcut main.py tarafı result sözlüğündeki alanları kullanarak text üretir.
"""

from __future__ import annotations
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Mevcut projede var: live_providers.core.get_live_match_global
# (Yoksa try/except içinde sessiz düşer ve sadece prematch çalışır)
try:
    from live_providers.core import get_live_match_global, HoopbrainLiveError
except Exception:  # noqa: BLE001
    get_live_match_global, HoopbrainLiveError = None, Exception  # type: ignore


# =========================
#   HYBRID FAMILY CONFIG
# =========================
@dataclass
class FamilyCfg:
    base: float          # çekirdek baseline
    pace_vol: float      # temponun baseline'a etkisi (0.0-1.0)
    live_gain: float     # canlı verinin ağırlığı (0.0-1.0)
    prematch_gain: float # prematch verinin ağırlığı (0.0-1.0)
    ha_boost: float      # home advantage toplam puan katkısı (pozitif ufak)
    def_factor: float    # defensif sapmalar için sönüm

FAMILIES: Dict[str, FamilyCfg] = {
    # Büyük ligler
    "NBA":          FamilyCfg(base=230.0, pace_vol=0.60, live_gain=0.70, prematch_gain=0.30, ha_boost=0.09, def_factor=0.11),
    "EUROLEAGUE":   FamilyCfg(base=162.0, pace_vol=0.35, live_gain=0.60, prematch_gain=0.40, ha_boost=0.08, def_factor=0.12),
    "EUROCUP":      FamilyCfg(base=162.0, pace_vol=0.35, live_gain=0.55, prematch_gain=0.45, ha_boost=0.09, def_factor=0.12),
    "TURKISHBSL":   FamilyCfg(base=160.0, pace_vol=0.35, live_gain=0.55, prematch_gain=0.45, ha_boost=0.10, def_factor=0.11),
    "JAPANBLEAGUE": FamilyCfg(base=178.0, pace_vol=0.45, live_gain=0.55, prematch_gain=0.45, ha_boost=0.07, def_factor=0.10),

    # Generikler
    "GENERICMID":   FamilyCfg(base=165.0, pace_vol=0.32, live_gain=0.50, prematch_gain=0.50, ha_boost=0.09, def_factor=0.11),
    "GENERICHIGH":  FamilyCfg(base=172.0, pace_vol=0.35, live_gain=0.50, prematch_gain=0.50, ha_boost=0.09, def_factor=0.11),
}

# Lig -> family eşleme (case-insensitive contains)
FAMILY_HINTS: Tuple[Tuple[str, str], ...] = (
    ("nba", "NBA"),
    ("euroleague", "EUROLEAGUE"),
    ("eurocup", "EUROCUP"),
    ("türkiye", "TURKISHBSL"),
    ("turkishbsl", "TURKISHBSL"),
    ("bsl", "TURKISHBSL"),
    ("japan", "JAPANBLEAGUE"),
    ("b1", "JAPANBLEAGUE"),
    ("proa", "GENERICMID"),
    ("france", "GENERICMID"),
    ("ncaa", "GENERICHIGH"),
    ("college", "GENERICHIGH"),
)

def detect_family(league: str) -> str:
    key = (league or "").strip().lower()
    for needle, fam in FAMILY_HINTS:
        if needle in key:
            return fam
    # bilinmiyorsa orta seviye
    return "GENERICMID"


# =========================
#   HYBRID BASELINE
# =========================
def hybrid_baseline(fam: FamilyCfg,
                    prematch_total: Optional[float],
                    recent_avg: Optional[float],
                    live_total_line: Optional[float],
                    live_pace_delta: Optional[float]) -> float:
    """
    Farklı kaynakları karıştırıp tek TOTAL çıkarır.
    Öncelik: canlı veri (varsa) → prematch → family base.
    """
    # 1) çekirdek
    x = fam.base

    # 2) prematch çizgi (kitapçı total) varsa karıştır
    if prematch_total:
        x = fam.prematch_gain * float(prematch_total) + (1.0 - fam.prematch_gain) * x

    # 3) kısa dönem ortalama (isteğe bağlı)
    if recent_avg:
        x = 0.50 * float(recent_avg) + 0.50 * x

    # 4) canlı toplam çizgi (en güçlü sinyal)
    if live_total_line:
        x = fam.live_gain * float(live_total_line) + (1.0 - fam.live_gain) * x

    # 5) tempo sapması → baseline kaydır
    if live_pace_delta:
        x += fam.pace_vol * float(live_pace_delta)

    return round(x, 1)


# =========================
#   LIVE PROVIDERS FUSION
# =========================
@dataclass
class LiveCtx:
    is_live: bool
    live_total: Optional[float]
    pace_delta: Optional[float]          # beklenenden +/- hız
    period_points: Optional[Tuple[float, float, float, float]]
    score_home: Optional[int]
    score_away: Optional[int]
    provider: Optional[str]
    ts: float

def fetch_live_ctx(league: str, home: str, away: str) -> LiveCtx:
    if not get_live_match_global:
        return LiveCtx(False, None, None, None, None, None, None, time.time())

    try:
        data = get_live_match_global(league=league, home=home, away=away)  # proje içi API
        # Beklenen minimal alanlar: is_live, total_line, pace_delta, q1..q4, score_h, score_a, provider
        return LiveCtx(
            is_live=bool(data.get("is_live")),
            live_total=float(data["total_line"]) if data.get("total_line") else None,
            pace_delta=float(data["pace_delta"]) if data.get("pace_delta") else None,
            period_points=tuple(data["period_points"]) if data.get("period_points") else None,  # type: ignore[arg-type]
            score_home=int(data["score_home"]) if data.get("score_home") else None,
            score_away=int(data["score_away"]) if data.get("score_away") else None,
            provider=data.get("provider"),
            ts=time.time(),
        )
    except Exception:
        return LiveCtx(False, None, None, None, None, None, None, time.time())


# =========================
#   PREMISE HELPERS
# =========================
def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def clamp_band(x: float, width: float = 16.0) -> Tuple[float, float]:
    lo = round(x - width/2.0, 1)
    hi = round(x + width/2.0, 1)
    return lo, hi

def score_vector(x: float) -> Tuple[float, float, float]:
    lo, hi = clamp_band(x, 16.0)
    mid = round((lo + hi) / 2.0, 1)
    return (lo, mid, hi)


# =========================
#   PUBLIC ENTRYPOINT
# =========================
def run_faz13_auto_pipeline(
    league: str,
    date_str: str,
    home: str,
    away: str,
    prematch_total_hint: Optional[float] = None,
    recent_points_avg: Optional[float] = None,
) -> Dict:
    """
    main.py -> /mac komutu burayı çağırır.
    Dönen dict mevcut metin üreticisi ile %100 uyumludur.
    """
    family_name = detect_family(league)
    fam = FAMILIES[family_name]

    # 1) canlı bağlamı çek
    live = fetch_live_ctx(league=league, home=home, away=away)

    # 2) hybrid total
    total = hybrid_baseline(
        fam=fam,
        prematch_total=prematch_total_hint,
        recent_avg=recent_points_avg,
        live_total_line=live.live_total,
        live_pace_delta=live.pace_delta,
    )

    # 3) band + vektör
    lo, hi = clamp_band(total, 16.0)
    vec = score_vector(total)

    # 4) period projeksiyonu (basit dağıtım)
    q1 = round(total * 0.24, 1)
    q2 = round(total * 0.26, 1)
    q3 = round(total * 0.25, 1)
    q4 = round(total * 0.25, 1)

    # 5) takım skor (naif pay)
    home_share = 0.522  # hafif ev sahibi
    home_pts = round(total * home_share, 1)
    away_pts = round(total - home_pts, 1)

    # 6) FAZ-23 META (çok hafif)
    over_score = 0.5
    under_score = 0.5
    flags = ["SAFEBASELINE"]

    if live.is_live:
        flags.append("LIVE")
        # canlı çizgi total'den belirgin farklıysa eğilim ver
        if live.live_total and abs(live.live_total - total) >= 6:
            if live.live_total > total:
                over_score = 0.58
                under_score = 0.42
            else:
                over_score = 0.42
                under_score = 0.58

    meta23 = {
        "model_over": round(over_score, 3),
        "model_under": round(under_score, 3),
        "primary_total": total,
        "flags": flags,
    }

    # 7) Analiz metni için hızlı özet
    analysis = {
        "league_baseline": fam.base,
        "tempo_style": "MID",
        "volatility": fam.pace_vol,
        "def": fam.def_factor,
        "match_type": "CLUB",
        "news_range": "TOTAL: NEUTRAL",
        "home_boost": fam.ha_boost,
        "family": family_name,
        "live_provider": live.provider,
        "is_live": live.is_live,
    }

    # 8) Donen sözlük (mevcut şablon alanları)
    return {
        "family": family_name,
        "total": total,
        "band": (lo, hi),
        "vector": vec,
        "periods": (q1, q2, q3, q4),
        "team_scores": (home_pts, away_pts),
        "analysis": analysis,
        "meta23": meta23,
        "live_ctx": {
            "is_live": live.is_live,
            "live_total": live.live_total,
            "pace_delta": live.pace_delta,
            "score_h": live.score_home,
            "score_a": live.score_away,
            "provider": live.provider,
        },
        "debug": {
            "prematch_total_hint": prematch_total_hint,
            "recent_points_avg": recent_points_avg,
        },
    }


# =========================
#   LEGACY NORMALIZERS
# =========================
# Mevcut kod geri uyumluluk için bu adlar ile import ediyorsa kırılmasın.
def normalize_manual_text(x):  # noqa: D401
    """Gerilik uyum: no-op."""
    return x

def normalize_api_data(x):  # noqa: D401
    """Gerilik uyum: no-op."""
    return x

def normalize_visual_meta(x):  # noqa: D401
    """Gerilik uyum: no-op."""
    return x
