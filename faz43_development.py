"""Explicit development-only /analyze and manual day plans. No bot startup.

Does not import main, read credentials, send messages itself, install timers or
activate storage. Registration needs a stopped DEVELOPMENT app and chat allowlist.
"""
import asyncio
from copy import deepcopy
from datetime import datetime
import html
import re
import time
import unicodedata
from zoneinfo import ZoneInfo

from telegram.ext import CommandHandler
from core.elite_league_registry import normalize_league_input
from faz40_archive import require,LEAGUES
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz42_schedule import validate_schedule
from faz42_snapshot import build_snapshot,validate_snapshot


def parse_request(text):
    require(type(text) is str and len(text)<=320,'INVALID_COMMAND_LENGTH')
    parts=text.split();require(len(parts)>=6 and parts[0].split('@')[0].lower()=='/analyze','INVALID_ANALYZE_COMMAND')
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',parts[2]) is not None,'INVALID_REQUEST_DATE')
    try:datetime.strptime(parts[2],'%Y-%m-%d')
    except ValueError as ex:raise ValueError('INVALID_REQUEST_DATE') from ex
    rest=parts[3:];separators=[i for i,v in enumerate(rest) if v.casefold()=='vs'];require(len(separators)==1,'ONE_VS_SEPARATOR_REQUIRED')
    index=separators[0];home=' '.join(rest[:index]);away=' '.join(rest[index+1:])
    require(home and away and home.casefold()!=away.casefold(),'DISTINCT_TEAM_NAMES_REQUIRED')
    return dict(league=normalize_league_input(parts[1]),date=parts[2],home=home,away=away)


def _key(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())


def _abstain(reason,request=None):
    safe=reason if type(reason) is str and re.fullmatch('[A-Z][A-Z0-9_]{0,95}',reason) else 'INVALID_SOURCE_DATA'
    return dict(status='ABSTAIN',reason=safe,request=request,snapshot=None,prospective_records_created=0,storage_status='NOT_ACTIVATED')


def _alias_directory(schedule):
    p=schedule['payload'];valid={pid for r in p['fixtures'] for pid in r['provider_fixture_ids']};aliases={}
    if p['provider']=='ESPN':
        teams=[c['team'] for e in p['raw']['events'] if e.get('id') in valid for c in e['competitions'][0]['competitors']]
        rows=[(t['id'],[t.get(k) for k in ('id','displayName','shortDisplayName','name','abbreviation')]) for t in teams]
    else:
        teams=[e[side]['club'] for e in p['raw']['data'] if e.get('identifier') in valid for side in ('local','road')]
        rows=[(t['code'],[t['code'],t.get('name')]) for t in teams]
    for tid,names in rows:
        for name in names:
            if type(name) is str and name.strip():aliases.setdefault(_key(name),set()).add(tid)
    return aliases


class DevelopmentAnalysisService:
    def __init__(self,backend=None,*,mode='DEVELOPMENT',allow_synthetic=False,registry=REGISTRY,registry_pin=REGISTRY_PIN,clock=None,timeout_seconds=5):
        require(mode=='DEVELOPMENT' and type(allow_synthetic) is bool,'DEVELOPMENT_MODE_REQUIRED')
        require(type(timeout_seconds) in (int,float) and 0<timeout_seconds<=15,'BOUNDED_BACKEND_TIMEOUT_REQUIRED')
        self.backend=backend;self.mode=mode;self.allow_synthetic=allow_synthetic;self.registry=registry;self.pin=registry_pin
        self.clock=clock or (lambda:int(time.time()));self.timeout=timeout_seconds;self.cache={};self.query_cache={}

    def _today(self):return datetime.fromtimestamp(self.clock(),ZoneInfo('Europe/Istanbul')).date().isoformat()

    async def _load(self,league,day):
        return await asyncio.wait_for(self.backend.load_inputs(league,day),timeout=self.timeout)

    def for_delivery(self,result):
        if result['status']!='PREDICTED_EXPERIMENTAL':return deepcopy(result)
        try:
            require(self.mode=='DEVELOPMENT','DEVELOPMENT_MODE_REQUIRED')
            p=validate_snapshot(result['snapshot'],registry=self.registry,registry_pin=self.pin)
            require(self.allow_synthetic or p['usage']!='SYNTHETIC_TEST','SYNTHETIC_SOURCE_REFUSED')
            require(type(self.clock()) is int and self.clock()>=p['created_utc'],'DELIVERY_CLOCK_REVERSED')
            require(self.clock()<p['fixture']['start_utc'],'ALREADY_STARTED')
            require(self.clock()<=p['cutoff_utc']+60,'SNAPSHOT_STALE_NO_REGENERATION')
            require(0<=self.clock()-p['schedule']['payload']['observed_at_utc']<=300,'STALE_SCHEDULE_AT_DELIVERY')
            providers={p['schedule']['payload']['provider']}|{o['payload']['provider'] for o in p['history']}
            for provider in providers:
                policy=self.registry[provider]
                require(policy['usage']=='PERMITTED' and policy['reviewed_at_utc']<self.clock()<=policy['expires_at_utc'],
                        'SOURCE_PERMISSION_EXPIRED_AT_DELIVERY')
            return deepcopy(result)
        except (ValueError,KeyError,TypeError) as ex:return _abstain(str(ex),result.get('request'))

    def _prepare(self,request,inputs):
        try:
            require(self.mode=='DEVELOPMENT','DEVELOPMENT_MODE_REQUIRED')
            require(type(inputs) is dict and set(inputs)=={'schedules','history','model'} and type(inputs['schedules']) is list and type(inputs['history']) is list,'BACKEND_INPUT_SCHEMA')
            cutoff=self.clock();candidates={}
            for schedule in inputs['schedules']:
                p=validate_schedule(schedule,cutoff_utc=cutoff,maximum_age_seconds=300,require_permitted=False,registry=self.registry,registry_pin=self.pin)
                require(p['league']==request['league'],'CROSS_LEAGUE_SCHEDULE')
                require(self.allow_synthetic or p['usage']!='SYNTHETIC_TEST','SYNTHETIC_SOURCE_REFUSED')
                aliases=_alias_directory(schedule)
                home=aliases.get(_key(request['home']),set());away=aliases.get(_key(request['away']),set())
                require(len(home)<=1 and len(away)<=1,'AMBIGUOUS_TEAM_ALIAS')
                if not home or not away:continue
                for item in p['fixtures']:
                    f=item['fixture'];day=datetime.fromtimestamp(f['start_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()
                    if day==request['date'] and f['home_team_id'] in home and f['away_team_id'] in away:
                        candidates.setdefault(f['canonical_id'],(f,schedule))
            require(candidates,'NO_VERIFIED_FIXTURE_MATCH');require(len(candidates)==1,'AMBIGUOUS_FIXTURE_MATCH')
            cid,(f,schedule)=next(iter(candidates.items()))
            if cid in self.cache:return self.for_delivery(dict(status='PREDICTED_EXPERIMENTAL',request=request,snapshot=deepcopy(self.cache[cid]),prospective_records_created=0,storage_status='EPHEMERAL_DEVELOPMENT_CACHE'))
            snapshot=build_snapshot(inputs['history'],schedule,cid,inputs['model'],cutoff_utc=cutoff,registry=self.registry,registry_pin=self.pin)
            p=snapshot['payload']
            if p['status']=='ABSTAIN':return _abstain(p['abstain_reason'],request)
            result=dict(status=p['status'],request=request,snapshot=snapshot,prospective_records_created=0,storage_status='EPHEMERAL_DEVELOPMENT_CACHE')
            result=self.for_delivery(result)
            if result['status']=='PREDICTED_EXPERIMENTAL':self.cache[cid]=deepcopy(snapshot)
            return result
        except (ValueError,KeyError,TypeError,AttributeError) as ex:return _abstain(str(ex),request)

    async def analyze(self,text):
        if self.mode!='DEVELOPMENT':return _abstain('DEVELOPMENT_MODE_REQUIRED')
        try:request=parse_request(text)
        except ValueError as ex:return _abstain(str(ex))
        if request['league'] not in LEAGUES:return _abstain('LEAGUE_ADAPTER_UNAVAILABLE',request)
        if request['date']<self._today():return _abstain('HISTORICAL_REQUEST_NOT_ALLOWED',request)
        query=tuple(_key(request[k]) for k in ('league','date','home','away'))
        if query in self.query_cache:
            cid=self.query_cache[query]
            return self.for_delivery(dict(status='PREDICTED_EXPERIMENTAL',request=request,snapshot=deepcopy(self.cache[cid]),prospective_records_created=0,storage_status='EPHEMERAL_DEVELOPMENT_CACHE'))
        if self.backend is None:return _abstain('DEVELOPMENT_SOURCE_NOT_CONFIGURED',request)
        try:inputs=await self._load(request['league'],request['date'])
        except (asyncio.TimeoutError,TimeoutError):return _abstain('SOURCE_TIMEOUT',request)
        except Exception:return _abstain('SOURCE_UNAVAILABLE',request)
        result=self._prepare(request,inputs)
        if result['status']=='PREDICTED_EXPERIMENTAL':self.query_cache[query]=result['snapshot']['payload']['fixture']['canonical_id']
        return result

    async def prepare_day(self,day):
        if self.mode!='DEVELOPMENT':return dict(status='ABSTAIN',reason='DEVELOPMENT_MODE_REQUIRED',plans=[],prospective_records_created=0)
        try:parse_request('/analyze NBA '+day+' 19 vs 2')
        except (ValueError,TypeError):return dict(status='ABSTAIN',reason='INVALID_REQUEST_DATE',plans=[],prospective_records_created=0)
        if day<self._today() or self.backend is None:return dict(status='ABSTAIN',reason='DEVELOPMENT_DAY_SOURCE_UNAVAILABLE',plans=[],prospective_records_created=0)
        plans=[];seen=set()
        for league in LEAGUES:
            try:
                inputs=await self._load(league,day);require(type(inputs) is dict,'BACKEND_INPUT_SCHEMA')
                for schedule in inputs['schedules']:
                    p=validate_schedule(schedule,cutoff_utc=self.clock(),require_permitted=False,registry=self.registry,registry_pin=self.pin)
                    require(p['league']==league,'CROSS_LEAGUE_SCHEDULE')
                    for item in p['fixtures']:
                        f=item['fixture'];cid=f['canonical_id'];local=datetime.fromtimestamp(f['start_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()
                        if local!=day or cid in seen:continue
                        require(len(seen)<100,'DAY_FIXTURE_LIMIT');seen.add(cid)
                        req=dict(league=league,date=day,home=f['home_team_id'],away=f['away_team_id'])
                        result=self._prepare(req,inputs);result['canonical_id']=cid;plans.append(result)
            except Exception:plans.append(dict(status='ABSTAIN',reason='DAY_SOURCE_UNAVAILABLE',league=league))
        return dict(status='DEVELOPMENT_DAY_PLAN_NOT_RECORDED',plans=plans,unique_fixture_plans=len(seen),
            prospective_records_created=0,scheduler_status='NOT_INSTALLED',storage_status='NOT_ACTIVATED')


def render_analysis(result):
    header='<b>GELİŞTİRME — kalıcı kayıt yapılmadı</b>'
    if result['status']!='PREDICTED_EXPERIMENTAL':
        return header+'\nABSTAIN: '+html.escape(result.get('reason','SOURCE_UNAVAILABLE'))+'\nDoğrulanabilir veri/izin/model olmadan skor üretilmedi.'
    p=result['snapshot']['payload'];q=p['prediction'];f=p['fixture'];req=result['request'];sim=p['simulation']
    lines=['Dönem     Ev    Dep    Toplam']
    for i in range(4):
        h=q['home']['quarters'][i];a=q['away']['quarters'][i];lines.append(f'{i+1}Q      {h:6.2f} {a:6.2f} {h+a:7.2f}')
    for label,key in [('1H','first_half'),('2H','second_half'),('NORMAL','total')]:
        h=q['home'][key];a=q['away'][key];lines.append(f'{label:6} {h:6.2f} {a:6.2f} {h+a:7.2f}')
    utc=datetime.fromtimestamp(p['cutoff_utc'],ZoneInfo('UTC')).isoformat()
    synthetic='\n<b>SENTETİK TEST — gerçek tahmin performansı değildir</b>' if p['usage']=='SYNTHETIC_TEST' else '\nDeneysel dry-run; gerçek tahmin kaydı değildir.'
    title=html.escape(req['league']+' '+req['date']+' '+req['home']+' vs '+req['away'])
    text=header+synthetic+'\n'+title+'\n<pre>'+html.escape('\n'.join(lines))+'</pre>'
    text+=f'\nEv sahibi farkı: {q["home_margin"]:+.2f}\nNormal süre (uzatma hariç): ev %{sim["probabilities"][0]*100:.2f}, dep %{sim["probabilities"][1]*100:.2f}, beraberlik %{sim["probabilities"][2]*100:.2f}'
    text+='\nKalibrasyon: yapılmadı.\nMonte Carlo: '+str(sim['simulations'])+'; tohum: '+str(sim['seed'])
    text+='\nCutoff UTC: '+utc+'\nModel SHA: '+p['model_manifest']['payload']['git_sha']+'\nKaynak digest: '+p['source_digest']
    text+='\nEksikler: '+html.escape(', '.join(p['missing']))
    return text if len(text)<=3800 else header+'\nABSTAIN: OUTPUT_TOO_LONG'


def register_development_analyze(application,service,*,allowed_chat_ids):
    require(isinstance(service,DevelopmentAnalysisService) and service.mode=='DEVELOPMENT','DEVELOPMENT_SERVICE_REQUIRED')
    require(application.bot_data.get('deployment_scope')=='DEVELOPMENT' and not getattr(application,'running',False),'STOPPED_DEVELOPMENT_APP_REQUIRED')
    require(type(allowed_chat_ids) in (set,frozenset) and allowed_chat_ids and all(type(v) is int and v!=0 for v in allowed_chat_ids),'EXPLICIT_DEVELOPMENT_CHAT_ALLOWLIST_REQUIRED')
    for handlers in getattr(application,'handlers',{}).values():
        require(not any('analyze' in getattr(h,'commands',set()) for h in handlers),'EXISTING_ANALYZE_HANDLER_REFUSED')
    chats=frozenset(allowed_chat_ids)
    async def callback(update,context):
        if context.application is not application or application.bot_data.get('deployment_scope')!='DEVELOPMENT' or service.mode!='DEVELOPMENT':return
        chat=getattr(update,'effective_chat',None);message=getattr(update,'effective_message',None)
        if chat is None or type(chat.id) is not int or chat.id not in chats or message is None:return
        result=service.for_delivery(await service.analyze(message.text or ''))
        # Recheck after awaiting data/model work; runtime scope/chat may change.
        if context.application is not application or application.bot_data.get('deployment_scope')!='DEVELOPMENT' or service.mode!='DEVELOPMENT':return
        chat=getattr(update,'effective_chat',None)
        if chat is None or type(chat.id) is not int or chat.id not in chats:return
        await message.reply_text(render_analysis(result),parse_mode='HTML',disable_web_page_preview=True)
    handler=CommandHandler('analyze',callback);application.add_handler(handler);return handler


class FrozenInputsBackend:
    """Read-only, explicitly pinned development bundles; no source permission grant."""
    def __init__(self,sealed,*,trusted_sha256):
        from prediction_inputs import digest
        require(type(sealed) is dict and set(sealed)=={'payload','sha256'} and sealed['sha256']==trusted_sha256 and
                digest(sealed['payload'])==trusted_sha256,'TRUSTED_INPUT_BUNDLE_PIN_MISMATCH')
        p=sealed['payload'];require(set(p)=={'format','partitions'} and p['format']=='FAZ43_DEVELOPMENT_INPUT_BUNDLE_V1' and
                                   type(p['partitions']) is dict and len(p['partitions'])<=30,'DEVELOPMENT_INPUT_BUNDLE_SCHEMA')
        for key,inputs in p['partitions'].items():
            require(type(key) is str and ':' in key,'INPUT_PARTITION_REQUIRED')
            league,day=key.split(':',1)
            require(league in LEAGUES and parse_request('/analyze '+league+' '+day+' A vs B')['date']==day,'INPUT_PARTITION_REQUIRED')
            require(type(inputs) is dict and set(inputs)=={'schedules','history','model'},'BACKEND_INPUT_SCHEMA')
        self.partitions=deepcopy(p['partitions'])

    @classmethod
    def from_file(cls,path,*,trusted_sha256):
        import json
        from pathlib import Path
        p=Path(path);require(not p.is_symlink() and Path('/data') not in p.resolve().parents and p.is_file() and
                             p.stat().st_size<=8_000_000,'READONLY_DEVELOPMENT_BUNDLE_REQUIRED')
        return cls(json.loads(p.read_text()),trusted_sha256=trusted_sha256)

    async def load_inputs(self,league,day):return deepcopy(self.partitions.get(league+':'+day))


def main():
    import argparse
    import json
    parser=argparse.ArgumentParser(description=__doc__);choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--request');choice.add_argument('--day');parser.add_argument('--inputs');parser.add_argument('--trusted-bundle-sha256')
    parser.add_argument('--allow-synthetic',action='store_true');parser.add_argument('--source-policy');parser.add_argument('--trusted-policy-sha256');args=parser.parse_args()
    try:
        require(bool(args.inputs)==bool(args.trusted_bundle_sha256),'INPUT_FILE_AND_TRUSTED_PIN_REQUIRED_TOGETHER')
        require(bool(args.source_policy)==bool(args.trusted_policy_sha256),'POLICY_FILE_AND_TRUSTED_PIN_REQUIRED_TOGETHER')
        policy={};bundle_policy={}
        if args.source_policy:
            from faz44_policy import read_source_policy
            loaded=read_source_policy(args.source_policy,trusted_sha256=args.trusted_policy_sha256)
            policy=dict(registry=loaded['registry'],registry_pin=loaded['registry_sha256'])
            bundle_policy=dict(policy_bundle_sha256=loaded['policy_bundle_sha256'])
        from faz44_inputs import read_development_inputs
        backend=None if not args.inputs else read_development_inputs(args.inputs,trusted_sha256=args.trusted_bundle_sha256,**policy,**bundle_policy)
        service=DevelopmentAnalysisService(backend,allow_synthetic=args.allow_synthetic,**policy)
        if args.request:print(render_analysis(asyncio.run(service.analyze(args.request))))
        else:
            r=asyncio.run(service.prepare_day(args.day))
            for row in r['plans']:
                snapshot=row.pop('snapshot',None)
                if snapshot is not None:row['snapshot_sha256']=snapshot['sha256']
            print(json.dumps(r,sort_keys=True,allow_nan=False))
        return 0
    except (ValueError,TypeError,KeyError,OSError):
        print('ABSTAIN: INVALID_DEVELOPMENT_INPUT_BUNDLE');return 1


if __name__=='__main__':raise SystemExit(main())
