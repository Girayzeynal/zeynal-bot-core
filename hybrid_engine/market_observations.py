"""Source-neutral, append-only research market observations.

An image hash binds the supplied evidence, not the correctness of a manual
transcription. Manual records never become native/API-verified prices. No OCR,
downloads, credentials, betting selections or forecast writes occur here.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit, parse_qsl

from core.league_identity import resolve_league
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.decision_layer import QuoteEvidence

VERSION = 'SOURCE_NEUTRAL_MARKET_OBSERVATION_V1'
MAX_QUOTES = 32
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_FILES = 128
MAX_MATCHING = 8
IDENTITY = ('league', 'season', 'fixture_id', 'home_team_id', 'away_team_id', 'tipoff_utc')


def stamp(value, *, optional=False):
    if optional and value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError('MARKET_UTC_INTEGER_REQUIRED')
    return value


def text(value, *, limit=128):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('BOUNDED_MARKET_TEXT_REQUIRED')
    return value.strip()


def pin(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('MARKET_SHA256_REQUIRED')
    return value


def public_url(value):
    if value is None:
        return None
    value=text(value,limit=1200)
    uri = urlsplit(value)
    if (uri.scheme != 'https' or not uri.netloc or uri.username or uri.password or uri.fragment or
            len(value) > 1200 or any(k.lower() in ('token','key','apikey','api_key','api-key','authorization','signature','access_token','secret','client_secret','auth')
                                      for k,v in parse_qsl(uri.query))):
        raise ValueError('PUBLIC_MARKET_SOURCE_URL_REQUIRED')
    return value


def fixture_identity(value):
    if not isinstance(value, dict) or set(value) != set(IDENTITY):
        raise ValueError('EXPLICIT_MARKET_FIXTURE_IDENTITY_REQUIRED')
    result = {k:text(value[k]) for k in IDENTITY if k != 'tipoff_utc'}
    result['league'] = resolve_league(result['league']).code
    if result['league'] not in ('NBA','EUROLEAGUE','EUROCUP'):
        raise ValueError('SUPPORTED_BASKETBALL_COMPETITION_REQUIRED')
    pin(result['fixture_id'])
    match = re.fullmatch(r'(20\d{2})/(20\d{2})', result['season'])
    if match is None or int(match[2]) != int(match[1])+1 or result['home_team_id'] == result['away_team_id']:
        raise ValueError('MARKET_SEASON_OR_TEAM_CONFLICT')
    result['tipoff_utc'] = stamp(value['tipoff_utc'])
    return result


def quote_rows(fixture, bookmaker_id, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_QUOTES:
        raise ValueError('BOUNDED_NONEMPTY_OBSERVED_LINES_REQUIRED')
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'period','market','line','prices'}:
            raise ValueError('EXPLICIT_OBSERVED_MARKET_FIELDS_REQUIRED')
        QuoteEvidence.validate(dict(fixture,bookmaker_id=bookmaker_id,**row))
        normalized = dict(row,line=float(row['line']),prices={k:float(v) for k,v in sorted(row['prices'].items())})
        key = (normalized['period'],normalized['market'],normalized['line'])
        if key in seen:
            raise ValueError('DUPLICATE_OR_CONFLICTING_LINE_IN_ONE_SOURCE_SNAPSHOT')
        seen.add(key)
        result.append(normalized)
    return sorted(result,key=lambda r:(r['period'],r['market'],r['line']))


def validate(payload):
    if payload.get('format') != VERSION:
        raise ValueError('MARKET_OBSERVATION_FORMAT_REQUIRED')
    fixture = fixture_identity(payload['fixture'])
    bookmaker = payload['bookmaker']
    if set(bookmaker) != {'id','name'}:
        raise ValueError('EXPLICIT_BOOKMAKER_REQUIRED')
    text(bookmaker['id']);text(bookmaker['name'])
    quote_rows(fixture,bookmaker['id'],payload['quotes'])
    source = payload['source']
    text(source['provider_id']);text(source['provider_name'])
    public_url(source['url'])
    method = source['method']
    if method not in ('NATIVE_RETRIEVAL','MANUAL_SCREENSHOT'):
        raise ValueError('EXPLICIT_MARKET_CAPTURE_METHOD_REQUIRED')
    captured = stamp(source['captured_at_utc'],optional=True)
    published = stamp(source['published_at_utc'],optional=True)
    available = stamp(payload['available_at_utc'])
    if (available > int(time.time()) or (captured is not None and captured > available) or
            published is not None and (published > available or captured is not None and published > captured)):
        raise ValueError('MARKET_SOURCE_CLOCK_CONFLICT')
    if method == 'NATIVE_RETRIEVAL':
        if captured is None or source['attestation'] != 'LOCAL_NATIVE_RECEIPT_NOT_PROVIDER_SIGNATURE':
            raise ValueError('NATIVE_MARKET_CAPTURE_PROOF_REQUIRED')
        pin(source['receipt_sha256']);pin(source['document_sha256']);pin(source['native_quote_sha256'])
    else:
        if source['attestation'] != 'USER_TRANSCRIPTION_NOT_INDEPENDENTLY_VERIFIED':
            raise ValueError('MANUAL_MARKET_MUST_NOT_CLAIM_API_VERIFICATION')
        evidence = source['evidence']
        if evidence['file'] != pin(evidence['sha256'])+'.image' or type(evidence['bytes']) is not int or not 0 < evidence['bytes'] <= MAX_IMAGE_BYTES:
            raise ValueError('MANUAL_IMAGE_EVIDENCE_REQUIRED')
    if payload.get('settlement_verification') != 'NOT_VERIFIED_BY_OBSERVATION':
        raise ValueError('OBSERVATION_CANNOT_VERIFY_SETTLEMENT_RULES')
    if payload.get('calibration_status') != 'NOT_CALIBRATED':
        raise ValueError('OBSERVATION_CANNOT_CLAIM_MODEL_CALIBRATION')
    return payload


def from_espn(observation, receipt):
    """Retain publisher ESPN separately from the actual quoted bookmaker."""
    from hybrid_engine.observed_markets import observe_espn
    if digest(observation['payload']) != observation['sha256']:
        raise ValueError('NATIVE_QUOTE_PIN')
    parsed = observe_espn(receipt,now_utc=receipt['ingested_at_utc'])
    if observation['sha256'] not in {q['sha256'] for q in parsed['quotes']}:
        raise ValueError('QUOTE_NOT_IN_BOUND_NATIVE_SOURCE')
    q = observation['payload']
    fixture = fixture_identity(dict(league=q['league'],season=q['season'],fixture_id=q['fixture_id'],
        home_team_id=q['home_team_id'],away_team_id=q['away_team_id'],tipoff_utc=q['fixture_start_utc']))
    p = dict(format=VERSION,fixture=fixture,bookmaker=dict(id=q['bookmaker_id'],name=q['bookmaker']),
        source=dict(provider_id='ESPN',provider_name='ESPN',method='NATIVE_RETRIEVAL',url=q['source_url'],
            published_at_utc=None,captured_at_utc=q['observed_at_utc'],
            receipt_sha256=digest(receipt),document_sha256=q['document_sha256'],native_quote_sha256=q['native_quote_sha256'],
            attestation='LOCAL_NATIVE_RECEIPT_NOT_PROVIDER_SIGNATURE'),
        available_at_utc=q['ingested_at_utc'],settlement_verification='NOT_VERIFIED_BY_OBSERVATION',
        quotes=quote_rows(fixture,q['bookmaker_id'],[dict(period='FULL',market=q['market'],line=q['line'],
            prices=dict(over=q['decimal_over_or_home_cover'],under=q['decimal_under_or_away_cover']))]),calibration_status='NOT_CALIBRATED')
    validate(p)
    return dict(payload=p,sha256=digest(p))


def image_info(path):
    path = local_path(path)
    size = path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        raise ValueError('BOUNDED_SCREENSHOT_REQUIRED')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        header = stream.read(16)
        if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff') or
                header.startswith(b'RIFF') and header[8:12] == b'WEBP'):
            raise ValueError('PNG_JPEG_OR_WEBP_SCREENSHOT_REQUIRED')
        sha.update(header)
        for chunk in iter(lambda:stream.read(65536),b''):
            sha.update(chunk)
    return dict(sha256=sha.hexdigest(),bytes=size,file=sha.hexdigest()+'.image')


def _publish_image(source, destination):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,prefix='.market-',delete=False) as out:
            temporary=Path(out.name)
            with source.open('rb') as stream:
                for chunk in iter(lambda:stream.read(65536),b''):
                    out.write(chunk)
            out.flush();os.fsync(out.fileno())
        if image_info(temporary)['file'] != destination.name:
            raise ValueError('SCREENSHOT_CHANGED_DURING_IMPORT')
        try:
            os.link(temporary,destination)
        except FileExistsError:
            if destination.is_symlink() or image_info(destination)['file'] != destination.name:
                raise ValueError('SCREENSHOT_ARCHIVE_CONFLICT')
        fd=os.open(destination.parent,os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ObservationStore:
    """Separate optional research files. Constructor/read never create a schema."""
    def __init__(self,directory):
        self.root=local_path(directory)

    def import_screenshot(self,document,image):
        if not isinstance(document,dict) or set(document) != {'fixture','bookmaker','source','quotes'}:
            raise ValueError('MANUAL_OBSERVATION_INPUT_FIELDS_REQUIRED')
        fixture=fixture_identity(document['fixture']);book=document['bookmaker'];source=document['source']
        if set(book) != {'id','name'} or set(source) != {'provider_id','provider_name','url','captured_at_utc','published_at_utc'}:
            raise ValueError('EXPLICIT_MANUAL_SOURCE_AND_BOOKMAKER_REQUIRED')
        book={k:text(book[k]) for k in ('id','name')}
        source=dict(source,provider_id=text(source['provider_id']),provider_name=text(source['provider_name']),
                    url=public_url(source['url']),captured_at_utc=stamp(source['captured_at_utc'],optional=True),
                    published_at_utc=stamp(source['published_at_utc'],optional=True))
        info=image_info(image);source.update(method='MANUAL_SCREENSHOT',evidence=info,
            attestation='USER_TRANSCRIPTION_NOT_INDEPENDENTLY_VERIFIED')
        fields=dict(format=VERSION,fixture=fixture,bookmaker=book,source=source,
            quotes=quote_rows(fixture,book['id'],document['quotes']),
            settlement_verification='NOT_VERIFIED_BY_OBSERVATION',calibration_status='NOT_CALIBRATED')
        key=digest(fields);path=self.root/('observation-'+key+'.json')
        now=int(time.time());payload=dict(fields,available_at_utc=now);validate(payload)
        if path.exists():
            old=self._read(path)
            if {k:v for k,v in old['payload'].items() if k!='available_at_utc'} != fields:
                raise ValueError('IMMUTABLE_OBSERVATION_CONFLICT')
            self._image(old['payload'])
            return old
        if self.root.exists():
            paths=[]
            for old_path in self.root.glob('observation-*.json'):
                paths.append(old_path)
                if len(paths)>MAX_FILES:
                    raise ValueError('MARKET_OBSERVATION_COUNT_BUDGET')
            for old_path in paths:
                old=self._read(old_path)['payload']
                same=(old['fixture']==fixture and old['bookmaker']['id']==book['id'] and
                    old['source']['evidence']['sha256']==info['sha256'] and
                    old['source']['captured_at_utc']==source['captured_at_utc'])
                if same and old['quotes']!=fields['quotes']:
                    raise ValueError('IMMUTABLE_MANUAL_TRANSCRIPTION_CONFLICT')
        self.root.mkdir(parents=True,exist_ok=True)
        evidence_root=local_path(self.root/'evidence');evidence_root.mkdir(exist_ok=True)
        _publish_image(local_path(image),evidence_root/info['file'])
        wrapper=dict(payload=payload,sha256=digest(payload))
        publish_json(path,wrapper)
        return wrapper

    def _read(self,path):
        path=local_path(path)
        if path.stat().st_size>MAX_JSON_BYTES:
            raise ValueError('MARKET_OBSERVATION_FILE_BUDGET')
        wrapper=json.loads(path.read_text());p=validate(wrapper['payload'])
        if p['source']['method']!='MANUAL_SCREENSHOT':
            raise ValueError('STORED_MANUAL_INPUT_CANNOT_CLAIM_NATIVE_RETRIEVAL')
        if digest(p)!=wrapper['sha256'] or path.name!='observation-'+digest({k:v for k,v in p.items() if k!='available_at_utc'})+'.json':
            raise ValueError('MARKET_OBSERVATION_PIN_OR_NAME')
        return wrapper

    def _image(self,payload):
        info=payload['source']['evidence']
        actual=image_info(self.root/'evidence'/info['file'])
        if actual != info:
            raise ValueError('MARKET_SCREENSHOT_PIN')

    def read(self,fixture,*,asof_utc):
        fixture=fixture_identity(fixture);stamp(asof_utc)
        if asof_utc>int(time.time()):
            raise ValueError('ACTUAL_MARKET_READ_CLOCK_REQUIRED')
        if not self.root.exists():
            return []
        paths=[]
        for path in self.root.glob('observation-*.json'):
            paths.append(path)
            if len(paths)>MAX_FILES:
                raise ValueError('MARKET_OBSERVATION_COUNT_BUDGET')
        result=[];total=0;image_bytes=0
        for path in sorted(paths):
            total+=path.stat().st_size
            if total>4*1024*1024:
                raise ValueError('MARKET_OBSERVATION_READ_BUDGET')
            wrapper=self._read(path);p=wrapper['payload']
            if p['fixture']!=fixture or p['available_at_utc']>asof_utc:
                continue
            image_bytes+=p['source']['evidence']['bytes']
            if len(result)>=MAX_MATCHING or image_bytes>32*1024*1024:
                raise ValueError('MATCHING_MARKET_EVIDENCE_BUDGET')
            self._image(p)
            result.append(wrapper)
        return sorted(result,key=lambda w:(w['payload']['available_at_utc'],w['sha256']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input');parser.add_argument('--screenshot')
    parser.add_argument('--output-directory')
    parser.add_argument('--show-fixture',action='store_true')
    parser.add_argument('--ledger');parser.add_argument('--fixture-id');parser.add_argument('--league',default='NBA')
    a=parser.parse_args()
    if a.show_fixture:
        if not a.ledger or not a.fixture_id or any((a.input,a.screenshot,a.output_directory)):
            raise ValueError('READ_ONLY_FIXTURE_LOOKUP_ARGUMENTS_REQUIRED')
        from ledger_reports import LedgerReports,MAX_PAYLOAD_BYTES
        path=local_path(a.ledger);report=LedgerReports(path).read(a.league,a.fixture_id)
        options={}
        if report['forecasts']:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                deadline=time.monotonic()+2;db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
                for r in report['forecasts']:
                    row=db.execute(f'SELECT CASE WHEN length(CAST(payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN payload END FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
                        (r['league'],r['fixture_id'],r['model_digest'])).fetchone()
                    p=json.loads(row[0])
                    if digest(p)!=r['snapshot_sha256']:raise ValueError('FIXTURE_LOOKUP_SNAPSHOT_CHANGED')
                    fixture=fixture_identity(dict(league=p['league'],season=p['season'],fixture_id=p['fixture_id'],
                        home_team_id=p['home']['provider_id'],away_team_id=p['away']['provider_id'],tipoff_utc=p['fixture_start_utc']))
                    options[digest(fixture)]=fixture
        if len(options)!=1:raise ValueError('SINGLE_ARCHIVED_FIXTURE_REQUIRED')
        print(json.dumps(dict(fixture=next(iter(options.values())),source='READ_ONLY_VERIFIED_LEDGER_IDENTITY',
                              market_lines_created=0,forecast_changed=False)))
        return
    if not all((a.input,a.screenshot,a.output_directory)) or a.ledger or a.fixture_id:
        raise ValueError('MANUAL_IMAGE_IMPORT_ARGUMENTS_REQUIRED')
    path=local_path(a.input)
    if path.stat().st_size>MAX_JSON_BYTES:
        raise ValueError('MANUAL_MARKET_INPUT_BUDGET')
    wrapper=ObservationStore(a.output_directory).import_screenshot(json.loads(path.read_text()),a.screenshot)
    print(json.dumps(dict(status='IMPORTED_MANUAL_UNVERIFIED',sha256=wrapper['sha256'],
        alternatives=len(wrapper['payload']['quotes']),available_at_utc=wrapper['payload']['available_at_utc'],
        source_method='MANUAL_SCREENSHOT',forecast_changed=False,production_changed=False)))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED',error_type=type(exc).__name__,reason='MARKET_IMPORT_NOT_COMPLETED')))
        raise SystemExit(2)
