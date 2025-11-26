# live_providers/core.py
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from . import provider_dummy  # Şimdilik tek provider; yenilerini buraya ekle

log = logging.getLogger(__name__)


@dataclass
class HoopbrainLiveError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


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


def _candidate_providers() -> List:
    """
    Buraya yeni provider ekleyerek sistemi genişleteceğiz.
    Örn:
        from . import provider_mackolik, provider_rapidapi
        return [provider_mackolik, provider_rapidapi, provider_dummy]
    Şimdilik sadece dummy provider var.
    """
    return [provider_dummy]


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
    - İlk dolu sonucu dönen provider kazanır
    - Hiçbiri veri döndürmezse HoopbrainLiveError fırlatır
    """
    query = _normalize_query(league, home, away, match_id)
    providers = _candidate_providers()

    last_error: Optional[Exception] = None

    for p in providers:
        name = getattr(p, "__name__", str(p))
        try:
            result = p.fetch_live(query)
            if result:
                log.info(
                    "[LIVE CORE] Provider '%s' başarıyla veri döndürdü: mode=%s league=%s home=%s away=%s match_id=%s",
                    name,
                    query.get("mode"),
                    query.get("league"),
                    query.get("home"),
                    query.get("away"),
                    query.get("match_id"),
                )
                return result
        except Exception as e:  # Provider içi hata botu düşürmez
            last_error = e
            log.warning(
                "[LIVE CORE] Provider '%s' hata verdi: %s", name, e, exc_info=True
            )

    msg = "Hiçbir LIVE provider veri döndürmedi."
    if last_error:
        msg += f" Son hata: {last_error}"
    raise HoopbrainLiveError(msg)
