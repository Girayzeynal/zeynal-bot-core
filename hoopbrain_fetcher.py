"""
hoopbrain_fetcher.py
====================

FAZ-13.4 PRO | HOOPBRAIN GLOBAL LIVE ENGINE (ULTRA)

Bu modül sadece Telegram bot tarafı:
- Birden fazla sağlayıcıyı (provider) destekleyecek şekilde tasarlandı.
- Şu an 3 level mimari var:

  1) HOOPBRAIN CORE API (senin kendi backend’in)     -> PRIMARY
  2) GENEL BASKET API (örnek iskelet, API-Sports vb) -> SECONDARY
  3) MAÇKOLIK HTML FALLBACK (çok kaba skor yakalayıcı)-> TERTIARY

Dış dünya API detaylarını bilmediğimiz için:
- URL ve parametre isimleri ENV üzerinden geliyor.
- Bazı kısımlar iskelet (ŞABLON). Kendi API dokümanına göre dolduracaksın.
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

# ================================================================
#  ÖZEL HATA TİPİ
# ================================================================


class HoopbrainLiveError(RuntimeError):
    """HoopBrain canlı veri hatası (bot tarafında yakalanır)."""


# ================================================================
#  KONFİG: ENV DEĞİŞKENLERİ
# ================================================================

# 1) Senin kendi backend’in (önerilen yol)
HOOPBRAIN_CORE_URL = os.getenv("HOOPBRAIN_CORE_URL", "").strip()
HOOPBRAIN_CORE_KEY = os.getenv("HOOPBRAIN_CORE_KEY", "").strip()

# 2) Genel basket API (örn. API-Sports / RapidAPI / kendi microservice)
GENERIC_BASKET_URL = os.getenv("GENERIC_BASKET_URL", "").strip()
GENERIC_BASKET_KEY = os.getenv("GENERIC_BASKET_KEY", "").strip()

# 3) Maçkolik fallback (senin kuracağın proxy veya direkt HTML sayfa)
MACKOLIK_BASE_URL = os.getenv("MACKOLIK_BASE_URL", "").strip()
# Örn: "https://arsiv.mackolik.com" veya kendi proxy endpoint'in


# Timeout ve tekrar sayıları
HTTP_TIMEOUT = float(os.getenv("HOOPBRAIN_HTTP_TIMEOUT", "6.0"))
RETRY_DELAY = float(os.getenv("HOOPBRAIN_RETRY_DELAY", "0.8"))
MAX_RETRIES = int(os.getenv("HOOPBRAIN_MAX_RETRIES", "2"))


# ================================================================
#  NORMALİZE EDİLMİŞ VERİ MODELİ
# ================================================================


@dataclass
class LiveMatch:
    league: str
    home_name: str
    away_name: str
    home_score: int
    away_score: int
    period_label: str
    clock: str
    status: str
    pace: float
    win_prob: float  # 0.0 - 1.0
    win_side_label: str  # "HOME" / "AWAY" / "DRAW"
    provider: str
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "league": self.league,
            "home_name": self.home_name,
            "away_name": self.away_name,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "period_label": self.period_label,
            "clock": self.clock,
            "status": self.status,
            "pace": float(self.pace),
            "win_prob": float(self.win_prob),
            "win_side_label": self.win_side_label,
            "provider": self.provider,
            "raw": self.raw,
        }


# ================================================================
#  GENEL HTTP YARDIMCISI
# ================================================================


def _http_get_json(url: str, params: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code >= 500:
                raise HoopbrainLiveError(f"HTTP {resp.status_code} (server hatası)")
            if resp.status_code == 404:
                raise HoopbrainLiveError("Maç bulunamadı (404)")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning(
                "[HoopBrainHTTP] GET hata (deneme %s/%s): %s",
                attempt,
                MAX_RETRIES,
                e,
            )
            time.sleep(RETRY_DELAY)
    # tüm denemeler bitti
    raise HoopbrainLiveError(f"HTTP isteği başarısız: {last_err}")


# ================================================================
#  PROVIDER 1: HOOPBRAIN CORE BACKEND
# ================================================================


def _fetch_from_core(league: str, home: str, away: str) -> Optional[LiveMatch]:
    """
    Senin kuracağın merkezi HoopBrain backend.
    Önerilen response şeması (örnek):

    {
      "league": "NBA",
      "home": {"code": "LAL", "name": "Los Angeles Lakers", "score": 104},
      "away": {"code": "BOS", "name": "Boston Celtics", "score": 101},
      "period": "Q4",
      "clock": "02:34",
      "status": "LIVE",
      "pace": 98.7,
      "win_prob_home": 0.63
    }

    Backend tarafını bu şemaya yakın tasarlarsan bot tarafı direkt çalışır.
    """
    if not HOOPBRAIN_CORE_URL:
        return None

    params = {
        "league": league,
        "home": home,
        "away": away,
    }
    headers = {}
    if HOOPBRAIN_CORE_KEY:
        headers["X-API-KEY"] = HOOPBRAIN_CORE_KEY

    data = _http_get_json(HOOPBRAIN_CORE_URL, params=params, headers=headers)

    try:
        home_obj = data.get("home", {}) or {}
        away_obj = data.get("away", {}) or {}

        home_score = int(home_obj.get("score", 0))
        away_score = int(away_obj.get("score", 0))

        win_prob_home = float(data.get("win_prob_home", 0.5))
        win_side = "HOME" if win_prob_home > 0.5 else "AWAY" if win_prob_home < 0.5 else "DRAW"

        lm = LiveMatch(
            league=str(data.get("league", league)),
            home_name=str(home_obj.get("name") or home),
            away_name=str(away_obj.get("name") or away),
            home_score=home_score,
            away_score=away_score,
            period_label=str(data.get("period", "-")),
            clock=str(data.get("clock", "-")),
            status=str(data.get("status", "UNKNOWN")),
            pace=float(data.get("pace", 0.0)),
            win_prob=max(0.0, min(1.0, win_prob_home)),
            win_side_label=win_side,
            provider="HOOPBRAIN_CORE",
            raw=data,
        )
        return lm
    except Exception as e:  # noqa: BLE001
        log.error("[HoopBrainCore] Parse hatası: %s", e, exc_info=True)
        raise HoopbrainLiveError(f"HoopBrain CORE parse hatası: {e}") from e


# ================================================================
#  PROVIDER 2: GENEL BASKET API (ŞABLON)
# ================================================================


def _fetch_from_generic_api(league: str, home: str, away: str) -> Optional[LiveMatch]:
    """
    Bu fonksiyon bir örnek iskelet.
    Buraya API-Sports / RapidAPI / herhangi bir basket servisini bağlayabilirsin.

    ENV:
      GENERIC_BASKET_URL -> temel endpoint
      GENERIC_BASKET_KEY -> header için anahtar (opsiyonel)

    NOT:
    - Buradaki parametreler örnek; kendi API dökümanına göre güncelle.
    """
    if not GENERIC_BASKET_URL:
        return None

    params = {
        "league": league,
        "home": home,
        "away": away,
        "live": "1",
    }
    headers = {}
    if GENERIC_BASKET_KEY:
        headers["X-API-KEY"] = GENERIC_BASKET_KEY

    data = _http_get_json(GENERIC_BASKET_URL, params=params, headers=headers)

    # Buradan sonrası API şemana göre değişecek. Örnek generic şema:
    try:
        # Örn: data["game"] içinde tek maç
        game = data.get("game") or data.get("result") or data.get("data")
        if isinstance(game, list):
            game = game[0] if game else {}

        if not isinstance(game, dict):
            raise HoopbrainLiveError("GENERIC API: game objesi bulunamadı")

        home_name = str(game.get("home_name") or home)
        away_name = str(game.get("away_name") or away)
        home_score = int(game.get("home_score", 0))
        away_score = int(game.get("away_score", 0))
        period = str(game.get("period", game.get("quarter", "-")))
        clock = str(game.get("clock", game.get("time", "-")))
        status = str(game.get("status", "UNKNOWN"))

        # Basit pace & win prob heuristiği
        total_points = home_score + away_score
        pace = float(game.get("pace", 0.0) or total_points * 1.2)

        if home_score + away_score == 0:
            win_prob_home = 0.5
        else:
            diff = home_score - away_score
            win_prob_home = 0.5 + max(-0.35, min(0.35, diff / 40.0))

        win_prob_home = max(0.0, min(1.0, win_prob_home))
        win_side = "HOME" if win_prob_home > 0.5 else "AWAY" if win_prob_home < 0.5 else "DRAW"

        lm = LiveMatch(
            league=str(game.get("league", league)),
            home_name=home_name,
            away_name=away_name,
            home_score=home_score,
            away_score=away_score,
            period_label=period,
            clock=clock,
            status=status,
            pace=pace,
            win_prob=win_prob_home,
            win_side_label=win_side,
            provider="GENERIC_API",
            raw=data,
        )
        return lm
    except Exception as e:  # noqa: BLE001
        log.error("[GenericBasketAPI] Parse hatası: %s", e, exc_info=True)
        raise HoopbrainLiveError(f"GENERIC API parse hatası: {e}") from e


# ================================================================
#  PROVIDER 3: MAÇKOLIK HTML FALLBACK (ÇOK BASİT)
# ================================================================


def _fetch_from_mackolik(league: str, home: str, away: str) -> Optional[LiveMatch]:
    """
    Maçkolik HTML fallback.

    Burada gerçek bir "maç bul" lojik yazmak için sitenin HTML yapısını bilmek lazım.
    Bunu ezbere yazmak saçma olacağı için:

    - ENV'den bir "tam URL" veya "proxy URL" alıyoruz.
      MACKOLIK_BASE_URL:
        1) Direkt bir maç sayfası adresi olabilir
        2) Senin yazdığın bir proxy olabilir, o da HTML'den JSON çıkarsın.

    - Biz sadece HTML içinde ilk "NN - MM" skor pattern'ini yakalayıp
      basit bir LiveMatch üretiriz.

    Bu tamamen "son çare" fallback. Ultra modunun parçası ama mucize bekleme. :)
    """
    if not MACKOLIK_BASE_URL:
        return None

    # Eğer sen kendi proxy yazarsan burada query param o proxy'ye gider:
    params = {
        "league": league,
        "home": home,
        "away": away,
    }

    try:
        resp = requests.get(MACKOLIK_BASE_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:  # noqa: BLE001
        log.warning("[MackolikFallback] HTTP hata: %s", e)
        return None

    import re

    # İlk skor pattern: "nn - mm"
    m = re.search(r"(\d+)\s*[-:]\s*(\d+)", html)
    if not m:
        raise HoopbrainLiveError("Maçkolik HTML içinde skor bulunamadı")

    home_score = int(m.group(1))
    away_score = int(m.group(2))

    # Periyot / saat yakalamaya çalış (çok kaba)
    period = "-"
    clock = "-"

    m_q = re.search(r"(Q[1-4]|1\.?Ç|2\.?Ç|3\.?Ç|4\.?Ç)", html, re.IGNORECASE)
    if m_q:
        period = m_q.group(1)

    m_time = re.search(r"(\d{1,2}:\d{2})", html)
    if m_time:
        clock = m_time.group(1)

    # Basit win prob
    if home_score + away_score == 0:
        win_prob_home = 0.5
    else:
        diff = home_score - away_score
        win_prob_home = 0.5 + max(-0.35, min(0.35, diff / 40.0))
    win_prob_home = max(0.0, min(1.0, win_prob_home))
    win_side = "HOME" if win_prob_home > 0.5 else "AWAY" if win_prob_home < 0.5 else "DRAW"

    lm = LiveMatch(
        league=league,
        home_name=home,
        away_name=away,
        home_score=home_score,
        away_score=away_score,
        period_label=period,
        clock=clock,
        status="UNKNOWN",
        pace=float((home_score + away_score) * 1.1),
        win_prob=win_prob_home,
        win_side_label=win_side,
        provider="MACKOLIK_HTML",
        raw={"html_len": len(html)},
    )
    return lm


# ================================================================
#  PUBLIC API: get_live_match_global
# ================================================================


def get_live_match_global(league: str, home: str, away: str) -> Dict[str, Any]:
    """
    Ultra modun tek giriş kapısı.

    Sıra:
      1) HoopBrain CORE backend (varsa)
      2) Generic basket API (varsa)
      3) Maçkolik HTML fallback (varsa)

    Hiçbiri çalışmazsa HoopbrainLiveError fırlatır.
    """
    league = (league or "").upper()
    home = (home or "").upper()
    away = (away or "").upper()

    if not league or not home or not away:
        raise HoopbrainLiveError("Eksik parametre: league/home/away boş olamaz.")

    errors: list[str] = []

    # 1) CORE
    try:
        lm = _fetch_from_core(league, home, away)
        if lm is not None:
            return lm.to_dict()
    except HoopbrainLiveError as e:
        msg = f"CORE: {e}"
        log.warning("[HoopBrainLive] %s", msg)
        errors.append(msg)

    # 2) GENERIC API
    try:
        lm = _fetch_from_generic_api(league, home, away)
        if lm is not None:
            return lm.to_dict()
    except HoopbrainLiveError as e:
        msg = f"GENERIC: {e}"
        log.warning("[HoopBrainLive] %s", msg)
        errors.append(msg)

    # 3) MAÇKOLIK FALLBACK
    try:
        lm = _fetch_from_mackolik(league, home, away)
        if lm is not None:
            return lm.to_dict()
    except HoopbrainLiveError as e:
        msg = f"MACKOLIK: {e}"
        log.warning("[HoopBrainLive] %s", msg)
        errors.append(msg)

    if not errors:
        raise HoopbrainLiveError("Hiçbir live provider yapılandırılmamış.")

    raise HoopbrainLiveError(" / ".join(errors))
