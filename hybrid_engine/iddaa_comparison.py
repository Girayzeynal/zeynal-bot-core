"""Descriptive first-half benchmark from the first witnessed pregame İddaa line."""
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.iddaa_bulletin import matching
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS


def first_path(root, league, event):
    return root/'first-half'/league/str(event['start'])/(str(event['id'])+'.json')


def indexable(event, now):
    return (sum(q['period'] == '1H' for q in event['quotes']) == 1
            and now < event['start'] - PREMATCH_MINIMUM_LEAD_SECONDS)


def remember(root, observation, pin, now):
    for event in observation['events']:
        if observation['observed_at_utc'] > now or not indexable(event, now):
            continue
        path = first_path(root, observation['league'], event)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(observation_sha256=pin, indexed_at_utc=now, id=event['id'])
        try:
            publish_json(path, dict(payload=payload, sha256=digest(payload)))
        except ValueError:
            # Another process can win first publication. Its record remains authoritative.
            if not path.is_file() or path.is_symlink():
                raise


def read_event(root, path, forecast, documents):
    receipt = json.loads(path.read_bytes())
    p = receipt['payload']
    if path.is_symlink() or digest(p) != receipt['sha256'] or path.stem != str(p['id']):
        raise ValueError('Invalid first-observation receipt')
    pin = p['observation_sha256']
    if pin not in documents:
        if len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
            raise ValueError('Invalid bulletin digest')
        source = root/('bulletin-'+pin+'.json')
        doc = json.loads(source.read_bytes())
        if source.is_symlink() or digest(doc) != pin:
            raise ValueError('Bulletin digest mismatch')
        documents[pin] = doc
    doc = documents[pin]
    start = forecast['fixture_start_utc']
    if (doc['platform'] != 'İddaa' or doc['league'] != forecast['league']
            or not 0 < doc['observed_at_utc'] <= p['indexed_at_utc'] < start - PREMATCH_MINIMUM_LEAD_SECONDS):
        raise ValueError('Invalid bulletin scope or cutoff')
    if (doc['fixture_id'] not in (None, forecast['fixture_id'])
            or not 0 < forecast['first_archived_at_utc'] <= doc['observed_at_utc']):
        return None
    ctx = dict(league=forecast['league'], fixture_start_utc=start,
               home={'official_name':forecast['home']}, away={'official_name':forecast['away']})
    for event in doc['events']:
        if event['id'] == p['id'] and matching(dict(d=event['start'], hn=event['home'], an=event['away']), ctx):
            quotes = [q for q in event['quotes'] if q['period'] == '1H']
            if len(quotes) == 1:
                return quotes[0]['line']
    return None


def render_comparison(root, reports):
    from hybrid_engine.unified_results_view import unwrap
    root = Path(root)
    errors = defaultdict(list)
    documents = {}
    for league, report in reports.items():
        for r in unwrap(report)['forecasts']:
            if (r.get('actual') is None or not r.get('actual_periods') or not r.get('predicted_halves')
                    or r.get('legacy_publication_clock_unrecorded') or r.get('eligible_for_live_performance') is False
                    or not r.get('first_archived_at_utc')):
                continue
            folder = root/'first-half'/league/str(r['fixture_start_utc'])
            lines = [line for p in folder.glob('*.json') if (line := read_event(root, p, r, documents)) is not None]
            if len(lines) != 1:
                continue
            actual = sum(sum(r['actual_periods'][side][:2]) for side in ('home', 'away'))
            model = sum(r['predicted_halves'][0])
            errors[(league,r['season'],r['model_version'],r['model_digest'])].append((model-actual, lines[0]-actual))
    text = ['İddaa · İlk yarı toplamı · Aynı maçlarda ortalama mutlak hata']
    if not errors:
        return text[0]+'\nEşleşmiş sonuç henüz yok.'
    for (league, season, version, pin), pairs in sorted(errors.items()):
        model, market = zip(*pairs)
        text.append(f'{league} {season} · {version} {pin[:8]} · {len(pairs)} maç · '
                    f'Model {mean(map(abs,model)):.2f} · Barem {mean(map(abs,market)):.2f}')
    return '\n'.join(text)
