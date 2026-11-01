from __future__ import annotations

from dataclasses import dataclass
import math
import random
import statistics
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class PrematchSimulationInput:
    home_mean: float
    away_mean: float
    home_std: float
    away_std: float
    score_correlation: float = 0.15
    shared_pace_std: float = 0.0
    periods: int = 4
    simulations: int = 10000
    seed: int = 20261101
    market_total: Optional[float] = None


@dataclass(frozen=True)
class PrematchSimulationResult:
    simulations: int
    seed: int
    home_win_probability: float
    away_win_probability: float
    tie_probability: float
    expected_home_score: float
    expected_away_score: float
    expected_total: float
    total_std: float
    total_quantiles: Dict[str, float]
    expected_margin: float
    period_home_means: Tuple[float, ...]
    period_away_means: Tuple[float, ...]
    over_probability: Optional[float]
    under_probability: Optional[float]
    push_probability: Optional[float]


def _finite_positive(name: str, value: float, allow_zero: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        op = 'non-negative' if allow_zero else 'positive'
        raise ValueError(f'{name} must be finite and {op}')
    return value


def _allocate_periods(total: int, periods: int, rng: random.Random) -> Tuple[int, ...]:
    if total == 0:
        return tuple(0 for _ in range(periods))
    weights = [rng.gammavariate(18.0, 1.0) for _ in range(periods)]
    weight_sum = sum(weights)
    raw = [total * w / weight_sum for w in weights]
    allocated = [int(x) for x in raw]
    remainder = total - sum(allocated)
    order = sorted(range(periods), key=lambda i: raw[i] - allocated[i], reverse=True)
    for i in order[:remainder]:
        allocated[i] += 1
    return tuple(allocated)


class PrematchMonteCarloEngine:
    '''Deterministic correlated-score Monte Carlo engine; no external data fetching.''

    def simulate(self, request: PrematchSimulationInput) -> PrematchSimulationResult:
        hm = _finite_positive('home_mean', request.home_mean)
        am = _finite_positive('away_mean', request.away_mean)
        hs = _finite_positive('home_std', request.home_std)
        aws = _finite_positive('away_std', request.away_std)
        pace_std = _finite_positive('shared_pace_std', request.shared_pace_std, allow_zero=True)
        corr = float(request.score_correlation)
        if not math.isfinite(corr) or not -0.95 <= corr <= 0.95:
            raise ValueError('score_correlation must be finite and within [-0.95, 0.95]')
        periods = int(request.periods)
        if periods not in (2, 4, 5):
            raise ValueError('periods must be 2, 4, or 5')
        n = int(request.simulations)
        if not 1000 <= n <= 1000000:
            raise ValueError('simulations must be between 1000 and 1000000')
        market = request.market_total
        if market is not None:
            market = _finite_positive('market_total', market)

        rng = random.Random(int(request.seed))
        root = math.sqrt(max(0.0, 1.0 - corr * corr))
        home_scores, away_scores, totals, margins = [], [], [], []
        home_period_sums = [0] * periods
        away_period_sums = [0] * periods
        home_wins = away_wins = ties = over = under = pushes = 0

        for _ in range(n):
            common = rng.gauss(0.0, 1.0)
            h_ind = rng.gauss(0.0, 1.0)
            a_ind = rng.gauss(0.0, 1.0)
            shared = rng.gauss(0.0, pace_std) if pace_std else 0.0
            h_score = max(0, int(round(hm + shared + hs * common * math.sqrt(abs(corr)) + hs * h_ind * root)))
            a_score = max(0, int(round(am + shared + aws * common * math.sqrt(abs(corr)) * (1 if corr >= 0 else -1) + aws * a_ind * root)))
            h_periods = _allocate_periods(h_score, periods, rng)
            a_periods = _allocate_periods(a_score, periods, rng)
            for i in range(periods):
                home_period_sums[i] += h_periods[i]
                away_period_sums[i] += a_periods[i]
            total = h_score + a_score
            margin = h_score - a_score
            home_scores.append(h_score)
            away_scores.append(a_score)
            totals.append(total)
            margins.append(margin)
            if margin > 0:
                home_wins += 1
            elif margin < 0:
                away_wins += 1
            else:
                ties += 1
            if market is not None:
                if total > market:
                    over += 1
                elif total < market:
                    under += 1
                else:
                    pushes += 1

        totals_sorted = sorted(totals)
        def quantile(p: float) -> float:
            index = (len(totals_sorted) - 1) * p
            lo = int(index)
            hi = min(lo + 1, len(totals_sorted) - 1)
            frac = index - lo
            return round(totals_sorted[lo] * (1 - frac) + totals_sorted[hi] * frac, 2)

        return PrematchSimulationResult(
            simulations=n, seed=int(request.seed),
            home_win_probability=home_wins / n, away_win_probability=away_wins / n, tie_probability=ties / n,
            expected_home_score=statistics.fmean(home_scores), expected_away_score=statistics.fmean(away_scores),
            expected_total=statistics.fmean(totals), total_std=statistics.pstdev(totals),
            total_quantiles={'p05': quantile(0.05), 'p25': quantile(0.25), 'p50': quantile(0.50), 'p75': quantile(0.75), 'p95': quantile(0.95)},
            expected_margin=statistics.fmean(margins),
            period_home_means=tuple(round(x / n, 3) for x in home_period_sums),
            period_away_means=tuple(round(x / n, 3) for x in away_period_sums),
            over_probability=(over / n if market is not None else None),
            under_probability=(under / n if market is not None else None),
            push_probability=(pushes / n if market is not None else None),
        )


__all__ = ['PrematchSimulationInput', 'PrematchSimulationResult', 'PrematchMonteCarloEngine']
