"""Explicit native NBA event-clock binding; never rewrites an ESPN fixture.

The measured +600s provider offset is a local research association, not an
assertion that two publishers use identical scheduled start times. Every bound
quote retains both clocks, the event ID, the discovery pin and earliest cutoff.
"""
from datetime import datetime, timezone
import re
import time
from urllib.parse import urlsplit

from core.team_identity import digest

RULE='NBA_ORDERED_UNIQUE_PAIR_PLUS600_V1'


def pair(event,snapshot):
    from hybrid_engine.provider_bridge import team_side
    try:
        return (team_side(event['home_team'],snapshot)=='home' and
                team_side(event['away_team'],snapshot)=='away')
    except (KeyError,ValueError,TypeError):return False


def bind(receipt,snapshot,*,asof_utc=None):
    from hybrid_engine.provider_bridge import SPORTS,utc,matches
    now=int(time.time()) if asof_utc is None else asof_utc
    sport=SPORTS.get(snapshot['league'])
    expected='https://api.the-odds-api.com/v4/sports/'+str(sport)+'/events'
    if (receipt.get('provider')!='THE_ODDS_API' or receipt.get('source_url')!=expected or
            receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
            digest(receipt.get('document'))!=receipt.get('document_sha256') or
            not isinstance(receipt.get('document'),list) or len(receipt['document'])>1000):
        raise ValueError('NATIVE_EVENT_DISCOVERY_PROOF_REQUIRED')
    if (type(now) is not int or type(receipt.get('observed_at_utc')) is not int or
            type(receipt.get('ingested_at_utc')) is not int or
            not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now<=int(time.time()) or
            now-receipt['observed_at_utc']>120):
        raise ValueError('FRESH_EVENT_DISCOVERY_CLOCK_REQUIRED')
    events=receipt['document'];exact=[e for e in events if matches(e,snapshot)]
    if len(exact)>1:raise ValueError('AMBIGUOUS_NATIVE_EVENT_DISCOVERY')
    mode='EXACT_SCHEDULE_MATCH'
    if len(exact)==1:
        event=exact[0]
    else:
        same=[e for e in events if pair(e,snapshot)]
        if snapshot['league'] in ('EUROLEAGUE','EUROCUP'):
            raise ValueError('OFFICIAL_TEAM_ALIAS_OR_EXACT_START_REQUIRED')
        if snapshot['league']!='NBA' or len(same)!=1:
            raise ValueError('EXACT_OR_UNIQUE_NBA_PLUS600_MATCH_REQUIRED')
        event=same[0]
        if event.get('sport_key')!='basketball_nba' or utc(event['commence_time'])-snapshot['fixture_start_utc']!=600:
            raise ValueError('EXPLICIT_NBA_PLUS600_ONLY')
        # A reversed pairing nearby signals an ambiguous event slate.
        from hybrid_engine.provider_bridge import name
        for other in events:
            try:
                reversed_pair=(name(other['home_team'])==name(snapshot['away']['official_name']) and
                               name(other['away_team'])==name(snapshot['home']['official_name']))
                if reversed_pair and abs(utc(other['commence_time'])-snapshot['fixture_start_utc'])<=86400:
                    raise ValueError('REVERSED_NATIVE_EVENT_CONFLICT')
            except (KeyError,TypeError):continue
        mode='EXPLICIT_UNIQUE_NBA_PLUS600_ASSOCIATION'
    eid=event.get('id');provider_start=utc(event['commence_time']);official_start=snapshot['fixture_start_utc']
    if (not isinstance(eid,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',eid) or
            event.get('sport_key',sport)!=sport):
        raise ValueError('NATIVE_EVENT_ID_OR_COMPETITION_CONFLICT')
    cutoff=min(provider_start,official_start)
    if now>=cutoff:raise ValueError('EARLIEST_NATIVE_START_ALREADY_REACHED')
    payload=dict(format='NATIVE_PROVIDER_EVENT_CLOCK_BINDING_V1',rule=RULE,mode=mode,
        canonical_fixture_id=snapshot['fixture_id'],league=snapshot['league'],season=snapshot['season'],
        original_snapshot_sha256=digest(snapshot),provider_event_id=eid,
        archived_start_utc=official_start,provider_start_utc=provider_start,
        delta_seconds=provider_start-official_start,prematch_deadline_utc=cutoff,
        discovery_receipt_sha256=digest(receipt),discovery_document_sha256=receipt['document_sha256'],
        discovery_event_sha256=digest(event),available_at_utc=receipt['ingested_at_utc'],
        forecast_changed=False,scheduled_times_are_identical=provider_start==official_start)
    if snapshot.get('league') in ('EUROLEAGUE','EUROCUP') and snapshot.get('european_team_catalog') is not None:
        from hybrid_engine.europe_provider_identity import binding_evidence,RULE as EUROPE_RULE
        payload['team_identity']=binding_evidence(snapshot)
        payload['rule']=EUROPE_RULE
        payload['mode']='OFFICIAL_TEAM_ALIASES_EXACT_START'
        # Version only this newly authorized native event alias; preserve all
        # historic V1 bindings, immutable receipts and original forecasts.
        from core.league_identity import normalize_name
        from hybrid_engine.europe_provider_identity import (OBSERVED_LABELS,CATALOG_OBSERVED_LABELS,
            official_registry,observed_catalog_anchor)
        used={normalize_name(event[k]):OBSERVED_LABELS[normalize_name(event[k])][0]
              for k in ('home_team','away_team') if normalize_name(event[k]) in OBSERVED_LABELS}
        if used and snapshot['league']=='EUROLEAGUE' and snapshot['season']=='2026/2027':
            payload['rule']='EUROPE_OBSERVED_PROVIDER_LABELS_E2026_V3'
            payload['team_identity']['observed_exact_provider_aliases']=used
        # Only a newly used fallback changes the binding format; direct
        # official aliases and earlier accepted bindings retain their pins.
        if snapshot['league']=='EUROLEAGUE' and snapshot['season']=='2026/2027':
            from core.team_identity import IdentityRefusal
            registry,_,at=official_registry(snapshot);extra={}
            for side in ('home_team','away_team'):
                label=event[side];key=normalize_name(label)
                if key not in CATALOG_OBSERVED_LABELS:continue
                try:registry.resolve(snapshot['league'],snapshot['season'],label,asof_utc=at)
                except IdentityRefusal as exc:
                    if str(exc)!='TEAM_ALIAS_NOT_REGISTERED':raise
                    team=observed_catalog_anchor(label,snapshot,registry,at)
                    extra[key]=team.provider_ids[0][1]
            if extra:
                payload['rule']='EUROPE_OBSERVED_CATALOG_ANCHORS_E2026_V4'
                payload['team_identity']['observed_catalog_anchor_aliases']=extra
        if (snapshot['league']=='EUROLEAGUE' and
                snapshot['season']=='2026/2027' and
                (normalize_name(event['home_team'])=='kkpartizannis' or
                 normalize_name(event['away_team'])=='kkpartizannis')):
            payload['rule']='EUROPE_EXACT_HISTORIC_PARTIZAN_NIS_PAR_V2'
            payload['team_identity']['historic_label']='KK_PARTIZAN_NIS'
            payload['team_identity']['historic_label_target']='EUROLEAGUE_LIVE:PAR'
            payload['team_identity']['historic_label_scope']='E2026_EXACT_MATCH_ONLY'
    return event,dict(payload=payload,sha256=digest(payload))


def verify_detail(discovery,detail,snapshot):
    from hybrid_engine.provider_bridge import utc
    if (detail.get('status')!='DOCUMENT_RECEIVED' or detail.get('provider')!='THE_ODDS_API' or
            detail.get('http_status')!=200 or digest(detail.get('document'))!=detail.get('document_sha256')):
        raise ValueError('NATIVE_ODDS_DETAIL_PROOF_REQUIRED')
    event,binding=bind(discovery,snapshot)
    d=detail['document'];b=binding['payload'];uri=urlsplit(detail['source_url'])
    if (uri.scheme!='https' or uri.netloc!='api.the-odds-api.com' or
            uri.path!=f"/v4/sports/{event.get('sport_key')}/events/{event['id']}/odds" or
            not isinstance(d,dict) or d.get('id')!=event['id'] or not pair(d,snapshot) or
            d.get('sport_key')!=event.get('sport_key') or utc(d['commence_time'])!=b['provider_start_utc']):
        raise ValueError('DISCOVERY_AND_ODDS_DETAIL_IDENTITY_CONFLICT')
    observed=detail.get('observed_at_utc');ingested=detail.get('ingested_at_utc')
    if (type(observed) is not int or type(ingested) is not int or
            not discovery['observed_at_utc']<=observed<=ingested<=int(time.time())<b['prematch_deadline_utc']):
        raise ValueError('ODDS_DETAIL_AFTER_EARLIEST_START_OR_INVALID_CLOCK')
    return binding


def clock_text(binding):
    p=binding['payload']
    def iso(ts):return datetime.fromtimestamp(ts,timezone.utc).isoformat()
    return ('ESPN/arşiv UTC: '+iso(p['archived_start_utc'])+
            ' | Sağlayıcı UTC: '+iso(p['provider_start_utc'])+
            ' | Fark: '+str(p['delta_seconds'])+' sn'+
            ' | Maç öncesi son sınır UTC: '+iso(p['prematch_deadline_utc']))
