# faz23_engine/faz23_datahub.py
# -*- coding: utf-8 -*-

"""
FAZ-23 DATA HUB
----------------
Dış basketbol API'lerini tek yerden yöneten katman.

- API-SPORTS Basketball (istatistik / maç bilgisi / skor / vs.)
- İleride: odds, balldontlie, başka provider'lar

Amaç:
- FAZ-13 / FAZ-23 için "api_data" ve "market_data" paketlerini hazırlamak
- Günlük request limitlerine saygı duymak
- Basit disk + RAM cache ile gereksiz istekleri engellemek
"""

import os
import json
import time
import logging
from typing import Dict, Any, Optional, Tuple

import requests

log = logging.getLogger(__name__)

# ================================================================
# ENV + SABİTLER
# ================================================================
API_BASK_KEY = os.getenv("API_BASK_KEY")  # API-SPORTS basketbol key
API_BASK_BASE = "https://v1.basketball.api-sports.io"

# Yumuşak günlük limit (örn. 40) – Fly secret üzerinden override edilebilir
API_BASK_MAX_PER_DAY = int(os.getenv("API_BASK_MAX_PER_DAY", "40"))

# Fly.io volume kullanıyorsan /data altında tutmak mantıklı
CACHE_DIR = os.getenv("FAZ23_CACHE_DIR", "/data/faz23")
CACHE_FILE = os.path.join(CACHE_DIR, "api_cache.json")
COUNTER_FILE = os.path.join(CACHE_DIR, "api_counter.json")


# ================================================================
# BASİT DOSYA CACHE / COUNTER
# ================================================================
def _safe_mkdir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 cache klasörü oluşturulamadı: %s", e)


def _load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 JSON okuyamadı (%s): %s", path, e)
        return None


def _save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 JSON yazılamadı (%s): %s", path, e)


def _get_today_str() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _can_call_api() -> bool:
    """
    Günlük API çağrı sayısını COUNTER_FILE üzerinden takip eder.
    Limit dolduysa False döner, böylece FAZ-13 içeriye sadece
    "no_external_data" şeklinde bilgi verir.
    """
    _safe_mkdir(CACHE_DIR)
    counter = _load_json(COUNTER_FILE) or {}
    today = _get_today_str()

    day_info = counter.get(today, {"count": 0})
    if day_info["count"] >= API_BASK_MAX_PER_DAY:
        return False

    return True


def _inc_api_counter() -> None:
    _safe_mkdir(CACHE_DIR)
    counter = _load_json(COUNTER_FILE) or {}
    today = _get_today_str()

    day_info = counter.get(today, {"count": 0})
    day_info["count"] += 1
    counter[today] = day_info
    _save_json(COUNTER_FILE, counter)


def _cache_key(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}|{date_str}|{home}|{away}".lower()


def _load_cache() -> Dict[str, Any]:
    _safe_mkdir(CACHE_DIR)
    data = _load_json(CACHE_FILE)
    return data or {}


def _save_cache(cache: Dict[str, Any]) -> None:
    _safe_mkdir(CACHE_DIR)
    _save_json(CACHE_FILE, cache)


# ================================================================
# API-SPORTS BASKETBALL İSTEKLERİ
# ================================================================
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        if API_BASK_KEY:
            _session.headers.update({"x-apisports-key": API_BASK_KEY})
    return _session


def _api_bask_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not API_BASK_KEY:
        raise RuntimeError("API_BASK_KEY tanımlı değil (Fly secret)")

    if not _can_call_api():
        raise RuntimeError("FAZ23 API limiti bugün için dolu")

    url = f"{API_BASK_BASE}{path}"
    sess = _get_session()
    log.info("FAZ23 API-SPORTS isteği: %s params=%s", url, params)

    resp = sess.get(url, params=params, timeout=8)
    _inc_api_counter()

    resp.raise_for_status()
    data = resp.json()

    # API-SPORTS genelde "errors" ve "response" alanı döner
    errors = data.get("errors") or {}
    if errors:
        raise RuntimeError(f"API-SPORTS hata: {errors}")

    return data


# ================================================================
# MAÇ BAZLI KULLANILACAK ÖZETLER
# ================================================================
def _map_league_to_id(league: str) -> Optional[int]:
    """
    League ismini API-SPORTS league_id'ye çevir.

    NOT:
    - Buradaki değerleri dashboard'daki "Ids → Leagues" kısmından
      sen dolduracaksın. Şimdilik placeholder.
    """
    normalized = league.strip().lower()

    mapping: Dict[str, int] = {
        # ÖRNEKLER (sen kendi ID'lerini yazacaksın):
        # "nba": 12,
        # "euroleague": 120,
        # "eurocup": 121,
        # "türkiye bsl": 122,
    }

    return mapping.get(normalized)


def _extract_season_from_date(date_str: str) -> Optional[int]:
    """
    2025-12-11 → 2025 gibi.
    Basketbolda sezonlar genelde yıl bazlı olduğu için bu iş görür.
    İstersen daha akıllı yaparız (yıl sonu / başı).
    """
    try:
        return int(date_str.split("-", 1)[0])
    except Exception:  # noqa: BLE001
        return None


def fetch_match_context_from_api_sports(
    *, league: str, date_str: str, home: str, away: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Dış API'den FAZ-13 / FAZ-23 için gerekli özetleri hazırlar.

    Dönen:
        (api_data, market_data)

    - api_data → tempo, ofans/defans rating, son maç ortalamaları, vs.
    - market_data → ana total çizgisi, line hareketi vs. (bulabildiğimiz kadar)
    """
    if not API_BASK_KEY:
        log.info("API_BASK_KEY yok, dış veri kapalı.")
        return None, None

    cache = _load_cache()
    ck = _cache_key(league, date_str, home, away)
    cached = cache.get(ck)
    if cached:
        return cached.get("api_data"), cached.get("market_data")

    league_id = _map_league_to_id(league)
    season = _extract_season_from_date(date_str)

    if league_id is None or season is None:
        log.warning(
            "FAZ23 league_id/season çözülemedi (league=%s, date=%s) – dış veri yok.",
            league,
            date_str,
        )
        return None, None

    # ------------------------------------------------------------
    # 1) Maç bilgisi (games endpoint)
    # ------------------------------------------------------------
    try:
        # Param adları football ürününe benzer; basketbol dokümanına göre
        # ufak fark olabilir → takıldığında sadece burayı dokümana göre düzeltmen yeterli.
        games_raw = _api_bask_get(
            "/games",
            {
                "league": league_id,
                "season": season,
                "date": date_str,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 games fetch hatası: %s", e)
        return None, None

    games = games_raw.get("response") or []
    match = None

    # Ev/deplasman ismini zayıf da olsa eşleştir
    h_low = home.lower()
    a_low = away.lower()
    for g in games:
        try:
            th = (
                g.get("teams", {})
                .get("home", {})
                .get("name", "")
                .strip()
                .lower()
            )
            ta = (
                g.get("teams", {})
                .get("away", {})
                .get("name", "")
                .strip()
                .lower()
            )
            if h_low in th and a_low in ta:
                match = g
                break
        except Exception:  # noqa: BLE001
            continue

    if not match:
        log.warning("FAZ23: API-SPORTS games içinde eşleşen maç bulunamadı.")
        return None, None

    # Basit api_data: tempo / ofans / defans / son form vs.
    # Bu kısım tamamen senin ileride genişleteceğin yer.
    stats = match.get("statistics") or {}
    league_info = match.get("league") or {}
    country_info = league_info.get("country")

    api_data: Dict[str, Any] = {
        "provider": "API_SPORTS",
        "league": league_info.get("name"),
        "league_id": league_info.get("id"),
        "country": country_info,
        "season": league_info.get("season"),
        "stage": league_info.get("stage"),
        "tipoff": match.get("date"),
        # İleride: pace, ofans/defans rating, son 5 maç ortalamaları...
        "raw_stats": stats,
    }

    # ------------------------------------------------------------
    # 2) Market / barem bilgisi (varsa)
    # ------------------------------------------------------------
    market_data: Optional[Dict[str, Any]] = None

    try:
        # Eğer API-SPORTS odds / lines endpoint'leri açık ise buradan dolduracağız.
        # Endpoint tam adı dokümandan kontrol edilmeli; burada mantık gösteriyoruz.
        odds_raw = _api_bask_get(
            "/odds",
            {
                "league": league_id,
                "season": season,
                "date": date_str,
            },
        )
        odds_resp = odds_raw.get("response") or []
        if odds_resp:
            # En basit hali: ilk bookie'nin ana total çizgisi
            first = odds_resp[0]
            # Bu yapı API-SPORTS dokümanına göre değişebilir, o yüzden korumalı alıyoruz
            main_total = None
            line_move = 0.0

            try:
                totals = (
                    first.get("bookmakers", [])[0]
                    .get("bets", [])[0]
                    .get("values", [])
                )
                if totals:
                    main_total = float(totals[0].get("value"))
            except Exception:  # noqa: BLE001
                main_total = None

            market_data = {
                "provider": "API_SPORTS",
                "main_total": main_total,
                "line_move": line_move,
                "raw_odds": odds_resp,
            }
    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 odds/market verisi çekilemedi: %s", e)
        market_data = None

    # Cache’e yaz
    cache[ck] = {
        "ts": int(time.time()),
        "api_data": api_data,
        "market_data": market_data,
    }
    _save_cache(cache)

    return api_data, market_data


# ================================================================
# DIŞA AÇILAN ANA FONKSİYON
# ================================================================
def get_match_context(
    *, league: str, date_str: str, home: str, away: str
) -> Dict[str, Any]:
    """
    FAZ-13 / main.py yalnızca bu fonksiyonu çağırmalı.

    Dönen sözlük:
    {
        "api_data": {...} | None,
        "market_data": {...} | None,
        "meta": {
            "provider": "API_SPORTS",
            "used_cache": bool,
            "error": str | None,
        }
    }
    """
    ctx: Dict[str, Any] = {
        "api_data": None,
        "market_data": None,
        "meta": {
            "provider": "API_SPORTS",
            "used_cache": False,
            "error": None,
        },
    }

    try:
        cache = _load_cache()
        ck = _cache_key(league, date_str, home, away)
        cached = cache.get(ck)
        if cached:
            ctx["api_data"] = cached.get("api_data")
            ctx["market_data"] = cached.get("market_data")
            ctx["meta"]["used_cache"] = True
            return ctx

        api_data, market_data = fetch_match_context_from_api_sports(
            league=league, date_str=date_str, home=home, away=away
        )
        ctx["api_data"] = api_data
        ctx["market_data"] = market_data
        return ctx

    except Exception as e:  # noqa: BLE001
        log.warning("FAZ23 get_match_context hata: %s", e)
        ctx["meta"]["error"] = str(e)
        return ctx
