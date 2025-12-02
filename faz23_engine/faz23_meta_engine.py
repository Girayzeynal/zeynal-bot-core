import math
from typing import Dict, Any, Tuple

# ================================================================
# FAZ-23 META ENGINE CORE
# ================================================================

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


# ------------------------------------------------
# 🔹 PREMATCH META ENGINE
# ------------------------------------------------
def faz23_prematch_meta(match_key: str, fusion: Dict[str, Any]) -> Dict[str, Any]:
    """
    fusion: live_providers.core.get_live_match_global(match_key) çıktısı.
    Beklenen ana alanlar:
      fusion["prematch_avg_total"]
      fusion["prematch_market_total"]
      fusion["prematch_pace_index"]
      fusion["prematch_news_bias"]
    Boş ise hepsini 0 kabul edip -4 / +4 aralığı döner.
    """

    avg = _safe_float(fusion.get("prematch_avg_total"), 0.0)
    line = _safe_float(fusion.get("prematch_market_total"), 0.0)
    pace = _safe_float(fusion.get("prematch_pace_index"), 0.0)
    news = _safe_float(fusion.get("prematch_news_bias"), 0.0)

    # Hiç veri yoksa (şu an gördüğün durum)
    if avg == 0 and line == 0 and pace == 0 and news == 0:
        return {
            "match_key": match_key,
            "mode": "PREMATCH",
            "low": -4.0,
            "high": 4.0,
            "center": 0.0,
            "avg": 0.0,
            "pace": 0.0,
            "line": 0.0,
            "news": 0.0,
            "regime": "NO_DATA",
            "stability": 0.0,
        }

    # ------------------------------------------------------------------
    # Basit META formül:
    #   base = (avg + line) / 2
    #   pace faktörü, haber bias'ı ile oynanmış
    # ------------------------------------------------------------------
    base = 0.0
    cnt = 0
    if avg > 0:
        base += avg
        cnt += 1
    if line > 0:
        base += line
        cnt += 1
    if cnt == 0:
        base = 150.0  # wild fallback
    else:
        base /= cnt

    # pace 0-2 arası normalize
    pace_norm = _clamp(pace, 0.6, 1.6)
    news_norm = _clamp(news, -1.0, 1.0)

    center = base * pace_norm + news_norm * 2.5

    # yayılımı belirleyelim (spread)
    spread = 8.0
    if pace_norm > 1.2:
        spread += 2.0
    if abs(news_norm) > 0.3:
        spread += 1.5

    low = center - spread
    high = center + spread

    # regime & stability heuristik
    regime = "NORMAL"
    stability = 1.0
    if abs(news_norm) > 0.7:
        regime = "NEWS_DRIVEN"
        stability -= 0.2
    if pace_norm > 1.4:
        regime = "FAST"
        stability -= 0.1

    stability = _clamp(stability, 0.2, 1.0)

    return {
        "match_key": match_key,
        "mode": "PREMATCH",
        "low": round(low, 1),
        "high": round(high, 1),
        "center": round(center, 1),
        "avg": round(avg, 1),
        "pace": round(pace, 3),
        "line": round(line, 1),
        "news": round(news, 3),
        "regime": regime,
        "stability": stability,
    }


def format_faz23_prematch(result: Dict[str, Any]) -> str:
    low = result["low"]
    high = result["high"]
    center = result["center"]
    avg = result["avg"]
    pace = result["pace"]
    line = result["line"]
    news = result["news"]
    regime = result["regime"]
    stability = result["stability"]

    mk = result.get("match_key", "")

    if result["regime"] == "NO_DATA":
        note = "⚠️ Veri kaynağı bulunamadı; FAZ-23 şimdilik boş çekirdekle çalıştı."
    else:
        note = (
            "Not: Bu skor aralığı FAZ-23 NEWS + MULTI-DATA çekirdeği "
            "ile hesaplanmış META tahmindir."
        )

    txt = (
        f"🎯 FAZ-23 META ENGINE PREMATCH\n"
        f"🏀 {mk or 'HOME vs AWAY'}\n\n"
        f"📌 Beklenen toplam skor aralığı:\n"
        f"{low:.1f} ➡️ {high:.1f}  (merkez ≈ {center:.1f})\n\n"
        f"🧩 Çekirdek parametreler:\n"
        f"• avg_total: {avg:.1f}\n"
        f"• market_line: {line:.1f}\n"
        f"• pace_index: {pace:.3f}\n"
        f"• news_bias: {news:.3f}\n\n"
        f"⚙️ Regime: {regime} | stability={stability:.3f}\n\n"
        f"{note}"
    )
    return txt


# ------------------------------------------------
# 🔹 LIVE META ENGINE
# ------------------------------------------------
def faz23_live_meta(match_key: str, fusion: Dict[str, Any]) -> Dict[str, Any]:
    """
    Beklenen alanlar:
      fusion["prematch_center_guess"]
      fusion["live_score_home"]
      fusion["live_score_away"]
      fusion["live_quarter"]
      fusion["live_seconds_elapsed"]
      fusion["live_pace_index"]
      fusion["live_fouls_factor"]
      fusion["live_news_bias"]
    """
    # Prematch merkez tahmin; yoksa 160 gibi bir şey varsay.
    pre_center = _safe_float(
        fusion.get("prematch_center_guess", fusion.get("prematch_market_total", 160.0)),
        160.0,
    )

    h = _safe_float(fusion.get("live_score_home"), 0.0)
    a = _safe_float(fusion.get("live_score_away"), 0.0)
    live_total = h + a

    quarter = int(fusion.get("live_quarter") or 1)
    sec = int(fusion.get("live_seconds_elapsed") or 0)
    pace = _safe_float(fusion.get("live_pace_index"), 1.0)
    fouls = _safe_float(fusion.get("live_fouls_factor"), 0.0)
    news = _safe_float(fusion.get("live_news_bias"), 0.0)

    # Maçın toplam süresini 40dk (FIBA) / 48dk (NBA) → 45dk ortalama gibi düşün.
    total_seconds = 45 * 60
    ratio = _clamp(sec / total_seconds, 0.05, 0.99) if total_seconds > 0 else 0.5

    # Basit live projection:
    if live_total == 0:
        proj = pre_center
    else:
        proj = live_total / ratio

    # pace, faul, news ile oynayalım
    pace_norm = _clamp(pace, 0.6, 1.6)
    fouls_norm = _clamp(fouls, -1.0, 1.0)
    news_norm = _clamp(news, -1.0, 1.0)

    proj *= pace_norm
    proj += fouls_norm * 3.0
    proj += news_norm * 2.0

    spread = 7.0
    if quarter >= 3:
        spread -= 1.0
    if abs(fouls_norm) > 0.5:
        spread += 1.5

    low = proj - spread
    high = proj + spread

    regime = "LIVE_NORMAL"
    stability = 1.0
    if ratio < 0.15:
        regime = "VERY_EARLY"
        stability = 0.4
    elif ratio < 0.3:
        regime = "EARLY"
        stability = 0.6
    elif ratio > 0.8:
        regime = "ENDGAME"
        stability = 0.9

    stability = _clamp(stability, 0.2, 1.0)

    return {
        "match_key": match_key,
        "mode": "LIVE",
        "low": round(low, 1),
        "high": round(high, 1),
        "center": round(proj, 1),
        "live_total": live_total,
        "quarter": quarter,
        "seconds": sec,
        "pace": round(pace, 3),
        "fouls": round(fouls, 3),
        "news": round(news, 3),
        "regime": regime,
        "stability": stability,
    }


def format_faz23_live(result: Dict[str, Any]) -> str:
    mk = result.get("match_key", "")
    low = result["low"]
    high = result["high"]
    center = result["center"]
    live_total = result["live_total"]
    quarter = result["quarter"]
    sec = result["seconds"]
    pace = result["pace"]
    fouls = result["fouls"]
    news = result["news"]
    regime = result["regime"]
    stability = result["stability"]

    txt = (
        f"🔥 FAZ-23 LIVE META ENGINE\n"
        f"🏀 {mk or 'HOME vs AWAY'}\n\n"
        f"📌 Tahmini bitiş aralığı:\n"
        f"{low:.1f} – {high:.1f}  (proj ≈ {center:.1f})\n\n"
        f"📊 Anlık durum:\n"
        f"• live_total: {live_total:.1f}\n"
        f"• quarter: {quarter} | elapsed_sec: {sec}\n"
        f"• live_pace: {pace:.3f} | fouls_factor: {fouls:.3f} | news_bias: {news:.3f}\n\n"
        f"⚙️ Regime: {regime} | stability={stability:.3f}\n\n"
        f"Not: Bu çıkış FAZ-23 prematch çekirdeği + canlı tempo/foül/news "
        f"parametreleri ile üretilmiş LIVE META tahmindir."
    )
    return txt
