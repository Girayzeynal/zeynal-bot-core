"""Permission-gated RSS metadata, explicit fixture binding, no inferred facts.

No default feeds or network calls. A headline is a claim or commentary, never
an official injury/lineup announcement. Binding/policy pins must come from the caller.
"""
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import seal_observation, validate_observation, REGISTRY, REGISTRY_PIN


def claims_from_rss(raw,fixture,bindings,bindings_pin):
    require(type(bindings) is dict and digest(bindings)==bindings_pin,'TRUSTED_NEWS_BINDING_PIN_MISMATCH')
    text=raw['rss'];require(type(text) is str and len(text)<=1_000_000 and
                           '<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper(), 'UNSAFE_RSS_DOCUMENT')
    try:root=ET.fromstring(text)
    except ET.ParseError as ex:raise ValueError('MALFORMED_RSS') from ex
    require(root.tag=='rss','RSS_FORMAT_REQUIRED')
    matches=[]
    for item in root.findall('./channel/item'):
        link=item.findtext('link');title=item.findtext('title');date=item.findtext('pubDate')
        if link not in bindings or bindings[link]!=fixture['canonical_id']:continue
        require(type(title) is str and 0<len(title.strip())<=1000 and type(date) is str,'RSS_METADATA_REQUIRED')
        u=urlsplit(link);require(u.scheme=='https' and u.hostname and not u.username and not u.password,'INVALID_ARTICLE_URL')
        try:published=parsedate_to_datetime(date)
        except (ValueError,TypeError) as ex:raise ValueError('PUBLICATION_TIME_REQUIRED') from ex
        require(published.tzinfo is not None,'PUBLICATION_TIMEZONE_REQUIRED')
        matches.append(dict(claims={'headline':title.strip(),'article_url':link,'claim_status':'UNVERIFIED_SOURCE_CLAIM'},
                            published_at_utc=int(published.timestamp())))
    require(len(matches)==1,'EXPLICIT_UNIQUE_FIXTURE_NEWS_BINDING_REQUIRED')
    return matches[0]


def capture_rss(raw, *, fixture, bindings, bindings_pin, provider, source_url,
                observed_at_utc,ingested_at_utc,data_type='NEWS_CLAIM',usage='RETROSPECTIVE_RESEARCH',
                registry=REGISTRY,registry_pin=REGISTRY_PIN):
    require(data_type in ('NEWS_CLAIM','ANALYST_OPINION'),'NEWS_IS_NOT_OFFICIAL_LINEUP_OR_INJURY')
    require(provider in registry and registry[provider]['usage']=='PERMITTED','NEWS_PERMISSION_NOT_ESTABLISHED')
    n=claims_from_rss(raw,fixture,bindings,bindings_pin)
    return seal_observation(**n,fixture=fixture,provider=provider,provider_fixture_id=fixture['canonical_id'],
        source_url=source_url,data_type=data_type,raw=raw,observed_at_utc=observed_at_utc,
        ingested_at_utc=ingested_at_utc,usage=usage,registry=registry,registry_pin=registry_pin)


def replay_rss(observation, *, bindings, bindings_pin, **validation):
    p=validate_observation(observation,**validation)
    require(p['data_type'] in ('NEWS_CLAIM','ANALYST_OPINION') and p['scope']=='NOT_APPLICABLE' and
            p['provider_fixture_id']==p['fixture']['canonical_id'],'NEWS_REPLAY_TYPE_MISMATCH')
    n=claims_from_rss(p['raw'],p['fixture'],bindings,bindings_pin)
    require(all(p[k]==v for k,v in n.items()),'NEWS_CLAIMS_CANNOT_REPLAY')
    return p
