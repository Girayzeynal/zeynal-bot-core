"""Observed ESPN bookmaker quotes, never invented reference lines or settlement rules."""
import math
import re
from urllib.parse import urlparse

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.markets import market_grid
from season_archive_inventory import archive_catalog


def number(value):
    if isinstance(value,bool):raise ValueError('MARKET_FINITE_NUMBER_REQUIRED')
    x=float(value)
    if not math.isfinite(x) or abs(x)>10000:raise ValueError('MARKET_FINITE_NUMBER_REQUIRED')
    return x


def decimal_price(american):
    if american=='EVEN':return 2.
    if not isinstance(american,str) or not re.fullmatch(r'[+-]\d{3,6}',american):raise ValueError('EXPLICIT_AMERICAN_PRICE_REQUIRED')
    x=int(american)
    if abs(x)<100:raise ValueError('INVALID_AMERICAN_PRICE')
    return 1+x/100 if x>0 else 1+100/abs(x)


def implied_prices(over_or_home, under_or_away):
    """Two-sided proportional de-vig, conditional on no push; not fair-value proof."""
    prices = [number(over_or_home), number(under_or_away)]
    if min(prices) <= 1: raise ValueError('DECIMAL_PRICE_MUST_EXCEED_ONE')
    raw = [1/p for p in prices]; mass = sum(raw)
    return dict(over_or_home=raw[0]/mass, under_or_away=raw[1]/mass,
        implied_mass=mass, overround=mass-1,
        method='PROPORTIONAL_TWO_SIDED_NO_PUSH_CONDITIONAL_NOT_CALIBRATED',
        evidence='OBSERVED_PRICES_NOT_PROVEN_TRUE_PROBABILITIES')


def observe_espn(receipt, *, now_utc):
    """The provider field named close means observed value, not proven closing time.

    ESPN's game totals/spreads do not declare overtime settlement in this schema.
    Therefore their settlement scope remains UNKNOWN, even for a verified price.
    """
    uri=urlparse(receipt.get('source_url',''))
    if (receipt.get('provider')!='ESPN' or receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
        uri.scheme!='https' or uri.netloc!='site.api.espn.com' or uri.path!='/apis/site/v2/sports/basketball/nba/scoreboard' or
        digest(receipt['document'])!=receipt['document_sha256']):raise ValueError('QUOTE_RECEIPT_BINDING')
    o,i=receipt['observed_at_utc'],receipt['ingested_at_utc']
    if any(type(t) is not int for t in (o,i,now_utc)) or not 0<o<=i<=now_utc:raise ValueError('QUOTE_OBSERVATION_CLOCK')
    events=receipt['document']['events'];quotes=[];rejected=[]
    for event in events:
        try:
            year=event['season']['year']-1
            b=archive_catalog({'events':[event]},provider='ESPN',season_start_year=year,observed_at_utc=o,ingested_at_utc=i)
            g=b['payload']['fixtures'][0]
            if g['completed'] or event['competitions'][0]['status']['type']['state']!='pre' or g['start_ts_utc']<=now_utc:
                raise Abstain('QUOTE_NOT_FOR_UNSTARTED_FIXTURE')
            for native in event['competitions'][0].get('odds',[]):
                book=native['provider']
                if not isinstance(book['id'],str) or not isinstance(book['name'],str) or not book['name'].strip():raise ValueError('BOOKMAKER_ID_REQUIRED')
                definitions=[]
                if 'total' in native:
                    over=native['total']['over']['close'];under=native['total']['under']['close']
                    if not over['line'].startswith('o') or not under['line'].startswith('u'):raise ValueError('TOTAL_SIDE_PREFIX_CONFLICT')
                    line=number(over['line'][1:])
                    if line<=0 or line!=number(under['line'][1:]) or line!=number(native['overUnder']):raise ValueError('TOTAL_LINE_CONFLICT')
                    definitions.append(('TOTAL',line,decimal_price(over['odds']),decimal_price(under['odds'])))
                if 'pointSpread' in native:
                    home=native['pointSpread']['home']['close'];away=native['pointSpread']['away']['close']
                    line=number(home['line'])
                    if line!=-number(away['line']):raise ValueError('SPREAD_SIDE_LINE_CONFLICT')
                    definitions.append(('HOME_HANDICAP',line,decimal_price(home['odds']),decimal_price(away['odds'])))
                for market,line,over,under in definitions:
                    p=dict(format='OBSERVED_BOOKMAKER_QUOTE_V1',league='NBA',season=f'{year}/{year+1}',
                        fixture_id=g['canonical_id'],provider_fixture_id=event['id'],fixture_start_utc=g['start_ts_utc'],
                        home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],
                        bookmaker_id=book['id'],bookmaker=book['name'],market=market,line=line,
                        decimal_over_or_home_cover=over,decimal_under_or_away_cover=under,
                        observed_at_utc=o,ingested_at_utc=i,source_url=receipt['source_url'],
                        document_sha256=receipt['document_sha256'],native_quote_sha256=digest(native),
                        provider_field='close',closing_time_verified=False,settlement_scope='UNKNOWN',
                        source_attestation='LOCAL_RETRIEVAL_RECEIPT_NOT_SIGNED_BOOKMAKER_FEED')
                    quotes.append(dict(payload=p,sha256=digest(p)))
        except (KeyError,TypeError,ValueError) as exc:
            rejected.append(dict(provider_fixture_id=event.get('id'),reason=str(exc) if isinstance(exc,ValueError) else 'MISSING_NATIVE_MARKET_FIELDS'))
    return dict(quotes=quotes,rejected=rejected,synthetic_lines_created=0)


def evaluate_observation(quote,forecast,*,trusted_sha256,model_digest,prediction_utc,roster_verified=False,profiles=None):
    p=quote['payload']
    if quote['sha256']!=trusted_sha256 or digest(p)!=trusted_sha256:raise ValueError('OBSERVED_QUOTE_PIN')
    if not p['observed_at_utc']<=p['ingested_at_utc']<=prediction_utc<p['fixture_start_utc']:raise Abstain('QUOTE_NOT_AVAILABLE_AT_PREDICTION')
    grid=market_grid(forecast,{p['market']:[p['line']]},model_digest=model_digest,prediction_utc=prediction_utc,
        profiles=profiles,roster_verified=roster_verified,model_disagreement=None)
    result=grid[0]
    if prediction_utc-p['observed_at_utc']>300:result['reasons'].append('STALE_BOOKMAKER_OBSERVATION')
    if p['settlement_scope']!='REGULATION_ONLY':result['reasons'].append('MARKET_SCOPE_UNVERIFIED_WITH_REGULATION_MODEL')
    raw=result.pop('raw_probabilities')
    prices=implied_prices(p['decimal_over_or_home_cover'],p['decimal_under_or_away_cover'])
    result.update(quote_sha256=trusted_sha256,bookmaker=p['bookmaker'],observed_at_utc=p['observed_at_utc'],
        conditional_regulation_probabilities=raw,conditional_probability_is_settlement_probability=False,
        conditional_direction=None if raw is None or raw['under']==raw['over'] else 'OVER' if raw['over']>raw['under'] else 'UNDER',
        recommended_direction=None,risk_level='NOT_ESTIMABLE',verified_confidence_index=None,
        observed_price_probabilities=prices,
        comparable_model_market_edge=None,
        comparison_status='NOT_COMPARABLE_WITHOUT_MATCHED_SETTLEMENT_AND_CALIBRATION')
    if result['reasons']:
        result.update(status='ABSTAIN',confidence_index=None,calibrated_probabilities=None)
    return result
