"""Anonymous, read-only observations from the basketball bulletin on iddaa.com."""
import hashlib
import html
import json
import math
import threading
import time
from urllib.robotparser import RobotFileParser

import requests

from core.league_identity import normalize_name
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from telegram_delivery import tsi

HOST = 'https://sportsbookv2.iddaa.com'
EVENTS = HOST + '/sportsbook/events?st=2&type=0&version=0&live=true'
COMPETITIONS = HOST + '/sportsbook/competitions'
MARKETS = HOST + '/sportsbook/get_market_config'
AGENT = 'ZeynalMarketResearch/1.0'
LEAGUES = {'NBA': (138, 'ABD Amerika Basketbol Ligi'), 'EUROLEAGUE': (251000, 'Euroleague'),
           'EUROCUP': (666, 'Eurocup')}
TOTALS = {114: ('FULL_OT', 'Toplam Sayı Alt/Üst (Uzt. Dahil) {0}'),
          116: ('1H', '1. Yarı Toplam Sayı Alt/Üst {0}')}
# Only explicit native city labels. Never use prefixes or an unordered team match.
NBA_CITIES = dict(pair.split('|') for pair in (
    'Atlanta|Atlanta Hawks', 'Boston|Boston Celtics', 'Brooklyn|Brooklyn Nets',
    'Charlotte|Charlotte Hornets', 'Chicago|Chicago Bulls', 'Cleveland|Cleveland Cavaliers',
    'Dallas|Dallas Mavericks', 'Denver|Denver Nuggets', 'Detroit|Detroit Pistons',
    'Golden State|Golden State Warriors', 'Houston|Houston Rockets', 'Indiana|Indiana Pacers',
    'LA Clippers|Los Angeles Clippers', 'LA Lakers|Los Angeles Lakers', 'Memphis|Memphis Grizzlies',
    'Miami|Miami Heat', 'Milwaukee|Milwaukee Bucks', 'Minnesota|Minnesota Timberwolves',
    'New Orleans|New Orleans Pelicans', 'New York|New York Knicks', 'Oklahoma City|Oklahoma City Thunder',
    'Orlando|Orlando Magic', 'Philadelphia|Philadelphia 76ers', 'Phoenix|Phoenix Suns',
    'Portland|Portland Trail Blazers', 'Sacramento|Sacramento Kings', 'San Antonio|San Antonio Spurs',
    'Toronto|Toronto Raptors', 'Utah|Utah Jazz', 'Washington|Washington Wizards'))


class SourceError(ValueError):
    def __init__(self, message, wait=60):
        super().__init__(message)
        self.wait = wait


def read(url, deadline, *, robots=False):
    with requests.get(url, headers={'User-Agent': AGENT}, timeout=(2, 3),
                      allow_redirects=False, stream=True) as response:
        if robots and response.status_code in (404, 410):
            return b''
        if response.status_code != 200:
            from email.utils import parsedate_to_datetime
            raw = response.headers.get('Retry-After', '')
            try:
                wait = int(raw) if raw.isdigit() else int(parsedate_to_datetime(raw).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                wait = 300
            raise SourceError('HTTP ' + str(response.status_code), max(60, wait))
        mime = response.headers.get('Content-Type', '').split(';')[0].lower().strip()
        if mime != ('text/plain' if robots else 'application/json'):
            raise SourceError('Beklenmeyen belge türü')
        body = bytearray()
        for block in response.iter_content(32768):
            body.extend(block)
            if len(body) > (65536 if robots else 2 * 1024 * 1024) or time.monotonic() >= deadline:
                raise SourceError('Kaynak okuma sınırı')
        return bytes(body)


def lines(event, config):
    found = {}
    for m in event.get('m') or []:
        if not isinstance(m, dict) or m.get('t') != 2 or m.get('st') not in TOTALS or m.get('s') != 1:
            continue
        kind, label = TOTALS[m['st']]
        spec = config.get('2_' + str(m['st']), {})
        if (spec.get('st'), spec.get('mt'), spec.get('mst')) != (2, 2, m['st']):
            continue
        if ' '.join(spec.get('n', '').split()) != label:
            continue
        try:
            if type(m.get('i')) is not int or m['i'] <= 0 or type(m.get('sov')) not in (str, int, float):
                continue
            point = float(m['sov'])
            outcomes = m['o']
            if not isinstance(outcomes, list) or len(outcomes) != 2 or not 0 < point < 1000:
                continue
            prices = {o['n']: o['odd'] for o in outcomes}
            if set(prices) != {'Alt', 'Üst'} or not all(type(v) in (float, int) and 1 < v <= 1001 for v in prices.values()):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        key = (kind, point)
        value = dict(period=kind, line=point, native_market_id=m.get('i'), native_odd=prices)
        if key not in found:
            found[key] = value
        elif found[key] != value:
            found[key] = None
    return [v for v in found.values() if v is not None]


def matching(event, ctx):
    if event.get('d') != ctx['fixture_start_utc']:
        return False
    for native, side in [('hn', 'home'), ('an', 'away')]:
        name = event[native]
        official = ctx[side]['official_name']
        if normalize_name(name) == normalize_name(official):
            continue
        if ctx['league'] == 'NBA':
            from hybrid_engine.current_roster import team_key
            if team_key(NBA_CITIES.get(name, name)) == team_key(official):
                continue
        return False
    return True


class Bulletin:
    def __init__(self, root, *, getter=read, clock=time.time):
        self.root = local_path(root)
        self.getter = getter
        self.clock = clock
        self.cache = {}
        self.lock = threading.Lock()
        self.retry_at = 0

    def document(self, url, lifetime, deadline):
        now = int(self.clock())
        cached = self.cache.get(url)
        if cached and 0 <= now - cached[0] < lifetime:
            return cached
        if time.monotonic() >= deadline:
            raise SourceError('Kaynak zaman sınırı')
        robots_url = HOST + '/robots.txt'
        if url == robots_url:
            raw = self.getter(url, deadline, robots=True)
            policy = RobotFileParser()
            policy.parse(raw.decode('utf-8-sig').splitlines())
            if raw.strip() and not any(line.lower().lstrip().startswith(('user-agent:', 'sitemap:'))
                                       for line in raw.decode('utf-8-sig').splitlines()):
                raise SourceError('Robots kuralı okunamadı')
            value = policy
        else:
            _, policy, _ = self.document(robots_url, 3600, deadline)
            if not policy.can_fetch(AGENT, url):
                raise SourceError('Robots erişim kısıtı', 3600)
            raw = self.getter(url, deadline)
            obj = json.loads(raw)
            if not isinstance(obj, dict) or obj.get('isSuccess') is not True:
                raise SourceError('Kaynak yanıtı geçersiz')
            value = obj['data']
        entry = (int(self.clock()), value, hashlib.sha256(raw).hexdigest())
        self.cache[url] = entry
        return entry

    def review(self, league, ctx=None, *, first_only=False):
        now = int(self.clock())
        if league not in LEAGUES or (ctx is not None and (
                ctx.get('league') != league or type(ctx.get('fixture_start_utc')) is not int
                or not ctx.get('fixture_id'))):
            return 'İddaa · Lig veya maç kimliği doğrulanamadı.'
        if ctx and now >= ctx['fixture_start_utc']:
            return 'İddaa · Maç başladı. Yeni bülten sorgusu yapılmadı.'
        if self.retry_at > now or not self.lock.acquire(blocking=False):
            return 'İddaa · Kaynak beklemede. Daha sonra tekrar deneyin.'
        try:
            deadline = time.monotonic() + 10
            _, competitions, cp = self.document(COMPETITIONS, 3600, deadline)
            _, config, mp = self.document(MARKETS, 3600, deadline)
            stamp, board, bp = self.document(EVENTS, 60, deadline)
            code, title = LEAGUES[league]
            if [r.get('n') for r in competitions if r.get('i') == code and r.get('si') == '2'] != [title]:
                return 'İddaa · Lig kimliği bültende doğrulanamadı.'
            if board.get('isdiff') is not False or not isinstance(board['events'], list):
                raise SourceError('Tam bülten alınamadı')
            now = int(self.clock())
            events = [e for e in board['events'] if isinstance(e, dict) and e.get('ci') == code
                      and e.get('sid') == 2 and e.get('s') == 0 and type(e.get('d')) is int and e['d'] > now
                      and all(isinstance(e.get(k), str) and 0 < len(e[k]) <= 100 for k in ('hn','an'))
                      and type(e.get('i')) is int and (not ctx or matching(e, ctx))]
            if ctx and len(events) != 1:
                return 'İddaa · Aynı lig, iki takım ve başlangıç saatiyle tekil maç eşleşmedi.'
            if len({e['i'] for e in events}) != len(events):
                raise SourceError('Çakışan maç kimliği')
            observed = []
            for e in sorted(events, key=lambda e: (e['d'], e['i'])):
                quotes = lines(e, config['m'])
                if quotes:
                    observed.append(dict(id=e['i'], home=e['hn'], away=e['an'], start=e['d'], quotes=quotes))
            if not observed:
                return 'İddaa · '+league+' için eşleşmiş maç öncesi toplam baremi bulunamadı.'
            if int(self.clock()) >= min(e['start'] for e in observed):
                return 'İddaa · Bülten okunurken maç başladı. Bülteni yeniden açın.'
            from hybrid_engine.iddaa_comparison import first_path, indexable, remember
            if first_only and not any(indexable(e, now) and not first_path(self.root, league, e).exists()
                                      for e in observed):
                return 'İddaa · Kaydedilecek yeni ilk yarı baremi yok.'
            record = dict(platform='İddaa', league=league, url=EVENTS, observed_at_utc=stamp,
                          price_published_at_utc=None, opening_verified=False, events=observed,
                          fixture_id=ctx['fixture_id'] if ctx else None, source_sha256={'competitions': cp, 'market_definitions': mp, 'events': bp})
            self.root.mkdir(parents=True, exist_ok=True)
            pin = digest(record)
            target = self.root / ('bulletin-'+pin+'.json')
            if not target.exists() and sum(1 for _ in self.root.glob('bulletin-*.json')) >= 2048:
                return 'İddaa · Gözlem arşivinin kapasitesi doldu.'
            publish_json(target, record)
            remember(self.root, record, pin, int(self.clock()))
            out = ['🇹🇷 <b>İddaa · '+league+' basketbol bülteni</b>', 'Okuma '+tsi(stamp),
                   'İlk açılış ve fiyat yayın saati bilinmiyor.']
            shown = 0
            for event in observed[:8]:
                section = ['\n<b>'+html.escape(event['home'])+' – '+html.escape(event['away'])+'</b> · '+tsi(event['start'])]
                for quote in event['quotes'][:4]:
                    point = quote['line']
                    label = 'Maç toplamı (uzatma dahil)' if quote['period'] == 'FULL_OT' else 'İlk yarı toplamı'
                    section.append(label+' · '+format(point, 'g').replace('.',','))
                    mean = ctx.get('first_half_total') if ctx and quote['period'] == '1H' else None
                    if type(mean) in (int, float) and math.isfinite(mean) and mean > 0:
                        gap = mean - point
                        relation = ('baremle aynı' if gap == 0 else
                                    f"baremin {abs(gap):.1f} sayı {'üstünde' if gap > 0 else 'altında'}")
                        section.append(f'İlk kayıtlı model · İlk yarı {mean:.1f} · {relation}'.replace('.', ','))
                if len('\n'.join(out + section).encode('utf-16-le')) // 2 > 3650:
                    break
                out.extend(section)
                shown += 1
            if shown < len(observed):
                out.append(f'Gösterilen maç {shown}/{len(observed)}')
            if int(self.clock()) >= min(e['start'] for e in observed):
                return 'İddaa · Bülten okunurken maç başladı. Bülteni yeniden açın.'
            return '\n'.join(out)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.retry_at = int(self.clock()) + getattr(exc, 'wait', 60)
            return 'İddaa · '+(str(exc) if isinstance(exc, SourceError) else 'Kaynak doğrulanamadı.')
        finally:
            self.lock.release()


async def collect_bulletins(bulletin):
    import asyncio
    from hybrid_engine.isolated_execution import optional_source_thread
    # Give the initial fixture and model checks a head start on UserLAnd.
    await asyncio.sleep(60)
    while True:
        for league in LEAGUES:
            await optional_source_thread(bulletin.review, league, first_only=True)
        await asyncio.sleep(1800)
