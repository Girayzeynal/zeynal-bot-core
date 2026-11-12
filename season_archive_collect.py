"""Opt-in, bounded retrospective source collection; no scheduler or SQLite.

One ESPN request per date replaces unsupported range queries. Failures remain
unknown coverage, never zero-game dates. Local artifacts are insert-only JSON.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from season_archive_inventory import archive_catalog, _hash
from providers.espn_identity_audit import audit_scoreboard_identity


def fetch_document(provider, url):
    import requests
    receipt = dict(provider=provider, source_url=url)
    began = time.monotonic()
    try:
        with requests.get(url, timeout=(3, 10), stream=True, allow_redirects=False) as response:
            receipt['http_status'] = response.status_code
            if response.status_code != 200:
                receipt['status'] = {401: 'SOURCE_ACCESS_DENIED', 403: 'SOURCE_ACCESS_DENIED',
                    429: 'SOURCE_RATE_LIMITED'}.get(response.status_code, 'SOURCE_HTTP_ERROR')
                retry = response.headers.get('Retry-After')
                if type(retry) is str and retry.isascii() and retry.isdigit():
                    receipt['retry_after_seconds'] = min(int(retry),86400)
                return receipt
            body = bytearray()
            for chunk in response.iter_content(65536):
                if time.monotonic()-began>15:
                    return dict(receipt,status='SOURCE_TOTAL_TIMEOUT')
                body.extend(chunk)
                if len(body) > 4*1024*1024:
                    return dict(receipt, status='SOURCE_BODY_LIMIT')
            observed = int(time.time())
            try:
                document = json.loads(body)
                document_pin = _hash(document)
            except (ValueError, UnicodeError):
                return dict(receipt, status='SOURCE_INVALID_JSON')
            return dict(receipt, status='DOCUMENT_RECEIVED', document=document,
                observed_at_utc=observed, ingested_at_utc=int(time.time()),
                body_sha256=hashlib.sha256(body).hexdigest(), document_sha256=document_pin)
    except requests.RequestException:
        return dict(receipt, status='SOURCE_NETWORK_ERROR')


def _plan(dates, euroleague, year):
    if (type(dates) not in (tuple, list) or len(dates)>31 or type(euroleague) is not bool
            or type(year) is not int or not 2000<=year<=2100):
        raise ValueError('bounded_archive_plan_required')
    unique = []
    for day in dates:
        if type(day) is not str or len(day)!=8 or not day.isascii() or not day.isdigit():
            raise ValueError('YYYYMMDD_dates_required')
        at = datetime.strptime(day, '%Y%m%d').replace(tzinfo=timezone.utc)
        if not datetime(year,7,1,tzinfo=timezone.utc)<=at<datetime(year+1,7,1,tzinfo=timezone.utc):
            raise ValueError('date_outside_season_envelope')
        if day not in unique: unique.append(day)
    plan = [dict(provider='ESPN', date=day,
        url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day+'&limit=1000') for day in unique]
    if euroleague: plan.append(dict(provider='EUROLEAGUE_LIVE', date=None,
        url=f'https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games'))
    return plan


def collect_archives(nba_dates=(), *, euroleague=False, season_start_year=2026, live=False, fetcher=fetch_document):
    if type(live) is not bool: raise ValueError('explicit_live_boolean_required')
    plan = _plan(nba_dates, euroleague, season_start_year)
    if not live:
        return dict(status='DRY_RUN_NO_NETWORK', plan=plan, network_requests=0, prospective_predictions_created=0)
    if not plan: raise ValueError('nonempty_archive_plan_required')
    receipts, catalogs, games, aliases, slots, conflicts = [], {}, {}, {}, {}, set()
    blocked_providers, attempts = {}, 0
    for item in plan:
        if item['provider'] in blocked_providers:
            receipt = dict(status='SKIPPED_PROVIDER_BLOCKED', blocked_by_status=blocked_providers[item['provider']])
        else:
            attempts += 1
            try: receipt = fetcher(item['provider'], item['url'])
            except OSError: receipt = dict(status='SOURCE_NETWORK_ERROR')
        if type(receipt) is not dict:
            receipt = dict(status='SOURCE_RECEIPT_INVALID')
        receipt = dict(receipt)
        if receipt.get('status') in ('SOURCE_ACCESS_DENIED','SOURCE_RATE_LIMITED'):
            blocked_providers[item['provider']] = receipt['status']
        document = receipt.pop('document', None)
        row = dict(request=item, receipt=receipt, catalog_sha256=None, status=receipt.get('status', 'SOURCE_RECEIPT_INVALID'))
        if row['status']=='DOCUMENT_RECEIVED':
            try:
                if (receipt.get('provider')!=item['provider'] or receipt.get('source_url')!=item['url']
                        or type(receipt.get('http_status')) is not int or receipt.get('http_status')!=200
                        or receipt.get('document_sha256')!=_hash(document)):
                    raise ValueError('SOURCE_RECEIPT_BINDING_MISMATCH')
                catalog = archive_catalog(document, provider=item['provider'],
                    observed_at_utc=receipt['observed_at_utc'], ingested_at_utc=receipt['ingested_at_utc'],
                    season_start_year=season_start_year)
                if item['provider']=='ESPN':
                    identity = audit_scoreboard_identity([dict(g,provider_fixture_id=g['provider_fixture_ids'][0])
                        for g in catalog['payload']['fixtures']],item['date'])
                    if identity['eastern_date_mismatch_fixture_ids']:
                        raise ValueError('SOURCE_PROVIDER_DATE_MISMATCH')
                row.update(status='CATALOG_VALIDATED', catalog_sha256=catalog['sha256'])
                catalogs[catalog['sha256']] = catalog
                for game in catalog['payload']['fixtures']:
                    cid = game['canonical_id']
                    identity = {k:v for k,v in game.items() if k!='provider_fixture_ids'}
                    if cid in games and games[cid]!=identity: conflicts.add(cid)
                    games[cid] = identity
                    for pid in game['provider_fixture_ids']:
                        key = (item['provider'], pid)
                        if key in aliases and aliases[key]!=cid: conflicts.update((aliases[key], cid))
                        aliases[key] = cid
                    for team in (game['home_team_id'],game['away_team_id']):
                        key = (item['provider'],team,game['start_ts_utc'])
                        if key in slots and slots[key]!=cid: conflicts.update((slots[key],cid))
                        slots[key] = cid
            except (ValueError, KeyError, TypeError) as exc:
                row.update(status='SOURCE_VALIDATION_FAILED', unvalidated_document=document,
                           reason=str(exc) if isinstance(exc,ValueError) else 'MALFORMED_SOURCE_RECEIPT')
        receipts.append(row)
    successful = sum(r['status']=='CATALOG_VALIDATED' for r in receipts)
    summary = {}
    for league in ('NBA','EuroLeague'):
        valid = [g for cid,g in games.items() if cid not in conflicts and g['league']==league]
        requested = [r for r in receipts if (r['request']['provider']=='ESPN') == (league=='NBA')]
        success = sum(r['status']=='CATALOG_VALIDATED' for r in requested)
        summary[league] = dict(requested_documents=len(requested), successful_documents=success,
            failed_documents=len(requested)-success,
            known_independent_fixtures=len(valid) if success else None,
            known_completed_fixtures=sum(g['completed'] for g in valid) if success else None,
            known_completed_with_periods=sum(g['completed'] and g['periods'] is not None for g in valid) if success else None,
            coverage='KNOWN_SUBSET_ONLY' if success else 'NOT_VERIFIED')
    payload = dict(format='RETROSPECTIVE_ARCHIVE_COLLECTION_V1', created_at_utc=int(time.time()), season_start_year=season_start_year,
        status='COLLECTED_NOT_CALIBRATED' if successful==len(plan) and not conflicts else 'PARTIAL_OR_BLOCKED',
        receipts=receipts, catalogs=catalogs, leagues=summary, conflicting_fixtures=len(conflicts),
        planned_requests=len(plan), request_attempts=attempts, source_permission='NOT_ESTABLISHED',
        point_in_time_training_eligible=False, season_archive_complete=False,
        prospective_predictions_created=0, production_database_accessed=False, calibration_status='NOT_ESTABLISHED')
    return dict(payload=payload, sha256=_hash(payload))


def validate_collection(bundle, *, trusted_sha256):
    """Replay archived source documents, never HTTP or prediction generation."""
    try:
        if (type(bundle) is not dict or set(bundle)!={'payload','sha256'}
                or bundle['sha256']!=trusted_sha256 or trusted_sha256!=_hash(bundle['payload'])):
            raise ValueError('COLLECTION_PIN_MISMATCH')
        p=bundle['payload']
        if type(p['created_at_utc']) is not int or not 0<p['created_at_utc']<=int(time.time()):
            raise ValueError('COLLECTION_CLOCK_INVALID')
        rows=p['receipts']; dates=[r['request']['date'] for r in rows if r['request']['provider']=='ESPN']
        euro=any(r['request']['provider']=='EUROLEAGUE_LIVE' for r in rows)
        if [r['request'] for r in rows]!=_plan(dates,euro,p['season_start_year']):
            raise ValueError('COLLECTION_PLAN_MISMATCH')
        responses={}
        for r in rows:
            receipt=dict(r['receipt'])
            if receipt.get('status')=='DOCUMENT_RECEIVED':
                document=p['catalogs'][r['catalog_sha256']]['payload']['raw'] if r['catalog_sha256'] else r['unvalidated_document']
                if any(type(receipt.get(k)) is not int or receipt[k]>p['created_at_utc'] for k in ('observed_at_utc','ingested_at_utc')):
                    raise ValueError('COLLECTION_CLOCK_INVALID')
                receipt['document']=document
            responses[(r['request']['provider'],r['request']['url'])]=receipt
        rebuilt=collect_archives(dates,euroleague=euro,season_start_year=p['season_start_year'],live=True,
                                 fetcher=lambda provider,url:responses[(provider,url)])
        # Historical report creation time is preserved only during replay;
        # original source observation/ingestion clocks are never changed.
        rebuilt['payload']['created_at_utc']=p['created_at_utc'];rebuilt['sha256']=_hash(rebuilt['payload'])
        if rebuilt!=bundle: raise ValueError('COLLECTION_CANNOT_REPLAY')
        return rebuilt
    except (KeyError,TypeError,AttributeError,StopIteration) as exc:
        raise ValueError('MALFORMED_COLLECTION') from exc


def _local_root(directory):
    root = Path(directory).absolute()
    if (root==Path('/data') or Path('/data') in root.parents or not root.is_dir()
            or root.resolve()!=root or root.is_symlink()):
        raise ValueError('LOCAL_EXISTING_ARCHIVE_DIRECTORY_REQUIRED')
    return root


def publish_collection(directory, bundle):
    """Exclusive, atomic content-addressed LOCAL publication; no overwrite."""
    root = _local_root(directory)
    validate_collection(bundle,trusted_sha256=bundle.get('sha256') if type(bundle) is dict else None)
    target = root/('archive-collection-'+bundle['sha256']+'.json')
    body = (json.dumps(bundle, sort_keys=True, allow_nan=False)+'\n').encode()
    if target.is_symlink(): raise ValueError('ARCHIVE_TARGET_SYMLINK_REFUSED')
    if target.exists():
        if target.read_bytes()!=body: raise ValueError('ARCHIVE_CONTENT_CONFLICT')
        return dict(path=str(target), created=False, sha256=bundle['sha256'])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.archive-collection-', delete=False) as stream:
            temporary = Path(stream.name); stream.write(body); stream.flush(); os.fsync(stream.fileno())
        try: os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes()!=body: raise ValueError('ARCHIVE_CONTENT_CONFLICT')
            return dict(path=str(target), created=False, sha256=bundle['sha256'])
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return dict(path=str(target), created=True, sha256=bundle['sha256'])
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nba-date', action='append', default=[])
    parser.add_argument('--euroleague', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output-dir')
    args = parser.parse_args(argv)
    try:
        if args.live and args.output_dir: _local_root(args.output_dir)
        result = collect_archives(args.nba_date, euroleague=args.euroleague, live=args.live)
        if not args.live: print(json.dumps(result)); return 0
        publication = publish_collection(args.output_dir,result) if args.output_dir else None
        p=result['payload']
        print(json.dumps(dict(status=p['status'],leagues=p['leagues'],request_attempts=p['request_attempts'],
            publication=publication,prospective_predictions_created=0,calibration_status='NOT_ESTABLISHED')))
        return 0 if p['status']=='COLLECTED_NOT_CALIBRATED' else 1
    except (ValueError,OSError) as exc:
        print(json.dumps(dict(status='COLLECTION_OR_PUBLICATION_NOT_CONFIRMED',reason=str(exc),prospective_predictions_created=0)))
        return 2


if __name__=='__main__': raise SystemExit(main())
