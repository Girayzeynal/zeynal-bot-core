"""Read-only NBA daily, timezone-aware comparison of *stored* regulation forecasts.

No model fitting, result backfill, provider calls, database writes or release
promotion. The ledger reader verifies native fixture/final and commit receipts.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from ledger_reports import LedgerReports
from hybrid_engine.live_metrics import metrics as live_metrics

FORMAT='NBA_DAILY_IMMUTABLE_REVIEW_V1'
V1='ELITE_HYBRID_NBA_BAYES_QMC_RESEARCH_V1'
ISTANBUL=ZoneInfo('Europe/Istanbul')
MARKETS=('TOTAL','HOME','AWAY','MARGIN','HOME_HANDICAP',
         '1Q','2Q','3Q','4Q','1H','2H')


def proof(row):
    """Never use a result to certify a forecast with missing prematch clocks."""
    tip=row['fixture_start_utc']
    created=row.get('created_utc')
    generated=row.get('prediction_generated_at_utc')
    archived=row.get('first_archived_at_utc')
    if any(type(x) is not int for x in (tip,created,generated,archived)):
        return 'PREMATCH_CLOCK_MISSING'
    if not 0 < generated <= created <= archived < tip:
        return 'PREMATCH_CLOCK_ORDER_INVALID'
    fitted=row.get('parameter_fit_cutoff_utc')
    if fitted is not None and (type(fitted) is not int or fitted>generated):
        return 'MODEL_FITTED_AFTER_PREDICTION'
    if row.get('actual') is not None:
        observed=row.get('label_available_utc')
        if type(observed) is not int or observed<=tip:
            return 'RESULT_TIMESTAMP_NOT_POST_TIPOFF'
    return None


def describe(rows):
    settled=[x for x in rows if x.get('actual') is not None]
    if not settled:
        return dict(n=0,status='NO_SETTLED_FORECASTS')
    d=live_metrics(settled)
    ranges={}
    for market in MARKETS:
        group=d['coverage']['markets'].get(market)
        if group:
            ranges[market]={k:dict(hits=group[k]['hits'],n=group[k]['n'],
                              nominal_mass=group[k]['nominal_mass'],
                              observed_coverage=group[k]['observed_coverage'])
                            for k in ('P25_P75','P05_P95')}
    non_ties=[x for x in settled if x['actual'][0]!=x['actual'][1]]
    winners=sum((x['prediction'][0]-x['prediction'][1])*
                (x['actual'][0]-x['actual'][1])>0 for x in non_ties)
    correlations=[]
    for r in settled:
        a=(r.get('intervals') or {}).get('simulated_correlations',{}).get('quarter_totals')
        if a is None:continue
        if (len(a)!=4 or any(len(row)!=4 for row in a) or
            any(type(a[i][j]) not in (float,int) or
                not math.isfinite(a[i][j]) for i in range(4) for j in range(4))):
            raise ValueError('INVALID_ARCHIVED_QUARTER_CORRELATIONS')
        correlations.append(sum(a[i][j] for i in range(4) for j in range(i))/6)
    corr=None if not correlations else sum(correlations)/len(correlations)
    return dict(n=len(settled),status='DESCRIPTIVE_ONLY_NOT_CALIBRATED',
        total_mae=d['total']['mae'],total_rmse=d['total']['rmse'],
        total_bias_forecast_minus_actual=d['total']['bias'],
        team_score_mae=d['team_scores']['mae'],margin_mae=d['margin']['mae'],
        quarter_total_mae={k:v['mae'] for k,v in d['period_totals'].items()},
        half_total_mae={k:v['mae'] for k,v in d['half_totals'].items()},
        coverage=ranges,
        winner_direction=dict(correct=winners,n=len(non_ties),
                              excluded_regulation_ties=len(settled)-len(non_ties)),
        period_simulation=dict(
            method='DETERMINISTIC_LARGEST_REMAINDER_NOT_POSSESSION_SIMULATION',
            average_off_diagonal_quarter_correlation=corr,
            observed_games=len(correlations),
            high_path_dependence=bool(corr is not None and corr>=.95)),
        confidence_index=None,parameters_fitted_now=False,auto_promoted=False)


def audit(report,day_tsi,*,model_version=V1,include_games=True):
    day=date.fromisoformat(day_tsi)
    if report.get('status')!='VERIFIED_LIVE_REPORT':
        return dict(format=FORMAT,day_tsi=day.isoformat(),
                    status='UNAVAILABLE_NO_ACCURACY_CLAIM',
                    source_status=report.get('status'),cohorts=[],cases=[])
    selected=sorted((r for r in report.get('forecasts',[])
        if r['league']=='NBA' and r['model_version']==model_version
        and datetime.fromtimestamp(r['fixture_start_utc'],ISTANBUL).date()==day),
        key=lambda r:(r['fixture_start_utc'],r['fixture_id'],r['model_digest']))
    seen=set();groups=defaultdict(list);excluded=[];cases=[];pending=[]
    for r in selected:
        key=(r['fixture_id'],r['model_digest'])
        if key in seen:raise ValueError('DUPLICATE_FIXTURE_MODEL')
        seen.add(key)
        failure=proof(r)
        if failure:
            excluded.append(dict(fixture_id=r['fixture_id'],
                snapshot_sha256=r.get('snapshot_sha256'),reason=failure))
            continue
        groups[r['model_digest']].append(r)
        actual=r.get('actual')
        if actual is None:pending.append(r['fixture_id'])
        if include_games:
            predicted_quarters=r.get('predicted_quarters')
            period_actual=r.get('actual_periods')
            actual_q=None if actual is None else [
                period_actual['home'][i]+period_actual['away'][i] for i in range(4)]
            cases.append(dict(fixture_id=r['fixture_id'],home=r['home'],away=r['away'],
                model_version=r['model_version'],model_digest=r['model_digest'],
                snapshot_sha256=r['snapshot_sha256'],
                fixture_start_utc=r['fixture_start_utc'],
                generated_utc=r['prediction_generated_at_utc'],
                first_archived_at_utc=r['first_archived_at_utc'],
                forecast_lead_seconds=r['fixture_start_utc']-r['first_archived_at_utc'],
                meets_current_five_minute_boundary=
                    r['first_archived_at_utc']<=r['fixture_start_utc']-300,
                predicted_home_away=r['prediction'],actual_regulation_home_away=actual,
                final_including_overtime=None if actual is None else r.get('final_with_ot'),
                prediction_total=round(sum(r['prediction']),4),
                actual_regulation_total=None if actual is None else sum(actual),
                error_actual_minus_prediction=None if actual is None else
                    round(sum(actual)-sum(r['prediction']),4),
                quarter_total_projection=None if predicted_quarters is None else
                    [round(sum(p),4) for p in predicted_quarters],
                quarter_total_actual=actual_q))
    cohorts=[dict(model_digest=model_digest,model_version=model_version,
                  settled=sum(x['actual'] is not None for x in rows),
                  pending=sum(x['actual'] is None for x in rows),
                  summary=describe(rows)) for model_digest,rows in sorted(groups.items())]
    return dict(format=FORMAT,day_tsi=day.isoformat(),timezone='Europe/Istanbul',
        status='READ_ONLY_DESCRIPTIVE_NOT_CALIBRATED',
        source_status=report['status'],model_version=model_version,
        selected_forecasts=len(selected),
        unique_fixtures=len({x['fixture_id'] for x in selected}),
        clock_verified_rows=sum(map(len,groups.values())),
        excluded=excluded,pending_fixture_ids=sorted(set(pending)),
        cohorts=cohorts,cases=cases,
        safeguards=dict(
            source_result_and_ledger_commit_validated_upstream=True,
            external_preforecast_source_assets_fully_replayed=False,
            five_minute_rule_not_applied_retroactively=True,
            immutable_forecasts_unchanged=True,training=False,
            new_prediction=False,production_changed=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,
        default=Path.home()/'zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite')
    parser.add_argument('--day-tsi',required=True)
    parser.add_argument('--model-version',default=V1)
    parser.add_argument('--summary-only',action='store_true')
    args=parser.parse_args()
    report=LedgerReports(args.db).read('NBA')
    result=audit(report,args.day_tsi,model_version=args.model_version,
                 include_games=not args.summary_only)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
