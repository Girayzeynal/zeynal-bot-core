"""Safe provider failure evidence; no fuzzy acceptance or forecast changes."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from core.team_identity import digest
from hybrid_engine.data import local_path


def failure(receipt, operation):
    document=receipt.get('document')
    errors=document.get('errors') if isinstance(document,dict) else None
    # Inspect provider errors only for fixed classes; never return native text,
    # echoed parameters, credentials, account details or unknown field names.
    text=json.dumps(errors,ensure_ascii=True).lower()[:8192]
    codes=[]
    if any(s in text for s in ('quota','too many requests','rate limit','request limit','requests limit','limit for the day','requests left')):
        codes.append('QUOTA_OR_RATE_LIMIT_REPORTED')
    if any(s in text for s in ('subscription','free plan','paid plan','upgrade','not subscribed','plan does not','plan do not')):
        codes.append('PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED')
    if 'season' in text:
        codes.append('SEASON_ERROR_REPORTED')
    if any(s in text for s in ('invalid api','api key is','api-key is','token is','authentication','unauthorized')):
        codes.append('CREDENTIAL_OR_AUTH_ERROR_REPORTED')
    if any(s in text for s in ('field is required','parameter','invalid timezone','invalid league','not supported')):
        codes.append('QUERY_PARAMETER_ERROR_REPORTED')
    if not codes:codes=['UNCLASSIFIED_PROVIDER_ERROR']
    return dict(status='PROVIDER_REPORTED_ERROR',operation=operation,error_codes=codes,
                http_status=receipt.get('http_status'),document_sha256=receipt.get('document_sha256'),
                observed_at_utc=receipt.get('observed_at_utc'),native_error_text_exposed=False)


def fixture_diagnostic(events,snapshot,*,basketball=False):
    from hybrid_engine.provider_bridge import name, utc, matches
    home=name(snapshot['home']['official_name']);away=name(snapshot['away']['official_name'])
    target=snapshot['fixture_start_utc'];same=[];reversed_rows=[];near=[];invalid=0;starts=[];exact=0
    for e in events[:1000]:
        try:
            if basketball:
                h,a=e['teams']['home']['name'],e['teams']['away']['name'];start=utc(e['date']);pid=str(e['id'])
            else:
                h,a=e['home_team'],e['away_team'];start=utc(e['commence_time']);pid=e['id']
            hn,an=name(h),name(a)
            if not isinstance(pid,str) or not 1<=len(pid)<=80 or not pid.replace('-','').replace('_','').isalnum():
                raise ValueError('PROVIDER_ID')
            starts.append(start)
            row=dict(provider_fixture_id=pid,home=h[:120],away=a[:120],
                     start_utc=datetime.fromtimestamp(start,timezone.utc).isoformat(),
                     delta_seconds=start-target)
            if hn==home and an==away:same.append(row)
            elif hn==away and an==home:reversed_rows.append(row)
            elif abs(start-target)<=86400:near.append(row)
            exact+=int(matches(e,snapshot,basketball=basketball))
        except (ValueError,KeyError,TypeError,OverflowError):invalid+=1
    reason=('EXACT_MATCH' if exact==1 else 'AMBIGUOUS_EXACT_MATCH' if exact>1 else
            'MATCHING_TEAMS_DIFFERENT_START' if same else 'ONLY_REVERSED_PAIR_FOUND' if reversed_rows else
            'EMPTY_PROVIDER_EVENT_LIST' if not events else 'NO_TEAM_PAIR_IN_RETURNED_EVENTS')
    candidates=(same+reversed_rows)[:5] if same or reversed_rows else sorted(near,key=lambda r:abs(r['delta_seconds']))[:5]
    return dict(reason=reason,returned_events=len(events),exact_matches=exact,same_order_pair_count=len(same),
                reversed_pair_count=len(reversed_rows),invalid_rows=invalid,
                target=dict(home=snapshot['home']['official_name'],away=snapshot['away']['official_name'],
                            start_utc=datetime.fromtimestamp(target,timezone.utc).isoformat()),
                provider_window_utc=[datetime.fromtimestamp(x,timezone.utc).isoformat() for x in (min(starts),max(starts))] if starts else None,
                candidates=candidates,equivalence_inferred=False)


def readonly_snapshot(path, fixture_id):
    from ledger_reports import LedgerReports,MAX_PAYLOAD_BYTES
    path=local_path(path);report=LedgerReports(path).read('NBA',fixture_id)
    rows=report['forecasts']
    if len(rows)!=1:raise ValueError('SINGLE_VERIFIED_ARCHIVED_FORECAST_REQUIRED')
    r=rows[0]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        row=db.execute(f'SELECT CASE WHEN length(CAST(payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN payload END FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
                       (r['league'],r['fixture_id'],r['model_digest'])).fetchone()
    p=json.loads(row[0])
    if digest(p)!=r['snapshot_sha256']:raise ValueError('DIAGNOSTIC_ARCHIVE_PIN_CHANGED')
    return p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-id',required=True)
    parser.add_argument('--ledger',default=str(Path.home()/'zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite'))
    a=parser.parse_args()
    try:
        from hybrid_engine.provider_access import ProviderAccess,credentials
        from hybrid_engine.provider_bridge import ProviderBridge
        path=local_path(a.ledger);snapshot=readonly_snapshot(path,a.fixture_id)
        bridge=ProviderBridge(ProviderAccess(credentials()),path.parent.parent/'provider-evidence',diagnostic_only=True)
        report=bridge.collect(snapshot)
        report['original_snapshot_sha256']=digest(snapshot)
        report['query_read_only']=True;report['actual_telegram_delivery_verified']=False
        print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    except Exception:
        print(json.dumps(dict(status='PROVIDER_DIAGNOSTIC_BLOCKED',forecast_changed=False,
                              reason='VERIFIED_LOCAL_ARCHIVE_OR_PROVIDER_CONFIG_UNAVAILABLE')))
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
