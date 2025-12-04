# ================================================================
# FAZ-13 ORCHESTRATOR (NEWS + STATS + VISUAL INTEGRATED VERSION)
# ================================================================

import time
import json
import logging

from faz13_engine.faz13_news_scraper import (
    MatchMeta,
    get_match_news,
)

# Burada ileride istatistik, OCR ve varyans motorlarını da aynı şekilde bağlayacağız:
# from faz13_engine.faz13_stats_core import get_stat_features
# from faz13_engine.faz13_visual_core import get_visual_features
# from faz17_engine.faz17_vmap import build_vmap
# from faz23_engine.faz23_stability import calibrate_total, calibrate_spread


log = logging.getLogger(__name__)

# =====================================================================
# 1) Tahmin Çekirdeği – Fusion Brain
# =====================================================================

def fusion_brain(news_features, stat_features=None, visual_features=None):
    """
    NEWS + STATS + VISUAL → tek karara dönüşen bölüm.
    Stat & visual henüz bağlanmadıysa None olabilir.
    """

    score = 0.0
    reasons = []

    # ---------------------------
    # 🟦 NEWS EFFECT
    # ---------------------------
    if news_features.get("news_total_over_flag") == 1:
        score += 0.7
        reasons.append("News: OVER eğilimi yüksek")
    if news_features.get("news_total_under_flag") == 1:
        score -= 0.7
        reasons.append("News: UNDER eğilimi yüksek")

    inj_home = news_features.get("news_inj_impact_home", 0)
    inj_away = news_features.get("news_inj_impact_away", 0)

    if inj_home > 0.2:
        reasons.append("Ev sahibi sakatlık etkisi var (tempo düşebilir)")
        score -= 0.3
    if inj_away > 0.2:
        reasons.append("Deplasman sakatlık etkisi var (tempo düşebilir)")
        score -= 0.3

    if news_features.get("news_pace_high_flag") == 1:
        score += 0.4
        reasons.append("News: Yüksek tempo sinyali")

    if news_features.get("news_pace_low_flag") == 1:
        score -= 0.4
        reasons.append("News: Düşük tempo sinyali")

    # =====================================================================
    # 2) Hibrit SONUÇ
    # =====================================================================
    if score > 0.6:
        total_call = "OVER"
    elif score < -0.6:
        total_call = "UNDER"
    else:
        total_call = "NEUTRAL"

    return {
        "score_vector": score,
        "total_call": total_call,
        "reasons": reasons,
    }


# =====================================================================
# 2) Ana Fonksiyon – “run_faz13_auto_pipeline”
# =====================================================================

def run_faz13_auto_pipeline(
    league: str,
    date: str,
    home_team: str,
    away_team: str,
    full_output: bool = True
):
    """
    SENİN ANA FAZ-13 PIPELINE FONKSİYONUN
    =====================================
    1) Haberleri al (NewsScraper)
    2) İstatistikleri al (ileride bağlanacak)
    3) Görsel analiz (OCR) — bağlanacak
    4) Fusion Brain
    5) Tahmin formatı üret
    """

    # 1) META
    meta = MatchMeta(
        league=league,
        date=date,
        home_team=home_team,
        away_team=away_team,
    )

    # 2) NEWS VERİSİ
    summary, news_features = get_match_news(meta, use_cache=True)

    # 3) İSTATİSTİK + GÖRSEL (henüz bağlı değil)
    stat_features = {}
    visual_features = {}

    # 4) FÜZYON BEYİN
    fused = fusion_brain(
        news_features=news_features,
        stat_features=stat_features,
        visual_features=visual_features,
    )

    # 5) ÇIKTI FORMAT
    output = {
        "match": f"{home_team} vs {away_team}",
        "league": league,
        "date": date,
        "news_summary": summary.soft_score_range,
        "news_total_consensus": summary.total_view.get("consensus"),
        "fusion_total_call": fused["total_call"],
        "internal_score_vector": fused["score_vector"],
        "debug_reasons": fused["reasons"],
        "sources_used": summary.sources_used,
        "confidence": summary.confidence,
    }

    return output
