# ============================================================
# Zeynal Core AI - FINAL BUILD (FAZ-7/10/11/12/13/17/22/23)
# ENGINEERING / HIGH FOCUS / HATA AVCI MODE
# Fly.io 512MB uyumlu, stabil, gözlemci log + sebep kodlu
# ============================================================

import os
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import telebot
from flask import Flask, request

# -----------------------------
# LOGGING
# -----------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("zeynal-core")

# -----------------------------
# ENV
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()  # opsiyonel
PORT = int(os.getenv("PORT", "8080"))

# OCR / concurrency (Fly 512MB)
OCR_MAX_WORKERS = int(os.getenv("OCR_MAX_WORKERS", "2"))
OCR_TIMEOUT_S = int(os.getenv("OCR_TIMEOUT_S", "12"))

# Flags
FAZ17_MARKET_ENABLED = os.getenv("FAZ17_MARKET_ENABLED", "1").strip() == "1"
FAZ23_META_ENABLED = os.getenv("FAZ23_META_ENABLED", "1").strip() == "1"
AUTO_WEBHOOK = os.getenv("AUTO_WEBHOOK", "1").strip() == "1"  # gunicorn-safe deneme

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

# -----------------------------
# TELEGRAM + FLASK
# -----------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=2)
app = Flask(__name__)

# ================================================================
# FAZ-13 OCR DEBUG STATE + GLOBAL OCR CACHE (hafif)
# ================================================================
LAST_OCR_TEXT = None
LAST_OCR_META = {}

OCR_CACHE = {}
OCR_CACHE_LOCK = threading.Lock()

# ================================================================
# SAFE IMPORTS (fail-soft) + FAZ STATUS
# ================================================================
FAZ_STATUS = {}  # {"FAZ-10": ("ON/OFF", "reason"), ...}

def _set_faz(name: str, ok: bool, reason: str):
    FAZ_STATUS[name] = ("✅" if ok else "🔴", reason)

def _safe_import(path: str, name: str):
    try:
        module = __import__(path, fromlist=[name])
        obj = getattr(module, name)
        _set_faz(name, True, f"import_ok:{path}.{name}")
        return obj
    except Exception as e:
        _set_faz(name, False, f"import_fail:{path}.{name}:{e}")
        log.warning("Import fail: %s.%s -> %s", path, name, e)
        return None

# ---- FAZ-10 / 11 / 12 / 13
faz10_stability_check = _safe_import("faz10_engine.faz10_stability", "faz10_stability_check")

faz11_feedback = _safe_import("faz11_engine.faz11_feedback", "faz11_feedback")
faz11_last_summary = _safe_import("faz11_engine.faz11_feedback", "faz11_last_summary")

faz12_run_once = _safe_import("faz12_engine.faz12_autoadjust", "faz12_run_once")
faz12_auto_profile = _safe_import("faz12_engine.faz12_autoadjust", "faz12_auto_profile")

normalize_manual_text = _safe_import("faz13_engine.faz13_orchestrator", "normalize_manual_text")
normalize_api_data = _safe_import("faz13_engine.faz13_orchestrator", "normalize_api_data")
normalize_visual_meta = _safe_import("faz13_engine.faz13_orchestrator", "normalize_visual_meta")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")
faz13_daily_coupon = _safe_import("faz13_engine.faz13_orchestrator", "faz13_daily_coupon")

# ---- FAZ-17 market (birden çok olası isim)
faz17_fetch_market = (
    _safe_import("faz17_engine.faz17_market", "faz17_fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "faz17_fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "fetch_market")
    or _safe_import("faz17_engine.faz17_market_fetcher", "get_market")
)

# ---- FAZ-23 meta (opsiyonel)
faz23_meta_evaluate = (
    _safe_import("faz23_engine.faz23_meta", "faz23_meta_evaluate")
    or _safe_import("faz22_engine.faz22_meta_engine", "faz22_meta_engine")  # sende fonksiyon adı buydu
)

# ================================================================
# THREAD POOL (Fly.io 512MB friendly)
# ================================================================
OCR_POOL = ThreadPoolExecutor(max_workers=max(1, min(4, OCR_MAX_WORKERS)))

# ================================================================
# UTILS
# ================================================================
def _clean_team(s: str) -> str:
    return (s or "").strip().lower().replace(".", "").replace("-", " ").replace("  ", " ")

def _normalize_league_key(league: str) -> str:
    L = (league or "").strip().upper()
    if L in ("EUROLEAGUE", "EL", "EURL"):
        return "EUROLEAGUE"
    if L in ("NBA",):
        return "NBA"
    return L

def _parse_mac_command(text: str):
    """
    Beklenen format:
    /mac LEAGUE | YYYY-MM-DD | Home - Away
    """
    raw = (text or "").strip()
    if not raw.startswith("/mac"):
        return None
    payload = raw[4:].strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 3:
        return None
    league = parts[0]
    date_str = parts[1]
    teams = parts[2]
    if "-" not in teams:
        return None
    home, away = [t.strip() for t in teams.split("-", 1)]
    return league, date_str, home, away

# ================================================================
# HATA AVCI: MARKET FETCH SAFE WRAPPER
# ================================================================
def _try_fetch_market_safe(league, date_str, home, away):
    """
    Returns: (market_data, market_flag, market_reason)
      - market_data: dict|None
      - market_flag: "MARKET_OK" | "NO_MARKET_DATA" | "MARKET_DISABLED"
      - market_reason: sebep kodu
    """
    if not FAZ17_MARKET_ENABLED:
        return None, "MARKET_DISABLED", "FAZ17_MARKET_ENABLED=0"

    if not faz17_fetch_market:
        return None, "NO_MARKET_DATA", "faz17_fetch_market is None (import/wire missing)"

    league_key = _normalize_league_key(league)

    # 1) direct
    try:
        md = faz17_fetch_market(league=league_key, date_str=date_str, home=home, away=away)
        if md:
            return md, "MARKET_OK", "direct"
    except Exception as e:
        log.warning("FAZ-17 market failed (direct): %s", e)

    # 2) normalized teams
    try:
        md = faz17_fetch_market(
            league=league_key,
            date_str=date_str,
            home=_clean_team(home),
            away=_clean_team(away),
        )
        if md:
            return md, "MARKET_OK", "normalized_teams"
    except Exception as e:
        log.warning("FAZ-17 market failed (normalized_teams): %s", e)

    return None, "NO_MARKET_DATA", "all attempts failed/empty"

# ================================================================
# OUTPUT FORMATTERS
# ================================================================
def _fmt_kv(title, v):
    return f"• {title}: {v}"

def _render_prediction_message(result: dict, league: str, home: str, away: str, market_flag: str, market_reason: str):
    lines = []
    lines.append("📌 FAZ-13 Maç Tahmini (Pro)")
    lines.append(f"Maç: {home} - {away}")
    lines.append(f"Lig: {league}")
    lines.append("—" * 30)

    lines.append("🧪 FAZ DURUMU (yeşil/kırmızı)")
    # kısa göster
    for k in sorted(FAZ_STATUS.keys()):
        icon, reason = FAZ_STATUS[k]
        lines.append(f"{icon} {k} | {reason[:90]}")

    lines.append("—" * 30)
    lines.append("💹 MARKET DURUMU")
    lines.append(_fmt_kv("flags", f"{market_flag} ({market_reason})"))

    if not isinstance(result, dict):
        lines.append("—" * 30)
        lines.append("⚠️ FAZ-13 pipeline dict dönmedi.")
        lines.append(str(result))
        return "\n".join(lines)

    # ortak anahtar toleransı
    fusion_total = result.get("fusion_total") or result.get("total") or result.get("pred_total")
    band = result.get("band") or result.get("total_band")
    score_vector = result.get("score_vector") or result.get("vector")

    lines.append("—" * 30)
    lines.append("🎯 TOPLAM TAHMİNİ")
    if fusion_total is not None:
        lines.append(_fmt_kv("Fusion Total", fusion_total))
    if band is not None:
        lines.append(_fmt_kv("Bant", band))
    if score_vector is not None:
        lines.append(_fmt_kv("Score Vector", score_vector))

    per = result.get("periods") or result.get("period_projection")
    if isinstance(per, (dict, list)) and per:
        lines.append("—" * 30)
        lines.append("⏱️ PERİYOT PROJEKSİYONLARI")
        lines.append(_fmt_kv("periods", per))

    team_scores = result.get("team_scores") or result.get("teams")
    if isinstance(team_scores, (dict, list)) and team_scores:
        lines.append("—" * 30)
        lines.append("🏀 TAKIM SKOR TAHMİNİ")
        lines.append(_fmt_kv("team_scores", team_scores))

    notes = result.get("analysis") or result.get("notes") or result.get("meta")
    if notes:
        lines.append("—" * 30)
        lines.append("🧾 ANALİZ / NOTLAR")
        if isinstance(notes, dict):
            for kk, vv in list(notes.items())[:25]:
                lines.append(_fmt_kv(kk, vv))
        else:
            lines.append(str(notes))

    return "\n".join(lines)

# ================================================================
# CORE: RUN MATCH PIPELINE
# ================================================================
def run_match_pipeline(league: str, date_str: str, home: str, away: str):
    league_key = _normalize_league_key(league)

    # FAZ-10 stability (IMZA UYUMLU FIX)
    if faz10_stability_check:
        try:
            meta = {"league": league_key, "date": date_str, "home": home, "away": away}
            # yeni imza
            faz10_stability_check("mac_command", meta)
        except TypeError:
            # eski imza varsa çakılma
            try:
                faz10_stability_check()
            except Exception as e:
                log.warning("FAZ-10 stability fail (legacy): %s", e)
        except Exception as e:
            log.warning("FAZ-10 stability fail: %s", e)

    # FAZ-12 auto adjust
    if faz12_run_once:
        try:
            faz12_run_once()
        except Exception as e:
            log.warning("FAZ-12 run once fail: %s", e)

    # FAZ-17 market
    market_data, market_flag, market_reason = _try_fetch_market_safe(league_key, date_str, home, away)

    # FAZ-13 pipeline
    if not run_faz13_auto_pipeline:
        fallback = {
            "fusion_total": 230.0 if league_key == "NBA" else None,
            "band": [223.5, 236.5] if league_key == "NBA" else None,
            "vector": [226.0, 230.0, 234.0] if league_key == "NBA" else None,
            "analysis": {
                "error": "run_faz13_auto_pipeline import missing",
                "league": league_key,
                "date": date_str,
            },
            "raw": {
                "input": {
                    "source": "manual",
                    "league": league_key,
                    "date_str": date_str,
                    "home": home,
                    "away": away,
                    "market_data": market_data,
                }
            },
        }
        return fallback, market_flag, market_reason

    try:
        # market_data destekliyorsa geçir
        try:
            result = run_faz13_auto_pipeline(
                league=league_key,
                date_str=date_str,
                home=home,
                away=away,
                market_data=market_data,
                mode="PREMATCH",
            )
        except TypeError:
            # orchestrator imzasında market_data yoksa: crash etme, uyarı bas
            log.warning("FAZ-13 orchestrator signature missing market_data. Update orchestrator!")
            result = run_faz13_auto_pipeline(
                league=league_key,
                date_str=date_str,
                home=home,
                away=away,
                mode="PREMATCH",
            )
            if not market_data:
                market_flag, market_reason = "NO_MARKET_DATA", "orchestrator_signature_missing_market_data"
    except Exception as e:
        log.exception("FAZ-13 pipeline crash: %s", e)
        result = {"analysis": {"error": f"FAZ-13 crash: {e}"}}

    # FAZ-23 META (opsiyonel)
    if FAZ23_META_ENABLED and faz23_meta_evaluate:
        try:
            meta_out = None
            # iki olası imza toleransı
            try:
                meta_out = faz23_meta_evaluate(
                    league=league_key,
                    date_str=date_str,
                    home=home,
                    away=away,
                    faz13_result=result,
                    market_data=market_data,
                )
            except TypeError:
                meta_out = faz23_meta_evaluate(league=league_key, date_str=date_str, home=home, away=away)

            if isinstance(result, dict):
                result.setdefault("meta23", {})
                result["meta23"]["external"] = meta_out
        except Exception as e:
            log.warning("FAZ-23 meta fail: %s", e)

    # raw input debug (sende ekran çıktısı bu formatta hoşuna gidiyor)
    if isinstance(result, dict):
        result.setdefault("raw", {})
        result["raw"].setdefault("input", {})
        result["raw"]["input"].update(
            {
                "source": "manual",
                "league": league_key,
                "date_str": date_str,
                "home": home,
                "away": away,
                "market_data": market_data if market_data else {
                    "ok": False,
                    "main_total": None,
                    "total_line": None,
                    "confidence": 0.0,
                    "sources": [],
                    "reason": "no_sources_no_cache" if market_flag != "MARKET_DISABLED" else "disabled",
                    "cache_hit": False,
                },
            }
        )

    return result, market_flag, market_reason

# ================================================================
# TELEGRAM COMMANDS
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(m):
    bot.reply_to(m, "Zeynal Core AI aktif.\n/mac LIG | YYYY-MM-DD | Ev - Dep")

@bot.message_handler(func=lambda m: (m.text or "").strip().startswith("/mac"))
def cmd_mac(m):
    parsed = _parse_mac_command(m.text)
    if not parsed:
        bot.reply_to(m, "Format: /mac LIG | YYYY-MM-DD | Ev - Dep")
        return

    league, date_str, home, away = parsed
    bot.send_message(m.chat.id, f"⏳ Analiz ediliyor:\n{league} | {date_str}\n{home} - {away}")

    try:
        result, market_flag, market_reason = run_match_pipeline(league, date_str, home, away)
        msg = _render_prediction_message(
            result=result,
            league=_normalize_league_key(league),
            home=home,
            away=away,
            market_flag=market_flag,
            market_reason=market_reason,
        )
        # JSON debug isteyen sen olduğun için: hem mesaj hem JSON (kısa)
        bot.send_message(m.chat.id, msg)
        bot.send_message(m.chat.id, json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        log.exception("MAC error")
        bot.reply_to(m, f"❌ Hata: {e}")

# ================================================================
# WEBHOOK (Fly.io)
# ================================================================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        if request.headers.get("X-Webhook-Secret", "") != WEBHOOK_SECRET:
            return "FORBIDDEN", 403

    try:
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
    except Exception as e:
        log.exception("Webhook processing error: %s", e)

    return "OK", 200

def _set_webhook_safe():
    if not WEBHOOK_URL:
        log.info("WEBHOOK_URL yok. (Local dev için normal)")
        return
    try:
        bot.remove_webhook()
        time.sleep(0.2)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info("Webhook set: %s", WEBHOOK_URL)
    except Exception as e:
        log.warning("Webhook set failed: %s", e)

# Gunicorn altında __main__ çalışmaz → import-time güvenli deneme
if AUTO_WEBHOOK:
    try:
        _set_webhook_safe()
    except Exception as _e:
        # kesinlikle crash yok
        log.warning("AUTO_WEBHOOK failed: %s", _e)

# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    _set_webhook_safe()
    app.run(host="0.0.0.0", port=PORT, threaded=False)
