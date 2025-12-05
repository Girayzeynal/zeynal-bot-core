# ================================================================
# FAZ-13 ORCHESTRATOR
# NEWS-SCRAPER + (OPSİYONEL) LIVE PROVIDER KÖPRÜSÜ
# ================================================================

import logging
from typing import Any, Dict, Optional

from faz13_engine.faz13_news_scraper import (
    MatchMeta,
    get_match_news,
)

log = logging.getLogger(__name__)

# ------------------------------------------------
# OPSİYONEL: Proxy üzerinden gelen FAZ-23 ham verisi
# ------------------------------------------------
try:  # live_providers yoksa sistem ÇÖKMEYECEK, sadece uyarı loglar.
    from live_providers.core import get_live_match_global
except Exception:  # pragma: no cover
    get_live_match_global = None  # type: ignore
    log.info("live_providers.core bulunamadı, FAZ-13 sadece NEWS modunda çalışacak.")


# =====================================================================
# 1) Tahmin Çekirdeği – Fusion Brain
# =====================================================================

def fusion_brain(
    news_features: Dict[str, Any],
    provider_features: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    NEWS (+ opsiyonel live/proxy verisi) → tek karara dönüşen bölüm.

    Şu an skor vektörü ağırlıklı olarak NEWS üzerinden gidiyor.
    provider_features ileride FAZ-23 ile daha ağır basacak şekilde
    genişletilebilir.
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

    inj_home = news_features.get("news_inj_impact_home", 0.0)
    inj_away = news_features.get("news_inj_impact_away", 0.0)

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

    # ---------------------------
    # 🟥 PROVIDER (FAZ-23) EFFECT  — hafif dokunuş
    # ---------------------------
    if provider_features:
        # pre-match market total üzerinden minik bir bias
        market_total = provider_features.get("prematch_market_total", 0.0)
        center_guess = provider_features.get("prematch_center_guess", 0.0)
        pace_index = provider_features.get("live_pace_index", 1.0)

        # sadece çok kabaca, skorun büyüklüğüne göre mood
        if market_total and market_total >= 230:
            score += 0.2
            reasons.append("FAZ-23: Çok yüksek barem → tempo yukarı işareti")

        if market_total and market_total <= 165:
            score -= 0.2
            reasons.append("FAZ-23: Çok düşük barem → tempo aşağı işareti")

        if center_guess and pace_index > 1.02:
            score += 0.1
            reasons.append("FAZ-23: Center guess + yüksek pace → OVER tarafına hafif itme")

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
    full_output: bool = True,
    match_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SENİN ANA FAZ-13 PIPELINE FONKSİYONUN
    =====================================
    1) Haberleri al (NewsScraper)
    2) (Opsiyonel) Proxy'den FAZ-23 fusion verisini çek
    3) Fusion Brain
    4) Tahmin formatı üret

    NOT:
    - main.py eskisi gibi sadece ilk 4 parametreyi gönderiyorsa
      hiçbir şey bozulmaz; match_key None olduğu için
      live_providers tarafı devreye girmez.
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

    # 3) OPSİYONEL: FAZ-23 / live_providers fusion verisi
    provider_features: Optional[Dict[str, Any]] = None
    if match_key and get_live_match_global is not None:
        try:
            provider_features = get_live_match_global(match_key)
        except Exception as e:  # herhangi bir live/proxy hatası sistemi düşürmesin
            log.warning("get_live_match_global hata aldı (%s): %s", match_key, e)
            provider_features = None

    # 4) FÜZYON BEYİN
    fused = fusion_brain(
        news_features=news_features,
        provider_features=provider_features,
    )

    # 5) ÇIKTI FORMAT
    output: Dict[str, Any] = {
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

    # Debug & geniş info sadece full_output True ise
    if full_output:
        output["news_features"] = news_features
        if provider_features is not None:
            output["provider_features"] = provider_features

    return output
