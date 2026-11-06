"""Opt-in public research collection of player/PBP evidence for existing games.

python -m faz45_collection --help
Default: no network, no rights grant, no prediction or scheduler activation.
Archives, prior predictions and production are never written or started.
"""
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import re
import time

from prediction_inputs import digest
from faz40_archive import require
from faz40_archive_audit import file_sha
from faz41_adapters import capture,normalize
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz41_transport import fetch
from faz42_history import _validated
from faz43_pbp import capture_espn_timeline
from faz44_inputs import read_development_inputs,publish_development_artifact,MAX_BYTES
from faz45_support import kind,validate_support,support_report
from nba_research_store import compact_summary

FORMAT='FAZ45_SUPPORT_EVIDENCE_V1'


def _compact_players(raw):
    out=compact_summary(raw);blocks=[]
    for b in raw['boxscore']['players']:
        require(len(b['statistics'])==1,'AMBIGUOUS_PLAYER_STAT_BLOCK')
        stats=b['statistics'][0];labels=stats['labels'];require(len(labels)==len(set(labels)),'PLAYER_LABELS_REQUIRED')
        indices=[labels.index(k) for k in ('MIN','PTS')];athletes=[]
        for a in stats['athletes']:
            athletes.append(dict(athlete=dict(id=a['athlete']['id']),didNotPlay=a['didNotPlay'],starter=a['starter'],
                stats=[] if a['didNotPlay'] else [a['stats'][i] for i in indices]))
        blocks.append(dict(team=dict(id=b['team']['id']),statistics=[dict(labels=['MIN','PTS'],athletes=athletes)]))
    out.setdefault('boxscore',{})['players']=blocks
    return out


def _compact_timeline(raw):
    out=compact_summary(raw)
    out['plays']=[{k:deepcopy(p[k]) for k in ('id','sequenceNumber','period','clock','homeScore','awayScore','team','wallclock','type') if k in p} for p in raw['plays']]
    # Type labels/text, participant names and provider prose are not needed.
    for p in out['plays']:p['type']={'id':p['type']['id']}
    return out


def collect_support(scores,identities,*,live=False,collector=fetch,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    require(type(identities) is list and 1<=len(identities)<=6 and len(identities)==len(set(identities)),'ONE_TO_SIX_UNIQUE_SOURCE_GAMES_REQUIRED')
    rows=_validated(scores,int(time.time()),registry,registry_pin);available={}
    for o,p in rows:
        require(p['data_type']=='OFFICIAL_STAT' and p['usage']!='SYNTHETIC_TEST','REAL_RESEARCH_SCORE_INPUTS_REQUIRED')
        key=p['provider']+':'+p['provider_fixture_id'];available.setdefault(key,(o,p))
    require(set(identities)<=set(available),'GAME_NOT_IN_REPLAYED_SCORE_INPUTS')
    if live is not True:return dict(status='ABSTAIN_LIVE_SUPPORT_NOT_REQUESTED',observations=[],receipts=[],rejected=[],network_requests=0,prospective_records_created=0)
    observations=[];receipts=[];rejected=[]
    for identity in identities:
        score,p=available[identity];provider=p['provider'];f=p['fixture']
        require(provider in ('ESPN','EUROLEAGUE_LIVE'),'SUPPORT_PROVIDER_NOT_IMPLEMENTED')
        url=p['source_url']+('/stats' if provider=='EUROLEAGUE_LIVE' else '')
        response=collector(url,provider=provider,registry=registry,registry_pin=registry_pin)
        receipt={k:v for k,v in response.items() if k!='payload'};receipt['identity']=identity;receipts.append(receipt)
        if response['status']!='DOCUMENT_RECEIVED':continue
        require(response['source_url']==url and response['provider']==provider,'SUPPORT_RECEIPT_SOURCE_MISMATCH')
        raw=response['payload'];observed=response['observed_at_utc'];receipt['response_sha256']=digest(raw)
        lineage=dict(score_observation_sha256=score['sha256'],response_sha256=digest(raw),source_observed_at_utc=observed,
            usage='CAPTURED_NOW_RETROSPECTIVE_NOT_ORIGINAL_PREMATCH_INPUT')
        for label in (('PLAYER_MINUTES','PBP_TIMELINE') if provider=='ESPN' else ('PLAYER_MINUTES',)):
            try:
                if provider=='ESPN':body=_compact_players(raw) if label=='PLAYER_MINUTES' else _compact_timeline(raw)
                else:body=dict(game=deepcopy(p['raw']),stats=deepcopy(raw))
                body['_faz45_derivation']=deepcopy(lineage)
                n=normalize(body['game'] if provider=='EUROLEAGUE_LIVE' else body,provider=provider,league=f['league'],
                    season_end_year=f['season_end_year'],observed_at_utc=observed,data_type='OFFICIAL_STAT')
                require(n['fixture']==f and n['claims']==p['claims'],'COLLECTED_SUPPORT_SCORE_CONFLICT')
                if label=='PBP_TIMELINE':o=capture_espn_timeline(body,observed_at_utc=observed,ingested_at_utc=int(time.time()),registry=registry,registry_pin=registry_pin)
                else:o=capture(body,provider=provider,league=f['league'],season_end_year=f['season_end_year'],
                    data_type='PLAYER_MINUTES',observed_at_utc=observed,ingested_at_utc=int(time.time()),registry=registry,registry_pin=registry_pin)
                observations.append(o)
            except (ValueError,KeyError,TypeError,IndexError) as ex:
                rejected.append(dict(identity=identity,kind=label,reason=str(ex) if type(ex) is ValueError else 'MALFORMED_SUPPORT_DOCUMENT'))
    return dict(status='SUPPORT_RESEARCH_COLLECTION_NOT_PREDICTION',observations=observations,receipts=receipts,rejected=rejected,
        network_requests=len(receipts),prospective_records_created=0)


def seal_support_bundle(collection,score_input_sha256,scores,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    p=dict(format=FORMAT,schema_version=1,usage='RETROSPECTIVE_SUPPORT_RESEARCH',created_at_utc=int(time.time()),
        score_input_sha256=score_input_sha256,registry_sha256=registry_pin,
        observations={o['sha256']:deepcopy(o) for o in collection['observations']},
        receipts=deepcopy(collection['receipts']),rejected=deepcopy(collection['rejected']),prospective_records_created=0)
    sealed=dict(payload=p,sha256=digest(p))
    validate_support_bundle(sealed,trusted_sha256=sealed['sha256'],score_input_sha256=score_input_sha256,scores=scores,registry=registry,registry_pin=registry_pin)
    return sealed


def validate_support_bundle(sealed,*,trusted_sha256,score_input_sha256,scores,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and sealed['sha256']==trusted_sha256 and digest(sealed['payload'])==trusted_sha256,'TRUSTED_SUPPORT_PIN_MISMATCH')
    p=sealed['payload'];require(type(p) is dict and set(p)==set('format schema_version usage created_at_utc score_input_sha256 registry_sha256 observations receipts rejected prospective_records_created'.split()) and
        type(p['schema_version']) is int and p['schema_version']==1 and p['format']==FORMAT and p['usage']=='RETROSPECTIVE_SUPPORT_RESEARCH' and
        p['prospective_records_created']==0 and type(p['observations']) is dict and type(p['receipts']) is list and type(p['rejected']) is list,'SUPPORT_BUNDLE_SCHEMA')
    require(type(p['created_at_utc']) is int and 0<p['created_at_utc']<=int(time.time()),'SUPPORT_BUNDLE_CLOCK')
    require(p['score_input_sha256']==score_input_sha256 and p['registry_sha256']==registry_pin==digest(registry),'SUPPORT_SCORE_POLICY_BINDING')
    require(all(h==o['sha256'] for h,o in p['observations'].items()),'SUPPORT_OBSERVATION_REFERENCE')
    observations=list(p['observations'].values())
    validate_support(scores,observations,asof_utc=p['created_at_utc'],registry=registry,registry_pin=registry_pin)
    parents={s['sha256']:s['payload'] for s in scores}
    for o in observations:
        row=o['payload'];raw=row['raw']['summary'] if kind(o)=='PBP_TIMELINE' else row['raw'];lineage=raw.get('_faz45_derivation')
        require(type(lineage) is dict and set(lineage)=={'score_observation_sha256','response_sha256','source_observed_at_utc','usage'} and
            lineage['usage']=='CAPTURED_NOW_RETROSPECTIVE_NOT_ORIGINAL_PREMATCH_INPUT' and lineage['score_observation_sha256'] in parents and
            parents[lineage['score_observation_sha256']]['fixture']==row['fixture'] and type(lineage['response_sha256']) is str and
            re.fullmatch('[0-9a-f]{64}',lineage['response_sha256']) and lineage['source_observed_at_utc']==row['observed_at_utc'],'SUPPORT_DERIVATION_BINDING_REQUIRED')
        require(any(r.get('status')=='DOCUMENT_RECEIVED' and r.get('source_url')==row['source_url'] and r.get('provider')==row['provider'] and
            r.get('observed_at_utc')==row['observed_at_utc'] and r.get('response_sha256')==lineage['response_sha256'] for r in p['receipts']),
            'SUPPORT_COMPLETED_RECEIPT_REQUIRED')
    return deepcopy(p)


def read_support_bundle(path,**validation):
    p=Path(path);require(p.is_file() and not p.is_symlink() and Path('/data') not in p.resolve().parents and p.stat().st_size<=MAX_BYTES,'READONLY_SUPPORT_BUNDLE_REQUIRED')
    return validate_support_bundle(json.loads(p.read_text()),**validation)


def main():
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--score-inputs',required=True);a.add_argument('--trusted-score-sha256',required=True)
    mode=a.add_mutually_exclusive_group(required=True);mode.add_argument('--collect',action='store_true');mode.add_argument('--audit',action='store_true')
    a.add_argument('--live',action='store_true');a.add_argument('--identities',nargs='+');a.add_argument('--output')
    a.add_argument('--support-inputs');a.add_argument('--trusted-support-sha256');a.add_argument('--target-canonical-id');a.add_argument('--cutoff-utc',type=int)
    a.add_argument('--source-policy');a.add_argument('--trusted-policy-sha256');args=a.parse_args()
    try:
        require(bool(args.source_policy)==bool(args.trusted_policy_sha256),'SOURCE_POLICY_PAIR_REQUIRED')
        policy=dict(registry=REGISTRY,registry_pin=REGISTRY_PIN);policy_ref=None
        if args.source_policy:
            from faz44_policy import read_source_policy
            loaded=read_source_policy(args.source_policy,trusted_sha256=args.trusted_policy_sha256)
            policy=dict(registry=loaded['registry'],registry_pin=loaded['registry_sha256']);policy_ref=loaded['policy_bundle_sha256']
        before=file_sha(args.score_inputs);backend=read_development_inputs(args.score_inputs,trusted_sha256=args.trusted_score_sha256,policy_bundle_sha256=policy_ref,**policy)
        require(backend.payload.get('format')=='FAZ44_INDEXED_DEVELOPMENT_INPUTS_V1','INDEXED_SCORE_INPUT_REQUIRED');scores=list(backend.payload['sources'].values())
        if args.collect:
            require(args.identities and args.output and not any((args.support_inputs,args.trusted_support_sha256,args.target_canonical_id)) and args.cutoff_utc is None,'COLLECTION_CONFIGURATION')
            collected=collect_support(scores,args.identities,live=args.live,**policy)
            if collected['observations'] and int(time.time())<=max(o['payload']['materialized_at_utc'] for o in collected['observations']):time.sleep(1.05)
            sealed=seal_support_bundle(collected,args.trusted_score_sha256,scores,**policy)
            require(file_sha(args.score_inputs)==before,'SCORE_INPUT_FILE_CHANGED')
            created=publish_development_artifact(args.output,sealed,expected_format=FORMAT,filename_prefix='faz45-support-')
            out=dict(status=collected['status'],trusted_support_sha256=sealed['sha256'],path=str(Path(args.output).resolve()),created=created,
                network_requests=collected['network_requests'],observations_by_kind=dict(Counter(kind(o) for o in collected['observations'])),
                rejected=collected['rejected'],prospective_records_created=0,score_inputs_unchanged=True,storage='LOCAL_RESEARCH_FILE_ONLY',scheduler='NOT_INSTALLED')
        else:
            require(args.support_inputs and args.trusted_support_sha256 and args.target_canonical_id and not any((args.live,args.identities,args.output)),'AUDIT_CONFIGURATION')
            p=read_support_bundle(args.support_inputs,trusted_sha256=args.trusted_support_sha256,score_input_sha256=args.trusted_score_sha256,scores=scores,**policy)
            fixtures={o['payload']['fixture']['canonical_id']:o['payload']['fixture'] for o in scores}
            for s in backend.payload['schedules'].values():fixtures.update({r['fixture']['canonical_id']:r['fixture'] for r in s['payload']['fixtures']})
            require(args.target_canonical_id in fixtures,'TARGET_NOT_IN_SCORE_INPUT_BUNDLE')
            out=support_report(scores,list(p['observations'].values()),fixtures[args.target_canonical_id],cutoff_utc=args.cutoff_utc if args.cutoff_utc is not None else int(time.time()),**policy)
            require(file_sha(args.score_inputs)==before,'SCORE_INPUT_FILE_CHANGED')
        print(json.dumps(out,sort_keys=True,allow_nan=False));return 0
    except (ValueError,KeyError,TypeError,OSError,AttributeError) as ex:
        print(json.dumps(dict(status='ABSTAIN_SUPPORT_OPERATION_NOT_CONFIRMED',reason=str(ex) if type(ex) is ValueError else type(ex).__name__,prospective_records_created=0)));return 1


if __name__=='__main__':raise SystemExit(main())
