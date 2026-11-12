"""Offline numerical error and bounded core inference benchmark; no model training in handlers."""
import argparse
import json
from pathlib import Path
import platform
import os
import resource
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import ASSUMED, feature_cut, load_manifest, local_path
from hybrid_engine.distributions import Budget, gaussian_forecast
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.possession import PossessionModel


def measured(job, repeats):
    elapsed = []; value = None
    for i in range(repeats):
        began = time.perf_counter(); value = job(i); elapsed.append(time.perf_counter()-began)
    return dict(p50_seconds=float(np.median(elapsed)), p95_seconds=float(np.quantile(elapsed, .95)),
        max_seconds=max(elapsed), repetitions=repeats, final_winner=value.probabilities())


def benchmark(manifest, *, repetitions=20):
    cohort, provenance = load_manifest(manifest)
    report = dict(format='HYBRID_RESOURCE_BENCHMARK_V1', generated_at_utc=int(time.time()),
        python_version=platform.python_version(), numpy_version=np.__version__, provenance=provenance,
        scope='CACHED_CUT_CORE_INFERENCE_NOT_WHOLE_TELEGRAM_PROCESS', cohorts={}, numerical_comparison={})
    means = [112., 108.]; std = [12., 11.]; weights = np.ones((4, 2))
    exact = gaussian_forecast(means, std, weights, method='ANALYTIC')
    truth = np.array(exact.probabilities()+list(exact.market('TOTAL', 220).values()))
    for method in ('MC', 'RQMC_HALTON', 'ANALYTIC'):
        errors = []
        def predict(i):
            f = gaussian_forecast(means, std, weights, method=method, budget=Budget(seed=20261112+i))
            errors.append(np.array(f.probabilities()+list(f.market('TOTAL', 220).values()))-truth)
            return f
        metrics = measured(predict, repetitions)
        metrics['probability_rmse_vs_assumed_analytic_law'] = float(np.sqrt(np.mean(np.array(errors)**2)))
        metrics['scenarios'] = 0 if method == 'ANALYTIC' else 10000
        metrics['interpretation'] = 'NUMERICAL_INTEGRATION_ERROR_NOT_REAL_GAME_ACCURACY_OR_CALIBRATION'
        report['numerical_comparison'][method] = metrics
    groups = sorted({(v[0]['league'], v[0]['season']) for v in cohort})
    for league, season in groups:
        target = max((v[0] for v in cohort if (v[0]['league'], v[0]['season']) == (league, season)),
                     key=lambda r: r['fixture_start_utc'])
        cut = feature_cut(cohort, target, mode=ASSUMED)
        # Fit offline before timing predictions. This process is not a Telegram handler.
        bayes = HierarchicalStrength().fit(cut.history, cutoff_utc=cut.cutoff_utc, mode=ASSUMED)
        models = dict(FAZ13=lambda i: v1_forecast(cut),
            POSSESSION_ANALYTIC=lambda i: PossessionModel().predict(cut),
            POSSESSION_MC=lambda i: PossessionModel().predict(cut, method='MC', budget=Budget(seed=20261112+i)),
            BAYES_RQMC=lambda i: bayes.predict(cut, method='RQMC_HALTON', budget=Budget(seed=20261112+i)))
        report['cohorts'][league+' '+season] = {name: measured(job, repetitions) for name, job in models.items()}
    report['peak_process_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    report['address_space_limit_bytes'] = list(resource.getrlimit(resource.RLIMIT_AS))
    report['cpu_affinity'] = sorted(os.sched_getaffinity(0))
    for name in ('memory.max', 'memory.peak', 'cpu.max'):
        p = Path('/sys/fs/cgroup')/name
        if p.exists(): report['cgroup_'+name] = p.read_text().strip()
    report['heavy_optional_ml_inference_in_container'] = 'NOT_TESTED_RUNTIME_IMAGE_HAS_NO_ML_PACKAGES'
    report['all_core_calls_below_two_seconds'] = all(m['max_seconds'] < 2 for g in report['cohorts'].values() for m in g.values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(); report = benchmark(args.manifest)
    publish_json(local_path(args.output), report)
    print(json.dumps(dict(report=args.output, content_digest=digest(report),
        peak_rss_mib=report['peak_process_rss_mib'], below_two_seconds=report['all_core_calls_below_two_seconds'])))


if __name__ == '__main__': main()
