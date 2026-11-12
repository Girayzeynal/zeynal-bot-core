"""Absorbing possession reward model: analytic convolution is the primary path.

Box-derived rates are explicitly approximations. Context semi-Markov inference needs
annotated possessions; unannotated play-by-play and final player minutes are not enough.
"""
from dataclasses import dataclass
import math
from statistics import NormalDist
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.distributions import Budget, Forecast, quarter_weights


@dataclass(frozen=True)
class Rates:
    actions: tuple  # turnover, inferred two-FT trip, two-point attempt, three-point attempt, non-shooting foul
    make2: float
    make3: float
    makeft: float
    offensive_rebound: float

    def reward(self):
        p = np.asarray(self.actions, dtype=float)
        values = [self.make2, self.make3, self.makeft, self.offensive_rebound]
        if (p.shape != (5,) or not np.isfinite(p).all() or np.any(p < 0) or abs(p.sum()-1) > 1e-8
                or any(not math.isfinite(x) or not 0 <= x <= 1 for x in values)):
            raise ValueError('INVALID_POSSESSION_TRANSITION_PROBABILITIES')
        turnover, foul, two, three, nonshoot = p
        continuation = nonshoot+(two*(1-self.make2)+three*(1-self.make3))*self.offensive_rebound
        if continuation >= .999:
            raise Abstain('NONABSORBING_POSSESSION_CHAIN')
        ended = np.array([turnover+(two*(1-self.make2)+three*(1-self.make3))*(1-self.offensive_rebound)+foul*(1-self.makeft)**2,
                          foul*2*self.makeft*(1-self.makeft),
                          two*self.make2+foul*self.makeft**2, three*self.make3])
        g = ended/(1-continuation)
        if abs(g.sum()-1) > 1e-8: raise ValueError('POSSESSION_REWARD_MASS_NOT_CONSERVED')
        return g/g.sum()


def _aggregate(entries):
    fields = ('fgm2', 'fga2', 'fgm3', 'fga3', 'ftm', 'fta', 'orb', 'drb', 'tov', 'fouls', 'points')
    own = {k: 0. for k in fields}; opponent_drb = 0.; opponent_fouls = 0.
    seen = set()
    for box, side, other in entries:
        key = (box['league'], box['fixture_id'], side)
        if key in seen: continue
        seen.add(key)
        for key in fields: own[key] += box['teams'][side][key]
        opponent_drb += box['teams'][other]['drb']; opponent_fouls += box['teams'][other]['fouls']
    # Priors are model assumptions, never represented as observed shots/possessions.
    nonshoot = max(0., opponent_fouls-own['fta']/2)
    counts = np.array([own['tov'], own['fta']/2, own['fga2'], own['fga3'], nonshoot])+1.
    return Rates(tuple(counts/counts.sum()), (own['fgm2']+1)/(own['fga2']+2),
        (own['fgm3']+1)/(own['fga3']+2), (own['ftm']+1)/(own['fta']+2),
        (own['orb']+1)/(own['orb']+opponent_drb+2))


def _quarter_rate(rate, ratio):
    """Fit an explicit score-profile tilt; never invent quarter box statistics."""
    base = float(np.dot(np.arange(4), rate.reward())); target = base*ratio
    def shifted(delta):
        def shift(p):
            p = min(1-1e-12, max(1e-12, p))
            return 1/(1+math.exp(-(math.log(p/(1-p))+delta)))
        return Rates(rate.actions, shift(rate.make2), shift(rate.make3), shift(rate.makeft), rate.offensive_rebound)
    lo, hi = -12., 12.
    if not float(np.dot(np.arange(4), shifted(lo).reward())) <= target <= float(np.dot(np.arange(4), shifted(hi).reward())):
        raise Abstain('QUARTER_SCORE_PROFILE_NOT_IDENTIFIABLE')
    for _ in range(40):
        mid = (lo+hi)/2
        if np.dot(np.arange(4), shifted(mid).reward()) < target: lo = mid
        else: hi = mid
    return shifted((lo+hi)/2)


def count_distribution(mean, std):
    if not math.isfinite(mean) or not math.isfinite(std) or not 1 <= mean <= 50 or not 0 <= std <= 15:
        raise Abstain('POSSESSION_COUNT_OUT_OF_BUDGET')
    if std == 0:
        p = np.zeros(max(1, round(mean))+1); p[-1] = 1; return p
    upper = math.ceil(mean+10*std)
    if upper > 100: raise Abstain('POSSESSION_SUPPORT_OUT_OF_BUDGET')
    normal = NormalDist(mean, std)
    cdf = np.array([0.]+[normal.cdf(k+.5) for k in range(1, upper+1)])
    p = np.maximum(0., np.diff(np.r_[0., cdf])); p /= p.sum()
    return p


class PossessionLaw:
    """Conditional team dependence via shared pace, exact finite count-support enumeration.

    Home/away rewards are independent *conditional* on quarter possession count.
    Different quarters are independent. These are testable assumptions, not calibrated facts.
    """
    def __init__(self, rates, mean_count, std_count, budget=Budget()):
        began = time.perf_counter(); self.quarters = []; self.means = []
        self.count_pmf = count_distribution(mean_count/4, std_count/2)
        max_n = len(self.count_pmf)-1
        for q in range(4):
            kernels = [rates[q][s].reward() for s in range(2)]
            powers = [np.array([1.]), np.array([1.])]
            size = 3*max_n+1
            home = np.zeros(size); away = np.zeros(size); total = np.zeros(2*size-1); margin = np.zeros(2*size-1)
            offset = size-1
            for n in range(max_n+1):
                probability = self.count_pmf[n]
                if probability:
                    h, a = powers
                    home[:len(h)] += probability*h; away[:len(a)] += probability*a
                    t = np.convolve(h, a); m = np.convolve(h, a[::-1])
                    total[:len(t)] += probability*t
                    start = offset-(len(a)-1); margin[start:start+len(m)] += probability*m
                if n < max_n:
                    powers = [np.convolve(powers[s], kernels[s]) for s in range(2)]
                if n % 10 == 0: budget.check(began, (home, away, total, margin))
            self.quarters.append(dict(HOME=(home, 0), AWAY=(away, 0), TOTAL=(total, 0), MARGIN=(margin, -offset)))
            self.means.append([float(np.dot(np.arange(size), v)) for v in (home, away)])
        self.means = np.array(self.means)
        self.full = {kind: self._combine(kind, range(4)) for kind in ('HOME', 'AWAY', 'TOTAL', 'MARGIN')}
        budget.check(began)

    def _combine(self, kind, indices):
        mass = np.array([1.]); offset = 0
        for q in indices:
            p, shift = self.quarters[q][kind]
            mass = np.convolve(mass, p); offset += shift
        mass = np.maximum(0., mass); mass /= mass.sum()
        return mass, offset

    def winner(self):
        p, offset = self.full['MARGIN']; scores = np.arange(len(p))+offset
        return [float(p[scores > 0].sum()), float(p[scores == 0].sum()), float(p[scores < 0].sum())]

    def market(self, kind, line):
        if not math.isfinite(float(line)): raise ValueError('FINITE_EVALUATION_LINE_REQUIRED')
        if kind in self.full: p, shift = self.full[kind]
        elif kind in ('1H', '2H'): p, shift = self._combine('TOTAL', range(2) if kind == '1H' else range(2, 4))
        elif kind in ('1Q', '2Q', '3Q', '4Q'): p, shift = self.quarters[int(kind[0])-1]['TOTAL']
        else: raise ValueError('UNKNOWN_POSSESSION_MARKET')
        scores = np.arange(len(p))+shift
        return {k: float(p[mask].sum()) for k, mask in [('under', scores < line), ('push', scores == line), ('over', scores > line)]}


class PossessionModel:
    def __init__(self, *, minimum_box_games=6):
        if type(minimum_box_games) is not int or minimum_box_games < 2:
            raise ValueError('MINIMUM_BOX_HISTORY_REQUIRED')
        self.minimum = minimum_box_games

    def predict(self, cut, *, budget=Budget(), method='ANALYTIC', context=None):
        budget.validate(); began = time.perf_counter()
        entries, counts = {}, {}
        for side in ('home', 'away'):
            data = cut.features[side]['boxes']
            if len(data) < self.minimum:
                raise Abstain('INSUFFICIENT_PRE_CUTOFF_REGULATION_BOX_SCORES')
            entries[side] = [(b, own, other) for r, b, own, other in data]
            for r, b, own, other in data:
                if not b['regulation_eligible']: raise ValueError('OVERTIME_BOX_CANNOT_TRAIN_REGULATION_POSSESSIONS')
                counts[r['fixture_id']] = np.mean([b['teams'][s]['possessions_estimate'] for s in ('home', 'away')])
        home = _aggregate(entries['home']+[(b, other, own) for b, own, other in entries['away']])
        away = _aggregate(entries['away']+[(b, other, own) for b, own, other in entries['home']])
        weights = quarter_weights(cut); ratios = 4*weights/weights.sum(axis=0)
        rates = [[_quarter_rate(rate, ratios[q, s]) for s, rate in enumerate((home, away))] for q in range(4)]
        mean_count, std_count = float(np.mean(list(counts.values()))), float(np.std(list(counts.values())))
        if context is not None:
            if method != 'MC': raise Abstain('CONTEXT_SEMI_MARKOV_REQUIRES_SAMPLED_PATH')
            samples = context.simulate(cut, budget=budget)
            return Forecast('CONTEXT_SEMI_MARKOV_RESEARCH_V1', samples.mean(axis=0), samples=samples,
                metadata=dict(context_artifact=context.artifact_digest, method='MC', scenarios=budget.scenarios,
                    seed=budget.seed, holding_times='EMPIRICAL_CONTEXT_MEANS', elapsed_seconds=time.perf_counter()-began))
        law = PossessionLaw(rates, mean_count, std_count, budget)
        samples = None
        if method == 'MC':
            rng = np.random.default_rng(budget.seed)
            samples = np.empty((budget.scenarios, 4, 2), dtype=np.int32)
            support = np.arange(len(law.count_pmf))
            for q in range(4):
                n = rng.choice(support, size=budget.scenarios, p=law.count_pmf)
                for side in range(2):
                    outcomes = rng.multinomial(n, rates[q][side].reward())
                    samples[:, q, side] = outcomes@np.arange(4)
                budget.check(began, (samples, outcomes))
        elif method != 'ANALYTIC': raise ValueError('UNKNOWN_POSSESSION_INFERENCE_METHOD')
        budget.check(began)
        return Forecast('POSSESSION_ABSORBING_REWARD_V1', law.means, samples=samples,
            law=law if method == 'ANALYTIC' else None,
            metadata=dict(method=method, scenarios=0 if samples is None else budget.scenarios, seed=budget.seed,
                possession_estimation='FGA+0.44FTA-ORB+TOTAL_TOV_NOT_MEASURED', pace_mean=mean_count,
                pace_std=std_count, box_games=len(counts), quarter_effect='SCORE_PROFILE_TILT_NOT_QUARTER_BOX_STATS',
                assumptions=['TWO_FT_TRIPS_INFERRED_FROM_FTA', 'NO_AND_ONE_OR_THREE_FT_TRIP_MODEL',
                    'NO_FT_OFFENSIVE_REBOUND', 'CONDITIONAL_REWARD_INDEPENDENCE', 'INDEPENDENT_QUARTERS'],
                missing=['INJURIES', 'PREMATCH_ROTATION', 'EMPIRICAL_CLUTCH_GARBAGE_TIME_TRANSITIONS'],
                elapsed_seconds=time.perf_counter()-began))


class ContextTransitions:
    """Semi-Markov context model for *annotated* possession rewards and game-clock durations.

    No possession labels are fabricated from incomplete native play lists. Complete context
    coverage is required before this component can be used, otherwise it abstains.
    """
    @staticmethod
    def context(quarter, gap, seconds_remaining):
        return (quarter, 'TRAILING' if gap < -8 else 'LEADING' if gap > 8 else 'CLOSE',
                'LATE' if quarter == 4 and seconds_remaining <= 120 else 'NORMAL')

    def fit(self, records, *, cutoff_utc, minimum_per_context=20):
        if type(cutoff_utc) is not int or not 0 < cutoff_utc <= int(time.time()):
            raise ValueError('PAST_CONTEXT_TRAINING_CUTOFF_REQUIRED')
        if type(minimum_per_context) is not int or minimum_per_context < 5:
            raise ValueError('CONTEXT_SAMPLE_POLICY_REQUIRED')
        groups = {}; seen = set(); identities = set()
        for r in records:
            if r.get('annotation') != 'VERIFIED_POSSESSION_BOUNDARY': raise Abstain('PBP_POSSESSION_ANNOTATIONS_REQUIRED')
            key = (r['provider'], r['fixture_id'], r['possession_id'])
            if key in seen: raise ValueError('DUPLICATE_POSSESSION_ANNOTATION')
            seen.add(key); identities.add((r['league'], r['season']))
            if not 0 < r['event_utc'] <= r['observed_at_utc'] <= r['ingested_at_utc'] <= cutoff_utc:
                raise ValueError('CONTEXT_TRAINING_SOURCE_LEAKAGE')
            if (type(r['quarter']) is not int or r['quarter'] not in (1, 2, 3, 4) or type(r['points']) is not int or
                    not 0 <= r['points'] <= 4 or not math.isfinite(r['duration_seconds']) or not 0 < r['duration_seconds'] <= 120 or
                    not math.isfinite(r['score_gap_before']) or not math.isfinite(r['seconds_remaining_before']) or
                    not 0 < r['seconds_remaining_before'] <= (720 if r['league'] == 'NBA' else 600)):
                raise ValueError('INVALID_POSSESSION_REWARD_OR_HOLDING_TIME')
            context = self.context(r['quarter'], r['score_gap_before'], r['seconds_remaining_before'])
            groups.setdefault(context, []).append(r)
        required = {(q, gap, phase) for q in range(1, 5) for gap in ('TRAILING', 'CLOSE', 'LEADING')
                    for phase in (('NORMAL', 'LATE') if q == 4 else ('NORMAL',))}
        if set(groups) != required or any(len(v) < minimum_per_context for v in groups.values()):
            raise Abstain('INSUFFICIENT_CONTEXT_TRANSITION_COVERAGE')
        if len(identities) != 1: raise ValueError('SINGLE_CONTEXT_LEAGUE_SEASON_REQUIRED')
        self.identity = next(iter(identities)); self.cutoff = cutoff_utc; self.groups = {}
        for key, rows in groups.items():
            counts = np.bincount([r['points'] for r in rows], minlength=5)+1
            self.groups[key] = (counts/counts.sum(), float(np.mean([r['duration_seconds'] for r in rows])))
        self.artifact_digest = digest(dict(records=records, cutoff_utc=cutoff_utc, minimum_per_context=minimum_per_context))
        return self

    def simulate(self, cut, *, budget=Budget()):
        budget.validate(); began = time.perf_counter()
        if not hasattr(self, 'groups'): raise Abstain('NO_SEMI_MARKOV_MODEL_AVAILABLE')
        if self.identity != (cut.target['league'], cut.target['season']) or self.cutoff > cut.cutoff_utc:
            raise ValueError('SEMI_MARKOV_SEASON_OR_CUTOFF_CONFLICT')
        n = budget.scenarios; duration = 720 if cut.target['league'] == 'NBA' else 600
        samples = np.zeros((n, 4, 2), dtype=np.int32); total = np.zeros((n, 2), dtype=np.int32)
        rng = np.random.default_rng(budget.seed)
        for q in range(4):
            remaining = np.full(n, float(duration))
            for turn in range(400):
                before = remaining.copy(); active = before > 0
                if not active.any(): break
                side = turn % 2; gap = total[:, side]-total[:, 1-side]
                for context, (prob, hold) in self.groups.items():
                    if context[0] != q+1: continue
                    mask = active & ((gap < -8) if context[1] == 'TRAILING' else (gap > 8) if context[1] == 'LEADING' else (np.abs(gap) <= 8))
                    if q == 3: mask &= (before <= 120) if context[2] == 'LATE' else (before > 120)
                    index = np.flatnonzero(mask)
                    if not len(index): continue
                    points = rng.choice(len(prob), len(index), p=prob)
                    points[before[index] < hold] = 0
                    remaining[index] -= hold
                    samples[index, q, side] += points; total[index, side] += points
                budget.check(began, (samples, total, remaining))
            if np.any(remaining > 0): raise Abstain('SEMI_MARKOV_MAX_EVENTS_BUDGET')
        return samples
