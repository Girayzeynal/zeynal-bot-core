"""Source-contract fixtures for İddaa, no provider account or external traffic."""
import json
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from core.team_identity import digest
from hybrid_engine.iddaa_bulletin import Bulletin, COMPETITIONS, EVENTS, HOST, LEAGUES, MARKETS, SourceError, lines, read


def market(code, point):
    return dict(i=900+code, t=2, st=code, s=1, sov=str(point),
                o=[dict(n="Alt", odd=1.66, wodd=1.62), dict(n="Üst", odd=1.65, wodd=1.62)])


@pytest.fixture
def source(tmp_path):
    state = dict(now=1000)
    event = dict(i=456, sid=2, ci=138, d=2000, s=0, il=True, hn="Golden State", an="Sacramento",
                 m=[market(114, 215.5), market(116, 110.5)])
    specs = {'2_114': dict(st=2, mt=2, mst=114, n='Toplam Sayı Alt/Üst (Uzt. Dahil) {0}'),
             '2_116': dict(st=2, mt=2, mst=116, n='1. Yarı Toplam Sayı Alt/Üst {0}')}
    data = {COMPETITIONS: [dict(i=i, n=name, si='2') for i, name in LEAGUES.values()],
            MARKETS: {'m': specs}, EVENTS: dict(isdiff=False, events=[event])}
    def get(url, deadline, **kwargs):
        if kwargs.get('robots'):
            return b'User-agent: *\nAllow: /'
        return json.dumps(dict(isSuccess=True, data=data[url])).encode()
    root = tmp_path/'observations'
    bulletin = Bulletin(root, getter=Mock(side_effect=get), clock=lambda:state['now'])
    ctx = dict(league='NBA', fixture_id='original', fixture_start_utc=2000,
               home=dict(official_name='Golden State Warriors'), away=dict(official_name='Sacramento Kings'),
               first_half_total=113.0)
    return bulletin, state, data, event, ctx


def test_current_bulletin_is_distinct_from_first_opening_price_and_from_nesine(source):
    b, _, _, _, ctx = source
    text = b.review('NBA', ctx)
    assert 'İddaa' in text and 'Nesine' not in text and 'yayın saati bilinmiyor' in text
    assert 'uzatma dahil) · 215,5' in text and 'İlk yarı toplamı · 110,5' in text
    assert 'baremin 2,5 sayı üstünde' in text and text.count('İlk kayıtlı model') == 1
    assert b.review('NBA', ctx) == text and b.getter.call_count == 4
    path, = b.root.glob('bulletin-*.json')
    row = json.loads(path.read_text())
    assert digest(row) in path.name and row['observed_at_utc'] == 1000
    assert row['opening_verified'] is False and row['price_published_at_utc'] is None
    assert row['events'][0]['quotes'][0]['native_odd'] == {'Alt': 1.66, 'Üst': 1.65}
    assert set(row['source_sha256']) == {'events', 'market_definitions', 'competitions'}
    assert 'İlk kayıtlı model' not in b.review('NBA')


@pytest.mark.parametrize('change', [{'ci': 666}, {'sid': 1}, {'s': 1}, {'d': 1999},
                                    {'hn': 'Sacramento', 'an': 'Golden State'}, {'d': 1000}])
def test_exact_home_away_league_status_and_tipoff_binding(source, change):
    b, _, _, event, ctx = source
    event.update(change)
    assert 'tekil maç eşleşmedi' in b.review('NBA', ctx)
    assert not b.root.exists()


def test_start_and_wrong_context_do_not_query_and_ambiguous_match_cannot_publish(source):
    b, state, data, event, ctx = source
    state['now'] = 2000
    assert 'Maç başladı' in b.review('NBA', ctx)
    assert 'kimliği doğrulanamadı' in b.review('EUROLEAGUE', ctx)
    b.getter.assert_not_called()
    state['now'] -= 1
    data[EVENTS]['events'].append(dict(event, i=457))
    assert 'tekil maç eşleşmedi' in b.review('NBA', ctx)
    assert not b.root.exists()


@pytest.mark.parametrize('league', ['EUROLEAGUE', 'EUROCUP'])
def test_europe_uses_own_competition_and_does_not_import_nba_aliases(source, league):
    b, _, _, event, ctx = source
    event.update(ci=LEAGUES[league][0], hn='Takım A', an='Takım B')
    ctx.update(league=league, home={'official_name':'Takım A'}, away={'official_name':'Takım B'})
    assert '110,5' in b.review(league, ctx)
    assert 'bulunamadı' in b.review('NBA')


def test_market_status_settlement_and_both_sides_verified(source):
    _, _, data, event, _ = source
    spec = data[MARKETS]['m']
    altered = deepcopy(spec)
    altered['2_114']['n'] = 'Toplam Sayı Alt/Üst (Normal Süre) {0}'
    assert [r['period'] for r in lines(event, altered)] == ['1H']
    original = event['m'][0]
    for invalid in (dict(s=0), dict(t=1), dict(sov=True), dict(sov='nan'), dict(i=None),
                    dict(o=original['o'][:1]), dict(o=[{'n':'Alt','odd':0},original['o'][1]])):
        assert not lines(dict(m=[dict(original, **invalid)]), spec)
    assert not lines(dict(m=[original, dict(original, i=777)]), spec)


def test_partial_source_failure_retries_after_cooldown_and_respects_robots(source):
    b, state, data, _, _ = source
    data[EVENTS]['isdiff'] = True
    assert 'Tam bülten alınamadı' in b.review('NBA')
    assert 'beklemede' in b.review('NBA') and b.getter.call_count == 4
    state['now'] += 61
    data[EVENTS]['isdiff'] = False
    assert '215,5' in b.review('NBA') and b.getter.call_count == 5
    b.cache.clear()
    b.getter.side_effect = lambda *args, **kwargs: b'User-agent: *\nDisallow: /'
    assert 'Robots erişim kısıtı' in b.review('NBA')
    assert b.getter.call_args.args[0] == HOST+'/robots.txt'


@pytest.mark.parametrize('status', [403, 429, 503])
def test_http_denial_observes_retry_after_without_retrying(status):
    with patch('hybrid_engine.iddaa_bulletin.requests.get') as get:
        response = get.return_value.__enter__.return_value
        response.status_code = status
        response.headers = {'Retry-After': '420'}
        with pytest.raises(SourceError, match=str(status)) as err:
            read(EVENTS, 0)
        assert err.value.wait == 420 and get.call_count == 1
        assert get.call_args.kwargs['allow_redirects'] is False


def test_first_half_benchmark_matches_prematch_observation_only_once_and_verifies_hashes(source):
    from hybrid_engine.iddaa_comparison import render_comparison
    b, state, _, event, _ = source
    b.review('NBA')
    forecast = dict(league='NBA', season='2026/2027', fixture_id='official', model_digest='a'*64,
                    model_version='v1', home='Golden State Warriors', away='Sacramento Kings',
                    actual=[110,110], final_with_ot=[120,118], actual_periods={'home':[28,30,28,24,10],
                    'away':[25,27,30,28,8]}, predicted_halves=[[59,54],[55,55]],
                    fixture_start_utc=2000, first_archived_at_utc=950)
    def report(**changes):
        return {'NBA': {'forecasts':[dict(forecast, **changes)]}}
    assert '1 maç · Model 3.00 · Barem 0.50' in render_comparison(b.root, report())
    event['m'][1]['sov'] = '120.5'
    state['now'] += 65
    b.review('NBA')
    assert 'Barem 0.50' in render_comparison(b.root, report())
    for exclusions in ({'first_archived_at_utc':1001}, {'actual':None}, {'eligible_for_live_performance':False},
                       {'home':forecast['away']}, {'fixture_start_utc':1999}):
        assert 'Eşleşmiş sonuç henüz yok' in render_comparison(b.root, report(**exclusions))
    receipt, = (b.root/'first-half').rglob('*.json')
    pin = json.loads(receipt.read_text())['payload']['observation_sha256']
    (b.root/('bulletin-'+pin+'.json')).write_text('{}')
    with pytest.raises(ValueError, match='digest mismatch'):
        render_comparison(b.root, report())


def test_archive_allows_reading_inside_five_minutes_but_excludes_it_from_performance(source):
    b, state, _, _, _ = source
    state['now'] = 1700
    assert '215,5' in b.review('NBA')
    assert not (b.root/'first-half').exists()


def test_first_half_above_below_and_equal_have_no_contract_probability(source):
    b, _, _, _, ctx = source
    for mean, expected in [(110.5, 'baremle aynı'), (98.0, 'baremin 12,5 sayı altında')]:
        text = b.review('NBA', dict(ctx, first_half_total=mean))
        assert expected in text and '%' not in text


def test_iddaa_market_callback_fits_telegram_and_is_opt_in():
    from hybrid_engine.telegram_premium_ui import keyboard
    def buttons(**kw):
        return [button.callback_data for row in keyboard('a'*12, **kw).inline_keyboard for button in row]
    callback = 'zui:'+('a'*12)+':iddaa'
    assert callback in buttons(section='market',include_iddaa=True)
    assert callback not in buttons(section='market')


def test_automatic_pass_does_not_fill_archive_with_duplicate_market_listings(source):
    b, state, data, event, _ = source
    assert '215,5' in b.review('NBA', first_only=True)
    state['now'] += 61
    assert 'yeni ilk yarı baremi yok' in b.review('NBA', first_only=True)
    assert len(list(b.root.glob('bulletin-*.json'))) == 1
    data[EVENTS]['events'].append(dict(event, i=457, d=2001))
    state['now'] += 61
    assert '215,5' in b.review('NBA', first_only=True)
    assert len(list((b.root/'first-half').rglob('*.json'))) == 2


def test_exact_clippers_display_name_alias(source):
    b, _, _, event, ctx = source
    event['hn'] = 'LA Clippers'
    ctx['home']['official_name'] = 'Los Angeles Clippers'
    assert '215,5' in b.review('NBA', ctx)
    ctx['home']['official_name'] = 'Los Angeles Lakers'
    assert 'tekil maç eşleşmedi' in b.review('NBA', ctx)
