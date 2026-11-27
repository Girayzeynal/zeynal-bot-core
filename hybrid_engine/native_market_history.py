"""Read-only locally recorded native market time series, never provider opening/closing proof."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re

from core.team_identity import digest
from hybrid_engine.data import local_path

MAX_FILES=1024
MAX_BYTES=2*1024*1024
LEAGUES=('NBA','EUROLEAGUE','EUROCUP')

def inspect(root,league,fixture_id):
    if league not in LEAGUES or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',fixture_id):
        raise ValueError('MARKET_HISTORY_EXACT_FIXTURE_REQUIRED')
    root=local_path(root)
    from hybrid_engine.current_market_review import fixture_journal_directory
    folders=[root/'current-market-reviews',root/'europe-data'/'market']
    # Legacy global journal plus the exact fixture's rollover, never a scan
    # of all other fixture directories. Keep local journal evidence distinct.
    folders += [fixture_journal_directory(folder,league,fixture_id) for folder in folders]
    files=[p for folder in folders for p in local_path(folder).glob('review-*.json')]
    if len(files)>MAX_FILES:raise ValueError('MARKET_HISTORY_FILE_BUDGET_EXCEEDED')
    series=defaultdict(dict);conflicts=set();rejected=0
    for path in sorted(files):
        try:
            path=local_path(path)
            if path.stat().st_size>MAX_BYTES:raise ValueError('SIZE')
            w=json.loads(path.read_text());p=w['payload']
            manifest={k:v for k,v in p.items() if k not in ('recorded_at_utc','record_class','eligible_for_current_prematch_metrics')}
            if (digest(p)!=w['sha256'] or digest(manifest)!=w['manifest_sha256']
                    or path.stem!='review-'+w['manifest_sha256']
                    or p['format']!='CURRENT_MARKET_REVIEW_BATCH_V1'):raise ValueError('PIN')
            for review in p['reviews']:
                f=review['fixture'];source=review['source']
                if f['league']!=league or f['fixture_id']!=fixture_id:continue
                captured=source.get('captured_at_utc');published=source.get('published_at_utc')
                available=review.get('available_at_utc');decision=review.get('decision_utc')
                cutoff=f['tipoff_utc']
                clock=source.get('event_clock_binding')
                if clock:
                    if digest(clock['payload'])!=clock['sha256']:raise ValueError('CLOCK_PIN')
                    cutoff=min(cutoff,clock['payload']['prematch_deadline_utc'])
                if (source.get('method')!='NATIVE_RETRIEVAL' or
                    not all(type(x) is int for x in (captured,published,available,decision,p['recorded_at_utc'],cutoff)) or
                    not 0<published<=captured<=available<=decision<=p['recorded_at_utc']<cutoff):continue
                for row in review['rows']:
                    if not row.get('quote_sha256') or 'NATIVE_PRICE_EVIDENCE_REQUIRED' in row.get('reasons',[]):continue
                    if not 0<=decision-published<=300 or not 0<=decision-captured<=300:continue
                    prices=row['prices']
                    if set(prices)!={'under','over'} or any(type(v) not in (float,int) or not math.isfinite(v) or v<=1 for v in prices.values()):continue
                    key=(f['season'],review['bookmaker']['id'],source['provider_id'],row['period'],row['market'],row['line'])
                    # The source publication clock is the deduplication unit,
                    # not a re-read or repeated model decision.
                    old=series[key].get(published)
                    if old and old['prices']!=prices:
                        conflicts.add((key,published));continue
                    if old is None or captured<old['captured_at_utc']:
                        series[key][published]=dict(published_at_utc=published,captured_at_utc=captured,
                            prices=prices,observation_sha256=review['observation_sha256'])
        except (ValueError,KeyError,TypeError,OSError):
            rejected+=1
    rows=[]
    for k,values in sorted(series.items()):
        ordered=[values[stamp] for stamp in sorted(values) if (k,stamp) not in conflicts]
        if not ordered:continue
        rows.append(dict(zip(('season','bookmaker_id','provider_id','period','market','line'),k),
            observation_count=len(ordered),earliest_local=ordered[0],latest_local=ordered[-1],
            decimal_price_change={side:round(ordered[-1]['prices'][side]-ordered[0]['prices'][side],6) for side in ('under','over')},
            observations=ordered))
    return dict(status='LOCAL_JOURNAL_OBSERVATIONS_ONLY',league=league,fixture_id=fixture_id,
        scanned_files=len(files),rejected_files=rejected,conflicting_observations=len(conflicts),series=rows,
        opening_verified=False,closing_verified=False,provider_signature_verified=False,network_requests=0,forecast_changed=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',required=True);parser.add_argument('--league',required=True,choices=LEAGUES)
    parser.add_argument('--fixture-id',required=True)
    a=parser.parse_args()
    print(json.dumps(inspect(a.data_directory,a.league,a.fixture_id),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
