import os
import json
import logging
from typing import Any, Dict, List

log = logging.getLogger("faz23_meta")

# ================================================================
#  FAZ-23 META ENGINE
#  - Prematch & live tahmin motoru
#  - Girdi: faz23_build_context() tarafından hazırlanmış ctx dict'i
#  - Çıktı: Telegram'a direkt basılabilecek açıklama string'i
# ================================================================

FAZ23_DIR = os.getenv("FAZ23_DIR", "/data/faz23")
os.makedirs(FAZ23_DIR, exist_ok=True)

FAZ23_HISTORY_FILE = os.path.join(FAZ23_DIR, "faz23_history.jsonl")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(str(v).replace(",", "."))
    except Exception:
        return default


def _append_history(record: Dict[str, Any]) -> None:
    """Basit JSONL log. Hata verirse sessizce devam et."""
    try:
        with open(FAZ23_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("[FAZ-23] history yazılamadı: %s", e)


# ================================================================
#  NEWS ENRICH
# ================================================================
def faz23_news_enrich(ctx: Dict[str, Any], mode: str = "prematch") -> Dict[str, Any]:
    """
    Haber / sakatlık / yorum sinyallerini tek özet alanında toplar.
    live_providers.core içeriğine göre esnek çalışır.
    Beklenen olası alanlar:
      - ctx["news_items"]: List[{"title","impact","source"}]
      - ctx["injuries"]:  List[{"player","team","impact"}]
    """
    news_items: List[str] = []

    for item in ctx.get("news_items", []) or []:
        title = str(item.get("title", "")).strip()
        impact = str(item.get("impact", "")).strip()
        src = str(item.get("source", "")).strip()
        if not title:
            continue
        line = f"{title}"
        if impact:
            line += f" (impact: {impact})"
        if src:
            line += f" [{src}]"
        news_items.append(line)

    for inj in ctx.get("injuries", []) or []:
        player = inj.get("player") or inj.get("name")
        team = inj.get("team") or inj.get("club")
        impact = inj.get("impact") or inj.get("status")
        if not player:
            continue
        line = f"Sakatlık: {player}"
        if team:
            line += f" ({team})"
        if impact:
            line += f" → {impact}"
        news_items.append(line)

    if news_items:
        ctx["news_summary"] = news_items[:10]
    else:
        ctx.setdefault("news_summary", [])

    ctx.setdefault("news_mode", mode.upper())
    return ctx


# ================================================================
#  CORE SCORING HELPERS
# ================================================================
def _build_match_header(ctx: Dict[str, Any]) -> Dict[str, str]:
    league = str(
        ctx.get("league")
        or ctx.get("competition_name")
        or ctx.get("tournament")
        or "Bilinmeyen Lig"
    )

    date = str(
        ctx.get("date")
        or ctx.get("start_time")
        or ctx.get("tipoff")
        or ctx.get("match_date")
        or "Tarih bilinmiyor"
    )

    home = (
        ctx.get("home_name")
        or ctx.get("home_team")
        or (ctx.get("teams") or {}).get("home")
        or "Ev Sahibi"
    )
    away = (
        ctx.get("away_name")
        or ctx.get("away_team")
        or (ctx.get("teams") or {}).get("away")
        or "Deplasman"
    )

    return {
        "league": str(league),
        "date": str(date),
        "home": str(home),
        "away": str(away),
    }


def _decide_total_side(ctx: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """
    Basit pace + verimlilik tahmini.
    live_providers.core ne getirirse onun üzerinden esnek çalışır.

    Beklenen olası alanlar:
      - ctx["lines"]["total"]  veya ctx["markets"]["total"]["line"]
      - ctx["stats"]["pace"], ctx["stats"]["off_rating"], ctx["stats"]["def_rating"]
      - LIVE modda: ctx["score_home"], ctx["score_away"], ctx["quarter"], ctx["time_left"]
    """
    lines = ctx.get("lines") or ctx.get("markets") or {}
    total_line = None

    if isinstance(lines, dict):
        if "total" in lines and isinstance(lines["total"], dict):
            total_line = lines["total"].get("line") or lines["total"].get("handicap")
        elif "total" in lines:
            total_line = lines.get("total")

    if total_line is None and isinstance(lines, dict):
        # başka anahtar isimleri dene
        for key in ["game_total", "ou_main", "totals"]:
            if key in lines:
                val = lines[key]
                if isinstance(val, dict):
                    total_line = val.get("line") or val.get("handicap")
                else:
                    total_line = val
                break

    total_line_f = _safe_float(total_line, 0.0)

    stats = ctx.get("stats") or {}
    pace = _safe_float(stats.get("pace") or stats.get("pace_estimate"), 95.0)
    off = _safe_float(stats.get("off_rating"), 110.0)
    deff = _safe_float(stats.get("def_rating"), 110.0)

    expected_total = (pace / 100.0) * (off + deff) / 2.0 * 2.0
    # Soft clamp
    expected_total = max(140.0, min(250.0, expected_total))

    live_score = _safe_float(ctx.get("score_home")) + _safe_float(ctx.get("score_away"))
    quarter = int(_safe_float(ctx.get("quarter"), 1))
    time_left = ctx.get("time_left") or ctx.get("clock")

    # LIVE modda ilerleme oranına göre projeksiyon
    if mode == "LIVE" and live_score > 0:
        progress = min(1.0, max(0.1, (quarter - 1) / 3.0))
        projected = live_score + (expected_total - live_score) * (1.0 - progress)
        model_total = projected
    else:
        model_total = expected_total

    diff = model_total - total_line_f
    if total_line_f <= 0:
        call = "NO_BAREM"
        confidence = 0.0
    else:
        if abs(diff) < 5:
            call = "NO_BET"
            confidence = 0.2
        elif diff > 0:
            call = "OVER"
            confidence = min(0.95, 0.4 + abs(diff) / 20.0)
        else:
            call = "UNDER"
            confidence = min(0.95, 0.4 + abs(diff) / 20.0)

    return {
        "total_line": total_line_f,
        "model_total": round(model_total, 1),
        "call": call,
        "confidence": round(confidence, 3),
        "live_score": live_score,
        "quarter": quarter,
        "time_left": str(time_left) if time_left is not None else "",
    }


def _decide_side(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maç kazanan / handikap tarafı için çok basit skor.

    Beklenen olası alanlar:
      - ctx["lines"]["spread"]["line"]
      - ctx["power_ratings"]["home"], ["away"]
      - ctx["elo"]["home"], ["away"]
    """
    lines = ctx.get("lines") or ctx.get("markets") or {}
    spread_line = None
    if isinstance(lines, dict) and "spread" in lines:
        sp = lines["spread"]
        if isinstance(sp, dict):
            spread_line = sp.get("line") or sp.get("handicap")
        else:
            spread_line = sp

    pr = ctx.get("power_ratings") or ctx.get("elo") or {}
    home_pow = _safe_float(pr.get("home"), 0.0)
    away_pow = _safe_float(pr.get("away"), 0.0)
    diff_pow = home_pow - away_pow

    if spread_line is None:
        adj_spread = diff_pow / 2.0
    else:
        adj_spread = diff_pow - _safe_float(spread_line, 0.0)

    if abs(adj_spread) < 1.0:
        call = "NO_BET"
        confidence = 0.2
    elif adj_spread > 0:
        call = "HOME"
        confidence = min(0.95, 0.4 + abs(adj_spread) / 10.0)
    else:
        call = "AWAY"
        confidence = min(0.95, 0.4 + abs(adj_spread) / 10.0)

    return {
        "spread_line": _safe_float(spread_line, 0.0),
        "power_diff": round(diff_pow, 2),
        "adj_spread": round(adj_spread, 2),
        "call": call,
        "confidence": round(confidence, 3),
    }


# ================================================================
#  PREMATCH PREDICT
# ================================================================
def faz23_prematch_predict(ctx: Dict[str, Any]) -> str:
    header = _build_match_header(ctx)
    news_summary = ctx.get("news_summary") or []
    if isinstance(news_summary, str):
        news_summary = [news_summary]

    total_info = _decide_total_side(ctx, mode="PREMATCH")
    side_info = _decide_side(ctx)

    fusion_vector = {
        "total_call": total_info["call"],
        "total_conf": total_info["confidence"],
        "side_call": side_info["call"],
        "side_conf": side_info["confidence"],
    }

    record = {
        "mode": "PREMATCH",
        "header": header,
        "total": total_info,
        "side": side_info,
        "fusion": fusion_vector,
    }
    _append_history(record)

    lines: List[str] = []
    lines.append("🧠 FAZ-23 META ENGINE (PREMATCH)")
    lines.append(
        f"🏀 Maç: {header['home']} vs {header['away']} | 🏆 Lig: {header['league']}"
    )
    lines.append(f"📅 Tarih: {header['date']}")
    lines.append("")
    lines.append(
        f"📌 Toplam Barem: {total_info['total_line']:.1f} | Model Total: {total_info['model_total']:.1f}"
    )
    lines.append(
        f"🎯 FAZ-23 Total Karar: {total_info['call']} (güven: {total_info['confidence']:.3f})"
    )
    lines.append(
        f"📌 Handikap: {side_info['spread_line']:.1f} | PowerDiff: {side_info['power_diff']:.2f}"
    )
    lines.append(
        f"🎯 FAZ-23 Taraf Kararı: {side_info['call']} (güven: {side_info['confidence']:.3f})"
    )
    lines.append("")
    lines.append("🧬 Fusion Vektörü:")
    lines.append(
        f"- total_call={fusion_vector['total_call']} (conf={fusion_vector['total_conf']:.3f})"
    )
    lines.append(
        f"- side_call={fusion_vector['side_call']} (conf={fusion_vector['side_conf']:.3f})"
    )

    if news_summary:
        lines.append("")
        lines.append("📰 Haber / Notlar:")
        for row in news_summary[:8]:
            lines.append(f"- {row}")

    return "\n".join(lines)


# ================================================================
#  LIVE PREDICT
# ================================================================
def faz23_live_predict(ctx: Dict[str, Any]) -> str:
    header = _build_match_header(ctx)
    news_summary = ctx.get("news_summary") or []
    if isinstance(news_summary, str):
        news_summary = [news_summary]

    total_info = _decide_total_side(ctx, mode="LIVE")
    side_info = _decide_side(ctx)

    fusion_vector = {
        "total_call": total_info["call"],
        "total_conf": total_info["confidence"],
        "side_call": side_info["call"],
        "side_conf": side_info["confidence"],
    }

    record = {
        "mode": "LIVE",
        "header": header,
        "total": total_info,
        "side": side_info,
        "fusion": fusion_vector,
    }
    _append_history(record)

    lines: List[str] = []
    lines.append("🧠 FAZ-23 META ENGINE (LIVE)")
    lines.append(
        f"🏀 Maç: {header['home']} vs {header['away']} | 🏆 Lig: {header['league']}"
    )
    lines.append(f"📅 Tarih: {header['date']}")
    lines.append(
        f"⏱ Skor: {total_info['live_score']:.1f} | Quarter: Q{int(total_info['quarter'])} | Kalan: {total_info['time_left']}"
    )
    lines.append("")
    lines.append(
        f"📌 Barem: {total_info['total_line']:.1f} | Projeksiyon: {total_info['model_total']:.1f}"
    )
    lines.append(
        f"🎯 FAZ-23 LIVE Total Karar: {total_info['call']} (güven: {total_info['confidence']:.3f})"
    )
    lines.append(
        f"📌 Handikap: {side_info['spread_line']:.1f} | PowerDiff: {side_info['power_diff']:.2f}"
    )
    lines.append(
        f"🎯 FAZ-23 LIVE Taraf Kararı: {side_info['call']} (güven: {side_info['confidence']:.3f})"
    )
    lines.append("")
    lines.append("🧬 Fusion Vektörü:")
    lines.append(
        f"- total_call={fusion_vector['total_call']} (conf={fusion_vector['total_conf']:.3f})"
    )
    lines.append(
        f"- side_call={fusion_vector['side_call']} (conf={fusion_vector['side_conf']:.3f})"
    )

    if news_summary:
        lines.append("")
        lines.append("📰 Haber / Notlar:")
        for row in news_summary[:8]:
            lines.append(f"- {row}")

    return "\n".join(lines)
