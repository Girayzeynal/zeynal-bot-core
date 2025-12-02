import json
import math
from typing import Dict, Any, Optional

# ================================================================
# 🔥 FAZ-23 CORE IDEA
# ================================================================
# Prematch + Live
# Multi-data + News Fusion
# Pure logical prediction ∼ FAZ-23 META STACK
# ================================================================


def _safe(v, d=None):
    return v if v is not None else d


# ================================================================
# 🧠 NEWS ENRICHER (opsiyonel)
# ================================================================
def faz23_news_enrich(ctx: Dict[str, Any], mode: str = "prematch") -> Dict[str, Any]:
    """
    Haber, sakatlık, form durumu, takım içi olaylar gibi
    ek verileri bağlamak için placeholder.
    Şimdilik 'news_score' üretir.
    """
    enriched = dict(ctx)

    # Eğer ctx içinde team_news / injuries gibi alanlar varsa skor yükselir
    news_raw = ctx.get("news", "")

    news_score = 0.0

    if isinstance(news_raw, str):
        low = news_raw.lower()
        if "injury" in low or "sakat" in low:
            news_score -= 0.15
        if "form" in low or "streak" in low:
            news_score += 0.10
        if "hot" in low or "winning" in low:
            news_score += 0.20

    enriched["news_score"] = news_score
    return enriched


# ================================================================
# 🎯 PREMATCH PREDICT
# ================================================================
def faz23_prematch_predict(ctx: Dict[str, Any]) -> str:
    """
    FAZ-23 PREMATCH tahmin motoru
    ctx = multi-data fused (teams, odds, totals, pace, injuries, news...)
    """

    home = ctx.get("home", "HOME")
    away = ctx.get("away", "AWAY")
    league = ctx.get("league", "Unknown League")

    total_line = _safe(ctx.get("total_line"), 0)
    avg_pts = _safe(ctx.get("avg_total"), 0)
    pace = _safe(ctx.get("pace"), 0)

    news_score = _safe(ctx.get("news_score"), 0)

    # Basit FAZ-23 skor
    expected_total = (avg_pts * 0.55) + (pace * 0.25) + (total_line * 0.20)

    expected_total += news_score * 10

    # Range
    low = expected_total - 4
    high = expected_total + 4

    return (
        f"🎯 <b>FAZ-23 META ENGINE PREMATCH</b>\n"
        f"🏀 {home} vs {away} ({league})\n\n"
        f"📌 Beklenen toplam skor aralığı:\n"
        f"<b>{low:.1f} – {high:.1f}</b>\n\n"
        f"🧩 (avg={avg_pts}, pace={pace}, line={total_line}, news={news_score})"
    )


# ================================================================
# 🎯 LIVE PREDICT
# ================================================================
def faz23_live_predict(ctx: Dict[str, Any]) -> str:
    """
    FAZ-23 LIVE tahmin motoru
    ctx = canlı skor, pace, momentum, quarter pace, foul rate, rotation info...
    """

    home = ctx.get("home", "HOME")
    away = ctx.get("away", "AWAY")

    current_total = _safe(ctx.get("current_total"), 0)
    live_pace = _safe(ctx.get("live_pace"), 0)
    fouls = _safe(ctx.get("fouls"), 0)
    qt = _safe(ctx.get("quarter"), 1)

    news_score = _safe(ctx.get("news_score"), 0)

    # FAZ-23 LIVE score engine
    projection = current_total + (live_pace * (5 - qt)) * 2.1

    projection += news_score * 8
    projection -= fouls * 0.2

    low = projection - 3
    high = projection + 3

    return (
        f"🔥 <b>FAZ-23 LIVE META ENGINE</b>\n"
        f"{home} vs {away}\n\n"
        f"📌 Tahmini bitiş aralığı:\n"
        f"<b>{low:.1f} – {high:.1f}</b>\n\n"
        f"🎛 live_pace={live_pace}, fouls={fouls}, quarter={qt}, news={news_score}"
    )
