from __future__ import annotations

import os
import html
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from providers.espn_adapter import ESPNAdapter  # SADECE ESPN

from faz13_engine import Faz13Engine, PrematchRequest
from faz17_engine import Faz17Engine, MarketRequest
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zeynal-core")


# ============================
# ENV
# ============================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")


# ============================
# HELPERS
# ============================
def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")


def nba_season_string(date_str: str) -> tuple[int, str]:
    d = _parse_date(date_str)
    start = d.year if d.month >= 10 else d.year - 1
    return start, f"{start}–{start + 1}"


def _ensure_dict(obj: Any, name: str) -> Dict[str, Any]:
    v = getattr(obj, name, None)
    if isinstance(v, dict):
        return v
    d: Dict[str, Any] = {}
    setattr(obj, name, d)
    return d


def _ensure_list(obj: Any, name: str) -> list:
    v = getattr(obj, name, None)
    if isinstance(v, list):
        return v
    lst: list = 
    setattr(obj, name, lst)
    return lst


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _inject_season(core: Any, league: str, date_str: str) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    if league.upper() == "NBA":
        season_start, season_str = nba_season_string(date_str)
    else:
        d = _parse_date(date_str)
        season_start = d.year
        season_str = str(d.year)

    meta["season"] = season_start
    meta["season_str"] = season_str

    notes[:] = [n for n in notes if not str(n).lower().startswith("season:")]
    notes.insert(0, f"Season: {season_str}")


def _apply_degraded_mode(core: Any) -> None:
    meta = _ensure_dict(core, "meta")
    notes = _ensure_list(core, "notes")

    cov = meta.get("data_coverage") or {}
    if any(bool(v) for v in cov.values()):
        return

    meta["degraded_mode"] = True
    meta.setdefault("risk", "HIGH")
    notes.append("⚠️ DEGRADED_MODE: Kaynak veriler eksik.")


def _parse_analyze_params(raw: str) -> tuple[str, str, str, str]:
    parts = raw.split()
    if len(parts) < 4:
        raise ValueError("Eksik parametre: /analyze <Lig> <Tarih> <Ev Sahibi> vs <Deplasman>")

    league = parts
    date_str = parts [1]
    rest = parts[2:]

    lower = [p.lower() for p in rest]
    if "vs" in lower:
        i = lower.index("vs")
        home = " ".join(rest[:i])
        away = " ".join(rest[i + 1 :])
    else:
        mid = len(rest) // 2
        home = " ".join(rest[:mid])
        away = " ".join(rest[mid:])

    return league, date_str, home.strip(), away.strip()


def _diag_adapter_list(app: Application) -> str:
    bs = app.bot_data.get("baseline_bootstrapper")
    if not bs:
        return "bootstrapper=NONE"
    ads = getattr(bs, "adapters", ) or 
    names = [a.__class__.__name__ for a in ads]
    return "adapters=" + ",".join(names)


# ============================
# /analyze
# ============================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not text or len(text.split()) < 4:
        await update.message.reply_text(
            "Kullanım: /analyze NBA 2026-01-04 Brooklyn Nets vs Denver Nuggets\n"
            "Lütfen tüm parametreleri doğru girdiğinizden emin olun.",
            disable_web_page_preview=True,
        )
        return

    try:
        _, params = text.split(" ", 1)
        league, date_str, home_raw, away_raw = _parse_analyze_params(params)
    except Exception as e:
        await update.message.reply_text(
            f"Parametre hatası: {html.escape(str(e))}\n"
            "Örnek: /analyze NBA 2026-01-04 Brooklyn Nets vs Denver Nuggets",
            disable_web_page_preview=True,
        )
        return

    # Güvenlik kontrolü: boş takım ismi
    if not home_raw or not away_raw:
        await update.message.reply_text(
            "Hata: Ev sahibi veya deplasman takımı boş olamaz.",
            disable_web_page_preview=True,
        )
        return

    logger.info(
        f"ANALYZE RAW league={league} date={date_str} home='{home_raw}' away='{away_raw}' | "
        f"{_diag_adapter_list(context.application)}"
    )

    # Engine'leri bot_data'dan al
    try:
        faz13: Faz13Engine = context.application.bot_data["faz13"]
        faz17: Faz17Engine = context.application.bot_data["faz17"]
        faz22: Faz22Engine = context.application.bot_data["faz22"]
        faz23: Faz23Engine = context.application.bot_data["faz23"]
        bootstrapper: TeamBaselineBootstrapper = context.application.bot_data["baseline_bootstrapper"]
        baseline_store: TeamBaselineStore = context.application.bot_data["baseline_store"]
    except KeyError as e:
        await update.message.reply_text(
            f"⚠️ Sistem hatası: Bot verileri eksik. {html.escape(str(e))}\n"
            "Lütfen botu yeniden başlatın.",
            disable_web_page_preview=True,
        )
        logger.error(f"Bot data eksik: {e}")
        return

    # Analiz başlat
    try:
        # Örnek: Faz13Engine ile analiz
        request = PrematchRequest(
            league=league,
            date=date_str,
            home=home_raw,
            away=away_raw,
            season_str=nba_season_string(date_str) if league.upper() == "NBA" else str(_parse_date(date_str).year) [1]
        )

        # Faz13 analizi
        result = faz13.analyze(request)
        _inject_season(result, league, date_str)
        _apply_degraded_mode(result)

        # Sonuç mesajı
        await update.message.reply_text(
            f"✅ {home_raw} vs {away_raw} için analiz tamamlandı.\n"
            f"Sezon: {result.meta.get('season_str', 'Bilinmiyor')}\n"
            f"Risk: {result.meta.get('risk', 'NORMAL')}\n"
            f"⚠️ {result.notes if result.notes else 'Not found'}",
            disable_web_page_preview=True,
        )

    except Exception as e:
        await update.message.reply_text(
            f"Analiz sırasında hata oluştu: {html.escape(str(e))}",
            disable_web_page_preview=True,
        )
        logger.error(f"Analiz hatası: {e}", exc_info=True)


# ============================
# UYGULAMA BAŞLATMA (ÖRNEK)
# ============================
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Bot verilerini başlat
    application.bot_data["faz13"] = Faz13Engine()
    application.bot_data["faz17"] = Faz17Engine()
    application.bot_data["faz22"] = Faz22Engine()
    application.bot_data["faz23"] = Faz23Engine()
    application.bot_data["baseline_bootstrapper"] = TeamBaselineBootstrapper()
    application.bot_data["baseline_store"] = TeamBaselineStore()

    # Adaptör ekle (isteğe bağlı)
    bootstrapper = application.bot_data["baseline_bootstrapper"]
    bootstrapper.adapters.append(ESPNAdapter(api_key=ODDS_API_KEY, base_url=ODDS_BASE))

    # Komutu ekle
    application.add_handler(CommandHandler("analyze", analyze_command))

    # Botu başlat
    application.run_polling()


if __name__ == "__main__":
    main()

