"""Offline synthetic resource fixture. Its labels are NEVER performance evidence."""
from dataclasses import asdict
import json
import hashlib
from pathlib import Path

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT, feature_cut, local_path
from hybrid_engine.models import BoostedScores, HierarchicalStrength
from hybrid_engine.portable import PortableBoostedScores, export_portable


def prepare(directory, *, cache_sources=None):
    from tests.test_hybrid_models import synthetic_cohort, example
    import numpy as np
    root = local_path(directory); root.mkdir(parents=True, exist_ok=True)
    cohort = synthetic_cohort(240); target = feature_cut(cohort, cohort[220][0])
    train = [example(cohort, i, 'TRAIN') for i in range(12, 152)]
    validation = [example(cohort, i, 'VALIDATION') for i in range(152, 192)]
    manifest = dict(format='SYNTHETIC_RUNTIME_FIXTURE_V1', data_class='SYNTHETIC_RESOURCE_ONLY',
        performance_evidence=False, cut=asdict(target), models={}, native_portable_checks={})
    for name in ('LIGHTGBM', 'CATBOOST'):
        native = BoostedScores(name).fit(train, cutoff_utc=cohort[152][0]['fixture_start_utc']-1)
        native.fit_residual_scale(validation, cutoff_utc=cohort[192][0]['fixture_start_utc']-1)
        artifact = export_portable(native); path = root/(name.lower()+'.json'); publish_json(path, artifact)
        portable = PortableBoostedScores.from_artifact(artifact, trusted_sha256=artifact['sha256'])
        errors = [float(np.max(np.abs(native._scores(feature_cut(cohort, cohort[i][0]))-portable._scores(feature_cut(cohort, cohort[i][0]))))) for i in range(192, 240)]
        if max(errors) > 1e-5: raise ValueError('NATIVE_PORTABLE_NUMERIC_MISMATCH')
        manifest['models'][name] = dict(path=str(path), sha256=artifact['sha256'])
        manifest['native_portable_checks'][name] = dict(n=48, max_absolute_error=max(errors))
    bayes = HierarchicalStrength().fit(target.history[:140], cutoff_utc=cohort[152][0]['fixture_start_utc']-1, mode=STRICT)
    artifact = bayes.artifact(); manifest['bayes'] = dict(payload=artifact, sha256=digest(artifact))
    manifest['cache_source_documents'] = []
    if cache_sources is not None:
        for path in sorted(local_path(cache_sources).glob('*.json')):
            raw = path.read_bytes(); receipt = json.loads(raw)
            if receipt.get('provider') != 'ESPN' or 'document' not in receipt: continue
            manifest['cache_source_documents'].append(dict(path=str(path), file_sha256=hashlib.sha256(raw).hexdigest()))
            if len(manifest['cache_source_documents']) == 32: break
        if len(manifest['cache_source_documents']) != 32: raise ValueError('32_NATIVE_PAYLOADS_REQUIRED_FOR_CACHE_STRESS')
    path = root/'fixture.json'; publish_json(path, manifest)
    return path
