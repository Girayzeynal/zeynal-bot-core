"""Conservative, source-aware market movement audit. No fabricated sharp-money claims."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Optional, Sequence


@dataclass(frozen=True)
class MarketSnapshot:
    bookmaker: str
    market: str  # TOTAL or SPREAD
    line: float
    decimal_over: float
    decimal_under: float
    observed_utc: int
    source: str


@dataclass(frozen=True)
class SharpGuardResult:
    status: str
    opening_line: Optional[float]
    current_line: Optional[float]
    movement: Optional[float]
    reason: str
    sharp_confirmed: bool = False


def audit_market(snapshots: Sequence[MarketSnapshot], *, now_utc: int,
                 max_age_seconds: int = 900) -> SharpGuardResult:
    """Require verifiable two-point same-book market history before interpreting a move.

    Never infer sharp money, steam, RLM or betting volume from odds alone.
    A move is descriptive only; it is NOT an edge or bet recommendation.
    """
    if not snapshots:
        return SharpGuardResult('NO_EDGE', None, None, None, 'Piyasa verisi yok')
    if type(now_utc) is not int or now_utc <= 0 or max_age_seconds <= 0:
        raise ValueError('invalid clock or freshness limit')
    groups = {}
    for x in snapshots:
        if (not x.bookmaker.strip() or not x.source.strip() or x.market not in ('TOTAL', 'SPREAD')
                or not all(isfinite(v) for v in (x.line, x.decimal_over, x.decimal_under))
                or min(x.decimal_over, x.decimal_under) <= 1
                or type(x.observed_utc) is not int or x.observed_utc <= 0
                or x.observed_utc > now_utc):
            return SharpGuardResult('NO_EDGE', None, None, None, 'Geçersiz veya geleceğe ait piyasa verisi')
        groups.setdefault((x.bookmaker, x.market, x.source), []).append(x)
    eligible = []
    for key, rows in groups.items():
        rows.sort(key=lambda x: x.observed_utc)
        if len(rows) < 2 or rows[0].observed_utc == rows[-1].observed_utc:
            continue
        if now_utc - rows[-1].observed_utc > max_age_seconds:
            continue
        eligible.append((key, rows[0], rows[-1]))
    if not eligible:
        return SharpGuardResult('NO_EDGE', None, None, None, 'Açılış/güncel aynı kaynak çifti yok veya veri eski')
    if len(eligible) != 1:
        return SharpGuardResult('NO_EDGE', None, None, None, 'Birden fazla piyasa serisi; açık seçim gerekli')
    _, opening, current = eligible[0]
    change = round(current.line - opening.line, 2)
    return SharpGuardResult('OBSERVED_ONLY', opening.line, current.line, change,
                            'Barem hareketi gözlendi; sharp para akışı ve avantaj doğrulanmadı')
