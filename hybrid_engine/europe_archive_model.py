"""Restore original European parameters for SHA-checked replay, never live fitting.

The three-day admission rule belongs to the ORIGINAL forecast clock. Passing
that boundary later must not invalidate reproducing its frozen sample paths.
The live PreparedEurope loader and its source pins stay unchanged.
"""
import time
import numpy as np

from core.team_identity import digest
from hybrid_engine.data import STRICT,available_at,regulation
from hybrid_engine.europe_models import VERSION,specification,pins,catalog,past_rows
from hybrid_engine.models import HierarchicalStrength


def restore(wrapper,receipt,ctx):
    p=wrapper['payload'];a=p['model'];generated=ctx['prediction_generated_at_utc']
    league=ctx['league'];year=int(ctx['season'][:4]);specification(league,year)
    identity=('EuroLeague' if league=='EUROLEAGUE' else 'EuroCup',f'{year}/{year+1}')
    clocks=[a['training_available_max'],a['cutoff_utc'],p['prepared_at_utc'],generated]
    if (digest(p)!=wrapper['sha256'] or wrapper['sha256']!=ctx['model_digest'] or
            digest(a)!=p['model_sha256'] or p['source_pins']!=pins() or
            p['format']!=VERSION or p['league']!=league or p['season']!=identity[1] or
            tuple(a['identity'])!=identity or a['players'] or a['mode']!=STRICT or
            any(type(c) is not int for c in clocks) or
            not 0<clocks[0]<=clocks[1]<=clocks[2]<=clocks[3]<=int(time.time()) or
            generated>=ctx['fixture_start_utc'] or generated-p['prepared_at_utc']>3*86400 or
            p['production_enabled'] is not False or ctx['fixture_id'] in a['training_ids']):
        raise ValueError('ARCHIVED_EUROPE_MODEL_SCOPE_OR_CLOCK')
    if digest(receipt)!=p['training_source']['sha256']:
        raise ValueError('ARCHIVED_EUROPE_TRAINING_SOURCE_PIN')
    bundle=catalog(receipt,league,year,max_age=None);rows=past_rows(bundle,a['cutoff_utc'])
    trace=digest([dict(id=r['fixture_id'],scores=regulation(r),source=r['source_catalog_sha256'],
        available=available_at(r,STRICT)) for r in rows])
    if (p['source_catalog_sha256']!=bundle['sha256'] or
            a['training_ids']!=sorted(r['fixture_id'] for r in rows) or
            a['training_digest']!=trace or p['training_games']!=len(rows) or len(rows)<30):
        raise ValueError('ARCHIVED_EUROPE_TRAINING_TRACE')
    n=2+2*len(a['teams']);coef=np.asarray(a['coefficients']);cov=np.asarray(a['covariance'])
    if (not 1<=len(a['teams'])<=64 or len(set(a['teams']))!=len(a['teams']) or
            coef.shape!=(n,) or cov.shape!=(n,n) or not np.isfinite(coef).all() or
            not np.isfinite(cov).all() or not np.allclose(cov,cov.T) or
            not 0<a['noise_variance']<10000):
        raise ValueError('ARCHIVED_EUROPE_NUMERIC_PARAMETERS')
    try:np.linalg.cholesky(cov)
    except np.linalg.LinAlgError as exc:raise ValueError('ARCHIVED_EUROPE_COVARIANCE') from exc
    model=HierarchicalStrength();model.identity=identity;model.mode=STRICT;model.cutoff=a['cutoff_utc']
    model.teams=a['teams'];model.team_index={t:i for i,t in enumerate(model.teams)}
    model.players=[];model.player_index={};model.duration=40;model.coefficients=coef;model.covariance=cov
    model.noise_variance=a['noise_variance'];model.training_ids=a['training_ids']
    model.artifact_digest=p['model_sha256'];model.fitted=True
    return model
