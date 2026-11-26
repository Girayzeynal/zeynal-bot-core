"""Read-only descriptive settlement of durably recorded native market directions.

Only the exact local decision, historical provider receipts, configured rule
pin and verified final may enter. No backfill, selections or calibration claims.
"""
from collections import Counter,defaultdict
import json
import math
import time

from core.team_identity import digest
from hybrid_engine.current_market_review import admit_odds,fixture_journal_directory
from hybrid_engine.data import local_path,Abstain
from hybrid_engine.decision_layer import RuleEvidence,settled_value,POLICY
from hybrid_engine.provider_identity import archived_price_clock
from hybrid_engine.provider_bridge import odds_observations,fixture_for
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.unified_results_view import unwrap,normalized_rows
from hybrid_engine.market_sample_evidence import replay,contract_mass

MAX_FILES=1024
MAX_BYTES=32*1024*1024
MAX_FILE_BYTES=2*1024*1024
ERRORS=(ValueError,KeyError,TypeError,OSError,RuntimeError,Abstain,AttributeError,IndexError)

def require(ok,reason):
    if not ok:raise ValueError(reason)

def read_wrapper(path,maximum=MAX_FILE_BYTES):
    path=local_path(path)
    require(path.stat().st_size<=maximum,'MARKET_REVIEW_FILE_LIMIT')
    w=json.loads(path.read_text())
    require(digest(w['payload'])==w['sha256'],'MARKET_REVIEW_PIN')
    return w

def audit_batch(path,bridge,labels,*,candidate_lookup=None,now=None):
    now=int(time.time()) if now is None else now
    require(type(now) is int and 0<now<=int(time.time()),'MARKET_AUDIT_ACTUAL_CLOCK')
    w=read_wrapper(path);p=w['payload'];key=w['manifest_sha256']
    manifest={k:v for k,v in p.items() if k not in ('recorded_at_utc','record_class','eligible_for_current_prematch_metrics')}
    require(path.name=='review-'+key+'.json' and digest(manifest)==key and
            p['format']=='CURRENT_MARKET_REVIEW_BATCH_V1','MARKET_REVIEW_MANIFEST_PIN')
    require('native_price_context' in p,'LEGACY_PRICE_CONTEXT_MISSING')
    native=p['native_price_context'];evaluation=p.get('evaluation_context',native)
    f=fixture_for(native)
    require(f==fixture_for(evaluation) and digest(evaluation)==p['original_snapshot_sha256'] and
            evaluation['intervals']['sample_sha256']==p['sample_sha256'] and
            evaluation['prediction_generated_at_utc']==p['prediction_utc'] and
            p['forecast_changed'] is False and p['eligible_for_original_forecast_metrics'] is False,
            'MARKET_MODEL_CONTEXT_CONFLICT')
    require(p['record_class']=='PREGAME_CURRENT_REVIEW','NON_PREMATCH_REVIEW')
    proof_path=path.parent/('market-commit-'+key+'.json')
    require(proof_path.is_file(),'MARKET_DURABLE_COMMIT_MISSING')
    proof=read_wrapper(proof_path,65536)['payload']
    completed=proof['completed_at_utc'];decision=p['decision_utc'];archived=p['recorded_at_utc']
    require(proof['format']=='CURRENT_MARKET_DURABLE_COMMIT_V1' and
            proof['batch_sha256']==w['sha256'] and proof['manifest_sha256']==key and proof['eligible'] is True and
            all(type(v) is int for v in (p['prediction_utc'],decision,archived,completed)) and
            0<p['prediction_utc']<=decision<=archived<=completed<f['tipoff_utc']-PREMATCH_MINIMUM_LEAD_SECONDS and completed<=now,
            'MARKET_PREMATCH_COMMIT_CLOCK')
    original=native.get('original_forecast_sha256',digest(native))
    require(not p.get('forecast_record_type') or p['linked_original_snapshot_sha256']==original,
            'MARKET_ORIGINAL_LINK_CONFLICT')
    matches=[r for r in labels if r['snapshot_sha256']==original and
             (r['league'],r['season'],r['fixture_id'],r['fixture_start_utc'])==
             (f['league'],f['season'],f['fixture_id'],f['tipoff_utc']) and
             r.get('actual') is not None and not r.get('legacy_publication_clock_unrecorded') and
             r.get('eligible_for_live_performance') is not False]
    require(bool(matches),'VERIFIED_FINAL_OR_ORIGINAL_MISSING')
    # Europe rows share one original snapshot, but each component has its own sample pin.
    suitable=[r for r in matches if (r.get('intervals') or {}).get('sample_sha256')==
              native['intervals']['sample_sha256']]
    require(bool(suitable),'ORIGINAL_SAMPLE_NOT_VERIFIED')
    result=suitable[0]
    require(all(r['actual_periods']==result['actual_periods'] and r['actual']==result['actual']
                and r['final_with_ot']==result['final_with_ot'] for r in matches),
            'CONFLICTING_NATIVE_FINALS')
    first_deadline=p['prediction_utc'] if p.get('forecast_record_type') else decision
    require(type(result.get('first_archived_at_utc')) is int and
            type(result.get('prediction_generated_at_utc')) is int and
            result['prediction_generated_at_utc']==native['prediction_generated_at_utc'] and
            0<result['prediction_generated_at_utc']<=result['first_archived_at_utc']<=first_deadline and
            type(result.get('label_available_utc')) is int and f['tipoff_utc']<result['label_available_utc']<=now and
            (f['league']!='NBA' or result.get('model_digest')==native['model_digest']),
            'ORIGINAL_OR_FINAL_CLOCK_UNVERIFIED')
    periods=result['actual_periods']
    # Verify regulation and full score agreement, valid preceding OT ties and
    # a completed, non-tied full result before classifying any direction.
    settled_value(periods,'FULL','TOTAL',include_overtime=True)
    require([sum(periods[s][:4]) for s in ('home','away')]==result['actual'] and
            [sum(periods[s]) for s in ('home','away')]==result['final_with_ot'] and
            result['final_with_ot'][0]!=result['final_with_ot'][1],'NATIVE_FINAL_SCORE_CONFLICT')
    if p.get('forecast_record_type'):
        require(candidate_lookup is not None,'CANDIDATE_ARCHIVE_UNAVAILABLE')
        candidate_lookup(p,evaluation,completed)
    else:
        require(digest(evaluation)==digest(native) and p['prediction_utc']==result['prediction_generated_at_utc'],
                'FIRST_MODEL_REVIEW_CONTEXT_CONFLICT')
    rules=bridge.rule_book.rules(decision)
    parsed={};rows=[];excluded=Counter();sample_paths=None
    for review in p['reviews']:
        require(review['fixture']==f and review['decision_utc']==decision and
                review['prediction_utc']==p['prediction_utc'] and
                review['model_version']==evaluation['model_version'] and
                review['model_digest']==evaluation['model_digest'] and
                review['policy_sha256']==p['policy_sha256'],'MARKET_REVIEW_SCOPE_CONFLICT')
        source=review['source'];clock=source['event_clock_binding'];cp=clock['payload']
        require(digest(cp)==clock['sha256'] and cp['original_snapshot_sha256']==digest(native) and
                completed<cp['prematch_deadline_utc']-PREMATCH_MINIMUM_LEAD_SECONDS and
                source['provider_id']=='THE_ODDS_API' and source['method']=='NATIVE_RETRIEVAL',
                'PROVIDER_IDENTITY_OR_PREMATCH_CONFLICT')
        stamps=(source['published_at_utc'],source['captured_at_utc'],review['available_at_utc'],decision)
        require(all(type(v) is int for v in stamps) and 0<stamps[0]<=stamps[1]<=stamps[2]<=stamps[3] and
                decision-stamps[0]<=POLICY['quote_max_age_seconds'] and
                decision-stamps[1]<=POLICY['quote_max_age_seconds'],'STALE_OR_UNAVAILABLE_PRICE')
        pair=(cp['discovery_receipt_sha256'],source['receipt_sha256'])
        if pair not in parsed:
            discovery,detail=(bridge.read_receipt(pin) for pin in pair)
            with archived_price_clock(decision):
                observations,_=odds_observations(detail,native,discovery=discovery)
                parsed[pair]={o['sha256']:(o,admit_odds(o,native,discovery,detail)) for o in observations}
        match=parsed[pair].get(review['observation_sha256'])
        require(match is not None,'PRICE_CAPTURE_OBSERVATION_MISMATCH')
        observation,quotes=match
        require(observation['payload']['bookmaker']==review['bookmaker'] and
                observation['payload']['source']==source and
                observation['payload']['available_at_utc']==review['available_at_utc'],
                'PRICE_CAPTURE_SCOPE_MISMATCH')
        native_rows={q.sha256:q.payload for q in quotes}
        for row in review['rows']:
            if row['period']!='FULL' or row['market'] not in ('WINNER','TOTAL'):continue
            try:
                q=native_rows.get(row.get('quote_sha256'))
                require(q is not None and all(q[k]==row[k] for k in ('period','market','line','prices')),
                        'PRICE_CAPTURE_QUOTE_MISMATCH')
                require(set(row['prices'])=={'under','over'},'EMPTY_OR_UNSUPPORTED_ODDS_ROWS')
                r=rules.get((review['bookmaker']['id'],f['league'],row['period'],row['market']))
                require(isinstance(r,RuleEvidence),'SETTLEMENT_RULE_UNVERIFIED')
                RuleEvidence.validate(r.payload)
                rp=r.payload
                require(digest(rp)==r.sha256==row.get('rule_sha256') and
                        (rp['bookmaker_id'],rp['league'],rp['period'],rp['market'])==
                        (review['bookmaker']['id'],f['league'],row['period'],row['market']) and
                        0<rp['observed_at_utc']<=rp['ingested_at_utc']<=decision and
                        rp['effective_from_utc']<=decision and
                        (rp['effective_until_utc'] is None or decision<rp['effective_until_utc']),
                        'SETTLEMENT_RULE_SCOPE_OR_PIN_MISMATCH')
                mass=row.get('raw_contract_probabilities')
                require(row.get('conditional_probability_is_contract_settlement') is True and
                        row.get('price_benchmarks',{}).get('settlement_scope_verified') is True and
                        set(row.get('reasons',[]))<= {'NO_APPROVED_DISJOINT_CALIBRATION'} and
                        isinstance(mass,dict) and set(mass)=={'under','push','over'} and
                        all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in mass.values()) and
                        abs(sum(mass.values())-1)<1e-8 and float(2*row['line']).is_integer(),
                        'VERIFIED_CONTRACT_PROBABILITIES_REQUIRED')
                require('contract_sample_evidence' in p,'CONTRACT_SAMPLE_EVIDENCE_MISSING')
                if sample_paths is None:
                    sample_paths=replay(p['contract_sample_evidence'],p['sample_sha256'])
                require(review['sample_count']==len(sample_paths[0]),'CONTRACT_SAMPLE_COUNT_MISMATCH')
                calculated=contract_mass(sample_paths,row['market'],row['line'],rp['include_overtime'])
                require(all(abs(mass[k]-calculated[k])<=1e-12 for k in mass),
                        'CONTRACT_PROBABILITY_REPLAY_MISMATCH')
                if abs(mass['under']-mass['over'])<1e-12 or mass['push']>=max(mass['under'],mass['over']):
                    excluded['NO_DISTINCT_DIRECTION']+=1;continue
                side='under' if mass['under']>mass['over'] else 'over'
                v=settled_value(periods,row['period'],row['market'],include_overtime=rp['include_overtime'])
                actual='push' if v==row['line'] else 'under' if v<row['line'] else 'over'
                group=(f['league'],f['season'],review['model_version'],review['bookmaker']['id'],
                       row['market'],rp['include_overtime'],row['line'])
                rows.append(dict(group=group,fixture_id=f['fixture_id'],decision_utc=decision,
                    completed_at_utc=completed,batch_sha256=w['sha256'],quote_sha256=row['quote_sha256'],
                    direction=side,prices=dict(row['prices']),model_digest=review['model_digest'],
                    outcome='PUSH' if actual=='push' else 'WIN' if side==actual else 'LOSS'))
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                reason=str(exc)
                excluded[reason if reason.isupper() and len(reason)<100 else 'MARKET_ROW_VALIDATION_FAILED']+=1
    return rows,excluded

def candidate_checker(assessments):
    entries=None;checked={}
    def check(p,evaluation,completed):
        nonlocal entries
        require(assessments is not None,'CANDIDATE_ARCHIVE_UNAVAILABLE')
        if entries is None:
            entries={digest(e['payload']):e for e in assessments.registry.records()}
        pin=p['current_assessment_sha256'];entry=entries.get(pin)
        require(entry is not None,'CANDIDATE_PUBLICATION_NOT_VERIFIED')
        c=entry['payload'];f=c['fixture']
        require(c['original_snapshot_sha256']==p['linked_original_snapshot_sha256'] and
                f['fixture_id']==evaluation['fixture_id'] and f['league']==evaluation['league'] and
                f['season']==evaluation['season'] and f['fixture_start_utc']==evaluation['fixture_start_utc'] and
                c['prediction_generated_at_utc']==p['prediction_utc'] and
                c['intervals']['sample_sha256']==p['sample_sha256'] and c['candidate']['model']==evaluation['model_version'] and
                entry['publication']['first_archived_at_utc']<=p['decision_utc'],
                'CANDIDATE_PUBLICATION_SCOPE_CONFLICT')
        if pin not in checked:
            assessments.registry.validate_assets(c)
            ref=next((r for r in c['assets'] if r['file'].startswith('joint-paths-')),None)
            require(ref is not None,'CANDIDATE_SAMPLE_ASSET_REQUIRED')
            asset=assessments.registry.read_asset(ref)
            key=digest(dict(fixture=f['canonical_id'],version=c['version']))
            receipt=read_wrapper(assessments.registry.root/('assessment-commit-'+key+'.json'),65536)['payload']
            require(receipt['forecast_sha256']==pin and
                    receipt['publication_sha256']==digest(entry['publication']) and receipt['eligible'] is True,
                    'CANDIDATE_COMMIT_PIN_CONFLICT')
            checked[pin]=(asset['model_artifact_sha256'],receipt['completed_at_utc'])
        model_pin,committed=checked[pin]
        require(model_pin==evaluation['model_digest'] and type(committed) is int and
                entry['publication']['first_archived_at_utc']<=committed<=p['decision_utc'],
                'CANDIDATE_MODEL_OR_COMMIT_CLOCK_CONFLICT')
    return check

def audit(root,reports,*,bridge,assessments=None):
    excluded=Counter();labels=[];fixtures=set();groups={};conflicts=set()
    if bridge is None:return dict(status='BLOCKED_PROVIDER_ARCHIVE_UNAVAILABLE',groups=[],excluded={},independent_fixtures=0)
    for league,report in reports.items():
        try:
            for batch in normalized_rows(unwrap(report),league):
                labels.extend(batch)
                fixtures.add((league,batch[0]['fixture_id']))
        except ERRORS:excluded['VERIFIED_LEAGUE_REPORT_UNAVAILABLE']+=1
    by_fixture=defaultdict(list)
    for row in labels:by_fixture[(row['league'],row['fixture_id'])].append(row)
    root=local_path(root);dirs=[root/'current-market-reviews',root/'europe-data'/'market']
    # Bounded scan: two legacy directories and exact known fixture segments.
    locations=dirs+[fixture_journal_directory(d,l,f) for d in dirs for l,f in sorted(fixtures)]
    files=[];size=0
    for loc in locations:
        for path in local_path(loc).glob('review-*.json'):
            size+=local_path(path).stat().st_size;files.append(path)
            if len(files)>MAX_FILES or size>MAX_BYTES:
                return dict(status='BLOCKED_MARKET_AUDIT_READ_BUDGET',groups=[],excluded=dict(excluded),independent_fixtures=0)
    check=candidate_checker(assessments)
    for path in sorted(files):
        try:
            # Route only to the actual verified result cohort, never another fixture.
            p=read_wrapper(path)['payload']
            if 'native_price_context' not in p:
                excluded['LEGACY_PRICE_CONTEXT_MISSING']+=1;continue
            ctx=p['native_price_context']
            rows,skips=audit_batch(path,bridge,by_fixture[(ctx['league'],ctx['fixture_id'])],candidate_lookup=check)
            excluded.update(skips)
            for row in rows:
                k=(row['group'],row['fixture_id']);rank=(row['completed_at_utc'],row['decision_utc'])
                old=groups.get(k)
                if old is None or rank<(old['completed_at_utc'],old['decision_utc']):
                    groups[k]=row;conflicts.discard(k)
                elif rank==(old['completed_at_utc'],old['decision_utc']) and any(
                        row[field]!=old[field] for field in ('direction','outcome','prices','model_digest')):
                    conflicts.add(k)
        except ERRORS as exc:
            reason=str(exc)
            excluded[reason if reason.isupper() and len(reason)<100 else 'MARKET_BATCH_VALIDATION_FAILED']+=1
    results=defaultdict(Counter);unique=set()
    for k,row in groups.items():
        if k in conflicts:excluded['CONFLICTING_FIRST_DIRECTION']+=1;continue
        results[row['group']][row['outcome']]+=1;unique.add((row['group'][0],row['fixture_id']))
    out=[]
    for key,c in sorted(results.items()):
        n=c['WIN']+c['LOSS']
        out.append(dict(group=list(key),win=c['WIN'],loss=c['LOSS'],push=c['PUSH'],
                        independent_fixtures=sum(c.values()),hit_rate=c['WIN']/n if n else None))
    return dict(status='DESCRIPTIVE_VERIFIED_PREMATCH_DIRECTIONS' if out else 'NO_VERIFIED_PREMATCH_DIRECTIONS',
                groups=out,excluded=dict(excluded),independent_fixtures=len(unique),
                forecast_changed=False,calibration_verified=False)

def render(root,reports,*,bridge,assessments=None):
    r=audit(root,reports,bridge=bridge,assessments=assessments)
    lines=['ZEYNAL | MAÇ SONUCU (ML) / ALT-ÜST | AYRI PİYASA KARAR DENETİMİ',
           r['status'],'Bağımsız doğrulanmış maç: '+str(r['independent_fixtures']),
           'İlk tahmin başarısına eklenmez. Gerçek bahis veya kalibrasyon başarısı değildir.']
    for market in ('WINNER','TOTAL'):
        rows=[g for g in r['groups'] if g['group'][4]==market]
        lines.append(('Maç sonucu (ML)' if market=='WINNER' else 'Alt/Üst')+' · '+str(len(rows))+' ayrı kohort')
        for g in rows[:32]:
            l,s,model,book,_,ot,line=g['group']
            rate='yok' if g['hit_rate'] is None else f"{100*g['hit_rate']:.1f}%"
            lines.append(f"{l} {s} | {model} | {book} | {'Uzatma dahil' if ot else 'Normal süre'} | {line:g} | "
                         f"D {g['win']} Y {g['loss']} İade {g['push']} | İade dışı isabet {rate}")
        if len(rows)>32:lines.append(f"Özet sınırı: 32/{len(rows)} kohort; toplu başarı yüzdesi hesaplanmadı.")
    lines.append('Dışlanan kayıt/satır nedenleri: '+(', '.join(f'{k}={v}' for k,v in sorted(r['excluded'].items())) or 'yok'))
    return '\n'.join(lines)
