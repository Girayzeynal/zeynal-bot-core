"""Paired game-day cluster uncertainty, with an explicit small-cluster abstention."""
import numpy as np

from hybrid_engine.evaluation import point_metrics, probability_metrics
from hybrid_engine.markets import wilson


def calibration_curve(probabilities, outcomes, *, bins=10):
    p = np.asarray(probabilities, dtype=float); y = np.asarray(outcomes)
    result = []
    for i in range(bins):
        mask = (p >= i/bins)&(p <= 1 if i == bins-1 else p < (i+1)/bins)
        n = int(mask.sum()); successes = int(y[mask].sum())
        result.append(dict(bin=[i/bins, (i+1)/bins], n=n,
            predicted=float(p[mask].mean()) if n else None,
            observed=successes/n if n else None, observed_wilson_95=wilson(successes, n)))
    return result


def paired_cluster_interval(baseline, candidate, *, iterations=2000, seed=20261112, family_size=13):
    """Resample TSİ game-day clusters, not individual team rows or individual lines.

    Shared-team dependence across dates is not fully solved by this estimator.
    Family-wise 95% intervals use a predeclared Bonferroni correction.
    """
    b = {r['fixture_id']: r for r in baseline}; c = {r['fixture_id']: r for r in candidate}
    ids = sorted(set(b)&set(c)); days = sorted({(b[i]['start_utc']+10800)//86400 for i in ids})
    if not ids: return dict(status='NOT_EVALUABLE', n=0, day_clusters=0)
    if any(b[i]['actual'] != c[i]['actual'] or b[i]['actual_quarters'] != c[i]['actual_quarters'] or b[i]['start_utc'] != c[i]['start_utc'] for i in ids):
        raise ValueError('PAIRED_COMPARISON_REQUIRES_IDENTICAL_OUTCOMES_AND_START')
    def loss(row):
        p = row['prediction']; a = np.asarray(row['actual']); q = np.asarray(p['quarters']); aq = np.asarray(row['actual_quarters'])
        return np.array([np.abs(np.array([p['home'], p['away']])-a).mean(),
            (np.array([p['home'], p['away']])-a).dot(np.array([p['home'], p['away']])-a)/2,
            np.abs(q[0]-aq[0]).mean(), np.abs(q[:2].sum(axis=0)-aq[:2].sum(axis=0)).mean(),
            abs(p['total']-a.sum()), abs(p['margin']-(a[0]-a[1])),
            *[np.abs(q[i]-aq[i]).mean() for i in range(1, 4)],
            np.abs(q[2:].sum(axis=0)-aq[2:].sum(axis=0)).mean(),
            abs(p['home']-a[0]), abs(p['away']-a[1])])
    bl = np.array([loss(b[i]) for i in ids]); ca = np.array([loss(c[i]) for i in ids]); errors = ca-bl
    names = ('team_mae', 'team_mse', 'first_quarter_mae', 'first_half_mae', 'total_mae', 'margin_mae',
             'second_quarter_mae', 'third_quarter_mae', 'fourth_quarter_mae', 'second_half_mae', 'home_mae', 'away_mae')
    result = dict(status='EXPLORATORY_CLUSTER_INTERVAL', n=len(ids), day_clusters=len(days),
        unit='PAIRED_TSI_GAME_DAY_CLUSTER', family_size=family_size,
        dependence_limit='CROSS_DAY_REPEATED_TEAM_DEPENDENCE_NOT_FULLY_MODELED', metrics={})
    if len(days) < 8:
        result.update(status='INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM')
        for j, name in enumerate(names): result['metrics'][name] = dict(baseline=float(bl[:, j].mean()), candidate=float(ca[:, j].mean()), interval=None)
        return result
    groups = [np.flatnonzero([(b[i]['start_utc']+10800)//86400 == day for i in ids]) for day in days]
    rng = np.random.default_rng(seed); samples = []; rmse_samples = []
    for _ in range(iterations):
        indexes = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        samples.append(errors[indexes].mean(axis=0))
        rmse_samples.append(np.sqrt(ca[indexes, 1].mean())-np.sqrt(bl[indexes, 1].mean()))
    samples = np.asarray(samples); alpha = .05/max(1, family_size)
    for j, name in enumerate(names):
        result['metrics'][name] = dict(baseline=float(bl[:, j].mean()), candidate=float(ca[:, j].mean()),
            difference=float(errors[:, j].mean()), interval=np.quantile(samples[:, j], [alpha/2, 1-alpha/2]).tolist())
    result['metrics']['team_rmse'] = dict(baseline=float(np.sqrt(bl[:, 1].mean())),
        candidate=float(np.sqrt(ca[:, 1].mean())), difference=float(np.sqrt(ca[:, 1].mean())-np.sqrt(bl[:, 1].mean())),
        interval=np.quantile(rmse_samples, [alpha/2, 1-alpha/2]).tolist())
    return result


def market_metrics(rows, market, offset):
    values = [m for r in rows for m in r['line_grid'] if m['market'] == market and m['offset'] == offset and m['probabilities'] is not None]
    if not values: return dict(n=0, status='NO_SUPPORTED_DISTRIBUTIONS')
    p = np.array([[v['probabilities'][k] for k in ('under', 'push', 'over')] for v in values])
    y = np.array([v['outcome'] for v in values]); result = probability_metrics(p, y)
    result['calibration_under'] = calibration_curve(p[:, 0], y == 0)
    result['calibration_over'] = calibration_curve(p[:, 2], y == 2)
    result['line_kind'] = 'MODEL_REFERENCE_SCENARIO_NOT_OBSERVED_MARKET_QUOTE'
    return result


def paired_market_interval(baseline, candidate, market, offset, *, seed=20261112, iterations=1000, family_size=30):
    def collect(rows):
        out = {}
        for row in rows:
            entries = [m for m in row['line_grid'] if m['market'] == market and m['offset'] == offset and m['probabilities'] is not None]
            if entries: out[row['fixture_id']] = (row, entries[0])
        return out
    b = collect(baseline); c = collect(candidate); ids = sorted(set(b)&set(c))
    if not ids: return dict(status='UNSUPPORTED_COMMON_DISTRIBUTION', n=0)
    days = sorted({(b[i][0]['start_utc']+10800)//86400 for i in ids})
    def loss(entry):
        p = np.array([entry['probabilities'][k] for k in ('under', 'push', 'over')]); truth = np.eye(3)[entry['outcome']]
        return [np.sum((p-truth)**2), -np.log(max(1e-15, p[entry['outcome']]))]
    if any(b[i][1]['line'] != c[i][1]['line'] or b[i][1]['outcome'] != c[i][1]['outcome'] or
           b[i][0]['start_utc'] != c[i][0]['start_utc'] for i in ids):
        raise ValueError('PAIRED_MARKET_REQUIRES_IDENTICAL_FIXTURE_LINE_AND_OUTCOME')
    bl = np.array([loss(b[i][1]) for i in ids]); ca = np.array([loss(c[i][1]) for i in ids]); diff = ca-bl
    result = dict(n=len(ids), day_clusters=len(days), market=market, offset=offset,
        family_size=family_size,
        interval_family=f'{family_size}_MARKET_LINE_CELLS_PER_METRIC_AND_MODEL_NOT_ALL_MODELS_JOINTLY',
        status='INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM' if len(days) < 8 else 'EXPLORATORY_CLUSTER_INTERVAL', metrics={})
    intervals = [None, None]
    if len(days) >= 8:
        groups = [np.flatnonzero([(b[i][0]['start_utc']+10800)//86400 == day for i in ids]) for day in days]
        rng = np.random.default_rng(seed); samples = []
        for _ in range(iterations):
            index = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
            samples.append(diff[index].mean(axis=0))
        alpha = .05/family_size
        intervals = np.quantile(samples, [alpha/2, 1-alpha/2], axis=0).T.tolist()
    for j, metric in enumerate(('brier', 'log_loss')):
        result['metrics'][metric] = dict(baseline=float(bl[:, j].mean()), candidate=float(ca[:, j].mean()),
            difference=float(diff[:, j].mean()), familywise_interval=intervals[j])
    return result


def paired_winner_interval(baseline, candidate, *, iterations=2000):
    def transform(rows):
        out=[]
        for r in rows:
            p=r['prediction']['winner']
            if p is None:continue
            a=r['actual'];y=0 if a[0]>a[1] else 1 if a[0]==a[1] else 2
            out.append(dict(r,line_grid=[dict(market='WINNER',offset=0.,line=0.,outcome=y,
                probabilities=dict(zip(('under','push','over'),p)))]))
        return out
    result=paired_market_interval(transform(baseline),transform(candidate),'WINNER',0.,
        iterations=iterations,family_size=2)
    result['probability_order']='HOME_REGULATION_WIN_TIE_AWAY_REGULATION_WIN'
    result['interval_family']='2_WINNER_LOSSES_PER_MODEL_NOT_ALL_MODELS_JOINTLY'
    return result
