"""Opt-in read-only source audit; no scheduler, secrets, ledger or model writes.

python -m faz41_source_smoke --live
A 200 response is not a usage grant. Blocked providers remain blocked.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import time

from prediction_inputs import digest
from faz41_transport import fetch
from faz41_adapters import capture

PLAN={
    'espn':('ESPN','https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909922'),
    'nba_schedule':('NBA','https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json'),
    'el_game':('EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games/87'),
    'el_stats':('EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games/87/stats'),
    'ec_game':('EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/U/seasons/U2026/games/91'),
    'ec_stats':('EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/U/seasons/U2026/games/91/stats'),
}


def run(*,live=False,collector=fetch):
    if live is not True:return dict(status='LIVE_ACCESS_NOT_REQUESTED',network_requests=0,prospective_records_created=0)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda p:collector(p[1],provider=p[0]),PLAN.values()))
    docs=dict(zip(PLAN,results));observations=[]
    for name,provider,league in [('espn','ESPN','NBA'),('el','EUROLEAGUE_LIVE','EUROLEAGUE'),('ec','EUROLEAGUE_LIVE','EUROCUP')]:
        game=docs[name if name=='espn' else name+'_game']
        if game['status']!='DOCUMENT_RECEIVED':continue
        for kind in ('OFFICIAL_STAT','PLAYER_MINUTES'):
            inputs=[game];raw=game['payload']
            if provider=='EUROLEAGUE_LIVE' and kind=='PLAYER_MINUTES':
                stats=docs[name+'_stats']
                if stats['status']!='DOCUMENT_RECEIVED':
                    observations.append(dict(provider=provider,league=league,data_type=kind,status='MISSING_STATS_DOCUMENT'));continue
                raw=dict(game=game['payload'],stats=stats['payload']);inputs.append(stats)
            row=dict(provider=provider,league=league,data_type=kind,source_urls=[d['source_url'] for d in inputs],
                     component_observed_at_utc=[d['observed_at_utc'] for d in inputs],usage_status='UNKNOWN')
            try:
                observation=capture(raw,provider=provider,league=league,season_end_year=2027,
                    observed_at_utc=max(d['observed_at_utc'] for d in inputs),ingested_at_utc=int(time.time()),data_type=kind)
                p=observation['payload']
                row.update(status='STRUCTURAL_CAPTURE_NOT_MODEL_ELIGIBLE',fixture=p['fixture'],provider_fixture_id=p['provider_fixture_id'],
                    source_json_sha256=p['raw_sha256'],evidence_sha256=observation['sha256'],
                    observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'],materialized_at_utc=p['materialized_at_utc'],
                    published_at_utc=p['published_at_utc'],model_eligible=False,claims=p['claims'])
            except (ValueError,KeyError,TypeError) as ex:
                row.update(status='PROVIDER_PAYLOAD_REFUSED',error_type=type(ex).__name__,reason=str(ex) if type(ex) is ValueError else 'MALFORMED_PROVIDER_PAYLOAD')
            observations.append(row)
    summaries={name:{k:v for k,v in doc.items() if k!='payload'} for name,doc in docs.items()}
    for name,doc in docs.items():
        if 'payload' in doc:summaries[name]['document_json_sha256']=digest(doc['payload'])
    return dict(status='READ_ONLY_SOURCE_AUDIT',network_requests=len(PLAN),sources=summaries,observations=observations,
        nba_espn_cross_check='NOT_PERFORMED' if docs['nba_schedule']['status']!='DOCUMENT_RECEIVED' else 'SCHEDULE_ONLY_NOT_FINAL_RESULT_VERIFICATION',
        news_sources='NO_PERMISSIONED_FEED_CONFIGURED',official_prematch_lineups=0,rotation_stints=0,
        independent_source_time_attestation=False,prospective_records_created=0,production_coefficients_changed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    print(json.dumps(run(live=args.live),sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
