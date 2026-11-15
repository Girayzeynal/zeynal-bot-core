"""Read-only quality and provenance audit outside the six frozen model pins.

An audit may explain a legacy field; it never rewrites a snapshot, refits a model,
or calls a live provider to backfill evidence into a historical prediction.
"""
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Cut,local_path
from projection_integrity import assert_projection
from season_archive_inventory import archive_catalog


class Assets:
    def __init__(self,directory):self.root=local_path(directory)
    def read(self,ref):
        if Path(ref['file']).name!=ref['file']:raise ValueError('AUDIT_ASSET_PATH')
        path=local_path(self.root/ref['file'])
        if path.stat().st_size>4*1024*1024:raise ValueError('AUDIT_ASSET_BUDGET')
        p=json.loads(path.read_text())
        if digest(p)!=ref['sha256']:raise ValueError('AUDIT_ASSET_PIN')
        return p


def audit_snapshot(snapshot,directory,*,replay=False):
    """Native identity, actual input availability and unchanged-distribution audit."""
    p=snapshot;assets=Assets(directory);generated=p['prediction_generated_at_utc'];tip=p['fixture_start_utc']
    cut=assets.read(p['input_asset']);prepared=assets.read(p['prepared_asset'])
    clocks=[p['parameter_fit_cutoff_utc'],p['feature_cutoff_utc'],p['simulation_completed_at_utc'],generated,p['created_at_utc'],tip]
    if (any(type(v) is not int for v in clocks) or not 0<clocks[0]<=clocks[1]<=clocks[2]<=clocks[3]<=clocks[4]<clocks[5] or
        prepared['sha256']!=p['prepared_artifact_sha256'] or digest(prepared['payload'])!=prepared['sha256'] or
        prepared['payload']['prepared_at_utc']>generated or prepared['payload']['model']['cutoff_utc']!=clocks[0] or
        p['fixture_id'] in prepared['payload']['model']['training_ids']):
        raise ValueError('AUDIT_MODEL_OR_PREMATCH_CLOCK')
    pins=p['input_clocks']
    if p['source_digest']!=digest(pins) or any(
        type(r.get('observed_at_utc')) is not int or type(r.get('ingested_at_utc')) is not int or
        not 0<r['observed_at_utc']<=r['ingested_at_utc']<=generated for r in pins):
        raise ValueError('AUDIT_INPUT_CLOCKS_OR_DIGEST')
    if not pins or p['source_data_time_utc']!=max(r['ingested_at_utc'] for r in pins):
        raise ValueError('AUDIT_SOURCE_DATA_TIME')
    if p.get('calibration_status')!='NOT_CALIBRATED' or p['prediction'].get('calibration_status')!='NOT_CALIBRATED' or p['confidence'].get('value') is not None:
        raise ValueError('AUDIT_UNSUPPORTED_CALIBRATION_CLAIM')
    if p['scope']!='REGULATION_ONLY' or p['prediction']['scope']!='REGULATION_ONLY':raise ValueError('AUDIT_REGULATION_SCOPE')
    assert_projection(p['prediction'])
    q=p['prediction'];prob=q.get('winner')
    if (not isinstance(prob,list) or len(prob)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in prob) or
        abs(sum(prob)-1)>1e-8):raise ValueError('AUDIT_PROBABILITY_SIMPLEX')
    bands=p['intervals']
    if (bands.get('scope')!='REGULATION_ONLY' or type(bands.get('scenarios')) is not int or
        bands['scenarios']!=q['metadata'].get('scenarios') or bands['scenarios']<10000):
        raise ValueError('AUDIT_SAMPLE_COUNT_OR_SCOPE')
    for b in bands['markets'].values():
        values=[b[k] for k in ('p05','p10','p25','p50','p75','p90','p95')]
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or values!=sorted(values):
            raise ValueError('AUDIT_QUANTILE_ORDER')
    keys=('p05','p10','p25','p50','p75','p90','p95')
    for a,b in zip(keys,reversed(keys)):
        if abs(bands['markets']['HOME_HANDICAP'][a]+bands['markets']['MARGIN'][b])>1e-8:
            raise ValueError('AUDIT_HANDICAP_MARGIN_QUANTILE_CONFLICT')
    from hybrid_engine.live_nba import VERSION,sampler_pins
    if (prepared['payload']['source_code_pins']!=sampler_pins() or p['model_version']!=VERSION or
        p['model_digest']!=digest(dict(version=VERSION,prepared_artifact=p['prepared_artifact_sha256'],
            seed=q['metadata']['seed'],scenarios=bands['scenarios'],source_code_pins=sampler_pins())) or
        q['metadata']['artifact_digest']!=prepared['payload']['model_sha256']):
        raise ValueError('AUDIT_MODEL_VERSION_OR_SOURCE_PIN')
    model=prepared['payload']['model']
    if digest(model)!=prepared['payload']['model_sha256'] or model['training_available_max']>model['cutoff_utc']:
        raise ValueError('AUDIT_MODEL_TRAINING_PROVENANCE')
    if (cut['cutoff_utc']!=p['feature_cutoff_utc'] or cut['target']['fixture_id']!=p['fixture_id'] or
        cut['target']['fixture_start_utc']!=tip or cut['target']['home_team_id']!=p['home']['provider_id'] or
        cut['target']['away_team_id']!=p['away']['provider_id']):raise ValueError('AUDIT_INPUT_TARGET_CONFLICT')
    for row in cut['history']:
        if (row['fixture_id']==p['fixture_id'] or row['fixture_start_utc']>=p['feature_cutoff_utc'] or
            not row['fixture_start_utc']<max(row['observed_at_utc'],row['ingested_at_utc'])<=p['feature_cutoff_utc']):
            raise ValueError('AUDIT_HISTORY_AVAILABILITY_LEAKAGE')
    verified=[];native_status=[]
    for ref in p['source_assets']:
        r=assets.read(ref)
        if (r.get('provider')!='ESPN' or r.get('status')!='DOCUMENT_RECEIVED' or r.get('http_status')!=200 or
            digest(r['document'])!=r['document_sha256'] or
            any(type(r.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<r['observed_at_utc']<=r['ingested_at_utc']<=generated):raise ValueError('AUDIT_SOURCE_TIME_OR_PIN')
        if '/scoreboard?' not in r['source_url']:continue
        # No current download: original pre-tipoff receipts establish fixture identity.
        if not r['source_url'].startswith('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?'):
            raise ValueError('AUDIT_FIXTURE_PROVIDER_BINDING')
        c=archive_catalog(r['document'],provider='ESPN',season_start_year=int(p['season'].split('/')[0]),
            observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'],regular_season_filter=True)
        matches=[g for g in c['payload']['fixtures'] if set(g['provider_fixture_ids'])&set(p['provider_fixture_ids'])]
        for g in matches:
            if (g['canonical_id']!=p['fixture_id'] or g['start_ts_utc']!=tip or g['completed'] or
                g['home_team_id']!=p['home']['provider_id'] or g['away_team_id']!=p['away']['provider_id']):
                raise ValueError('AUDIT_NATIVE_FIXTURE_CONFLICT')
            events=[e for e in r['document']['events'] if e['id'] in p['provider_fixture_ids']]
            for e in events:
                status=e['competitions'][0].get('status',e.get('status',{})).get('type',{}).get('name')
                if status!='STATUS_SCHEDULED':raise ValueError('AUDIT_NATIVE_NOT_SCHEDULED')
                native_status.append(status)
            verified.append(r['source_url'])
    if not verified:raise ValueError('AUDIT_TARGET_NATIVE_SOURCE_REQUIRED')
    recorded=p['fixture_source_url'];unique=sorted(set(verified))
    correlations=p['intervals'].get('simulated_correlations',{}).get('quarter_totals')
    off_diagonal=[] if correlations is None else [correlations[i][j] for i in range(4) for j in range(i)]
    report=dict(format='FROZEN_PREMATCH_QUALITY_AUDIT_V1',audit_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),snapshot_sha256=digest(p),status='VERIFIED_WITH_LIMITATIONS',
        original_recorded_fixture_source=recorded,verified_fixture_sources=unique,
        recorded_source_contains_fixture=recorded in unique,source_annotation_required=recorded not in unique,
        source_annotation_policy='KEEP_ORIGINAL_FIELD_DISPLAY_VERIFIED_NATIVE_SOURCE_SEPARATELY',
        raw_projection_coherent=True,scope='REGULATION_ONLY',winner_class_order=['HOME','REGULATION_TIE','AWAY'],
        calibration_status='NOT_CALIBRATED',confidence_index=None,source_time_utc=p['source_data_time_utc'],
        model_version=p['model_version'],parameter_fit_cutoff_utc=p['parameter_fit_cutoff_utc'],
        period_allocation=q['metadata']['quarter_allocation'],
        mean_off_diagonal_quarter_correlation=None if not off_diagonal else float(np.mean(off_diagonal)),
        period_uncertainty_limit='DETERMINISTIC_ALLOCATION_NOT_INDEPENDENT_POSSESSION_OR_PBP_SIMULATION',
        measured_possession_pace_used=False,verified_rotation_or_player_impact_used=False,
        model_type='EMPIRICAL_BAYES_TEAM_ATTACK_DEFENSE_IN_POINTS_NOT_PER_100_POSSESSIONS',
        missing_data=list(p['missing_data']),training_in_request=False,archived_prediction_changed=False,
        audit_at_utc=int(time.time()),replay_only=replay)
    if replay:
        from hybrid_engine.live_nba import PreparedBayes
        from hybrid_engine.intervals import prediction_intervals,sample_paths
        frozen=PreparedBayes(assets.root/p['prepared_asset']['file'],trusted_sha256=p['prepared_artifact_sha256'])
        if frozen.digest!=p['model_digest']:raise ValueError('AUDIT_PREPARED_MODEL_DIGEST')
        forecast=frozen.model.predict(Cut(**cut),method='RQMC_HALTON',bounded_workspace=True)
        reproduced=forecast.summary()
        for field in ('home','away','total','margin','home_handicap','quarters','halves','winner'):
            if not np.allclose(reproduced[field],q[field],atol=1e-8,rtol=0):
                raise ValueError('AUDIT_FROZEN_PROJECTION_REPLAY_MISMATCH')
        bands=prediction_intervals(forecast)
        if bands['sample_sha256']!=p['intervals']['sample_sha256'] or bands['markets']!=p['intervals']['markets']:
            raise ValueError('AUDIT_FROZEN_QMC_SAMPLE_MISMATCH')
        x=[];extra=[]
        for side,other in [('home','away'),('away','home')]:
            v,e=frozen.model._vector(cut['target'][side+'_team_id'],cut['target'][other+'_team_id'],side=='home')
            x.append(v);extra.append(e)
        x=np.asarray(x);posterior=np.einsum('ij,jk,lk->il',x,frozen.model.covariance,x,optimize=False)
        covariance=posterior+np.diag(frozen.model.noise_variance+np.asarray(extra))
        report['bayesian_math']=dict(status='POSTERIOR_PARAMETER_AND_RESIDUAL_VARIANCE_INCLUDED',
            projected_parameter_covariance=posterior.tolist(),predictive_covariance=covariance.tolist(),
            residual_noise_variance=frozen.model.noise_variance,empirical_bayes_hyperparameters_not_full_bayesian=True,
            latent_score_correlation=float(covariance[0,1]/np.sqrt(np.prod(np.diag(covariance)))))
        paths=sample_paths(forecast)
        report['simulation']=dict(status='EXACT_FROZEN_PATHS_REPRODUCED',method='RQMC_HALTON',scenarios=len(paths),
            sample_sha256=bands['sample_sha256'],every_path_integer_and_nonnegative=True,
            arithmetic='FOUR_QUARTERS_SUM_TO_REGULATION_TEAM_SCORES;HALVES_PARTITION_QUARTERS',
            quantiles_are_not_additive=True,refitted=False,new_prediction_created=False)
        mc=frozen.model.predict(Cut(**cut),method='MC',bounded_workspace=True);mb=prediction_intervals(mc)
        if mb['sample_sha256']!=p['mc_qmc']['mc_bands']['sample_sha256']:raise ValueError('AUDIT_FROZEN_MC_SAMPLE_MISMATCH')
        report['mc_qmc_comparison']=dict(status='SAME_POSTERIOR_NUMERICAL_CHECK_NOT_PREDICTIVE_ACCURACY_PROOF',
            qmc_total_median=bands['markets']['TOTAL']['p50'],mc_total_median=mb['markets']['TOTAL']['p50'],
            qmc_total_p05_p95=[bands['markets']['TOTAL'][k] for k in ('p05','p95')],
            mc_total_p05_p95=[mb['markets']['TOTAL'][k] for k in ('p05','p95')])
    return report


def render_source_annotation(audit):
    import html
    text='<b>KAYNAK VE MODEL DENETİMİ</b>\n'
    if audit['source_annotation_required']:
        text+='Orijinal kayıtlı fikstür URL’si bu maçı içermiyor; eski alan değiştirilmedi.\n'
    text+='Doğrulanmış fikstür: '+html.escape(audit['verified_fixture_sources'][0])
    text+='\nNOT_CALIBRATED | Güven endeksi yok.\nTempo ve oyuncu etkisi doğrulanmadı; modele uygulanmadı.'
    text+='\nPeriyot dağılımı deterministik: PBP/possession veya kalibre edilmiş çeyrek belirsizliği değildir.'
    return text


def main():
    import argparse
    from hybrid_engine.boxes import publish_json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True);parser.add_argument('--snapshot-sha',required=True)
    parser.add_argument('--assets-directory',required=True);parser.add_argument('--output-directory',required=True)
    parser.add_argument('--replay',action='store_true',help='Reproduce archived MC/QMC paths offline, never refit')
    args=parser.parse_args();file=local_path(args.snapshot)
    if file.stat().st_size>512*1024:raise ValueError('AUDIT_SNAPSHOT_BUDGET')
    wrapper=json.loads(file.read_text());snapshot=wrapper['payload']
    if digest(snapshot)!=args.snapshot_sha or wrapper['sha256']!=args.snapshot_sha:raise ValueError('AUDIT_TRUSTED_SNAPSHOT_PIN')
    report=audit_snapshot(snapshot,args.assets_directory,replay=args.replay)
    root=local_path(args.output_directory);root.mkdir(parents=True,exist_ok=True)
    target=root/('quality-audit-'+args.snapshot_sha+'-'+digest(report)+'.json')
    publish_json(target,dict(payload=report,sha256=digest(report)))
    print(json.dumps(dict(status=report['status'],output=str(target),audit_sha256=digest(report),
                         new_prediction_created=False,calibration_fit=False,production_changed=False)))


if __name__=='__main__':main()
