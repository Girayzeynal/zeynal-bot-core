"""Frozen engine assumptions and MC/QMC numerical checks, not new pregame forecasts."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Cut,reference,local_path
from hybrid_engine.distributions import gaussian_forecast,quarter_weights
from hybrid_engine.frozen_archive import FrozenArchive,read_gzip


def audit(archive):
    rows=[]
    for r in archive.records.values():
        cut=Cut(**read_gzip(archive.path/('inputs-'+r['input_file_sha256']+'.json.gz')))
        p=reference(cut);means=[p[s] for s in ('home','away')];sd=[cut.features[s]['points_for_std'] for s in ('home','away')]
        values={};paths={}
        for method in ('MC','RQMC_HALTON','ANALYTIC'):
            began=time.perf_counter();f=gaussian_forecast(means,sd,quarter_weights(cut),method=method)
            values[method]=dict(winner=f.probabilities(),seconds=time.perf_counter()-began,scenarios=0 if f.samples is None else len(f.samples))
            if f.samples is not None:paths[method]=hashlib.sha256(f.samples.tobytes()).hexdigest()
        repeated=gaussian_forecast(means,sd,quarter_weights(cut),method='MC')
        if hashlib.sha256(repeated.samples.tobytes()).hexdigest()!=paths['MC']:raise ValueError('FROZEN_MC_NONDETERMINISTIC')
        exact=np.array(values['ANALYTIC']['winner'])
        for method in ('MC','RQMC_HALTON'):values[method]['max_winner_probability_error_vs_analytic']=float(np.max(np.abs(np.array(values[method]['winner'])-exact)))
        artifact=r['models']['BAYES_QMC']['prediction']['metadata']['artifact_digest'];b=json.loads((archive.path/('bayes-'+artifact+'.json')).read_text())
        teams=b['teams'];size=2+2*len(teams);x=np.zeros((2,size))
        for side,other,index in [('home','away',0),('away','home',1)]:
            x[index,0]=1;x[index,1]=int(side=='home')
            x[index,2+teams.index(cut.target[side+'_team_id'])]=1
            x[index,2+len(teams)+teams.index(cut.target[other+'_team_id'])]=1
        posterior=np.einsum('ij,jk,lk->il',x,np.array(b['covariance']),x,optimize=False)
        rows.append(dict(fixture_id=r['fixture']['canonical_id'],numerical_law='SAME_INDEPENDENT_ROUNDED_NORMAL_SAME_PERIOD_WEIGHTS',
            methods=values,seed=20261112,mc_repeat_sample_hash_identical=True,
            bayes_parameter_score_covariance=posterior.tolist(),bayes_observation_variance=b['noise_variance'],
            prior_scales=b['prior_scales'],home_effect_present=True,attack_defense_hierarchy=True,
            player_coefficients=len(b['players']),pace_model='BOX_POSSESSION_ESTIMATE_IN_SEPARATE_POSSESSION_COMPONENT',
            rest='START_TIME_GAP_PROXY_NOT_VERIFIED_REST_TRAVEL_OR_ROTATION'))
    return dict(format='FROZEN_ENGINE_AUDIT_V1',created_at_utc=int(time.time()),cases=rows,
        record_type='POSTHOC_DISTRIBUTION_AUDIT_NOT_NEW_PREMATCH',new_score_model=False,
        numerical_comparison_is_accuracy_or_calibration_claim=False,
        missing=['VERIFIED_PLAYER_ROTATION_INJURIES','EMPIRICAL_POSSESSION_CONTEXT_TRANSITIONS','CURRENT_VERIFIED_MARKET_LINES'],
        production_default='FAZ13',production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive-directory',required=True);p.add_argument('--output-directory',required=True);args=p.parse_args()
    result=audit(FrozenArchive(args.archive_directory));root=local_path(args.output_directory);root.mkdir(exist_ok=True,parents=True)
    path=root/('engine-audit-'+digest(result)+'.json');publish_json(path,result);print(json.dumps(dict(path=str(path),cases=len(result['cases']))))


if __name__=='__main__':main()
