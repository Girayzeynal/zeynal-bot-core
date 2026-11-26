"""Replay a median total-score correction against an immutable walk-forward report."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


def describe(errors):
    if not errors:
        return {'n': 0}
    return dict(n=len(errors), mae=mean(abs(x) for x in errors), rmse=math.sqrt(mean(x*x for x in errors)),
                bias=mean(errors), within_minus2_plus3=sum(-2 <= x <= 3 for x in errors),
                absolute_25_or_more=sum(abs(x) >= 25 for x in errors))


def compare(cohort, model='BAYES_QMC'):
    prior = {}
    original = []
    paired = []
    corrected = []
    folds = []
    rows = cohort['model_rows'][model]
    for fold in sorted(cohort['folds'], key=lambda f: f['test_cutoff']):
        cutoff = fold['test_cutoff']
        labels = {}
        for versions in fold['label_version_pins'].values():
            for entry in versions:
                key = entry['fixture_id']
                if key not in prior or entry['available_utc'] >= cutoff:
                    continue
                if key in labels and labels[key] != entry['label']:
                    raise ValueError('Conflicting historical target versions')
                labels[key] = entry['label']
        past = [prior[key] - sum(label) for key, label in labels.items()]
        offset = median(past) if past else None
        ids = set(fold['test_ids'])
        if ids.intersection(prior):
            raise ValueError('A fixture appears in more than one test fold')
        scored = 0
        for row in rows:
            key = row['fixture_id']
            if key not in ids:
                continue
            if (key in prior or row['role'] != 'TEST' or row['trace']['fold'] != fold['fold']
                    or not cutoff <= row['trace']['prediction_utc'] < row['start_utc']):
                raise ValueError('Invalid out-of-sample forecast')
            projection = row['prediction']['total']
            error = projection - sum(row['actual'])
            prior[key] = projection
            original.append(error)
            if offset is not None:
                paired.append(error)
                corrected.append(error - offset)
            scored += 1
        folds.append(dict(fold=fold['fold'], label_count=len(past), median_error=offset, test_count=scored))
    if len(prior) != len(rows):
        raise ValueError('Model rows outside the declared test folds')
    return dict(archive=describe(original), paired_original=describe(paired),
                paired_corrected=describe(corrected), folds=folds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    report = json.loads(gzip.decompress(raw))
    if report['data_class'] != 'REAL_HISTORICAL' or report['evaluation_class'] != 'PIT_PROVEN_BACKTEST':
        raise ValueError('Requires a point-in-time historical replay')
    print(json.dumps(dict(report_sha256=hashlib.sha256(raw).hexdigest(),
                          cohorts={k:compare(v) for k,v in report['cohorts'].items()}), indent=2))


if __name__ == '__main__':
    main()
