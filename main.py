# ================================== main.py =====================================
from __future__ import annotations
import os
import json
import logging
from typing import Any, Dict, Optional, Tuple
from flask import Flask, request
import telebot
from telebot import types

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("ZeynalBotCore")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))
AUTO_SET_WEBHOOK = os.getenv("AUTO_SET_WEBHOOK", "0").strip() == "1"
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True) if BOT_TOKEN else None

def _safe_import(module_path: str, name: str):
    try:
        module = __import__(module_path, fromlist=[name])
        return getattr(module, name)
    except Exception as e:
        log.warning(f"Optional import failed: {module_path}.{name} -> {e}")
        return None

fetch_market = _safe_import("faz17_engine.faz17_market_fetcher", "fetch_market")
run_faz13_auto_pipeline = _safe_import("faz13_engine.faz13_orchestrator", "run_faz13_auto_pipeline")
faz22_meta_engine = _safe_import("faz22_engine.faz22_meta", "faz22_meta_engine")
faz23_apply_state = _safe_import("faz23_engine.faz23_state", "faz23_apply_state")
faz23_feedback = _safe_import("faz23_engine.faz23_stats", "faz23_feedback")

def _ok(v: Any) -> str:
    return "OK" if v else "MISSING"

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route(f"/debug/env", methods=["GET"])
def debug_env():
    return {
        "BOT_TOKEN": _ok(BOT_TOKEN),
        "WEBHOOK_URL": _ok(WEBHOOK_URL),
        "AUTO_SET_WEBHOOK": AUTO_SET_WEBHOOK,
    }, 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if not bot:
        return "ERR", 200
    try:
        payload = request.get_json(force=True)
        update = types.Update.de_json(payload)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        log.exception("Webhook processing failed")
        return "ERR", 200

_webhook_set_once = False
@app.before_request
def _maybe_set_webhook_once():
    global _webhook_set_once
    if AUTO_SET_WEBHOOK and not _webhook_set_once and bot and WEBHOOK_URL:
        try:
            bot.set_webhook(WEBHOOK_URL)
            _webhook_set_once = True
            log.info(f"Webhook set: {WEBHOOK_URL}")
        except Exception as e:
            log.warning(f"Failed to set webhook: {e}")

@bot.message_handler(commands=["status"])
def cmd_status(message: types.Message):
    lines = [
        f"BOT_TOKEN: {_ok(BOT_TOKEN)}",
        f"WEBHOOK_URL: {_ok(WEBHOOK_URL)}",
        f"FAZ-13: {_ok(run_faz13_auto_pipeline)}",
        f"FAZ-17: {_ok(fetch_market)}",
        f"FAZ-22: {_ok(faz22_meta_engine)}",
        f"FAZ-23: {_ok(faz23_apply_state)}",
    ]
    bot.reply_to(message, "🤖 Zeynal Core /status\n" + "\n".join(lines))

def _parse_mac_command(text: str) -> Optional[Dict[str, str]]:
    try:
        raw = (text or "").strip()
        if not raw.startswith("/mac"):
            return None
        raw = raw.replace("/mac", "", 1).strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3:
            return None
        league_in, date_str, matchup = parts
        league = league_in.upper()
        if " - " in matchup:
            home, away = [x.strip() for x in matchup.split(" - ", 1)]
        elif "-" in matchup:
            home, away = [x.strip() for x in matchup.split("-", 1)]
        else:
            return None
        return {
            "league": league,
            "date_str": date_str,
            "home": home,
            "away": away
        }
    except Exception:
        return None

def _format_faz13_reply(data: Dict[str, Any]) -> str:
    periods = data.get("periods", {})
    p1 = periods.get("q1")
    p2 = periods.get("q2")
    p3 = periods.get("q3")
    p4 = periods.get("q4")
    h1 = periods.get("h1")
    h2 = periods.get("h2")
    lines = [
        f"🧠 Base: {data.get('base_pred')}",
        f"📦 Band: {data.get('band')}",
        f"✅ Confidence: {data.get('confidence')}",
        f"⚠️ Risk: {data.get('risk')}",
    ]
    market = data.get("market", {})
    lines.append(
        f"📈 Market: {{'line': {market.get('line')}, "
        f"'delta': {market.get('delta')}, "
        f"'provider': {market.get('provider')}}}"
    )
    lines.append("")
    lines.append("📊 Periyot Tahminleri:")
    lines.append(f"• 1Q: {p1}")
    lines.append(f"• 2Q: {p2} (İY: {h1})")
    lines.append(f"• 3Q: {p3}")
    lines.append(f"• 4Q: {p4} (2Y: {h2})")
    return "\n".join(lines)

@bot.message_handler(commands=["mac"])
def cmd_mac(message: types.Message):
    if not (fetch_market and run_faz13_auto_pipeline):
        bot.reply_to(message, "🚫 Market veya FAZ-13 motoru yüklü değil.")
        return
    parsed = _parse_mac_command(message.text)
    if not parsed:
        bot.reply_to(message, "🚫 Komut hatalı. Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors")
        return
    league = parsed["league"]
    date_str = parsed["date_str"]
    home = parsed["home"]
    away = parsed["away"]
    try:
        market_data, market_meta = (None, None)
        if fetch_market:
            market_data, meta = fetch_market(league, date_str, home, away)
            market_meta = meta
        faz13_data = run_faz13_auto_pipeline(
            league=league,
            home=home,
            away=away,
            date_str=date_str,
            market_data=market_data
        )
        faz22_data = None
        if faz22_meta_engine:
            faz22_data = faz22_meta_engine({
                "league": faz13_data["match"]["league"],
                "base_pred": faz13_data["base_pred"],
                "band": faz13_data["band"],
                "confidence": faz13_data["confidence"],
                "market": {
                    "line": market_data.get("totals_line") if market_data else None,
                    "provider": market_data.get("provider") if market_data else None,
                    "used": market_meta.get("market", {}).get("used") if market_meta else None,
                }
            })
        if faz23_apply_state and faz22_data:
            try:
                faz23_apply_state(
                    league=league,
                    home=home,
                    away=away,
                    date_str=date_str,
                    result=faz22_data
                )
            except Exception as e:
                log.warning(f"FAZ-23 apply state failed: {e}")
        # Hangi veri gösterilecek: FAZ-22 çıktısı varsa onu, yoksa FAZ-13
        data_to_show = faz22_data or faz13_data
        reply = f"🏀 {home} — {away}\n{league} | {date_str}\n\n"
        reply += _format_faz13_reply({
            "base_pred": data_to_show["base_pred"],
            "band": data_to_show["band"],
            "confidence": data_to_show["confidence"],
            "risk": data_to_show.get("risk", "-"),
            "market": {
                "line": data_to_show.get("market", {}).get("line"),
                "delta": data_to_show.get("market", {}).get("delta"),
                "provider": data_to_show.get("market", {}).get("provider"),
            },
            "periods": faz13_data["periods"],
        })
        bot.reply_to(message, reply)
    except Exception as e:
        log.exception("FAZ-13 pipeline crashed")
        bot.reply_to(message, f"❌ FAZ-13 pipeline crashed: {e}")

# ---------------------------------------------------------------------
# Mesaj biçimleme (sade – f-string iç içelik yok)
def _format_faz13_reply_simple(league: str, date_str: str,
                               home: str, away: str,
                               base: Any, band: Any,
                               confidence: Any, risk: Any,
                               market: Dict[str, Any],
                               periods: Dict[str, Any]) -> str:
    m_line = market.get("line")
    m_delta = market.get("delta")
    m_provider = market.get("provider")

    p1 = periods.get("q1")
    p2 = periods.get("q2"); h1 = periods.get("h1")
    p3 = periods.get("q3")
    p4 = periods.get("q4"); h2 = periods.get("h2")

    lines = []
    lines.append(f"🏀 {home} — {away}")
    lines.append(f"{league} | {date_str}")
    lines.append("")
    lines.append(f"🧠 Base: {base}")
    lines.append(f"📦 Band: {band}")
    lines.append(f"✅ Confidence: {confidence}")
    lines.append(f"⚠️ Risk: {risk}")
    lines.append(f"📈 Market: {{'line': {m_line}, 'delta': {m_delta}, 'provider': {m_provider}}}")
    lines.append("")
    lines.append("📊 Periyot Tahminleri:")
    lines.append(f"• 1Q: {p1}")
    lines.append(f"• 2Q: {p2} (İY: {h1})")
    lines.append(f"• 3Q: {p3}")
    lines.append(f"• 4Q: {p4} (2Y: {h2})")
    return "\n".join(lines)

@bot.message_handler(commands=["mac"])
def cmd_mac(message: types.Message):
    if not (fetch_market and run_faz13_auto_pipeline):
        bot.reply_to(message, "🚫 Market veya FAZ-13 motoru yüklü değil.")
        return

    parsed = _parse_mac_command(message.text)
    if not parsed:
        bot.reply_to(message, "🚫 Komut hatalı. Örnek: /mac NBA | 2025-12-24 | Lakers - Warriors")
        return

    league = parsed["league"]
    date_str = parsed["date_str"]
    home = parsed["home"]
    away = parsed["away"]

    try:
        # 1) Market verisini çek (tolerant: (market, meta) veya None)
        market_data, market_meta = (None, None)
        try:
            m_out = fetch_market(league, date_str, home, away)
            if isinstance(m_out, tuple) and len(m_out) == 2:
                market_data, market_meta = m_out
            else:
                market_data, market_meta = m_out, {}
        except Exception as e:
            logging.warning(f"[FAZ17] fetch error: {e}")
            market_data, market_meta = None, {}

        # 2) FAZ-13 → team-first base (market_data sadece referans)
        faz13 = run_faz13_auto_pipeline(
            league=league, home=home, away=away, date_str=date_str, market_data=market_data
        )

        # 3) FAZ-22 → meta kalibrasyon (varsa)
        data_to_show = faz13
        if faz22_meta_engine:
            try:
                data_to_show = faz22_meta_engine({
                    "league": league,
                    "base_pred": faz13.get("base_pred"),
                    "band": faz13.get("band"),
                    "confidence": faz13.get("confidence"),
                    "market": {
                        "line": (market_data or {}).get("totals_line"),
                        "provider": (market_data or {}).get("provider"),
                        "used": ((market_meta or {}).get("market") or {}).get("used"),
                    }
                })
                # FAZ-22 periods üretmediği için FAZ-13 periods’u göster
                data_to_show.setdefault("periods", faz13.get("periods", {}))
            except Exception as e:
                logging.warning(f"[FAZ22] meta fail: {e}")
                data_to_show = faz13

        # 4) Mesaj
        reply = _format_faz13_reply_simple(
            league=league,
            date_str=date_str,
            home=home,
            away=away,
            base=data_to_show.get("base_pred"),
            band=data_to_show.get("band"),
            confidence=data_to_show.get("confidence"),
            risk=data_to_show.get("risk", "-"),
            market=data_to_show.get("market", {}),
            periods=faz13.get("periods", {}),
        )
        bot.reply_to(message, reply)

    except Exception as e:
        logging.exception("Pipeline crashed")
        bot.reply_to(message, f"❌ Pipeline crashed: {e}")

# --------------- __main__ BLOĞU: Parantez/tırnaklar kapalı, tek satır -------------
if __name__ == "__main__":
    try:
        if WEBHOOK_URL and bot:
            bot.remove_webhook()
            bot.set_webhook(WEBHOOK_URL)
    except Exception as e:
        logging.warning(f"Webhook set failed: {e}")

    app.run(host="0.0.0.0", port=PORT) 
