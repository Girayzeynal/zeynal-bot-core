"""Read-only fixture diagnostics, deliberately outside SHA-pinned model sources."""
import asyncio
import html
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.team_identity import digest
from season_archive_inventory import archive_catalog
from universal_analysis import require_fresh_source

ISTANBUL = ZoneInfo('Europe/Istanbul')


async def enrich_fixture_rejection(report, day, fetcher):
    """Explain a refusal from fresh native evidence; never retry/authorize prediction."""
    if report.get('reason') != 'FIXTURE_NOT_UNIQUELY_VERIFIED':
        return report
    try:
        requested = datetime.strptime(day, '%Y-%m-%d').date()
        home, away = (str(report[s]['provider_id']) for s in ('home', 'away'))
        games = {}
        for date in (requested-timedelta(days=1), requested):
            url = ('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
                   'scoreboard?dates='+date.strftime('%Y%m%d')+'&limit=1000')
            r = await asyncio.to_thread(fetcher, 'ESPN', url)
            if (r.get('status') != 'DOCUMENT_RECEIVED' or r.get('provider') != 'ESPN' or
                r.get('source_url') != url or r.get('http_status') != 200 or
                digest(r['document']) != r.get('document_sha256')):
                raise ValueError('FIXTURE_DIAGNOSTIC_SOURCE')
            require_fresh_source(r)
            catalog = archive_catalog(r['document'], provider='ESPN',
                season_start_year=int(report['season_id'].split('/')[0]),
                observed_at_utc=r['observed_at_utc'], ingested_at_utc=r['ingested_at_utc'])
            native = {str(e['id']): e for e in r['document']['events']}
            for g in catalog['payload']['fixtures']:
                if {g['home_team_id'],g['away_team_id']} != {home,away}:
                    continue
                cid = g['canonical_id']
                if cid in games and games[cid]['fixture'] != g:
                    raise ValueError('FIXTURE_DIAGNOSTIC_CONFLICT')
                event = native[str(g['provider_fixture_ids'][0])]
                comp = event['competitions'][0]
                teams = {t['homeAway']:t['team']['displayName'] for t in comp['competitors']}
                status = comp.get('status', event.get('status',{})).get('type',{})
                start = datetime.fromtimestamp(g['start_ts_utc'], ISTANBUL)
                scheduled = status.get('name') == 'STATUS_SCHEDULED' and not g['completed'] and g['start_ts_utc'] > int(time.time())
                games[cid] = dict(fixture=g, provider_fixture_ids=g['provider_fixture_ids'],
                    home=teams['home'], away=teams['away'], source_url=url,
                    source_start=event.get('date'), tipoff_utc=g['start_ts_utc'],
                    tipoff_tsi=start.isoformat(), command_day=start.date().isoformat(),
                    source_status=status.get('name'), reversed_teams=g['home_team_id'] == away,
                    suggested_command=(f'/analyze NBA {start.date().isoformat()} {teams["home"]} vs {teams["away"]}' if scheduled else None))
        candidates = list(games.values())[:4]
        diagnostic = dict(matched_count=sum(not c['reversed_teams'] and c['command_day']==day for c in candidates),
                          nearby=candidates, prediction_allowed=False)
    except (ValueError, KeyError, TypeError, OSError):
        diagnostic = dict(status='SOURCE_UNAVAILABLE', matched_count=None, nearby=[], prediction_allowed=False)
    return dict(report, fixture_diagnostic=diagnostic)


def fixture_rejection_diagnostic(report):
    if report.get('reason') != 'FIXTURE_NOT_UNIQUELY_VERIFIED':
        return None
    raw = report.get('fixture_diagnostic')
    if not isinstance(raw, dict):
        return dict(status='SOURCE_FIXTURE_EVIDENCE_NOT_EXPOSED', prediction_allowed=False)
    return dict(status=raw.get('status','DIAGNOSTIC_ONLY'), matched_count=raw.get('matched_count'),
                nearby=raw.get('nearby',[])[:4], prediction_allowed=False)


def render_fixture_rejection(report):
    d = fixture_rejection_diagnostic(report)
    if d is None:
        return ''
    if d['status'] != 'DIAGNOSTIC_ONLY':
        return '\nFikstür ayrıntıları doğrulanamadı; tahmin üretilmedi. /nba ile tarih ve ev/deplasman sırasını kontrol edin.'
    lines = ['\nFikstür teşhisi: Tahmin üretilmedi. Komut tarihi Türkiye takvim günüdür.']
    if not d['nearby']:
        lines.append('İstenen ev/deplasman ve tarihle doğrulanmış maç bulunamadı. /nba YYYY-MM-DD ile fikstürü kontrol edin.')
    for c in d['nearby']:
        if c.get('reversed_teams'):
            lines.append('Ev sahibi / deplasman sırası ters yazılmış.')
        lines.extend([html.escape(c['home']+' – '+c['away']),
            html.escape('Başlangıç: '+c['tipoff_tsi']+' TSİ | UTC: '+datetime.fromtimestamp(c['tipoff_utc'],ZoneInfo('UTC')).isoformat()),
            html.escape('ESPN kimliği: '+', '.join(c['provider_fixture_ids'])+' | '+str(c['source_status']))])
        if c.get('suggested_command'):
            lines.append('<code>'+html.escape(c['suggested_command'])+'</code>')
        else:
            lines.append('Başlangıç/durum uygun değil; yeni PREMATCH önerilmedi.')
    return '\n'.join(lines)
