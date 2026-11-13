"""Coherent regulation-only projections and bounded MC / randomized QMC / analytic laws."""
from dataclasses import dataclass
import math
from statistics import NormalDist
import time

import numpy as np

from hybrid_engine.data import Abstain


@dataclass(frozen=True)
class Budget:
    scenarios: int = 10000
    seed: int = 20261112
    seconds: float = 2.0
    array_bytes: int = 32 * 1024 * 1024

    def validate(self):
        if type(self.scenarios) is not int or not 10000 <= self.scenarios <= 32768:
            raise ValueError('BOUNDED_AT_LEAST_10000_SCENARIOS_REQUIRED')
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError('NONNEGATIVE_INTEGER_SEED_REQUIRED')
        if not math.isfinite(self.seconds) or not 0 < self.seconds <= 30 or self.array_bytes < self.scenarios*8*8:
            raise ValueError('INVALID_RUNTIME_BUDGET')

    def check(self, began, arrays=()):
        if time.perf_counter()-began > self.seconds:
            raise Abstain('RUNTIME_BUDGET_EXCEEDED')
        if sum(a.nbytes for a in arrays) > self.array_bytes:
            raise Abstain('ARRAY_MEMORY_BUDGET_EXCEEDED')


def periods_for_scores(scores, weights):
    """Largest-remainder allocation: every integer scenario sums exactly at all levels."""
    scores = np.asarray(scores)
    weights = np.asarray(weights, dtype=float)
    if scores.ndim != 2 or scores.shape[1] != 2 or not np.issubdtype(scores.dtype, np.integer) or np.any(scores < 0):
        raise ValueError('NONNEGATIVE_INTEGER_SCORE_PAIRS_REQUIRED')
    if weights.shape != (4, 2) or not np.isfinite(weights).all() or np.any(weights < 0) or np.any(weights.sum(axis=0) <= 0):
        raise ValueError('FOUR_PERIOD_WEIGHTS_REQUIRED')
    w = weights/weights.sum(axis=0)
    raw = scores[:, None, :] * w[None, :, :]
    out = np.floor(raw).astype(np.int32)
    remainder = scores-out.sum(axis=1)
    order = np.argsort(-(raw-out), axis=1, kind='stable')
    index = np.arange(len(scores))
    for side in range(2):
        for j in range(4):
            out[index, order[:, j, side], side] += remainder[:, side] > j
    if not np.array_equal(out.sum(axis=1), scores):
        raise ValueError('PERIOD_ALLOCATION_INVARIANT_FAILED')
    return out


def three_way(values, line):
    if not math.isfinite(float(line)):
        raise ValueError('FINITE_EVALUATION_LINE_REQUIRED')
    return dict(under=float(np.mean(values < line)), push=float(np.mean(values == line)),
                over=float(np.mean(values > line)))


@dataclass
class Forecast:
    model: str
    quarter_means: np.ndarray
    samples: object = None
    law: object = None
    metadata: object = None

    def __post_init__(self):
        self.quarter_means = np.asarray(self.quarter_means, dtype=float)
        if self.quarter_means.shape != (4, 2) or not np.isfinite(self.quarter_means).all() or np.any(self.quarter_means < 0):
            raise ValueError('INVALID_QUARTER_PROJECTION')
        if self.samples is not None:
            if (self.samples.ndim != 3 or self.samples.shape[1:] != (4, 2) or
                    not np.issubdtype(self.samples.dtype, np.integer) or np.any(self.samples < 0)):
                raise ValueError('INVALID_COHERENT_SAMPLE_PATHS')

    @property
    def scores(self):
        return self.quarter_means.sum(axis=0)

    def probabilities(self):
        if self.law is not None:
            return self.law.winner()
        if self.samples is None:
            return None
        margin = np.diff(self.samples.sum(axis=1), axis=1)[:, 0]
        return [float(np.mean(margin < 0)), float(np.mean(margin == 0)), float(np.mean(margin > 0))]

    def market(self, kind, line):
        if self.law is not None:
            return self.law.market(kind, line)
        if self.samples is None:
            raise Abstain('NO_DISTRIBUTION_FOR_REQUESTED_MARKET')
        scores = self.samples.sum(axis=1)
        if kind == 'TOTAL': values = scores.sum(axis=1)
        elif kind == 'HOME': values = scores[:, 0]
        elif kind == 'AWAY': values = scores[:, 1]
        elif kind == 'MARGIN': values = scores[:, 0]-scores[:, 1]
        elif kind in ('1H', '2H'):
            values = self.samples[:, :2 if kind == '1H' else 4, :].sum(axis=(1, 2))
            if kind == '2H': values -= self.samples[:, :2, :].sum(axis=(1, 2))
        elif kind in ('1Q', '2Q', '3Q', '4Q'):
            values = self.samples[:, int(kind[0])-1, :].sum(axis=1)
        else: raise ValueError('UNKNOWN_MARKET')
        return three_way(values, line)

    def summary(self):
        h, a = map(float, self.scores)
        return dict(model=self.model, home=h, away=a, total=h+a, margin=h-a, home_handicap=a-h,
                    quarters=self.quarter_means.tolist(), halves=[self.quarter_means[:2].sum(axis=0).tolist(),
                    self.quarter_means[2:].sum(axis=0).tolist()], winner=self.probabilities(),
                    scope='REGULATION_ONLY', calibration_status='NOT_CALIBRATED', metadata=self.metadata or {})


def quarter_weights(cut):
    f = cut.features
    return np.array([[(f['home']['quarters_for'][q]+f['away']['quarters_against'][q])/2,
                      (f['away']['quarters_for'][q]+f['home']['quarters_against'][q])/2] for q in range(4)])


def halton_uniforms(n, seed):
    """Randomly shifted 2-D Halton; no SciPy or heavy optional package at inference."""
    rng = np.random.default_rng(seed)
    out = np.zeros((n, 2))
    for j, base in enumerate((2, 3)):
        index = np.arange(1, n+1, dtype=np.int64)
        factor = 1.0
        while np.any(index):
            factor /= base
            out[:, j] += factor*(index % base)
            index //= base
        out[:, j] = (out[:, j]+rng.random()) % 1
    return np.clip(out, 1e-15, 1-1e-15)


class DiscreteNormalLaw:
    """Exact enumeration for independent, rounded/clipped Gaussian TEAM score assumptions.

    This is an analytic probability under an explicit model, not proof of basketball calibration.
    Quarter allocation uncertainty is not analytically claimed.
    """
    def __init__(self, means, stds):
        self.pmf = []
        self.period_marginals = None
        for mu, sd in zip(means, stds):
            if not math.isfinite(mu) or not math.isfinite(sd) or not 0 < mu <= 300 or not 0 < sd <= 80:
                raise ValueError('INVALID_GAUSSIAN_PARAMETERS')
            normal = NormalDist(mu, sd)
            upper = math.ceil(mu+12*sd)
            cdf = np.array([normal.cdf(k+.5) for k in range(upper+1)])
            mass = np.maximum(0., np.diff(np.r_[0, cdf])); mass /= mass.sum()
            self.pmf.append(mass)
        self.total = np.convolve(*self.pmf)

    def allocate_periods(self, weights):
        """Exact pushforward of the integer team-score law through the same allocation."""
        self.period_marginals = []; means = np.empty((4, 2))
        for side, mass in enumerate(self.pmf):
            scores = np.zeros((len(mass), 2), dtype=np.int32); scores[:, side] = np.arange(len(mass))
            allocated = periods_for_scores(scores, weights)[:, :, side]
            marginals = {}
            for quarter in range(4):
                values = allocated[:, quarter]
                marginals[str(quarter+1)+'Q'] = np.bincount(values, weights=mass)
                means[quarter, side] = np.dot(values, mass)
            marginals['1H'] = np.bincount(allocated[:, :2].sum(axis=1), weights=mass)
            marginals['2H'] = np.bincount(allocated[:, 2:].sum(axis=1), weights=mass)
            self.period_marginals.append(marginals)
        return means

    def winner(self):
        h, a = self.pmf
        cdf = np.r_[0., np.cumsum(a)]
        home = float(np.dot(h, cdf[np.minimum(np.arange(len(h)), len(a))]))
        tie = float(np.dot(h[:min(len(h), len(a))], a[:min(len(h), len(a))]))
        return [home, tie, max(0., 1-home-tie)]

    def market(self, kind, line):
        if not math.isfinite(float(line)): raise ValueError('FINITE_EVALUATION_LINE_REQUIRED')
        if kind in ('1Q', '2Q', '3Q', '4Q', '1H', '2H'):
            if self.period_marginals is None: raise Abstain('ANALYTIC_PERIOD_WEIGHTS_NOT_CONFIGURED')
            p = np.convolve(self.period_marginals[0][kind], self.period_marginals[1][kind]); index = np.arange(len(p))
            return {k: float(p[mask].sum()) for k, mask in
                    [('under', index < line), ('push', index == line), ('over', index > line)]}
        if kind in ('TOTAL', 'HOME', 'AWAY'):
            p = self.total if kind == 'TOTAL' else self.pmf[0 if kind == 'HOME' else 1]
            index = np.arange(len(p))
            return {k: float(p[mask].sum()) for k, mask in
                    [('under', index < line), ('push', index == line), ('over', index > line)]}
        if kind != 'MARGIN': raise Abstain('ANALYTIC_QUARTER_LAW_NOT_AVAILABLE')
        h, a = self.pmf; index = np.arange(len(a)); values = dict(under=0., push=0., over=0.)
        for score, weight in enumerate(h):
            for key, mask in [('under', score-index < line), ('push', score-index == line), ('over', score-index > line)]:
                values[key] += float(weight*a[mask].sum())
        return values


def gaussian_forecast(means, stds, weights, *, method='MC', budget=Budget(), model='GAUSSIAN_RESEARCH', correlation=0.0):
    budget.validate(); began = time.perf_counter()
    means = np.asarray(means, dtype=float); stds = np.asarray(stds, dtype=float)
    if means.shape != (2,) or stds.shape != (2,): raise ValueError('TEAM_SCORE_PARAMETERS_REQUIRED')
    if not math.isfinite(correlation) or not -1 < correlation < 1:
        raise ValueError('VALID_SCORE_CORRELATION_REQUIRED')
    if method == 'ANALYTIC' and correlation != 0:
        raise Abstain('CORRELATED_ANALYTIC_LATTICE_NOT_IMPLEMENTED')
    law = DiscreteNormalLaw(means, stds)
    weights = np.asarray(weights, dtype=float)
    # Validate weights even on the analytic path.
    periods_for_scores(np.array([[1, 1]], dtype=int), weights)
    # Report the expected *rounded/clipped* scores, including the lower-tail mass at zero.
    # The latent normal locations can differ substantially near zero with high variance.
    q = law.allocate_periods(weights)
    samples = None
    if method in ('MC', 'RQMC_HALTON'):
        if method == 'MC': z = np.random.default_rng(budget.seed).standard_normal((budget.scenarios, 2))
        else:
            u = halton_uniforms(budget.scenarios, budget.seed)
            normal = NormalDist()
            z = np.fromiter((normal.inv_cdf(float(x)) for x in u.flat), dtype=float).reshape(u.shape)
        if correlation:
            z[:, 1] = correlation*z[:, 0]+math.sqrt(1-correlation*correlation)*z[:, 1]
        scores = np.maximum(0, np.rint(means+z*stds)).astype(np.int32)
        samples = periods_for_scores(scores, weights)
        budget.check(began, (z, scores, samples))
    elif method != 'ANALYTIC': raise ValueError('UNKNOWN_SIMULATION_METHOD')
    budget.check(began)
    return Forecast(model, q, samples=samples, law=law if method == 'ANALYTIC' else None,
        metadata=dict(method=method, scenarios=0 if samples is None else budget.scenarios, seed=budget.seed,
            correlation_assumption=correlation, distribution='ROUNDED_CLIPPED_NORMAL',
            latent_normal_locations=means.tolist(),
            quarter_allocation='LARGEST_REMAINDER_HISTORICAL_WEIGHTS_NOT_PBP',
            elapsed_seconds=time.perf_counter()-began, player_effect='NOT_AVAILABLE'))
