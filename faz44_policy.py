"""Explicit pinned operator reviews for DEVELOPMENT_RESEARCH_ONLY.

No automated licence inference or permission upgrade. A trusted local review is
not a provider signature/legal attestation; defaults stay the FAZ41 UNKNOWN map.
"""
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY,REGISTRY_PIN

SCOPE='DEVELOPMENT_RESEARCH_ONLY'
FIELDS=set('owner host paths types level usage permission_ref reviewed_at_utc expires_at_utc'.split())


def _host(host):
    require(type(host) is str and host==host.lower() and len(host)<=253 and
            re.fullmatch(r'(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,63}',host) and
            not host.endswith(('.local','.internal','.localhost')),'PUBLIC_DNS_SOURCE_REQUIRED')
    try:ipaddress.ip_address(host)
    except ValueError:return
    raise ValueError('IP_LITERAL_SOURCE_REFUSED')


def template():
    p=dict(schema_version=1,scope=SCOPE,created_at_utc=int(time.time()),registry=deepcopy(REGISTRY),reviews={},
           attestation='OPERATOR_REVIEW_NOT_PROVIDER_SIGNATURE')
    return dict(payload=p,sha256=digest(p))


def validate_source_policy(sealed,*,trusted_sha256,asof_utc=None):
    now=int(time.time()) if asof_utc is None else asof_utc
    require(type(now) is int and 0<now<=int(time.time()),'POLICY_AUDIT_TIME_REQUIRED')
    require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and type(trusted_sha256) is str and
            re.fullmatch('[0-9a-f]{64}',trusted_sha256) and sealed['sha256']==trusted_sha256 and
            digest(sealed['payload'])==trusted_sha256,'TRUSTED_POLICY_PIN_MISMATCH')
    p=sealed['payload'];require(type(p) is dict and set(p)==set('schema_version scope created_at_utc registry reviews attestation'.split()) and
        type(p['schema_version']) is int and p['schema_version']==1 and p['scope']==SCOPE and
        p['attestation']=='OPERATOR_REVIEW_NOT_PROVIDER_SIGNATURE' and type(p['created_at_utc']) is int and
        0<p['created_at_utc']<=now and type(p['registry']) is dict and type(p['reviews']) is dict and
        set(REGISTRY)<=set(p['registry']) and len(p['registry'])<=20,'POLICY_BUNDLE_SCHEMA_OR_SCOPE')
    registry=p['registry'];owners={};permitted=set()
    for provider,policy in registry.items():
        require(type(provider) is str and re.fullmatch('[A-Z][A-Z0-9_]{1,63}',provider) and type(policy) is dict and set(policy)==FIELDS,'SOURCE_POLICY_SCHEMA')
        _host(policy['host'])
        require(type(policy['owner']) is str and policy['owner'] and policy['owner']==policy['owner'].strip() and
                policy['level'] in ('OFFICIAL','SECONDARY','COMMENTARY') and policy['usage'] in ('UNKNOWN','RESTRICTED','PERMITTED') and
                type(policy['paths']) is list and policy['paths'] and len(policy['paths'])==len(set(policy['paths'])) and
                all(type(path) is str and path.startswith('/') and path.endswith('/') and '..' not in path and
                    '?' not in path and '#' not in path and '\\' not in path for path in policy['paths']), 'SOURCE_POLICY_CLASSIFICATION')
        require(policy['host'] not in owners or owners[policy['host']]==policy['owner'],'HOST_OWNER_CONFLICT');owners[policy['host']]=policy['owner']
        if provider in REGISTRY:
            require(all(policy[k]==REGISTRY[provider][k] for k in ('owner','host','paths','types','level')),'BUILTIN_SOURCE_AUTHORITY_IMMUTABLE')
        else:
            require(type(policy['types']) is list and policy['types'] and len(policy['types'])==len(set(policy['types'])) and
                    set(policy['types'])<={'NEWS_CLAIM','ANALYST_OPINION'} and policy['level'] in ('SECONDARY','COMMENTARY') and
                    ('ANALYST_OPINION' not in policy['types'] or policy['level']=='COMMENTARY'),'EXTRA_SOURCE_MUST_REMAIN_NEWS_OR_COMMENTARY')
        if policy['usage']!='PERMITTED':
            require(all(policy[k] is None for k in ('permission_ref','reviewed_at_utc','expires_at_utc')) and provider not in p['reviews'],
                    'UNAPPROVED_SOURCE_CANNOT_HAVE_APPROVAL_RECEIPT')
            continue
        permitted.add(provider);review=p['reviews'].get(provider)
        require(type(review) is dict and set(review)==set('decision reviewer permission_ref reviewed_at_utc expires_at_utc document_sha256 allowed_purposes'.split()),'EXPLICIT_REVIEW_RECEIPT_REQUIRED')
        require(review['decision']=='PERMITTED' and type(review['reviewer']) is str and 0<len(review['reviewer'])<=120 and
                review['reviewer']==review['reviewer'].strip() and not any(ord(c)<32 for c in review['reviewer']) and
                review['allowed_purposes']==[SCOPE] and type(review['document_sha256']) is str and
                re.fullmatch('[0-9a-f]{64}',review['document_sha256']),'INVALID_REVIEW_RECEIPT')
        require(all(review[k]==policy[k] for k in ('permission_ref','reviewed_at_utc','expires_at_utc')) and
                type(policy['reviewed_at_utc']) is int and type(policy['expires_at_utc']) is int and
                0<policy['reviewed_at_utc']<=p['created_at_utc']<=now<policy['expires_at_utc'],'REVIEW_TIME_OR_BINDING_INVALID')
        url=urlsplit(policy['permission_ref']);require(url.scheme=='https' and url.hostname and not url.username and not url.password and
            url.port in (None,443) and not url.fragment,'REVIEW_REFERENCE_MUST_BE_HTTPS')
        _host(url.hostname)
    require(set(p['reviews'])==permitted,'UNUSED_OR_MISSING_REVIEW_RECEIPT')
    return dict(registry=deepcopy(registry),registry_sha256=digest(registry),policy_bundle_sha256=trusted_sha256,
                scope=SCOPE,permitted_providers=sorted(permitted),provider_signature_verified=False)


def read_source_policy(path,*,trusted_sha256,asof_utc=None):
    p=Path(path)
    require(not p.is_symlink() and Path('/data') not in p.resolve().parents and p.is_file() and p.stat().st_size<=512000,
            'READONLY_DEVELOPMENT_POLICY_REQUIRED')
    return validate_source_policy(json.loads(p.read_text()),trusted_sha256=trusted_sha256,asof_utc=asof_utc)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--template',action='store_true');parser.add_argument('--policy');parser.add_argument('--trusted-sha256');args=parser.parse_args()
    try:
        if args.template:
            require(not args.policy and not args.trusted_sha256,'ONE_POLICY_ACTION_REQUIRED');print(json.dumps(template(),sort_keys=True));return 0
        require(bool(args.policy) and bool(args.trusted_sha256),'POLICY_AND_TRUSTED_PIN_REQUIRED')
        p=read_source_policy(args.policy,trusted_sha256=args.trusted_sha256)
        print(json.dumps({k:v for k,v in p.items() if k!='registry'},sort_keys=True));return 0
    except (ValueError,KeyError,TypeError,OSError):print('ABSTAIN: SOURCE_POLICY_NOT_VERIFIED');return 1


if __name__=='__main__':raise SystemExit(main())
