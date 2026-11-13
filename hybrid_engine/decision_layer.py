"""Research decision interface. Frozen paths, observed prices, explicit settlement; no forced picks."""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from urllib.parse import urlparse
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.intervals import sample_paths
from hybrid_engine.observed_markets import implied_prices

PERIODS=('FULL','1Q','2Q','3Q','4Q','1H','2H')
KINDS=('TOTAL','HOME','AWAY','HOME_HANDICAP','WINNER')
POLICY=dict(version='ELITE_DECISION_GUARD_V1',minimum_raw_ev=0.,quote_max_age_seconds=300,
    recommendations_enabled=False,calibration_auto_update=False,
    probability_order=['under_or_away','push_or_regulation_draw','over_or_home'])
POLICY_SHA=digest(dict(policy=POLICY,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


def finite(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('FINITE_NUMBER_REQUIRED')
    return float(value)


def receipt_document(r,*,expected_url,trusted_document_sha256):
    uri=urlparse(expected_url)
    if uri.scheme!='https' or not uri.netloc or r.get('source_url')!=expected_url or r.get('status')!='DOCUMENT_RECEIVED' or r.get('http_status')!=200:
        raise ValueError('NATIVE_RECEIPT_BINDING_REQUIRED')
    if r.get('document_sha256')!=trusted_document_sha256 or digest(r['document'])!=trusted_document_sha256:
        raise ValueError('NATIVE_DOCUMENT_TRUSTED_PIN')
    if any(type(r.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or not 0<r['observed_at_utc']<=r['ingested_at_utc']<=int(time.time()):
        raise ValueError('NATIVE_RECEIPT_CLOCK_REQUIRED')
    return r['document']


@dataclass(frozen=True)
class RuleEvidence:
    payload:dict
    sha256:str

    @staticmethod
    def validate(d):
        if (d.get('format')!='EXPLICIT_BOOK_SETTLEMENT_V1' or d.get('period') not in PERIODS or d.get('market') not in KINDS or
            type(d.get('include_overtime')) is not bool or type(d.get('bookmaker_id')) is not str or not 1<=len(d['bookmaker_id'])<=128 or
            type(d.get('league')) is not str or not d['league'].strip() or len(d['league'])>128 or
            d.get('stake_rule')!='WHOLE_STAKE_WIN_LOSS_PUSH' or d.get('tie_policy')!='PUSH'):
            raise ValueError('EXPLICIT_SUPPORTED_SETTLEMENT_REQUIRED')
        if (type(d.get('effective_from_utc')) is not int or d['effective_from_utc']<=0 or
            'effective_until_utc' not in d or (d['effective_until_utc'] is not None and
            (type(d['effective_until_utc']) is not int or d['effective_until_utc']<=d['effective_from_utc']))):
            raise ValueError('EXPLICIT_SETTLEMENT_VALIDITY_REQUIRED')

    @classmethod
    def admit(cls,receipt,*,expected_url,trusted_document_sha256):
        d=receipt_document(receipt,expected_url=expected_url,trusted_document_sha256=trusted_document_sha256)
        cls.validate(d)
        p=dict(d,observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],
            source_url=expected_url,source_document_sha256=trusted_document_sha256,
            attestation='CAPTURED_STRUCTURED_INPUT_NOT_INDEPENDENT_PROVIDER_SIGNATURE')
        return cls(p,digest(p))


@dataclass(frozen=True)
class QuoteEvidence:
    payload:dict
    sha256:str

    @classmethod
    def admit_feed(cls,receipt,*,expected_url,trusted_document_sha256):
        """Explicit interface for a future configured structured feed; never synthesizes native prices."""
        d=receipt_document(receipt,expected_url=expected_url,trusted_document_sha256=trusted_document_sha256)
        if d.get('format')!='EXPLICIT_BOOK_MARKET_V1':raise ValueError('EXPLICIT_QUOTE_FEED_REQUIRED')
        p=dict(d,observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],
            source_url=expected_url,source_document_sha256=trusted_document_sha256,closing_time_verified=False)
        cls.validate(p)
        return cls(p,digest(p))

    @staticmethod
    def validate(p):
        if p.get('period') not in PERIODS or p.get('market') not in KINDS or type(p.get('bookmaker_id')) is not str or not 1<=len(p['bookmaker_id'])<=128:
            raise ValueError('SUPPORTED_QUOTE_SCOPE_REQUIRED')
        for k in ('fixture_id','league','season','home_team_id','away_team_id'):
            if type(p.get(k)) is not str or not p[k].strip() or len(p[k])>128:raise ValueError('QUOTE_FIXTURE_IDENTITY_REQUIRED')
        if type(p.get('tipoff_utc')) is not int or p['tipoff_utc']<=0:raise ValueError('QUOTE_TIPOFF_REQUIRED')
        line=finite(p['line'])
        if abs(line)>1000 or (p['market']=='WINNER' and line!=0):raise ValueError('SUPPORTED_QUOTE_LINE_REQUIRED')
        if not isinstance(p.get('prices'),dict) or not set(p['prices'])<=set(('under','over')):raise ValueError('EXPLICIT_PRICE_SIDES_REQUIRED')
        for price in p['prices'].values():
            if not 1<finite(price)<=1001:raise ValueError('DECIMAL_PRICE_MUST_EXCEED_ONE')

    @classmethod
    def from_espn(cls,observed,*,trusted_sha256):
        """Only use after observe_espn has replayed the pinned native receipt."""
        q=observed['payload']
        if digest(q)!=trusted_sha256 or observed['sha256']!=trusted_sha256:raise ValueError('OBSERVED_QUOTE_PIN')
        p=dict(format='EXPLICIT_BOOK_MARKET_V1',league=q['league'],season=q['season'],fixture_id=q['fixture_id'],
            home_team_id=q['home_team_id'],away_team_id=q['away_team_id'],tipoff_utc=q['fixture_start_utc'],period='FULL',
            bookmaker_id=q['bookmaker_id'],bookmaker=q['bookmaker'],market=q['market'],line=q['line'],
            prices=dict(over=q['decimal_over_or_home_cover'],under=q['decimal_under_or_away_cover']),
            observed_at_utc=q['observed_at_utc'],ingested_at_utc=q['ingested_at_utc'],source_url=q['source_url'],
            source_document_sha256=q['document_sha256'],native_quote_sha256=q['native_quote_sha256'],
            closing_time_verified=False,settlement_scope='UNKNOWN')
        cls.validate(p)
        return cls(p,digest(p))


class DecisionDistribution:
    def __init__(self,forecast,trace,*,overtime_paths=None):
        self.paths=sample_paths(forecast);self.trace=dict(trace);self.forecast=forecast;self.overtime=overtime_paths
        if not 0<trace['inputs_available_max_utc']<=trace['prediction_utc']<trace['tipoff_utc']:
            raise ValueError('DISTRIBUTION_PREMATCH_CLOCK_REQUIRED')
        if overtime_paths is not None:
            ot=np.asarray(overtime_paths);reg=self.paths.sum(axis=1)
            if (ot.shape!=(len(reg),2) or not np.issubdtype(ot.dtype,np.integer) or np.any(ot<0) or
                np.any(ot[reg[:,0]!=reg[:,1]]!=0) or np.any((reg+ot)[:,0]==(reg+ot)[:,1])):
                raise ValueError('COHERENT_COMPLETED_OVERTIME_PATHS_REQUIRED')
            self.overtime=ot

    def values(self,period,market,*,include_overtime=False):
        if period not in PERIODS or market not in KINDS:raise ValueError('UNSUPPORTED_DISTRIBUTION_MARKET')
        if period=='FULL':teams=self.paths.sum(axis=1)
        elif period.endswith('Q'):teams=self.paths[:,int(period[0])-1,:]
        else:
            start=0 if period=='1H' else 2;teams=self.paths[:,start:start+2,:].sum(axis=1)
        if include_overtime:
            if self.overtime is None:raise Abstain('NO_VERIFIED_OVERTIME_SIMULATION_PATHS')
            teams=teams+self.overtime
        if market=='TOTAL':return teams.sum(axis=1)
        if market in ('HOME','AWAY'):return teams[:,0 if market=='HOME' else 1]
        return teams[:,0]-teams[:,1]

    def describe(self,period='FULL',market='TOTAL',*,include_overtime=False):
        values=self.values(period,market,include_overtime=include_overtime);q=np.quantile(values,[.05,.25,.5,.75,.95],method='linear')
        unique,counts=np.unique(values,return_counts=True);modes=unique[counts==counts.max()]
        return dict(mean=float(values.mean()),p50=float(q[2]),p25=float(q[1]),p75=float(q[3]),p05=float(q[0]),p95=float(q[4]),
            discrete_modes=modes[:16].tolist(),mode_count=len(modes),mode_frequency=float(counts.max()/len(values)),
            samples=len(values),mode_is_not_mean_or_median=True,coverage_calibrated=False)


def evaluate_quote(distribution,quote=None,rule=None,*,asof_utc,calibration=None):
    trace=distribution.trace
    if type(asof_utc) is not int or asof_utc<trace['prediction_utc']:raise ValueError('ACTUAL_DECISION_CLOCK_REQUIRED')
    result=dict(policy_sha256=POLICY_SHA,status='NO_MARKET_DATA',reasons=[],quote_sha256=None,raw_probabilities=None,
        calibrated_probabilities=None,confidence_index=None,recommended_direction=None,selected=False,
        price_benchmarks=None,expected_value=None,conditional_no_push_edge=None,closing_line_value=None,
        prediction_utc=trace['prediction_utc'],evaluated_at_utc=asof_utc,
        audit_class='PREGAME_RESEARCH_DECISION' if asof_utc<trace['tipoff_utc'] else 'POSTHOC_AUDIT_NOT_PREGAME_DECISION')
    if quote is None:return result
    q=quote.payload
    if digest(q)!=quote.sha256:raise ValueError('QUOTE_PAYLOAD_MUTATED')
    QuoteEvidence.validate(q);result.update(quote_sha256=quote.sha256,quote=q,status='INSUFFICIENT_DATA')
    for k in ('fixture_id','league','season','home_team_id','away_team_id','tipoff_utc'):
        if q[k]!=trace[k]:result['reasons'].append('QUOTE_FIXTURE_SCOPE_CONFLICT');return result
    if not 0<q['observed_at_utc']<=q['ingested_at_utc']<=trace['prediction_utc']<=asof_utc:
        result['reasons'].append('QUOTE_NOT_AVAILABLE_AT_FORECAST');return result
    if trace['prediction_utc']-q['observed_at_utc']>POLICY['quote_max_age_seconds']:
        result['reasons'].append('STALE_MARKET_QUOTE');return result
    prices=q['prices']
    if prices:
        result['price_benchmarks']=dict(break_even_conditional_on_no_push={s:1/d for s,d in prices.items()},
            no_vig=(implied_prices(prices['over'],prices['under']) if set(prices)=={'over','under'} else None),
            not_true_event_probabilities=True)
    conditional=distribution.values(q['period'],q['market']);threshold=-q['line'] if q['market']=='HOME_HANDICAP' else q['line']
    result['conditional_regulation_probabilities']=dict(under=float(np.mean(conditional<threshold)),
        push=float(np.mean(conditional==threshold)),over=float(np.mean(conditional>threshold)))
    result['conditional_regulation_is_contract_settlement_probability']=False
    result['conditional_regulation_summary']=distribution.describe(q['period'],q['market'])
    if rule is None:result['reasons'].append('SETTLEMENT_RULE_UNVERIFIED');return result
    r=rule.payload
    if digest(r)!=rule.sha256:raise ValueError('SETTLEMENT_RULE_PAYLOAD_MUTATED')
    RuleEvidence.validate(r)
    if (any(r[k]!=q[k] for k in ('league','bookmaker_id','period','market')) or
        not 0<r['observed_at_utc']<=r['ingested_at_utc']<=trace['prediction_utc'] or
        r['effective_from_utc']>trace['prediction_utc'] or
        (r['effective_until_utc'] is not None and trace['prediction_utc']>=r['effective_until_utc'])):
        result['reasons'].append('SETTLEMENT_SCOPE_OR_CLOCK_CONFLICT');return result
    if not float(2*q['line']).is_integer():result['reasons'].append('SPLIT_STAKE_ASIAN_QUARTER_LINE_UNSUPPORTED');return result
    try:values=distribution.values(q['period'],q['market'],include_overtime=r['include_overtime'])
    except Abstain as exc:result['reasons'].append(str(exc));return result
    threshold=-q['line'] if q['market']=='HOME_HANDICAP' else q['line']
    raw=dict(under=float(np.mean(values<threshold)),push=float(np.mean(values==threshold)),over=float(np.mean(values>threshold)))
    result.update(raw_probabilities=raw,settlement_rule_sha256=rule.sha256,
        distribution_summary=distribution.describe(q['period'],q['market'],include_overtime=r['include_overtime']),
        probability_status='RAW_NOT_CALIBRATED',settlement=dict(period=q['period'],market=q['market'],include_overtime=r['include_overtime']))
    if not prices:result['reasons'].append('NO_OBSERVED_PRICES');return result
    ev={s:raw[s]*(d-1)-raw['under' if s=='over' else 'over'] for s,d in prices.items()}
    edge=None;bench=result['price_benchmarks']['no_vig'];mass=1-raw['push']
    if bench is not None and mass>0:edge=dict(over=raw['over']/mass-bench['over_or_home'],under=raw['under']/mass-bench['under_or_away'])
    result.update(expected_value=ev,conditional_no_push_edge=edge,
        break_even_unconditional_win_probability={s:mass/d for s,d in prices.items()})
    # No calibrated profiles are admitted through a caller-provided boolean.
    # Shadow profiles remain offline candidates until a separate release approval.
    result['status']='NO_EDGE' if max(ev.values())<=POLICY['minimum_raw_ev'] else 'UNCALIBRATED'
    result['reasons'].append('NO_APPROVED_DISJOINT_CALIBRATION')
    if calibration is not None:result['reasons'].append('SHADOW_CANDIDATE_CANNOT_AUTHORIZE_LIVE_SELECTION')
    if asof_utc>=trace['tipoff_utc']:result['reasons'].append('POST_TIPOFF_AUDIT_ONLY')
    return result


def settled_value(periods,period,market,*,include_overtime=False):
    h=np.asarray(periods['home']);a=np.asarray(periods['away'])
    if (h.ndim!=1 or len(h)<4 or len(h)!=len(a) or not np.issubdtype(h.dtype,np.integer) or
        not np.issubdtype(a.dtype,np.integer) or np.any(h<0) or np.any(a<0)):raise ValueError('VERIFIED_PERIOD_SCORES_REQUIRED')
    if any(h[:n].sum()!=a[:n].sum() for n in range(4,len(h))):raise ValueError('OVERTIME_REQUIRES_PRECEDING_TIE')
    if period not in PERIODS or market not in KINDS:raise ValueError('UNSUPPORTED_SETTLEMENT_SCOPE')
    sl=slice(0,4) if period=='FULL' else slice(int(period[0])-1,int(period[0])) if period.endswith('Q') else slice(0,2) if period=='1H' else slice(2,4)
    teams=np.array([h[sl].sum(),a[sl].sum()])
    if include_overtime:teams+=np.array([h[4:].sum(),a[4:].sum()])
    if market=='TOTAL':return int(teams.sum())
    if market in ('HOME','AWAY'):return int(teams[0 if market=='HOME' else 1])
    return int(teams[0]-teams[1])
