"""Explain verified forecast errors, not their unidentifiable causal basketball causes.

Native profiles require the existing snapshot/source audit. Frozen coefficients
and point-in-time inputs are inspected; fitting, simulating, fetching and changing
predictions are prohibited. Hypothetical baseline reconstructions are never
published PREMATCH forecasts or added to live accuracy.
"""
from collections import Counter
import math

import numpy as np

from core.team_identity import digest
from hybrid_engine.prediction_audit import Assets,audit_snapshot
from hybrid_engine.quality_monitor import monitor,identity

VERSION='FROZEN_FORECAST_ERROR_REVIEW_V1'


def input_profile(snapshot,directory,*,source_audit=None):
    p=snapshot
    a=audit_snapshot(p,directory) if source_audit is None else source_audit
    if a.get('snapshot_sha256')!=digest(p) or not a.get('frozen_history_features_reconstructed'):
        raise ValueError('ERROR_REVIEW_NATIVE_PROFILE_REQUIRED')
    assets=Assets(directory);cut=assets.read(p['input_asset']);prepared=assets.read(p['prepared_asset'])
    m=prepared['payload']['model'];teams=m['teams'];coef=m['coefficients'];terms={};variances={}
    for side,other in (('home','away'),('away','home')):
        own=cut['target'][side+'_team_id'];opponent=cut['target'][other+'_team_id']
        x=np.zeros(len(coef));x[0]=1;x[1]=side=='home'
        terms[side]=dict(league_intercept=coef[0],home_effect=coef[1] if side=='home' else 0.,
                         own_attack=0.,opponent_defense=0.)
        for team,offset,label in ((own,2,'own_attack'),(opponent,2+len(teams),'opponent_defense')):
            if team in teams:
                index=offset+teams.index(team);x[index]=1;terms[side][label]=coef[index]
        if abs(sum(terms[side].values())-p['prediction'][side])>1e-8:
            raise ValueError('ERROR_REVIEW_FROZEN_SCORE_RECONSTRUCTION')
        parameter=float(np.einsum('i,ij,j->',x,np.asarray(m['covariance']),x,optimize=False))
        extra=sum(float(m['prior_scales']['team'])**2 for t in (own,opponent) if t not in teams)
        variances[side]=dict(parameter_variance=parameter,residual_variance=m['noise_variance'],
                             unseen_team_variance=extra,raw_predictive_sd=math.sqrt(parameter+m['noise_variance']+extra))
    histories={};b={}
    for side,other in (('home','away'),('away','home')):
        f=cut['features'][side];wanted=set(f['recent_game_ids'])
        recent=[r for r in cut['history'] if r['fixture_id'] in wanted]
        if len(recent)!=f['n_games'] or len(recent)!=len(wanted):raise ValueError('ERROR_REVIEW_RECENT_HISTORY_ID_CONFLICT')
        histories[side]=dict(games=f['n_games'],recent_ids=list(f['recent_game_ids']),
            latest_game_utc=max(r['fixture_start_utc'] for r in recent),
            new_games_since_fit=sum(r['fixture_start_utc']>m['cutoff_utc'] for r in recent),
            raw_points_for=f['points_for'],raw_points_against=f['points_against'],
            measured_pace_used=False,verified_rest_used=False,
            start_gap_hours_proxy=f['start_gap_hours'],box_rows_present=len(f['boxes']))
        b[side]=(f['points_for']+cut['features'][other]['points_against'])/2
    # Current last-N scoring levels do not enter this V1's fixed coefficient
    # mean; quarter weights only change its allocation. This is a limitation,
    # not permission to rewrite that mean after observing a result.
    return dict(format='FROZEN_INPUT_USAGE_PROFILE_V1',snapshot_sha256=digest(p),
        model_digest=p['model_digest'],prepared_artifact_sha256=p['prepared_artifact_sha256'],
        generated_at_utc=p['prediction_generated_at_utc'],fit_cutoff_utc=m['cutoff_utc'],
        fit_age_seconds=p['prediction_generated_at_utc']-m['cutoff_utc'],training_games=len(m['training_ids']),
        latest_training_game_utc=max(r['start_utc'] for r in prepared['payload']['training_rows']),
        score_contributions=terms,predictive_variance=variances,history=histories,
        feature_usage=dict(full_game_mean='FROZEN_LEAGUE_HOME_TEAM_ATTACK_OPPONENT_DEFENSE_COEFFICIENTS',
            quarters='CURRENT_FROZEN_HISTORY_QUARTER_WEIGHTS',
            current_scoring_average_updates_full_game_mean=False,verified_pace=False,player_effects=False),
        retrospective_baseline=dict(name='PREGAME_LAST_N_FOR_AGAINST_CROSS_MEAN',scores=[b['home'],b['away']],
            total=b['home']+b['away'],published_forecast=False,fitted_on_outcome=False,
            scope='REGULATION_ONLY',eligible_for_live_performance=False),
        quarter_correlation=a.get('mean_off_diagonal_quarter_correlation'),
        causal_explanation='NOT_IDENTIFIED_FROM_ONE_REALIZED_SCORE',
        model_changed=False,calibration_fit=False,confidence_index=None)


def review(rows,*,asof_utc,profiles=()):
    """Rows must come from LedgerReports; clocks/dedup follow quality monitor."""
    monitored=monitor(rows,asof_utc=asof_utc)
    by_snapshot={p['snapshot_sha256']:p for p in profiles};groups=[]
    for cohort in monitored['groups']:
        key=tuple(cohort[k] for k in ('league','season','model_version','model_digest'))
        eligible=[]
        for r in rows:
            if identity(r)!=key:continue
            times=[r.get(k) for k in ('prediction_generated_at_utc','created_utc','first_archived_at_utc','fixture_start_utc')]
            pin=r.get('snapshot_sha256')
            if (not all(type(t) is int and t>0 for t in times) or not times[0]<=times[1]<=times[2]<times[3] or
                times[2]>asof_utc or not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin)):
                continue
            eligible.append(r)
        # Re-use first publication semantics rather than inflating by repeat rows.
        first={};conflicts=set()
        for r in eligible:
            old=first.get(r['fixture_id'])
            if old is None or r['first_archived_at_utc']<old['first_archived_at_utc']:
                first[r['fixture_id']]=r;conflicts.discard(r['fixture_id'])
            elif r['first_archived_at_utc']==old['first_archived_at_utc'] and r['snapshot_sha256']!=old['snapshot_sha256']:
                conflicts.add(r['fixture_id'])
        chosen=[r for fid,r in first.items() if fid not in conflicts and r.get('actual') is not None and
                type(r.get('label_available_utc')) is int and r['fixture_start_utc']<r['label_available_utc']<=asof_utc]
        if len(chosen)!=cohort['settled']:raise ValueError('ERROR_REVIEW_COHORT_SELECTION_CONFLICT')
        cases=[];paired=[];sse=0.;absolute=0.
        for r in chosen:
            pred=sum(r['prediction']);actual=sum(r['actual']);error=pred-actual
            sse+=error**2;absolute+=abs(error)
            q=r.get('predicted_quarters');period_errors=None
            if q is not None:
                a=np.asarray([r['actual_periods'][s][:4] for s in ('home','away')]).T
                period_errors=(np.asarray(q).sum(axis=1)-a.sum(axis=1)).tolist()
                if abs(sum(period_errors)-error)>.05:raise ValueError('ERROR_REVIEW_PERIOD_TOTAL_CONFLICT')
            final=r.get('final_with_ot');ot=None if final is None else sum(final)-actual
            if ot is not None and ot<0:raise ValueError('ERROR_REVIEW_NEGATIVE_OVERTIME_POINTS')
            case=dict(fixture_id=r['fixture_id'],provider_fixture_ids=r.get('provider_fixture_ids',[]),
                home=r.get('home','Ev sahibi'),away=r.get('away','Deplasman'),snapshot_sha256=r['snapshot_sha256'],
                prediction_total=pred,regulation_total=actual,signed_total_error=error,
                absolute_total_error=abs(error),period_total_errors=period_errors,
                overtime_points_excluded=ot,input_profile_status='BLOCKED_ORIGINAL_NATIVE_ASSETS_UNAVAILABLE',
                causal_explanation='NOT_ESTABLISHED',findings=[])
            profile=by_snapshot.get(r['snapshot_sha256'])
            if profile is not None:
                if profile['model_digest']!=r['model_digest'] or profile['generated_at_utc']!=r['prediction_generated_at_utc']:
                    raise ValueError('ERROR_REVIEW_PROFILE_MODEL_OR_CLOCK_CONFLICT')
                case.update(input_profile_status='FROZEN_INPUTS_VERIFIED',input_profile=profile)
                if any(h['new_games_since_fit'] for h in profile['history'].values()):case['findings'].append('NEW_HISTORY_DOES_NOT_REFIT_FROZEN_TEAM_STRENGTH')
                if profile.get('quarter_correlation') is not None and profile['quarter_correlation']>.95:case['findings'].append('HIGH_CO_MOVEMENT_FROM_DETERMINISTIC_PERIOD_ALLOCATION')
                if not profile['feature_usage']['verified_pace']:case['findings'].append('MEASURED_PACE_NOT_A_MODEL_INPUT')
                if not profile['feature_usage']['player_effects']:case['findings'].append('VERIFIED_PLAYER_IMPACT_NOT_A_MODEL_INPUT')
                base=profile['retrospective_baseline']['total']
                paired.append(dict(fixture_id=r['fixture_id'],snapshot_sha256=r['snapshot_sha256'],
                    frozen_model_error=error,retrospective_baseline_error=base-actual))
            cases.append(case)
        for c in cases:
            c['cohort_squared_error_share']=None if sse==0 else c['signed_total_error']**2/sse
            c['cohort_absolute_error_share']=None if absolute==0 else c['absolute_total_error']/absolute
        top=sorted(cases,key=lambda c:(-c['absolute_total_error'],c['fixture_id']))
        n=len(cases);comparisons={}
        for name,k in [('frozen_model','frozen_model_error'),('retrospective_baseline','retrospective_baseline_error')]:
            es=[r[k] for r in paired];comparisons[name]=dict(n=len(es),mae=None if not es else sum(map(abs,es))/len(es),
                rmse=None if not es else math.sqrt(sum(x*x for x in es)/len(es)))
        groups.append(dict(cohort={k:cohort[k] for k in ('league','season','model_version','model_digest')},n=n,
            day_clusters=len({(r['fixture_start_utc']+10800)//86400 for r in chosen}),cases=top,
            top_three_absolute_error_share=None if not absolute else sum(c['absolute_total_error'] for c in top[:3])/absolute,
            top_three_squared_error_share=None if not sse else sum(c['signed_total_error']**2 for c in top[:3])/sse,
            matched_input_baseline=dict(pairs=paired,metrics=comparisons,comparison_unit='SAME_FROZEN_PREISSUE_FEATURES_AND_SETTLED_FIXTURES',
                baseline_was_published=False,superiority_claim=False),
            findings=dict(Counter(code for c in cases for code in c['findings']))))
    return dict(format=VERSION,asof_utc=asof_utc,groups=groups,exclusions=monitored['exclusions'],
        input_provenance_required='LEDGER_REPORTS_NATIVE_VERIFIED',
        automatic_tuning=False,calibration_fit=False,confidence_index=None,production_changed=False,
        causal_error_attribution='UNPROVEN;DIAGNOSTIC_ASSOCIATIONS_ONLY')


def render_summary(report):
    lines=['HATA İNCELEMESİ | Normal süre | Salt okunur']
    for group in report['groups'][:12]:
        if not group['n']:continue
        lines.append(f"{group['cohort']['league']} · Sonuç {group['n']} · Gün kümesi {group['day_clusters']}")
        for case in group['cases'][:3]:
            lines.append(f"{case['home']} – {case['away']} | Toplam hata {case['signed_total_error']:+.2f}")
        if group['top_three_squared_error_share'] is not None:
            lines.append(f"İlk {min(3,group['n'])} sapmanın kare hata payı: %{100*group['top_three_squared_error_share']:.1f} (güven yüzdesi değil)")
    lines.append('Sapmaların nedeni henüz kanıtlanmadı; kayıtlar değiştirilmedi, otomatik kalibrasyon yapılmadı.')
    return '\n'.join(lines)
