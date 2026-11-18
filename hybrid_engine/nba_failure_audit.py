"""Five-game post-result audit; never creates or settles a prematch forecast.

ESPN is a third-party feed, not the NBA league authority. An inaccessible NBA
endpoint and an unavailable UserLAnd archive remain explicit NOT_VERIFIED.
"""
import argparse
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog

SCOREBOARD='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261117&limit=1000'
OFFICIAL='https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json'
CASES=(('401910002','28','18'),('401910003','16','22'),('401910004','24','8'),
       ('401910006','12','26'),('401910005','13','30'))


def catalog(receipt):
    now=int(time.time())
    if (receipt.get('provider')!='ESPN' or receipt.get('source_url')!=SCOREBOARD or receipt.get('http_status')!=200 or
        receipt.get('status')!='DOCUMENT_RECEIVED' or digest(receipt['document'])!=receipt.get('document_sha256') or
        any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
        not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now):
        raise ValueError('FAILURE_AUDIT_NATIVE_RECEIPT_REQUIRED')
    return archive_catalog(receipt['document'],provider='ESPN',season_start_year=2026,
        observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],regular_season_filter=True)


def review(receipt, *, ledger=None, assets_directory=None, official_verified=False):
    # No caller boolean can confer an official attestation.
    if official_verified:raise ValueError('NBA_OFFICIAL_NATIVE_DECODER_REQUIRED')
    bundle=catalog(receipt);rows=[];audit=None
    if ledger is not None:audit=audit_ledger(ledger,assets_directory=assets_directory)
    for pid,home,away in CASES:
        matches=[g for g in bundle['payload']['fixtures'] if pid in g['provider_fixture_ids']]
        if not matches:
            rows.append(dict(provider_fixture_id=pid,status='MISSING_FINAL',live_performance_eligible=False));continue
        if len(matches)!=1:raise ValueError('FAILURE_AUDIT_AMBIGUOUS_FIXTURE')
        g=matches[0];start=g['start_ts_utc']
        if (g['home_team_id'],g['away_team_id'])!=(home,away) or datetime.fromtimestamp(start,ZoneInfo('Europe/Istanbul')).date().isoformat()!='2026-11-18':
            raise ValueError('FAILURE_AUDIT_FIXTURE_TEAM_DATE_CONFLICT')
        if not g['completed'] or not start<receipt['observed_at_utc'] or g['periods'] is None:
            rows.append(dict(provider_fixture_id=pid,status='FINAL_NOT_VERIFIED',live_performance_eligible=False));continue
        periods=g['periods'];actual=[sum(periods[s][:4]) for s in ('home','away')]
        if any(len(periods[s])<4 or sum(periods[s])!=g['final_scores'][j] for j,s in enumerate(('home','away'))):
            raise ValueError('FAILURE_AUDIT_PERIOD_FINAL_ARITHMETIC')
        overtime=len(periods['home'])>4
        if overtime and actual[0]!=actual[1]:raise ValueError('FAILURE_AUDIT_OVERTIME_REQUIRES_REGULATION_TIE')
        record=dict(provider_fixture_id=pid,canonical_id=g['canonical_id'],fixture_start_utc=start,
            status='ESPN_FINAL_VERIFIED_NBA_AUTHORITY_NOT_VERIFIED',regulation_scores=actual,
            regulation_total=sum(actual),final_with_ot=g['final_scores'],overtime=overtime,periods=periods,
            original_prediction_status='NOT_VERIFIED_ARCHIVE_UNAVAILABLE' if audit is None else 'NOT_FOUND_OR_NOT_NATIVE_VERIFIED',
            forecasts=[],market_outcome_status='NOT_VERIFIED_ORIGINAL_PREMATCH_LINE_AND_SETTLEMENT_REQUIRED',
            live_performance_eligible=False)
        if audit is not None:
            for r in audit['rows']:
                if pid not in r.get('provider_fixture_ids',[]):continue
                if r['fixture_id']!=g['canonical_id'] or r['fixture_start_utc']!=start:raise ValueError('FAILURE_AUDIT_ARCHIVE_IDENTITY_CONFLICT')
                source=r.get('source_audit') or {}
                if r['findings'] or source.get('status')!='VERIFIED_WITH_LIMITATIONS' or source.get('snapshot_sha256')!=r['snapshot_sha256']:continue
                p=r['prediction'];record['forecasts'].append(dict(snapshot_sha256=r['snapshot_sha256'],model_digest=r['model_digest'],
                    model_version=r['model_version'],prediction_generated_at_utc=r['prediction_generated_at_utc'],
                    first_archived_at_utc=r['first_archived_at_utc'],predicted_scores=[p['home'],p['away']],
                    signed_total_error=p['home']+p['away']-sum(actual)))
            if record['forecasts']:record.update(original_prediction_status='NATIVE_PREMATCH_ARCHIVE_VERIFIED',live_performance_eligible=True)
        rows.append(record)
    return dict(format='NBA_20261118_FAILURE_AUDIT_V1',observed_at_utc=int(time.time()),cases=rows,
        source_url=SCOREBOARD,source_document_sha256=receipt['document_sha256'],
        nba_official_verification='NOT_VERIFIED',third_party_source='ESPN',
        database_bytes_unchanged=None if audit is None else audit['database_bytes_unchanged'],
        forecasts_created=False,forecasts_changed=False,results_ingested=False,calibration_fit=False,
        user_reported_forecasts_used_as_evidence=False,actual_telegram_delivery_verified=False,production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger');p.add_argument('--assets-directory')
    p.add_argument('--receipt',help='Previously captured native receipt, inspected at its actual capture time')
    p.add_argument('--output-directory',required=True);a=p.parse_args()
    receipt=json.loads(local_path(a.receipt).read_text()) if a.receipt else fetch_document('ESPN',SCOREBOARD)
    if 'payload' in receipt and 'sha256' in receipt:
        if digest(receipt['payload'])!=receipt['sha256']:raise ValueError('FAILURE_AUDIT_RECEIPT_FILE_PIN')
        receipt=receipt['payload']
    result=review(receipt,ledger=a.ledger,assets_directory=a.assets_directory)
    root=local_path(a.output_directory);root.mkdir(parents=True,exist_ok=True)
    for prefix,body in [('receipt',receipt),('audit',result)]:
        publish_json(root/(prefix+'-'+digest(body)+'.json'),dict(payload=body,sha256=digest(body)))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
