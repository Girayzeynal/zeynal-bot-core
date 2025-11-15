"""
FAZ-5 Heavy Engine – CORE MODULE
Burada tüm hesaplama motorunun iskeleti kurulur.
Bu modül diğer tüm alt modüllerin temelidir.
"""

from datetime import datetime
from .utils import safe_number, pct
from .models import MatchPack, EngineResult


class HeavyEngineCore:
    """
    FAZ-5'in beyni.
    Her maç için matematiksel hesaplamalar, güven yüzdesi,
    risk katsayıları ve edge tahminleri burada üretilir.
    """

    def __init__(self, mode="full"):
        self.mode = mode
        self.timestamp = datetime.utcnow()

    def compute_score_projection(self, home, away):
        """
        Takımların dummy istatistikleri üzerinden
        tahmini skor ve tempo üretir.
        """

        score_est = safe_number(home.pts) + safe_number(away.pts)
        pace_est = (safe_number(home.pace) + safe_number(away.pace)) / 2

        return {
            "score_est": round(score_est, 1),
            "pace_est": round(pace_est, 1)
        }

    def compute_winner(self, home, away):
        """
        Temel güç farkı hesaplaması.
        """

        diff = safe_number(home.power) - safe_number(away.power)

        if diff > 0:
            return home.code
        elif diff < 0:
            return away.code
        return "DENGELI"

    def compute_confidence(self, home, away):
        """
        Basit güven yüzdesi.
        """

        diff = abs(safe_number(home.power) - safe_number(away.power))
        conf = 0.55 + (diff / 40)

        return round(max(0.55, min(conf, 0.95)), 2)

    def process_match(self, match: MatchPack) -> EngineResult:
        """
        Tek maç üzerinden FAZ-5 çıktısı üretir.
        """

        proj = self.compute_score_projection(match.home, match.away)
        pick = self.compute_winner(match.home, match.away)
        conf = self.compute_confidence(match.home, match.away)

        return EngineResult(
            home=match.home.code,
            away=match.away.code,
            score_est=proj["score_est"],
            pace_est=proj["pace_est"],
            pick=pick,
            confidence=conf
        )
