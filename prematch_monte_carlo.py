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
    model_scope: str
    home_regulation_win_probability: float
    away_regulation_win_probability: float
    regulation_tie_probability: float
    observed_score_correlation: Optional[float]
    observed_home_std: float
    observed_away_std: float
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
    """Deterministic correlated-score Monte Carlo engine; no external data fetching."""

    def simulate(self, request: PrematchSimulationInput) -> PrematchSimulationResult:
        hm = _finite_positive('home_mean', request.home_mean)
        am = _finite_positive('away_mean', request.away_mean)
        hs = _finite_positive('home_std', request.home_std)
        aws = _finite_positive('away_std', request.away_std)
        pace_std = _finite_positive('shared_pace_std', request.shared_pace_std, allow_zero=True)
        corr = float(request.score_correlation)
        if not math.isfinite(corr) or not -0.95 <= corr <= 0.95:
            raise ValueError('score_correlation must be finite and within [-0.95, 0.95]')
        if isinstance(request.periods, bool) or not isinstance(request.periods, int):
            raise ValueError('periods must be an integer')
        periods = request.periods
        if periods not in (2, 4):
            raise ValueError('periods must be 2 or 4; overtime is not modeled')
        if isinstance(request.simulations, bool) or not isinstance(request.simulations, int):
            raise ValueError('simulations must be an integer')
        n = request.simulations
        if not 1000 <= n <= 1000000:
            raise ValueError('simulations must be between 1000 and 1000000')
        market = request.market_total
        if market is not None:
            market = _finite_positive('market_total', market)

        if isinstance(request.seed, bool) or not isinstance(request.seed, int):
            raise ValueError('seed must be an integer')
        # shared_pace_std is part of the requested marginal standard deviations,
        # not extra variance. Solve for the remaining residual covariance.
        if pace_std >= min(hs, aws):
            raise ValueError('shared_pace_std must be smaller than both team standard deviations')
        home_residual_std = math.sqrt(hs * hs - pace_std * pace_std)
        away_residual_std = math.sqrt(aws * aws - pace_std * pace_std)
        residual_corr = (corr * hs * aws - pace_std * pace_std) / (
            home_residual_std * away_residual_std
        )
        if not -1.0 <= residual_corr <= 1.0:
            raise ValueError('shared_pace_std and score_correlation imply an impossible covariance')
        rng = random.Random(request.seed)
        root = math.sqrt(max(0.0, 1.0 - residual_corr * residual_corr))
        home_scores, away_scores, totals, margins = [], [], [], []
        home_period_sums = [0] * periods
        away_period_sums = [0] * periods
        home_wins = away_wins = ties = over = under = pushes = 0

        for _ in range(n):
            common = rng.gauss(0.0, 1.0)
            a_ind = rng.gauss(0.0, 1.0)
            shared = rng.gauss(0.0, pace_std) if pace_std else 0.0
            h_score = max(0, int(round(hm + shared + home_residual_std * common)))
            a_score = max(0, int(round(am + shared + away_residual_std * (residual_corr * common + root * a_ind))))
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
            simulations=n, seed=request.seed, model_scope='REGULATION_ONLY',
            home_regulation_win_probability=home_wins / n,
            away_regulation_win_probability=away_wins / n,
            regulation_tie_probability=ties / n,
            observed_score_correlation=(
                statistics.correlation(home_scores, away_scores)
                if statistics.pstdev(home_scores) > 0 and statistics.pstdev(away_scores) > 0
                else None
            ),
            observed_home_std=statistics.pstdev(home_scores),
            observed_away_std=statistics.pstdev(away_scores),
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
