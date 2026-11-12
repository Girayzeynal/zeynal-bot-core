"""Quantiles of actual frozen sample paths, distinct from empirical coverage."""
import hashlib
import inspect
import json
import time
from pathlib import Path
import numpy as np

from hybrid_engine.data import Abstain
from hybrid_engine.markets import wilson

LEVELS=(.05,.10,.25,.50,.75,.90,.95)
KEYS=('p05','p10','p25','p50','p75','p90','p95')


def sample_paths(forecast):
    paths=forecast.samples
    if paths is None:
        paths=getattr(getattr(forecast.law,'paths',None),'samples',None)
    if paths is None:raise Abstain('NO_ACTUAL_SAMPLE_PATHS_FOR_QUANTILES')
    a=np.asarray(paths)
    if a.ndim!=3 or a.shape[1:]!=(4,2) or len(a)<10000 or not np.isfinite(a).all() or np.any(a<0):
        raise ValueError('VALID_ACTUAL_SIMULATION_PATHS_REQUIRED')
    return a


def market_values(paths):
    teams=paths.sum(axis=1);margin=teams[:,0]-teams[:,1]
    return dict(TOTAL=teams.sum(axis=1),HOME=teams[:,0],AWAY=teams[:,1],MARGIN=margin,HOME_HANDICAP=-margin,
        **{str(i+1)+'Q':paths[:,i].sum(axis=1) for i in range(4)},
        **{str(i+1)+'H':paths[:,2*i:2*i+2].sum(axis=(1,2)) for i in range(2)})


def prediction_intervals(forecast):
    try:paths=sample_paths(forecast)
    except Abstain as exc:return dict(status='UNSUPPORTED',reason=str(exc),scenarios=0,markets={})
    result={}
    for name,values in market_values(paths).items():
        q=dict(zip(KEYS,map(float,np.quantile(values,LEVELS,method='linear'))))
        q.update(narrow_width=q['p75']-q['p25'],wide_width=q['p95']-q['p05'])
        result[name]=q
    def correlations(values):
        centered=values.astype(float)-values.mean(axis=0)
        # Avoid lazy BLAS GEMM workspace under the hard inference address cap.
        covariance=np.einsum('ni,nj->ij',centered,centered,optimize=False)/(len(values)-1)
        sd=np.sqrt(np.diag(covariance))
        return [[float(covariance[i,j]/(sd[i]*sd[j])) if sd[i]>0 and sd[j]>0 else None for j in range(len(sd))] for i in range(len(sd))]
    return dict(status='RAW_MODEL_QUANTILES_NOT_CALIBRATED',scenarios=len(paths),markets=result,
        simulated_correlations=dict(team_scores=correlations(paths.sum(axis=1)),quarter_totals=correlations(paths.sum(axis=2))),
        sample_sha256=hashlib.sha256(paths.dtype.str.encode()+str(paths.shape).encode()+paths.tobytes()).hexdigest(),
        quantile_method='LINEAR',scope='REGULATION_ONLY',verified_coverage=None,
        distinction='NOMINAL_CENTRAL_MASS_IS_NOT_EMPIRICAL_COVERAGE_OR_MODEL_CONFIDENCE')


def actual_market_values(periods):
    q=np.asarray([periods[s][:4] for s in ('home','away')]).T
    if q.shape!=(4,2) or np.any(q<0):raise ValueError('FOUR_REGULATION_PERIODS_REQUIRED')
    return {k:float(v[0]) for k,v in market_values(q[None,:,:]).items()}


def empirical_coverage(cases):
    """Descriptive realized coverage; Wilson intervals assume independent games."""
    grouped={}
    for bands,periods in cases:
        if bands['status']=='UNSUPPORTED':continue
        actual=actual_market_values(periods)
        for market,q in bands['markets'].items():
            grouped.setdefault(market,[]).append((q,actual[market]))
    result={}
    for name,rows in grouped.items():
        cells={}
        for label,lo,hi,nominal in [('P25_P75','p25','p75',.5),('P10_P90','p10','p90',.8),('P05_P95','p05','p95',.9)]:
            hits=sum(q[lo]<=actual<=q[hi] for q,actual in rows);n=len(rows)
            cells[label]=dict(n=n,hits=hits,observed_coverage=hits/n,nominal_mass=nominal,
                wilson_95=wilson(hits,n),mean_width=float(np.mean([q[hi]-q[lo] for q,a in rows])))
        result[name]=cells
    return dict(markets=result,status='DESCRIPTIVE_NOT_CALIBRATION_PROOF',
        intervals_assume_independent_games=True,cross_game_dependence_not_corrected=True)


def assert_frozen_sampler_sources(record):
    from hybrid_engine import evaluation
    root=Path(__file__).parent
    for name in ('models.py','distributions.py','possession.py','../prematch_monte_carlo.py','../historical_research.py'):
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=record['source_code_pins'][name]:
            raise ValueError('FROZEN_SAMPLER_SOURCE_CHANGED:'+name)
    # evaluation.py also contains reporting code whose margin-bias sign was fixed.
    # Pin only its unchanged native sampler bridge, not the reporting function.
    # Pin verbatim source, verified equal to the d2f88ba bridge. AST dump text
    # changes between Python 3.11 and 3.12 (e.g. type_params=[]), even for the
    # same source. The exact text pin rejects actual sampler edits on both.
    sources=[inspect.getsource(obj) for obj in (evaluation.V1Law,evaluation.v1_forecast)]
    if hashlib.sha256('\n'.join(sources).encode()).hexdigest()!='9395cf47ac364b1a254c14f57858f19892383deeb6a33a6bbaf3a645e0944d40':
        raise ValueError('FROZEN_V1_SAMPLER_BRIDGE_CHANGED')


def derive_frozen_bands(archive,directory):
    from core.team_identity import digest
    from hybrid_engine.boxes import publish_json
    from hybrid_engine.data import local_path,Cut
    from hybrid_engine.frozen_archive import read_gzip
    root=local_path(directory);root.mkdir(parents=True,exist_ok=True);items=[]
    for fid,r in archive.records.items():
        assert_frozen_sampler_sources(r)
        cut=Cut(**read_gzip(archive.path/('inputs-'+r['input_file_sha256']+'.json.gz')))
        models={}
        for name,m in r['models'].items():
            if m['status']=='FORECAST_CREATED':models[name]=prediction_intervals(archive.replay(r,name,cut=cut))
        items.append(dict(fixture_id=fid,forecast_sha256=digest(r),models=models))
    p=dict(format='FROZEN_INTERVAL_DIAGNOSTICS_V1',created_at_utc=int(time.time()),
        record_type='POSTHOC_FROZEN_DISTRIBUTION_DIAGNOSTIC_NOT_NEW_PREMATCH',
        frozen_sampler_sources_verified=True,intervals_pre_registered_before_results=False,items=items)
    path=root/('intervals-'+digest(p)+'.json');publish_json(path,dict(payload=p,sha256=digest(p)))
    return path,p
