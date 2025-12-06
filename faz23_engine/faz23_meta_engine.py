# faz23_engine/faz23_meta_engine.py
# ================================================================
# 🧠 FAZ-23 META ENGINE v1.0 (Fly.io 512MB friendly)
# ------------------------------------------------
# - Multi-data + news füzyon motoru
# - Prematch ve Live tahmin çıktıları
# - Hafif cache sistemi (/data/faz23/)
# - Hata durumunda ASLA çökmez, daima string döner
# ================================================================

from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Dict, List

log = logging.getLogger("faz23-meta")

# ================================================================
# 📁 DİZİN ve CACHE AYARLARI
# ================================================================
DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ23_DIR = os.path.join(DATA_DIR, "faz23")
os.makedirs(FAZ23_DIR, exist_ok=True)

NEWS_CACHE_PATH = os.path.join(FAZ23_DIR, "faz23_news_cache.jsonl")


def _safe_load_jsonl(path: str, limit: int = 256) -> List[Dict[str, Any]]:
    try:
        items: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    continue
                if len(items) >= limit:
                    break
        return items
    except FileNotFoundError:
        return []
    except Exception as e:
        log.warning("[FAZ-23] JSONL okunamadı: %s", e, exc_info=False)
        return []


def _safe_append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except FileNotFoundError:
        # klasör yoksa oluşturup tekrar dene
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning("[FAZ-23] News cache yazılamadı: %s", e, exc_info=False)
    except Exception as e:
        log.warning("[FAZ-23] News cache yazılamadı: %s", e, exc_info=False)


# ================================================================
# 🔬 KÜÇÜK YARDIMCI FONKSİYONLAR
# ================================================================
def _get_team_names(ctx: Dict[str, Any]) -> Dict[str, str]:
    """Context içinden ev / deplasman takımlarını güvenli çek."""
    home = (
        ctx.get("home_name")
        or ctx.get("home", {}).get("name")
        or ctx.get("home_team")
        or "-"
    )
    away = (
        ctx.get("away_name")
        or ctx.get("away", {}).get("name")
        or ctx.get("away_team")
        or "-"
    )
    league = (
        ctx.get("league_name")
        or ctx.get("league")
        or ctx.get("competition")
        or "-"
    )
    return {
        "home": str(home),
        "away": str(away),
        "league": str(league),
    }


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(str(val).replace(",", "."))
    except Exception:
        return default


def _extract_prematch_totals(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Çeşitli provider formatlarından O/U baremini tahmin etmeye çalışır.
    Bulamazsa boş döner, ama çöktürmez.
    """
    odds = ctx.get("odds") or {}
    markets = odds.get("markets") or odds.get("prematch") or {}

    total = None
    over_price = None
    under_price = None

    # En yaygın pattern: markets["TOTAL_POINTS"]["line"], ["over"], ["under"]
    try:
        m_total = markets.get("TOTAL_POINTS") or markets.get("TOTAL") or {}
        total = m_total.get("line") or m_total.get("total")
        o = m_total.get("over") or {}
        u = m_total.get("under") or {}
        over_price = o.get("price") or o.get("odd")
        under_price = u.get("price") or u.get("odd")
    except Exception:
        pass

    # Alternatif basit formatlar
    if total is None:
        for key in ("total", "totals", "ou_line", "main_total"):
            if key in odds:
                total = odds[key]
                break

    return {
        "total_line": _safe_float(total, 0.0) if total is not None else 0.0,
        "over_price": _safe_float(over_price, 0.0) if over_price is not None else 0.0,
        "under_price": _safe_float(under_price, 0.0)
        if under_price is not None
        else 0.0,
    }


def _extract_live_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canlı maç context'inden periyot, süre, skor gibi temel sinyalleri çeker.
    Anahtar isimleri bilinmiyorsa, mümkün olduğunca tahmin etmeye çalışır.
    """
    score = ctx.get("score") or {}
    home_score = _safe_float(score.get("home") or score.get("home_score"), 0.0)
    away_score = _safe_float(score.get("away") or score.get("away_score"), 0.0)
    total = home_score + away_score

    period = (
        ctx.get("period")
        or ctx.get("quarter")
        or score.get("period")
        or score.get("quarter")
        or "?"
    )
    clock = (
        ctx.get("clock")
        or ctx.get("time_remaining")
        or score.get("clock")
        or score.get("time")
        or "?"
    )
    status = ctx.get("status") or ctx.get("match_status") or "UNKNOWN"

    return {
        "home_score": home_score,
        "away_score": away_score,
        "total": total,
        "period": str(period),
        "clock": str(clock),
        "status": str(status),
    }


def _compute_simple_score_vector(
    mode: str, ctx: Dict[str, Any], live: Dict[str, Any], totals: Dict[str, Any]
) -> float:
    """
    Çok ağır modele gerek yok; 0.0 - 1.0 arası basit bir skor vektörü üretelim.
    - prematch: form, barem, haber sinyali (var/yok)
    - live: tempo (skor/süre), fark, favori taraf ne yapıyor vs.
    """
    mode = (mode or "").lower()
    base = 0.5  # nötr

    # Haber sinyali (haber varsa hafif oynama)
    has_news = bool(ctx.get("news") or ctx.get("news_items") or ctx.get("injuries"))
    if has_news:
        base += 0.05

    # Prematch tarafı
    if mode == "prematch":
        t_line = totals.get("total_line", 0.0)
        if t_line > 0:
            if t_line >= 165 and t_line <= 185:
                base += 0.05
            elif t_line > 200:
                base += 0.02
            else:
                base -= 0.02

    # Live tarafı
    if mode == "live":
        total = live.get("total", 0.0)
        period_str = str(live.get("period", "1"))
        try:
            period = int("".join(ch for ch in period_str if ch.isdigit()) or "1")
        except Exception:
            period = 1

        # Basit tempo: periyot başına skor
        tempo = total / max(period, 1)
        if tempo >= 50:
            base += 0.10
        elif tempo >= 40:
            base += 0.05
        elif tempo <= 30:
            base -= 0.05

    # Güvenli clamp
    if base < 0.0:
        base = 0.0
    if base > 1.0:
        base = 1.0
    return round(base, 3)


def _build_news_summary(ctx: Dict[str, Any], mode: str) -> str:
    """
    Context içinde gelen 'news' / 'injuries' / 'notes' alanlarını tek satıra indirger.
    Çok uzun ise keser. Hiçbir şey yoksa {} yerine kısa not döner.
    """
    items: List[str] = []

    raw_news = ctx.get("news") or ctx.get("news_items") or []
    if isinstance(raw_news, list):
        for n in raw_news:
            if isinstance(n, str):
                items.append(n.strip())
            elif isinstance(n, dict):
                t = n.get("title") or n.get("headline") or ""
                if t:
                    items.append(str(t).strip())
    elif isinstance(raw_news, str):
        items.append(raw_news.strip())

    injuries = ctx.get("injuries") or []
    if isinstance(injuries, list):
        for inj in injuries:
            if isinstance(inj, str):
                items.append("Injury: " + inj.strip())
            elif isinstance(inj, dict):
                p = inj.get("player") or inj.get("name") or "?"
                s = inj.get("status") or inj.get("type") or "?"
                items.append(f"Injury: {p} ({s})")

    notes = ctx.get("notes") or ctx.get("comment") or ctx.get("comments")
    if isinstance(notes, str):
        items.append(notes.strip())

    if not items:
        return "{}"  # main.py ile uyumlu görünüm

    flat = " | ".join(items)
    if len(flat) > 260:
        flat = flat[:257] + "..."
    prefix = "PREMATCH" if mode.lower() == "prematch" else "LIVE"
    return f"[{prefix}] {flat}"


# ================================================================
# 📰 NEWS ENRICH HELPER (main.py faz23_build_context bunu çağırıyor)
# ================================================================
def faz23_news_enrich(raw_ctx: Dict[str, Any], mode: str = "prematch") -> Dict[str, Any]:
    """
    - INPUT: live_providers.core.get_live_match_global çıktısı (dict)
    - Çıkış: aynı dict + 'news_summary' gibi ek alanlar.
    - Ağır scraping yapmaz, sadece gelen veriyi toparlar + hafif cache tutar.
    """
    if raw_ctx is None or not isinstance(raw_ctx, dict):
        return {}

    ctx = dict(raw_ctx)  # kopya üzerinde çalışalım

    # Basit news summary üret
    news_summary = _build_news_summary(ctx, mode)
    ctx["news_summary"] = news_summary

    # Hafif cache kaydı (yalnızca başlık + temel meta)
    try:
        cache_item = {
            "ts": int(time.time()),
            "mode": mode,
            "league": _get_team_names(ctx)["league"],
            "home": _get_team_names(ctx)["home"],
            "away": _get_team_names(ctx)["away"],
            "news_summary": news_summary,
        }
        _safe_append_jsonl(NEWS_CACHE_PATH, cache_item)
    except Exception as e:
        log.debug("[FAZ-23] Cache append hata (ignore): %s", e, exc_info=False)

    return ctx


# ================================================================
# 🎯 PREMATCH TAHMİN MOTORU
# ================================================================
def faz23_prematch_predict(ctx: Dict[str, Any]) -> str:
    """
    ctx → faz23_build_context(match_code, mode="prematch") çıktısı.
    Her zaman string döndürür, asla exception bırakmaz.
    """
    try:
        if ctx is None or not isinstance(ctx, dict):
            raise ValueError("Boş veya geçersiz context")

        names = _get_team_names(ctx)
        totals = _extract_prematch_totals(ctx)
        live_dummy = {"total": 0.0, "period": "0"}  # skor yok, ama API ortak olsun

        score_vec = _compute_simple_score_vector("prematch", ctx, live_dummy, totals)
        news_summary = ctx.get("news_summary") or _build_news_summary(ctx, "prematch")

        regime = "NEUTRAL"
        if score_vec >= 0.75:
            regime = "AGGRESSIVE_OVER"
        elif score_vec >= 0.6:
            regime = "LEAN_OVER"
        elif score_vec <= 0.25:
            regime = "AGGRESSIVE_UNDER"
        elif score_vec <= 0.4:
            regime = "LEAN_UNDER"

        line_text = ""
        if totals.get("total_line", 0.0) > 0:
            line_text = f"{totals['total_line']:.1f}"

        # Ana çıktı metni (Telegram için optimize)
        lines: List[str] = []
        lines.append("🎛 FAZ-23 META ENGINE (PREMATCH)")
        lines.append(
            f"🏀 Maç: {names['home']} vs {names['away']} ({names['league']})"
        )
        if line_text:
            lines.append(f"📏 Ana Toplam Barem: {line_text}")
        lines.append("")
        lines.append(f"🧠 Internal Score Vector: {score_vec:.3f}")
        lines.append(f"🧷 Regime: {regime}")
        lines.append("")
        lines.append(f"📰 News Range: {news_summary}")
        lines.append("")
        lines.append("🔍 Açıklama notları:")
        lines.append("- Bu çıktı FAZ-23 multi-data füzyonundan gelir.")
        lines.append(
            "- Skor vektörü 0.0-1.0 arasıdır; 0.5 nötr, 0.7 üzeri güçlü eğilim anlamına gelir."
        )
        lines.append(
            "- Şu an model güvenli moddadır; agresif öneriler için zamanla sahadan öğrenme gereklidir."
        )

        return "\n".join(lines)

    except Exception as e:
        log.error("[FAZ-23 PREMATCH ERROR] %s", e, exc_info=True)
        return (
            "❌ FAZ-23 prematch motoru çalışırken hata oluştu.\n"
            f"Detay: {e}"
        )


# ================================================================
# ⚡ LIVE TAHMİN MOTORU
# ================================================================
def faz23_live_predict(ctx: Dict[str, Any]) -> str:
    """
    ctx → faz23_build_context(match_code, mode=\"live\") çıktısı.
    Canlı skor + tempo + barem kombinasyonu üzerinden yorum üretir.
    """
    try:
        if ctx is None or not isinstance(ctx, dict):
            raise ValueError("Boş veya geçersiz context")

        names = _get_team_names(ctx)
        totals = _extract_prematch_totals(ctx)  # çoğu durumda canlıda da geçerli
        live = _extract_live_state(ctx)

        score_vec = _compute_simple_score_vector("live", ctx, live, totals)
        news_summary = ctx.get("news_summary") or _build_news_summary(ctx, "live")

        regime = "NEUTRAL"
        if score_vec >= 0.8:
            regime = "HIGH_TEMPO_OVER"
        elif score_vec >= 0.6:
            regime = "TEMPO_OVER"
        elif score_vec <= 0.2:
            regime = "KILL_UNDER"
        elif score_vec <= 0.4:
            regime = "LEAN_UNDER"

        line_text = ""
        if totals.get("total_line", 0.0) > 0:
            line_text = f"{totals['total_line']:.1f}"

        lines: List[str] = []
        lines.append("⚡ FAZ-23 META ENGINE (LIVE)")
        lines.append(
            f"🏀 Maç: {names['home']} vs {names['away']} ({names['league']})"
        )
        if line_text:
            lines.append(f"📏 Ana Toplam Barem (referans): {line_text}")
        lines.append(
            f"⏱ Durum: {live['status']} | Periyot: {live['period']} | Saat: {live['clock']}"
        )
        lines.append(
            f"📊 Skor: {int(live['home_score'])} - {int(live['away_score'])} "
            f"(Toplam: {int(live['total'])})"
        )
        lines.append("")
        lines.append(f"🧠 Internal Score Vector: {score_vec:.3f}")
        lines.append(f"🧷 Regime: {regime}")
        lines.append("")
        lines.append(f"📰 News Range: {news_summary}")
        lines.append("")
        lines.append("🔍 Açıklama notları:")
        lines.append(
            "- Score vector, tempo + skor + haber sinyallerini tek skorda toplar."
        )
        lines.append(
            "- HIGH_TEMPO_OVER: maç ritmi baremin üzerinde akıyor; kill under tersi."
        )
        lines.append(
            "- Bu sürüm güvenli moddadır; sahadan toplanan geçmişle zamanla keskinleşecektir."
        )

        return "\n".join(lines)

    except Exception as e:
        log.error("[FAZ-23 LIVE ERROR] %s", e, exc_info=True)
        return (
            "❌ FAZ-23 live motoru çalışırken hata oluştu.\n"
            f"Detay: {e}"
        )
