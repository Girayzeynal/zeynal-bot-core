# live_providers/core.py
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Callable

from . import provider_dummy  # Her zaman en alttaki fallback

# Bu ikisini try/except ile import ediyoruz ki
# dosyalar eksik olsa bile core çökmesin.
try:
    from . import provider_mackolik
except Exception:
    provider_mackolik = None  # type: ignore

try:
    from . import provider_rapidapi
except Exception:
    provider_rapidapi = None  # type: ignore

log = logging.getLogger(__name__)


@dataclass
class HoopbrainLiveError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class ProviderInfo:
    name: str
    fetch_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
    priority: int  # Küçük olan önce denenir


def _normalize_query(
    league: Optional[str],
    home: Optional[str],
    away: Optional[str],
    match_id: Optional[str],
) -> Dict[str, Any]:
    """
    Kullanıcıdan gelen parametreleri tek ortak query formatına çevirir.
    """
    q: Dict[str, Any] = {}

    if match_id:
        q["mode"] = "ID"
        q["match_id"] = str(match_id).strip()
    else:
        q["mode"] = "TEAMS"

    if league:
        q["league"] = league.strip().upper()
    if home:
        q["home"] = home.strip().upper()
    if away:
        q["away"] = away.strip().upper()

    return q


def _candidate_providers() -> List[ProviderInfo]:
    """
    Buraya yeni provider ekleyerek sistemi genişleteceğiz.

    Şu sıra ile çalışır (priority küçükten büyüğe):
      1) MACKOLIK (varsa)
      2) RAPIDAPI (varsa)
      3) DUMMY_SIM (her zaman var, fallback)
    """
    providers: List[ProviderInfo] = []

    # A – Mackolik
    if provider_mackolik is not None:
        providers.append(
            ProviderInfo(
                name="MACKOLIK",
                fetch_func=provider_mackolik.fetch_live,  # type: ignore[attr-defined]
                priority=10,
            )
        )

    # B – RapidAPI
    if provider_rapidapi is not None:
        providers.append(
            ProviderInfo(
                name="RAPIDAPI",
                fetch_func=provider_rapidapi.fetch_live,  # type: ignore[attr-defined]
                priority=20,
            )
        )

    # C – Dummy (HER ZAMAN SON Fallback)
    providers.append(
        ProviderInfo(
            name="DUMMY_SIM",
            fetch_func=provider_dummy.fetch_live,
            priority=100,
        )
    )

    providers.sort(key=lambda p: p.priority)
    return providers


def _fill_defaults(q: Dict[str, Any], data: Dict[str, Any], provider_name: str) -> Dict[str, Any]:
    """
    Provider’dan gelen veriyi normalize eder, eksikleri doldurur.
    """
    league = data.get("league") or q.get("league") or "SIM"
    home_name = data.get("home_name") or q.get("home") or "HOME"
    away_name = data.get("away_name") or q.get("away") or "AWAY"

    home_score = data.get("home_score", 0) or 0
    away_score = data.get("away_score", 0) or 0

    win_side_label = data.get("win_side_label")
    if not win_side_label:
        win_side_label = "HOME" if home_score >= away_score else "AWAY"

    win_prob = data.get("win_prob", 0.5) or 0.5

    normalized = {
        "league": league,
        "match_id": data.get("match_id") or q.get("match_id") or "NA",
        "home_name": home_name,
        "away_name": away_name,
        "home_score": home_score,
        "away_score": away_score,
        "period_label": data.get("period_label") or data.get("period") or "Q1",
        "clock": data.get("clock") or "00:00",
        "status": data.get("status") or "SIMULATED",
        "pace": data.get("pace") or 98.5,
        "win_side_label": win_side_label,
        "win_prob": float(win_prob),
        "provider": data.get("provider") or provider_name,
    }

    return normalized


def get_live_match_global(
    league: Optional[str] = None,
    home: Optional[str] = None,
    away: Optional[str] = None,
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ANA /live core fonksiyonu.

    - Query normalize edilir
    - Provider listesi üzerinden geçilir
    - İlk anlamlı sonucu üreten provider kazanır
    - Hiçbiri sonuç üretemezse HoopbrainLiveError fırlatır
    """
    q = _normalize_query(league, home, away, match_id)

    last_error: Optional[Exception] = None

    for p in _candidate_providers():
        try:
            result = p.fetch_func(q)
        except Exception as e:
            # Provider kendi içinde patlarsa logla ve sıradakine geç
            log.error(
                "[LiveCore] Provider %s hata verdi: %s",
                p.name,
                e,
                exc_info=True,
            )
            last_error = e
            continue

        if not result:
            log.info("[LiveCore] Provider %s boş/None sonuç döndürdü.", p.name)
            continue

        # Normalizasyon + default doldurma
        normalized = _fill_defaults(q, result, provider_name=p.name)
        log.info(
            "[LiveCore] Provider %s başarıyla sonuç üretti: %s - %s vs %s",
            p.name,
            normalized["league"],
            normalized["home_name"],
            normalized["away_name"],
        )
        return normalized

    # Buraya geldiysek hiçbir provider iş göremedi
    msg = "Hiçbir canlı veri sağlayıcısı sonuç üretemedi."
    if last_error:
        msg += f" Son hata: {last_error}"
    raise HoopbrainLiveError(msg) 
