import os
import json
import logging
import traceback
from typing import Any, Dict, Optional, List

import telebot
from telebot import types
from flask import Flask, request

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hoopbrain-main")

# ================================================================
# ⚙️ CONFIG & GLOBALS
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev/webhook
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# Fly.io 512 MB free profile
PORT = int(os.getenv("PORT", "8080"))

DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ7_DIR = os.path.join(DATA_DIR, "faz7")
os.makedirs(FAZ7_DIR, exist_ok=True)

FAZ7_MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_HISTORY_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")

# Visual stack (FAZ-13 multi-screen)
VISUAL_STACK: List[Dict[str, Any]] = []
VISUAL_STACK_MAX = 32

# ================================================================
# 🧩 SAFE IMPORT HELPERS
# ================================================================
def _safe_import(module_path: str, attrs: Optional[List[str]] = None):
    """
    SAFE IMPORT (STABLE MODE)
    - Modül yoksa veya attr yoksa sistem ASLA çökmez.
    - Sadece DEBUG log yazar (Fly.io varsayılanında görünmez).
    """
    try:
        module = __import__(module_path, fromlist=attrs or [])
    except Exception as e:
        log.debug("Modül import edilemedi (SAFE): %s (%s)", module_path, e)
        if not attrs:
            return None
        return {name: None for name in attrs}

    if not attrs:
        return module

    out: Dict[str, Any] = {}
    for name in attrs:
        try:
            out[name] = getattr(module, name)
        except AttributeError:
            log.debug("Attr yok (SAFE): %s.%s", module_path, name)
            out[name] = None
    return out

# ================================================================
# 📦 IMPORT FAZ MODULES
# ================================================================
# FAZ-10
_faz10 = _safe_import("faz10_engine.faz10_stability", ["faz10_stability_check"])
faz10_stability_check = (_faz10 or {}).get("faz10_stability_check")

# FAZ-11
_faz11 = _safe_import(
    "faz11_engine.faz11_feedback",
    ["faz11_feedback", "faz11_last_summary"],
)
faz11_feedback = (_faz11 or {}).get("faz11_feedback")
faz11_last_summary = (_faz11 or {}).get("faz11_last_summary")

# FAZ-12
_faz12 = _safe_import(
    "faz12_engine.faz12_autoadjust",
    ["faz12_run_once", "faz12_auto_profile"],
)
faz12_run_once = (_faz12 or {}).get("faz12_run_once")
faz12_auto_profile = (_faz12 or {}).get("faz12_auto_profile")

# FAZ-13 ORCHESTRATOR + GOD-LAYER
_faz13_orch = _safe_import(
    "faz13_engine.faz13_orchestrator",
    [
        "normalize_manual_text",
        "normalize_visual_meta",
        "normalize_api_data",
        "run_faz13_auto_pipeline",
        "faz13_daily_coupon",
        "faz13_upcoming_coupon",
        "faz13_league_coupon",
        "faz13_live_coupon",
    ],
)
normalize_manual_text = (_faz13_orch or {}).get("normalize_manual_text")
normalize_visual_meta = (_faz13_orch or {}).get("normalize_visual_meta")
normalize_api_data = (_faz13_orch or {}).get("normalize_api_data")
run_faz13_auto_pipeline = (_faz13_orch or {}).get("run_faz13_auto_pipeline")
faz13_daily_coupon = (_faz13_orch or {}).get("faz13_daily_coupon")
faz13_upcoming_coupon = (_faz13_orch or {}).get("faz13_upcoming_coupon")
faz13_league_coupon = (_faz13_orch or {}).get("faz13_league_coupon")
faz13_live_coupon = (_faz13_orch or {}).get("faz13_live_coupon")

# FAZ-GLOBAL LEAGUE AUTO-DETECT (şimdilik sadece import, kullanım opsiyonel)
try:
    from faz13_engine.league_autodetect import guess_league  # noqa: F401
except Exception:
    guess_league = None  # type: ignore

_faz13_god = _safe_import("faz13_engine.faz13_god_layer", ["run_faz13_with_god_layer"])
run_faz13_with_god_layer = (_faz13_god or {}).get("run_faz13_with_god_layer")

# FAZ-17 market adjust
_faz17 = _safe_import("faz17_engine.faz17_market_adjust", ["faz17_market_adjust"])
faz17_market_adjust = (_faz17 or {}).get("faz17_market_adjust")

# FAZ-22 meta engine (FULL STACK)
_faz22 = _safe_import("faz22_engine.faz22_meta", ["faz22_meta_engine"])
faz22_meta_engine = (_faz22 or {}).get("faz22_meta_engine")

# Ultra OCR Engine v3 opsiyonel import (FAZ-13 visual için)
_faz13_ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13_ocr or {"ultra_ocr_engine_v3": None}).get("ultra_ocr_engine_v3")

# ================================================================
# 🌐 FAZ-23 NEWS + MULTI-DATA ENGINE IMPORT
# ================================================================
_faz23 = _safe_import(
    "faz23_engine.faz23_meta_engine",
    [
        "faz23_prematch_predict",
        "faz23_live_predict",
        "faz23_news_enrich",
    ],
)
faz23_prematch_predict = (_faz23 or {}).get("faz23_prematch_predict")
faz23_live_predict = (_faz23 or {}).get("faz23_live_predict")
faz23_news_enrich = (_faz23 or {}).get("faz23_news_enrich")

# Multi-data sağlayıcı çekirdeği (örn. maçkolik/flashscore/NBA/Euroleague füzyonu)
_faz_live_core = _safe_import(
    "live_providers.core",
    ["get_live_match_global", "HoopbrainLiveError"],
)
get_live_match_global = (_faz_live_core or {}).get("get_live_match_global")
HoopbrainLiveError = (_faz_live_core or {}).get("HoopbrainLiveError")

# ================================================================
# 🧠 FALLBACKS & MEMORY HELPERS (FAZ-7.9)
# ================================================================
def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("JSON kaydedilemedi: %s (%s)", path, e)


def faz7_load_memory() -> Dict[str, Any]:
    mem = _load_json(FAZ7_MEMORY_FILE, {})
    if not isinstance(mem, dict):
        mem = {}
    if "stats" not in mem or not isinstance(mem.get("stats"), dict):
        mem["stats"] = {}
    return mem


def faz7_save_memory(mem: Dict[str, Any]) -> None:
    if not isinstance(mem, dict):
        return
    if "stats" not in mem or not isinstance(mem.get("stats"), dict):
        mem["stats"] = {}
    _save_json(FAZ7_MEMORY_FILE, mem)


def faz7_touch_stat(key: str, delta: int = 1) -> None:
    """
    FAZ-7.9 hafızada basit metrik sayacı.
    Örn: total_matches, total_coupons vs.
    """
    try:
        mem = faz7_load_memory()
        stats = mem.get("stats", {})
        cur = stats.get(key, 0)
        try:
            cur_int = int(cur)
        except Exception:
            cur_int = 0
        stats[key] = cur_int + delta
        mem["stats"] = stats
        faz7_save_memory(mem)
    except Exception as e:
        log.error("faz7_touch_stat hata: %s", e, exc_info=True)

# ================================================================
# 🧱 FAZ-10 HardSync WRAPPER
# ================================================================
def faz10_hardsync(
    brain: Dict[str, Any],
    calib: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    FAZ-10 stabilite katmanı:
    - faz10_stability_check yoksa fallback döner.
    - Varsa "FAZ-13" kaynağı için meta ile birlikte çalışır.
    """
    if faz10_stability_check is None:
        return {
            "regime": "NORMAL",
            "stability_score": 1.0,
            "anomaly_level": 0.0,
            "suggested_mode": brain.get("mode", "INIT"),
            "bucket": (calib or {}).get("bucket", "MID") if calib else "MID",
            "lock": False,
            "lock_reason": "NO_FAZ10_MODULE",
        }

    try:
        # ⚠️ ÖNEMLİ: faz10_stability_check(source_type, meta) imzasına uyumlu
        stability = faz10_stability_check("FAZ-13", {}) or {}
    except Exception as e:
        log.error("[FAZ-10] Stability check hata: %s", e, exc_info=True)
        stability = {}

    regime = str(stability.get("regime", "NORMAL")).upper()
    score = float(stability.get("stability_score", 1.0) or 1.0)
    anomaly = float(stability.get("anomaly_level", 0.0) or 0.0)
    suggested_mode = str(
        stability.get("suggested_mode", brain.get("mode", "INIT"))
    ).upper()
    bucket = (calib or {}).get("bucket", "MID")
    lock = False
    lock_reason = "NO_LOCK"

    if ENGINEERING_MODE:
        if regime in ("CRITICAL", "UNSTABLE") or anomaly >= 0.7 or score < 0.6:
            lock = True
            lock_reason = "CRITICAL_LOCK"

    return {
        "regime": regime,
        "stability_score": score,
        "anomaly_level": anomaly,
        "suggested_mode": suggested_mode,
        "bucket": bucket,
        "lock": lock,
        "lock_reason": lock_reason,
    }

# ================================================================
# 🔎 ULTRA OCR ENGINE v3 (IMPORT + FALLBACK)
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes) -> Dict[str, Any]:
    """
    Ultra OCR Engine v3:
    - Eğer faz13_engine.ultra_ocr_v3.ultra_ocr_engine_v3 tanımlıysa onu kullan.
    - Yoksa hafif fallback döndür (Fly.io 512 MB uyumlu).
    """
    if _ext_ultra_ocr_engine_v3:
        try:
            return _ext_ultra_ocr_engine_v3(img_bytes)
        except Exception as e:
            log.error("External Ultra OCR Engine v3 hata: %s", e, exc_info=True)

    # Fallback: OCR modülü yoksa sessizce boş dön.
    return {
        "text": "",
        "meta": {
            "engine": "NONE",
            "classifier": "NONE",
            "prob_score": 0.0,
        },
    }

# ================================================================
# 🤖 TELEGRAM BOT & FLASK APP
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)


def _send_long_text(message: types.Message, text: str):
    if not text:
        return
    max_len = 3500
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for ch in chunks:
        bot.reply_to(message, ch)

# ================================================================
# /test_faz13 — FAZ-13 Pipeline Test Komutu
# ================================================================
@bot.message_handler(commands=["test_faz13"])
def cmd_test_faz13(message: types.Message):
    try:
        if not run_faz13_auto_pipeline:
            raise RuntimeError("FAZ-13 orchestrator bağlı değil")

        # Örnek test maçı (dummy meta)
        league = "NBA"
        date = "2025-01-01"
        home = "TEST_HOME"
        away = "TEST_AWAY"

        result = run_faz13_auto_pipeline(
            league=league,
            date=date,
            home_team=home,
            away_team=away,
            full_output=False,    # hafif test modu
            match_key=None        # FAZ-23 devrede değil
        )

        text = (
            "🧪 FAZ-13 Test Çalıştı\n"
            f"🏀 Maç: {result.get('match')}\n"
            f"📌 Fusion Call: {result.get('fusion_total_call')}\n"
            f"🧠 Score Vector: {result.get('internal_score_vector')}\n"
            f"ℹ️ News Range: {result.get('news_summary')}\n"
            f"🔍 Sebepler:\n" +
            "\n".join(f"- {str(r)}" for r in list(result.get("debug_reasons", [])))
        )

        bot.reply_to(message, text, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"❌ /test_faz13 hata: {e}")

# ================================================================
# SAFE OUTPUT ENGINE — Telegram için %100 güvenli metin hazırlama
# ================================================================
import re

def safe_clean(text: str) -> str:
    if not text:
        return ""
    # Telegram Markdown / HTML çakışan karakterler temizlenir
    text = text.replace("*", "") \
               .replace("_", "") \
               .replace("`", "") \
               .replace("[", "(") \
               .replace("]", ")") \
               .replace("|", " | ") \
               .replace("<", "(") \
               .replace(">", ")")

    # Çift boşluk / bozuk newline düzeltmesi
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" .", ".")
    return text.strip()


def safe_send(bot, chat_id, text: str, chunk=3500):
    """
    Telegram'ın maksimum 4096 limiti var.
    Güvenli olması için 3500 karaktere böldük.
    """
    text = safe_clean(text)

    if len(text) <= chunk:
        bot.send_message(chat_id, text)
        return

    # Mesaj bölme
    parts = [text[i:i+chunk] for i in range(0, len(text), chunk)]
    for p in parts:
        bot.send_message(chat_id, p)



# ================================================================
# /mac – Maç Tahmini (FAZ-13 NEWS PIPELINE + TEAM TOTALS) - PLAIN
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_mac(message: types.Message):
    try:
        if not run_faz13_auto_pipeline:
            raise RuntimeError("FAZ-13 orchestrator bağlı değil")

        # Komuttan ham metni al
        raw = message.text or ""
        txt = raw.replace("/mac", "", 1).strip()

        # Basit format kontrolü
        if "|" not in txt:
            safe_send(
                bot,
                message.chat.id,
                "❌ Format hatalı.\n\n"
                "Doğru format:\n"
                "/mac Euroleague | 2025-12-05 | Crvena Zvezda - Barcelona"
            )
            return

        # Kullanıcı formatını çöz
        parts = [p.strip() for p in txt.split("|")]
        if len(parts) != 3:
            safe_send(
                bot,
                message.chat.id,
                "❌ Format hatalı. 3 bölüm olmalı:\n"
                "Lig | Tarih | Ev - Deplasman"
            )
            return

        league = parts[0]
        date = parts[1]
        teams_part = parts[2]

        # Ev - Deplasman çöz
        if "-" not in teams_part:
            safe_send(
                bot,
                message.chat.id,
                "❌ Takım formatı hatalı. (Ev - Deplasman)"
            )
            return

        home_team, away_team = [t.strip() for t in teams_part.split("-", 1)]
        if not home_team or not away_team:
            safe_send(
                bot,
                message.chat.id,
                "❌ Takım bilgisi okunamadı."
            )
            return

        # ---------------------------------------------------------
        # 4) FAZ-13 PIPELINE ÇAĞIR
        # ---------------------------------------------------------
        result = run_faz13_auto_pipeline(
            league=league,
            date=date,
            home_team=home_team,
            away_team=away_team,
            full_output=True,
            match_key=None,  # FAZ-23 bağımsız, şimdilik kapalı
        )

        league_family = result.get("league_family", "-")
        per = result.get("per_period_projection") or {}
        team_totals = result.get("team_totals") or {}

    # ------------------------------------------------------------
    # 5) TELEGRAM ÇIKTISI - PLAIN SAFE FORMAT (vFinal Pro)
    # ------------------------------------------------------------
    lines: List[str] = []

    match_name   = result.get("match", "")
    match_date   = result.get("date", "-")
    league_name  = result.get("league", "-")
    league_family = result.get("league_family", "-")

    fusion_total = result.get("fusion_total_call", "-")
    score_vec    = result.get("internal_score_vector") or []

    low = mid = high = fusion_total
    if isinstance(score_vec, (list, tuple)) and len(score_vec) == 3:
        low, mid, high = score_vec

    # Periyot toplamları
    q1 = per.get("q1_total", "-")
    q2 = per.get("q2_total", "-")
    q3 = per.get("q3_total", "-")
    q4 = per.get("q4_total", "-")
    h1 = per.get("h1_total", "-")
    h2 = per.get("h2_total", "-")
    gt = per.get("game_total", "-")

    # Takım skorları
    ht_name  = team_totals.get("home_team", home_team)
    at_name  = team_totals.get("away_team", away_team)
    ht_total = team_totals.get("home_total", "-")
    at_total = team_totals.get("away_total", "-")

    # Analiz / haber tarafı
    baseline    = result.get("league_baseline")
    home_boost  = result.get("home_advantage_boost")
    h_strength  = result.get("final_strength_home")
    a_strength  = result.get("final_strength_away")
    h_share     = result.get("share_home")
    a_share     = result.get("share_away")

    # --------------------------------------------------------
    # Başlık
    # --------------------------------------------------------
    lines.append("🏀 FAZ-13 Tahmin (vFinal Pro)")
    lines.append("")
    lines.append(f"Maç: {match_name}")
    lines.append(f"Tarih: {match_date}")
    lines.append(f"Lig: {league_name} | Lig Family: {league_family}")
    lines.append("")
    lines.append("────────────────────")
    lines.append("")

    # --------------------------------------------------------
    # Toplam tahmini
    # --------------------------------------------------------
    lines.append("🪐 TOPLAM TAHMİNİ")
    lines.append(f"Fusion Total: {fusion_total}")
    lines.append(f"Bant: {low} – {high}")
    lines.append(f"Score Vector: [{low}, {mid}, {high}]")
    lines.append("")
    lines.append("────────────────────")
    lines.append("")

    # --------------------------------------------------------
    # Periyot projeksiyonları
    # --------------------------------------------------------
    lines.append("📊 PERİYOT PROJEKSİYONLARI")
    lines.append(f"1Ç: {q1}")
    lines.append(f"2Ç: {q2}")
    lines.append(f"3Ç: {q3}")
    lines.append(f"4Ç: {q4}")
    lines.append(f"İY: {h1} | İİY: {h2} | Maç: {gt}")
    lines.append("")
    lines.append("────────────────────")
    lines.append("")

    # --------------------------------------------------------
    # Takım skor tahmini
    # --------------------------------------------------------
    lines.append("🎯 TAKIM SKOR TAHMİNİ")
    lines.append(f"Ev Sahibi ({ht_name}): {ht_total}")
    lines.append(f"Deplasman ({at_name}): {at_total}")
    lines.append("")
    lines.append("────────────────────")
    lines.append("")

    # --------------------------------------------------------
    # Haber / Analiz
    # --------------------------------------------------------
    lines.append("🧠 HABER / ANALİZ")

    if baseline is not None:
        lines.append(f"• Baseline: {baseline}")
    if home_boost is not None:
        lines.append(f"• Home Boost: {home_boost}")
    if h_strength is not None and a_strength is not None:
        lines.append(f"• Strength → H:{h_strength} A:{a_strength}")
    if h_share is not None and a_share is not None:
        lines.append(f"• Win Share → H:{h_share} A:{a_share}")

    lines.append("")
    lines.append("────────────────────")

    text = "\n".join(lines)
    safe_send(bot, message.chat.id, text)

# ================================================================
# 📊 /status
# ================================================================
@bot.message_handler(commands=["status"])
def cmd_status(message: types.Message):
    mem = faz7_load_memory()
    stats = mem.get("stats", {})
    total_matches = stats.get("total_matches", 0)
    total_coupons = stats.get("total_coupons", 0)

    # FAZ-10 HardSync, sadece durum raporu (lock uygulatmıyoruz)
    faz10_state = faz10_hardsync(mem, {"bucket": "MID"})

    lines: List[str] = []
    lines.append("✅ Bot çalışıyor.")
    lines.append("Mod: Fly.io + Webhook + Flask")
    lines.append(f"ENGINEERING_MODE: {'ON' if ENGINEERING_MODE else 'OFF'}")
    lines.append("")
    lines.append(f"FAZ-7.9 hafıza dosyası: {FAZ7_MEMORY_FILE}")
    lines.append(f"Toplam maç: {total_matches} | Toplam kupon: {total_coupons}")
    lines.append("")
    lines.append(f"FAZ-10 modul: {'AKTİF' if faz10_stability_check else 'YOK (FALLBACK)'}")
    lines.append(
        "FAZ-10 regime: {reg} | score={score:.3f} | anomaly={anom:.3f} | "
        "lock={lock} ({reason})".format(
            reg=faz10_state.get("regime", "NORMAL"),
            score=float(faz10_state.get("stability_score", 1.0) or 1.0),
            anom=float(faz10_state.get("anomaly_level", 0.0) or 0.0),
            lock=bool(faz10_state.get("lock", False)),
            reason=faz10_state.get("lock_reason", "NO_LOCK"),
        )
    )
    lines.append(f"FAZ-11 feedback: {'AKTİF' if faz11_feedback else 'YOK'}")
    lines.append(f"FAZ-12 autoadjust: {'AKTİF' if faz12_run_once else 'YOK'}")
    lines.append(f"FAZ-13 orchestrator: {'AKTİF' if _faz13_orch else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-13 GOD-LAYER: {'AKTİF' if _faz13_god else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-17 market: {'AKTİF' if faz17_market_adjust else 'YOK'}")
    lines.append(f"FAZ-22 meta engine: {'AKTİF' if faz22_meta_engine else 'YOK'}")
    lines.append("")
    lines.append(
        "Ultra OCR Engine v3: {state}".format(
            state="AKTİF (external)" if _ext_ultra_ocr_engine_v3
            else "FALLBACK (GPU/OCR modülleri henüz bağlı değil)"
        )
    )
    lines.append(
        "FAZ-23 META ENGINE: {state}".format(
            state="AKTİF (NEWS+MULTI-DATA)"
            if faz23_prematch_predict and get_live_match_global
            else "YOK / EKSİK MODÜL"
        )
    )
    text = "\n".join(lines)
    bot.reply_to(message, text)

# ================================================================
# 🌐 /proxytest — Proxy Test (hoopbrain-proxy)
# ================================================================
@bot.message_handler(commands=["proxytest"])
def proxytest(message: types.Message):
    import requests

    try:
        r = requests.get("https://hoopbrain-proxy.fly.dev/ping", timeout=5)
        bot.send_message(message.chat.id, f"Proxy Çalışıyor: {r.text}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Proxy Hatası: {str(e)}")

# ================================================================
# 🏀 /mac13 — MANUAL INPUT (FAZ-13 + GOD-LAYER)
# ================================================================
@bot.message_handler(commands=["mac13"])
def cmd_manual_match(message: types.Message):
    try:
        if not normalize_manual_text or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        fusion = normalize_manual_text(message.text)
        if not fusion or not isinstance(fusion, dict):
            raise ValueError("normalize_manual_text boş veya dict değil")

        # FAZ-13 + GOD-LAYER
        result_text = run_faz13_with_god_layer("manual", fusion)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)
        _send_long_text(message, result_text)

        # FAZ-11 feedback + tarihçe
        if faz11_feedback:
            try:
                hist = _load_json(FAZ11_HISTORY_FILE, [])
                fb = faz11_feedback("manual", fusion, result_text)
                hist.append(fb)
                _save_json(FAZ11_HISTORY_FILE, hist)
            except Exception as e:
                log.error("[FAZ-11] feedback hata: %s", e, exc_info=True)

    except Exception as e:
        log.error("[FAZ-13 MANUAL ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ FAZ-13 manual input işlenemedi.\n"
            "Örnek: /mac13 BOS ORL 220.5 U 1.46",
        )

# ================================================================
# 🖼 /mac_img — VISUAL EXTREME MODE (FAZ-13 + OCR + GOD-LAYER)
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_visual_request(message: types.Message):
    bot.reply_to(
        message,
        "🧬 FAZ-13 EXTREME MODE aktif!\n"
        "Maç görselini gönder → OCR + GOD-LAYER pipeline çalışacak.",
    )


@bot.message_handler(content_types=["photo", "document"])
def cmd_visual_upload(message: types.Message):
    """
    Bu handler hem /mac_img sonrası, hem de direkt foto belgesinde devreye girer.
    FAZ-13 GOD-LAYER + Ultra OCR v3 pipeline kullanır.
    Ayrıca görseli VISUAL_STACK içine push eder (multi-screen analiz için).
    """

    try:
        # 1) İçerik tipi doğrulama
        if message.content_type not in ["photo", "document"]:
            bot.reply_to(
                message,
                "❌ Yalnızca fotoğraf veya belge kabul edilir.",
            )
            return

        if not normalize_visual_meta or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        # 2) Telegram file ID çıkar
        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id

        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        # 3) Görsel indir
        import requests

        bot.reply_to(message, "🛰 Görsel alındı → OCR çalışıyor...")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        img_bytes = r.content

        # 4) OCR ÇALIŞTIR
        ocr = ultra_ocr_engine_v3(img_bytes) or {}
        text = ocr.get("text", "") or ""
        meta = ocr.get("meta", {}) or {}

        if not isinstance(meta, dict):
            meta = {}

        if not text.strip():
            bot.reply_to(
                message,
                "❌ OCR başarısız → Daha net bir görsel gönder.",
            )
            return

        # 5) VISUAL STACK — SAFE PUSH
        VISUAL_STACK.append(
            {
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "text": text,
                "meta": meta,
            }
        )
        if len(VISUAL_STACK) > VISUAL_STACK_MAX:
            VISUAL_STACK.pop(0)

        # 6) normalize_visual_meta güvenli hale getir
        fusion = normalize_visual_meta(text)
        if not isinstance(fusion, dict):
            fusion = {"raw": text}

        # 7) GOD-LAYER ÇALIŞTIR
        result = run_faz13_with_god_layer("visual", fusion)
        result = str(result)

        # 8) FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        # 9) OCR meta ekle
        result = (
            result +
            "\n\n🧪 FAZ-13 OCR META\n"
            f"Engine: {meta.get('engine', '-')} | "
            f"Cls: {meta.get('classifier', '-')} | "
            f"Score: {meta.get('prob_score', 0):.3f}"
        )

        _send_long_text(message, result)

    except Exception as e:
        log.error("[FAZ-13 VISUAL ERROR] %s", e)
        bot.reply_to(
            message,
            "❌ Görsel işleme sırasında hata oluştu.",
        )

# ================================================================
# ⚡ /live13 — HYBRID INPUT (FAZ-13, canlı maç için)
# ================================================================
@bot.message_handler(commands=["live13"])
def cmd_live13(message: types.Message):
    try:
        if not normalize_manual_text or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
        fusion = normalize_manual_text(args)
        result = run_faz13_with_god_layer("live", fusion)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)
        _send_long_text(message, result)

    except Exception as e:
        log.error("[FAZ-13 LIVE13 ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /live13 komutunda hata.\n"
            "Örnek: /live13 LAL BOS 220.5 U 1.90",
        )

# ================================================================
# 📚 VISUAL STACK KOMUTLARI (FAZ-13 STACK:ON)
# ================================================================
@bot.message_handler(commands=["add_visual_item"])
def cmd_add_visual_item(message: types.Message):
    """
    Manuel olarak VISUAL_STACK'e string eklemek için.
    Örn: /add_visual_item DEN-UTA 3Q istatistik
    """
    raw = message.text or ""
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "Kullanım: /add_visual_item açıklama",
        )
        return

    item_text = parts[1].strip()
    VISUAL_STACK.append(
        {
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "text": item_text,
            "meta": {"engine": "MANUAL"},
        }
    )
    if len(VISUAL_STACK) > VISUAL_STACK_MAX:
        VISUAL_STACK.pop(0)

    bot.reply_to(message, f"✅ Visual stacke eklendi. Toplam: {len(VISUAL_STACK)}")


@bot.message_handler(commands=["visual_stack"])
def cmd_visual_stack(message: types.Message):
    if not VISUAL_STACK:
        bot.reply_to(message, "Visual stack boş.")
        return

    lines: List[str] = []
    lines.append(f"📚 VISUAL STACK (son {len(VISUAL_STACK)} kayıt):")
    for i, item in enumerate(VISUAL_STACK[-VISUAL_STACK_MAX:], start=1):
        preview = item.get("text", "").replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + "..."
        lines.append(f"{i:02d}) {preview}")

    _send_long_text(message, "\n".join(lines))


@bot.message_handler(commands=["visual_stack_status"])
def cmd_visual_stack_status(message: types.Message):
    bot.reply_to(
        message,
        f"Visual stack boyutu: {len(VISUAL_STACK)} / {VISUAL_STACK_MAX}",
    )


@bot.message_handler(commands=["reset_visual"])
def cmd_reset_visual(message: types.Message):
    VISUAL_STACK.clear()
    bot.reply_to(message, "♻️ Visual stack temizlendi.")

# ================================================================
# 🌌 FAZ-23 NEWS + MULTI-DATA ENGINE HELPERS
# ================================================================
def faz23_build_context(match_code: str, mode: str = "prematch") -> Dict[str, Any]:
    """
    Multi-data + news füzyonunu tek yerde toplar.
    - match_code: live_providers.core tarafında anlamlı olan ID / key
    - mode: "prematch" veya "live"

    1) get_live_match_global ile tüm sağlayıcıları fuse eder.
    2) faz23_news_enrich varsa haber / sakatlık / yorum sinyallerini ekler.
    """
    if not get_live_match_global:
        raise RuntimeError("live_providers.core.get_live_match_global modülü yok")

    raw_ctx: Dict[str, Any] = {}
    try:
        raw_ctx = get_live_match_global(match_code, mode=mode) or {}
    except Exception as e:
        if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
            # Domain spesifik hata, direkt yukarı taşı.
            raise
        log.error("[FAZ-23] get_live_match_global hata: %s", e, exc_info=True)
        raise

    if not isinstance(raw_ctx, dict):
        raw_ctx = {}

    # Haber / sakatlık / yorum sinyalleri ile zenginleştir
    if faz23_news_enrich:
        try:
            enriched = faz23_news_enrich(raw_ctx, mode=mode) or raw_ctx
            if isinstance(enriched, dict):
                raw_ctx = enriched
        except Exception as e:
            log.error("[FAZ-23] news_enrich hata: %s", e, exc_info=True)

    # Minimal meta alanı ekle (FAZ-10/11/12 vs için)
    raw_ctx.setdefault("mode", mode.upper())
    raw_ctx.setdefault("engine", "FAZ-23")
    return raw_ctx

# ================================================================
# 🔭 FAZ-23 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["meta23"])
def cmd_meta23(message: types.Message):
    """
    FAZ-23 PREMATCH tahmin motoru.
    Kullanım: /meta23 MATCH_CODE
    """
    try:
        if not faz23_prematch_predict or not get_live_match_global:
            bot.reply_to(
                message,
                "❌ FAZ-23 META ENGINE henüz tam bağlı değil.\n"
                "Eksik modül: faz23_engine.faz23_meta_engine veya live_providers.core",
            )
            return

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(
                message,
                "⚙ Kullanım:\n"
                "/meta23 LAL@BOS\n"
                "veya live_providers.core içinde tanımlı maç ID'si.",
            )
            return

        match_code = parts[1].strip()
        try:
            ctx = faz23_build_context(match_code, mode="prematch")
        except Exception as e:
            if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
                bot.reply_to(message, f"❌ FAZ-23 veri hatası: {str(e)}")
                return
            raise

        # FAZ-10 HardSync'i bilgi amaçlı çalıştırabiliriz (lock uygulatmıyoruz)
        faz10_state = faz10_hardsync(ctx, {"bucket": ctx.get("bucket", "MID")})
        ctx["faz10_state"] = faz10_state

        text = faz23_prematch_predict(ctx)
        if not isinstance(text, str):
            text = str(text)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)
        _send_long_text(message, text)

    except Exception as e:
        log.error("[FAZ-23 META23 ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /meta23 çalışırken hata oluştu.\n"
            "Kullanım: /meta23 MATCH_CODE",
        )


@bot.message_handler(commands=["meta23_live"])
def cmd_meta23_live(message: types.Message):
    """
    FAZ-23 LIVE tahmin motoru.
    Kullanım: /meta23_live MATCH_CODE
    """
    try:
        if not faz23_live_predict or not get_live_match_global:
            bot.reply_to(
                message,
                "❌ FAZ-23 LIVE META ENGINE henüz tam bağlı değil.\n"
                "Eksik modül: faz23_engine.faz23_meta_engine veya live_providers.core",
            )
            return

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(
                message,
                "⚙ Kullanım:\n"
                "/meta23_live LAL@BOS\n"
                "veya live_providers.core içinde tanımlı maç ID'si.",
            )
            return

        match_code = parts[1].strip()
        try:
            ctx = faz23_build_context(match_code, mode="live")
        except Exception as e:
            if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
                bot.reply_to(message, f"❌ FAZ-23 veri hatası: {str(e)}")
                return
            raise

        faz10_state = faz10_hardsync(ctx, {"bucket": ctx.get("bucket", "MID")})
        ctx["faz10_state"] = faz10_state

        text = faz23_live_predict(ctx)
        if not isinstance(text, str):
            text = str(text)

        faz7_touch_stat("total_matches", 1)
        _send_long_text(message, text)

    except Exception as e:
        log.error("[FAZ-23 META23_LIVE ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /meta23_live çalışırken hata oluştu.\n"
            "Kullanım: /meta23_live MATCH_CODE",
        )

# ================================================================
# 🧠 FAZ-22 META ENGINE KOMUTU (opsiyonel, FULL STACK)
# ================================================================
@bot.message_handler(commands=["meta22"])
def cmd_meta22(message: types.Message):
    """
    FAZ-22 META ENGINE:
    Kullanım: /meta22 SERBEST_METIN
    İçerik faz22_meta_engine'e ham context olarak iletilir.
    """
    if not faz22_meta_engine:
        bot.reply_to(
            message,
            "❌ FAZ-22 META ENGINE bağlı değil "
            "(faz22_engine.faz22_meta.faz22_meta_engine bulunamadı).",
        )
        return

    raw = message.text or ""
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "Kullanım: /meta22 herhangi bir açıklama / JSON / context",
        )
        return

    payload = {
        "raw": parts[1].strip(),
        "chat_id": message.chat.id,
        "mode": "MANUAL",
    }

    try:
        out = faz22_meta_engine(payload)
    except Exception as e:
        log.error("[FAZ-22 META ENGINE ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ FAZ-22 meta engine çalışırken hata oluştu.")
        return

    if isinstance(out, str):
        text = out
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)

    _send_long_text(message, text)

# ================================================================
# 🌐 FLASK ROUTES (WEBHOOK + HEALTH)
# ================================================================
@app.route("/", methods=["GET"])
def index():
    return "HoopBrain FAZ-CORE: OK", 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """
    Fly.io + Gunicorn altında Telegram webhook giriş noktası.
    """
    if request.headers.get("content-type") == "application/json":
        update_json = request.get_data().decode("utf-8")
        try:
            update = telebot.types.Update.de_json(update_json)
            bot.process_new_updates([update])
        except Exception as e:
            log.error("Webhook update parse hatası: %s", e, exc_info=True)
    else:
        log.warning(
            "Bilinmeyen content-type: %s",
            request.headers.get("content-type"),
        )

    return "OK", 200

# ================================================================
# 🚀 LOCAL DEV İÇİN POLLING (Fly.io'da kullanılmıyor)
# ================================================================
def _maybe_set_webhook():
    """
    WEBHOOK_URL set edilmişse Telegram webhook adresini günceller.
    Fly.io tarafında ilk deploy'da bir kere çalışması yeterli.
    """
    if not WEBHOOK_URL:
        log.info("WEBHOOK_URL tanımlı değil, webhook set edilmeyecek.")
        return

    try:
        info = bot.get_webhook_info()
        if info.url != WEBHOOK_URL:
            bot.delete_webhook()
            bot.set_webhook(url=WEBHOOK_URL, max_connections=40)
            log.info("Webhook güncellendi: %s", WEBHOOK_URL)
        else:
            log.info("Webhook zaten doğru URL'de.")
    except Exception as e:
        log.error("Webhook ayarlanamadı: %s", e, exc_info=True)


if __name__ == "__main__":
    # Local test için: Webhook yoksa polling aç
    if not WEBHOOK_URL:
        log.info(
            "Local / polling modu. WEBHOOK_URL yok, "
            "bot.infinity_polling başlıyor..."
        )
        bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
    else:
        _maybe_set_webhook()
        log.info("Flask dev server başlıyor (webhook modu).")
        app.run(host="0.0.0.0", port=PORT)
