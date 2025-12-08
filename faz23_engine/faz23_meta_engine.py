# faz23_engine/faz23_meta_engine.py
# ================================================================
#  FAZ-23 META ENGINE v1.1  (Tuple-safe, Fly.io 512MB friendly)
# ================================================================

import os
import json
import time
import logging
from typing import Any, Dict, List

log = logging.getLogger("faz23-meta")

# ================================================================
#  📁 DİZİN VE CACHE AYARLARI
# ================================================================
DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ23_DIR = os.path.join(DATA_DIR, "faz23")
os.makedirs(FAZ23_DIR, exist_ok=True)

NEWS_CACHE_PATH = os.path.join(FAZ23_DIR, "faz23_news_cache.jsonl")


# ================================================================
#  🔐 KÜÇÜK YARDIMCI FONKSİYONLAR
# ================================================================
def _safe_load_jsonl(path: str, limit: int = 256) -> List[Dict[str, Any]]:
    """Basit JSONL loader (sadece en son limit satırı okur)."""
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
    """JSONL cache append (hata olursa sessiz)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("[FAZ-23] News cache yazılamadı: %s", e, exc_info=False)


def _safe_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return 0.0


def _normalize_text(val: Any) -> str:
    """
    Tuple / list / başka türlü gelen her şeyi string'e çevirir.
    Tuple hatasının ana fix'i burada.
    """
    # Tuple veya list gelmişse parçalayıp birleştir
    if isinstance(val, (tuple, list)):
        val = " ".join(str(x) for x in val)
    # bytes gelirse decode et
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8", errors="ignore")
        except Exception:
            val = val.decode(errors="ignore")
    # kalan her şeyi string'e çevir
    val = str(val)
    return val.strip()


def _get_team_names(ctx: Dict[str, Any]) -> Dict[str, str]:
    """Context içinden ev / deplasman takım isimlerini güvenli çek."""
    home = (
        ctx.get("home_name")
        or ctx.get("home_team")
        or ctx.get("home", {}).get("name")
        or "-"
    )
    away = (
        ctx.get("away_name")
        or ctx.get("away_team")
        or ctx.get("away", {}).get("name")
        or "-"
    )
    return {"home": str(home), "away": str(away)}


def _extract_prematch_totals(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Context'ten toplam sayı baremini çek; farklı provider isimlerine toleranslı.
    Yoksa 0.0 döner, ama engine yine de string üretir.
    """
    # Muhtemel key isimleri
    candidates = [
        "total",
        "totals",
        "ou_line",
        "pre_total",
        "main_total",
        "barem",
    ]
    for key in candidates:
        if key in ctx:
            val = ctx.get(key)
            # bazı provider'lar {"total": 220.5, "period": "FT"} gibi dict dönebilir
            if isinstance(val, dict) and "total" in val:
                return {"total": _safe_float(val.get("total")), "raw": val}
            return {"total": _safe_float(val), "raw": val}
    return {"total": 0.0, "raw": None}


def _extract_live_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Live state/score bilgilerini çıkar.
    Eksikse defaults verecek, engine yine string dönecek.
    """
    score_home = _safe_float(ctx.get("score_home") or ctx.get("home_score"))
    score_away = _safe_float(ctx.get("score_away") or ctx.get("away_score"))
    period = (
        ctx.get("period")
        or ctx.get("quarter")
        or ctx.get("time", {}).get("period")
        or "-"
    )
    clock = ctx.get("clock") or ctx.get("time", {}).get("clock") or ""

    return {
        "score_home": score_home,
        "score_away": score_away,
        "period": str(period),
        "clock": str(clock),
    }


def _compute_simple_score_vector(
    mode: str, ctx: Dict[str, Any], live_dummy: Dict[str, Any], totals: Dict[str, Any]
) -> Dict[str, float]:
    """
    Çok basit bir skor vektörü: FAZ-23 içinde minimum tahmin objesi.
    Asıl model offline tarafta gelişecek; burası sadece string üretmek için.
    """
    total_line = totals.get("total", 0.0)
    cur_total = live_dummy.get("total", 0.0)
    period = str(live_dummy.get("period", "0"))

    over_bias = 0.5
    under_bias = 0.5

    if total_line > 0 and cur_total > 0:
        ratio = cur_total / total_line
        # İlk yarı / ilk 3 çeyrek vs. için kaba oran
        if ratio > 0.52:
            over_bias = 0.65
            under_bias = 0.35
        elif ratio < 0.48:
            over_bias = 0.35
            under_bias = 0.65

    return {
        "mode_over": float(over_bias),
        "mode_under": float(under_bias),
        "total_line": float(total_line),
        "cur_total": float(cur_total),
        "period": _safe_float(period),
    }


# ================================================================
#  📰 NEWS SUMMARY HELPER
# ================================================================
def _build_news_summary(ctx: Dict[str, Any], mode: str) -> str:
    """
    raw_ctx içinden haber / yorum / sakatlık parçalarını alır,
    tuple dahil her şeyi string'e çevirip tek satırda özetler.
    """
    # Provider'lardan gelebilecek muhtemel alanlar
    raw_news: Any = (
        ctx.get("news_summary")
        or ctx.get("news_raw")
        or ctx.get("news")
        or ctx.get("comment")
        or ""
    )

    text = _normalize_text(raw_news)
    if not text:
        return ""

    # Çok uzun olmasın; main.py tarafıyla uyumlu şekilde kırp
    max_len = 260
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."

    prefix = "PREMATCH" if mode.lower() == "prematch" else "LIVE"
    return f"[{prefix}] {text}"


# ================================================================
#  🧠 NEWS ENRICH (main.py faz23_build_context bunu çağırıyor)
# ================================================================
def faz23_news_enrich(raw_ctx: Dict[str, Any], mode: str = "prematch") -> Dict[str, Any]:
    """
    INPUT:  live_providers.core.get_live_match_global çıktısı (dict)
    OUTPUT: aynı dict + 'news_summary' gibi ek alanlar.
    Ağır scraping yapmaz, sadece gelen veriyi toparlar + hafif cache tutar.
    Tuple → string normalize burada da garanti altında.
    """
    if raw_ctx is None or not isinstance(raw_ctx, dict):
        return {}

    ctx = dict(raw_ctx)  # kopya üzerinde çalışalım

    # Haber özetini üret
    news_summary = _build_news_summary(ctx, mode)
    ctx["news_summary"] = news_summary

    # Hafif cache kaydı (yalnızca başlık + temel meta)
    try:
        names = _get_team_names(ctx)
        cache_item = {
            "ts": int(time.time()),
            "mode": mode,
            "league": str(ctx.get("league") or ctx.get("competition") or "-"),
            "home": names["home"],
            "away": names["away"],
            "news_summary": news_summary,
        }
        _safe_append_jsonl(NEWS_CACHE_PATH, cache_item)
    except Exception as e:
        log.debug("[FAZ-23] News cache append hata (ignore): %s", e, exc_info=False)

    return ctx


# ================================================================
#  🎯 PREMATCH TAHMİN MOTORU
# ================================================================
def faz23_prematch_predict(ctx: Dict[str, Any]) -> str:
    """
    ctx → faz23_build_context(match_code, mode="prematch") çıktısı.
    Her zaman string döndürür, asla exception bırakmaz
    (tuple dahil tüm alanlar normalize edilir).
    """
    try:
        if ctx is None or not isinstance(ctx, dict):
            raise ValueError("Boş veya geçersiz context")

        names = _get_team_names(ctx)
        totals = _extract_prematch_totals(ctx)

        # Basit skor vektörü (pre-match için dummy)
        live_dummy = {
            "total": 0.0,
            "period": "0",
        }
        score_vec = _compute_simple_score_vector("prematch", ctx, live_dummy, totals)

        league = str(ctx.get("league") or ctx.get("competition") or "-")
        news_summary = ctx.get("news_summary") or _build_news_summary(ctx, "prematch")

        lines = []
        lines.append("🧠 FAZ-23 PREMATCH Meta Tahmin")
        lines.append(f"🏆 Lig: {league}")
        lines.append(f"🏀 Maç: {names['home']} - {names['away']}")
        lines.append("")
        lines.append("📊 Toplam Sayı Barem Analizi")
        lines.append(f"• Ana total çizgisi: {score_vec['total_line']:.1f}")
        lines.append(f"• Model over ölçüsü  : {score_vec['mode_over']:.3f}")
        lines.append(f"• Model under ölçüsü : {score_vec['mode_under']:.3f}")
        lines.append("")
        lines.append("📰 Haber / Yorum Özeti:")
        if news_summary:
            lines.append(f"- {news_summary}")
        else:
            lines.append("- Bu maç için kayıtlı özel haber sinyali yok.")
        lines.append("")
        if score_vec["mode_over"] > score_vec["mode_under"]:
            lines.append("📌 FAZ-23 Eğilim: Ana baremde hafif **OVER** tarafı daha önde.")
        elif score_vec["mode_under"] > score_vec["mode_over"]:
            lines.append("📌 FAZ-23 Eğilim: Ana baremde hafif **UNDER** tarafı daha önde.")
        else:
            lines.append("📌 FAZ-23 Eğilim: OVER / UNDER tarafları dengede görünüyor.")

        return "\n".join(lines)

    except Exception as e:
        log.error("[FAZ-23 PREMATCH ERROR] %s", e, exc_info=True)
        return f"❌ FAZ-23 PREMATCH meta tahmini üretilemedi: {e}"


# ================================================================
#  🔴 LIVE TAHMİN MOTORU
# ================================================================
def faz23_live_predict(ctx: Dict[str, Any]) -> str:
    """
    ctx → faz23_build_context(match_code, mode="live") çıktısı.
    Her zaman string döndürür; tuple / list vs. normalize edilir.
    """
    try:
        if ctx is None or not isinstance(ctx, dict):
            raise ValueError("Boş veya geçersiz context")

        names = _get_team_names(ctx)
        totals = _extract_prematch_totals(ctx)
        live_state = _extract_live_state(ctx)

        cur_total = live_state["score_home"] + live_state["score_away"]
        live_dummy = {
            "total": cur_total,
            "period": live_state["period"],
        }
        score_vec = _compute_simple_score_vector("live", ctx, live_dummy, totals)

        league = str(ctx.get("league") or ctx.get("competition") or "-")
        news_summary = ctx.get("news_summary") or _build_news_summary(ctx, "live")

        lines = []
        lines.append("🧠 FAZ-23 LIVE Meta Tahmin")
        lines.append(f"🏆 Lig: {league}")
        lines.append(f"🏀 Maç: {names['home']} - {names['away']}")
        lines.append(
            f"⏱ Durum: {live_state['period']} | Skor: "
            f"{live_state['score_home']:.0f}-{live_state['score_away']:.0f}"
        )
        if live_state["clock"]:
            lines.append(f"🕒 Saat: {live_state['clock']}")
        lines.append("")
        lines.append("📊 Toplam Sayı / Tempo Analizi")
        lines.append(f"• Maç içi toplam skor      : {score_vec['cur_total']:.1f}")
        lines.append(f"• Maç öncesi ana barem     : {score_vec['total_line']:.1f}")
        lines.append(f"• Model over ölçüsü (live) : {score_vec['mode_over']:.3f}")
        lines.append(f"• Model under ölçüsü (live): {score_vec['mode_under']:.3f}")
        lines.append("")
        lines.append("📰 Haber / Yorum Özeti:")
        if news_summary:
            lines.append(f"- {news_summary}")
        else:
            lines.append("- Ekstra haber sinyali yok (live).")
        lines.append("")
        if score_vec["mode_over"] > score_vec["mode_under"]:
            lines.append("📌 FAZ-23 LIVE Eğilim: Tempo ana baremin **OVER** tarafına yakın.")
        elif score_vec["mode_under"] > score_vec["mode_over"]:
            lines.append("📌 FAZ-23 LIVE Eğilim: Tempo ana baremin **UNDER** tarafına yakın.")
        else:
            lines.append("📌 FAZ-23 LIVE Eğilim: OVER / UNDER tarafları dengede.")

        return "\n".join(lines)

    except Exception as e:
        log.error("[FAZ-23 LIVE ERROR] %s", e, exc_info=True)
        return f"❌ FAZ-23 LIVE meta tahmini üretilemedi: {e}"
