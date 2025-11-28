from dataclasses import dataclass, field
from typing import Optional, Dict, Any


# ================================================================
# 🧱 Temel Maç Meta Modeli
# ================================================================
@dataclass
class MatchMeta:
    """
    FAZ-13 normalize edilmiş meta bilgisi.
    Manuel, API veya OCR kaynaklı input'un tek formatı.
    """
    source: str
    raw: str
    league: str = "NBA"
    home: str = "UNKNOWN"
    away: str = "UNKNOWN"
    market: str = "FT TOTAL"
    line: Optional[float] = None
    direction: Optional[str] = None
    odds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "raw": self.raw,
            "league": self.league,
            "home": self.home,
            "away": self.away,
            "market": self.market,
            "line": self.line,
            "direction": self.direction,
            "odds": self.odds,
        }


# ================================================================
# 🧠 FAZ-7.9 Memory Engine Data Model
# ================================================================
@dataclass
class FazMemoryDay:
    """FAZ-7 günlük kayıt formatı."""
    ts: int
    conf: float
    edge: float

@dataclass
class FazMemory:
    """FAZ-7.9 full memory state."""
    days: list = field(default_factory=list)
    safe: float = 0.0
    bal: float = 0.0
    agg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "days": self.days,
            "safe": self.safe,
            "bal": self.bal,
            "agg": self.agg,
        }


# ================================================================
# 🏹 FAZ-9.x Trend Engine Input/Output Model
# ================================================================
@dataclass
class Faz9TrendInput:
    conf: float
    edge: float
    vol: float

@dataclass
class Faz9TrendOutput:
    tci: float
    noise: float
    behavior_index: float


# ================================================================
# 🔥 FAZ-13 Prediction Scoring Model
# ================================================================
@dataclass
class Faz13Score:
    """
    FAZ-13 modelinin çıkardığı skorlar:
    - Conf
    - Edge
    - Bucket (LOW/ MID / HIGH)
    - Risk
    - Score (final weighted score)
    - Implied probability
    """
    conf: float
    edge: float
    bucket: str
    risk: str
    implied_p: float
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conf": self.conf,
            "edge": self.edge,
            "bucket": self.bucket,
            "risk": self.risk,
            "implied_p": self.implied_p,
            "score": self.score,
        }


# ================================================================
# 🔮 GOD-LAYER Fusion Output Model
# ================================================================
@dataclass
class GodLayerOutput:
    """
    GOD-LAYER pipeline’ın final çıktısı:
      - Match Meta
      - FAZ-13 Score
      - FAZ-11 feedback
      - FAZ-12 auto profile kararı
    """
    source_type: str
    meta: Dict[str, Any]
    score: Dict[str, Any]
    faz11_feedback: Optional[Dict[str, Any]] = None
    faz12_decision: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "meta": self.meta,
            "score": self.score,
            "faz11_feedback": self.faz11_feedback,
            "faz12_decision": self.faz12_decision,
        }
