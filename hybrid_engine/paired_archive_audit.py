"""Read-only paired error audit of original and published candidate forecasts."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time

from core.league_identity import resolve_league
from core.team_identity import digest
from hybrid_engine.adaptive_research import FORMAT as V2_FORMAT, read_wrapper
from hybrid_engine.current_assessment import AssessmentRegistry, VERSION as CURRENT_VERSION
from hybrid_engine.data import local_path
from hybrid_engine.europe_premium_ui import publication as verify_publication
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.live_metrics import metrics
from hybrid_engine.paired_error_axes import summarize
from hybrid_engine.runtime_reports import REPORT_ERRORS, RuntimeLedgerReports, failure
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS
from hybrid_engine.unified_results_view import LEAGUES, normalized_rows, unwrap
from projection_integrity import assert_projection
from hybrid_engine.chronological_blend import evaluate

FOLDERS = {'adaptive-v2': ('adaptive-v2',), 'nba-v3': ('nba-research-v3-integrity-v2',),
           'current-assessment': ('current-assessments-v1',)}
MAX_PROTOCOLS = 256  # bounded mobile audit; independent of number of matches
MAX_SLOTS = 1024
MAX_ASSET_BYTES = 32 * 1024 * 1024


class ReadOnlyRegistry(ForwardRegistry):
    def __init__(self, directory):
        self.root = local_path(directory)

    def read_asset(self, ref):
        path = local_path(self.root/ref['file'])
        if path.parent != self.root or path.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError('PAIRED_AUDIT_ASSET_PATH_OR_SIZE')
        return super().read_asset(ref)


class ReadOnlyAssessments(AssessmentRegistry, ReadOnlyRegistry):
    def __init__(self, directory):
        ReadOnlyRegistry.__init__(self, directory)


def protocols(root):
    for family, legacy_dirs in FOLDERS.items():
        paths = sorted((root/'research-protocols'/family).glob('protocol-*'))
        for folder in [*paths, *(root/name for name in legacy_dirs)]:
            if folder.is_dir():
                folder = local_path(folder)
                if (folder/'plan.json').is_file() or (folder/'policy.json').is_file() or any(folder.glob('plan-*.json')):
                    yield family, folder


def plan_for(family, folder, now):
    if family == 'adaptive-v2':
        files = sorted(folder.glob('plan-*.json'))
    else:
        files = [folder/('plan.json' if family=='nba-v3' else 'policy.json')]
    if len(files) != 1:
        raise ValueError('PAIRED_AUDIT_ONE_PLAN_REQUIRED')
    plan = read_wrapper(files[0],maximum=256*1024)
    p = plan['payload']
    if (type(p.get('registered_at_utc')) is not int or not 0 < p['registered_at_utc'] <= now
            or not isinstance(p.get('source_pins'), dict) or not p['source_pins']
            or not isinstance(p.get('policy'), dict)):
        raise ValueError('PAIRED_AUDIT_PLAN_CLOCK_OR_PINS')
    if family=='adaptive-v2' and (p.get('format')!=V2_FORMAT or files[0].stem!='plan-'+plan['sha256']):
        raise ValueError('PAIRED_AUDIT_V2_PLAN_BINDING')
    if family=='current-assessment' and p['policy'].get('version')!=CURRENT_VERSION:
        raise ValueError('PAIRED_AUDIT_CURRENT_PLAN_BINDING')
    if p.get('production_enabled') is True or p['policy'].get('automatic_promotion') is True:
        raise ValueError('PAIRED_AUDIT_RESEARCH_SCOPE_REQUIRED')
    return plan


def lookup_labels(reader):
    labels, archives = {}, {}
    for league in LEAGUES:
        try:
            report = unwrap(reader.read(league,None))
            fixtures = normalized_rows(report,league)
            league_rows = {}
            for rows in fixtures:
                for r in rows:
                    if (r.get('actual') is None or r.get('legacy_publication_clock_unrecorded')
                            or r.get('eligible_for_live_performance') is False):
                        continue
                    # The European serving route displays only BAYES_QMC for
                    # snapshots that also bind other model components.
                    if league != 'NBA' and r['model_version'] != 'BAYES_QMC':
                        continue
                    key = (league,r['season'],r['fixture_id'],r['snapshot_sha256'])
                    if key in league_rows and league_rows[key] != r:
                        raise ValueError('PAIRED_AUDIT_CONFLICTING_LABEL')
                    league_rows[key] = r
            labels.update(league_rows)
            archives[league] = dict(status='READ',eligible_fixtures=len({k[2] for k in league_rows}))
        except REPORT_ERRORS as exc:
            archives[league] = dict(status='FAILED',reason=failure(exc))
    return labels,archives


def check_admission(family, folder, plan, p):
    target = p['fixture']
    if family == 'adaptive-v2':
        identity = dict(protocol=plan['sha256'], fixture=target['canonical_id'], league=target['league'])
    else:
        identity = dict(plan=plan['sha256'], fixture=target['canonical_id'])
    admission = read_wrapper(folder/('admit-'+digest(identity)+'.json'),maximum=256*1024)['payload']
    expected = {k: v for k, v in target.items() if k not in ('canonical_id', 'start_ts_utc')}
    if (admission['protocol_sha256'] != plan['sha256']
            or admission['original_snapshot_sha256'] != p['original_snapshot_sha256']
            or admission['target'] != expected
            or type(admission['admitted_at_utc']) is not int
            or not plan['payload']['registered_at_utc'] <= admission['admitted_at_utc'] <= p['prediction_generated_at_utc']):
        raise ValueError('PAIRED_AUDIT_ADMISSION_BINDING')


def components(family,p):
    if family=='adaptive-v2':
        return [(name,c['prediction'],c.get('intervals')) for name,c in p['components'].items()
                if c['status']=='FORECAST_CREATED' and name!='FROZEN_ORIGINAL']
    q = p['candidate']
    return [(q['model'],q,p.get('intervals'))]


def report_protocol(family, folder, labels, now):
    plan = plan_for(family, folder, now)
    pin = plan['sha256']
    if family=='current-assessment':
        registries = (ReadOnlyAssessments(folder/'records'),)
    elif family=='adaptive-v2':
        registries = (ReadOnlyRegistry(folder/'forecasts'), ReadOnlyRegistry(folder/'player-forecasts'))
    else:
        registries = (ReadOnlyRegistry(folder/'forecasts'),)
    first, excluded = {}, Counter()
    scanned = 0
    for registry in registries:
        for slot in sorted(registry.root.glob('first-*.json')):
            scanned += 1
            if scanned > MAX_SLOTS or slot.stat().st_size > 65536:
                raise ValueError('PAIRED_AUDIT_PUBLICATION_BUDGET')
            pub = registry.publication(local_path(slot))
            ref = pub['forecast']
            if ref['file']!='forecast-'+ref['sha256']+'.json':
                raise ValueError('PAIRED_AUDIT_FORECAST_REFERENCE')
            p = registry.read_asset(ref)
            g = p['fixture']
            league = resolve_league(g['league']).code
            snapshot_sha = p['original_snapshot_sha256']
            label = labels.get((league,g['season'],g['canonical_id'],snapshot_sha))
            if label is None:
                excluded['ORIGINAL_FINAL_NOT_PAIRED'] += 1
                continue
            if slot.stem!='first-'+digest(dict(fixture=g['canonical_id'],version=p['version'])):
                raise ValueError('PAIRED_AUDIT_PUBLICATION_IDENTITY')
            if family=='current-assessment':
                if p.get('record_type')!=CURRENT_VERSION or p['protocol_sha256']!=pin or not p['version'].startswith(pin+':'):
                    raise ValueError('PAIRED_AUDIT_CURRENT_PROTOCOL_CONFLICT')
                if registry._verified_slot(slot) is None:
                    excluded['LATE_CANDIDATE_COMMIT'] += 1
                    continue
            else:
                if ((family=='adaptive-v2' and (p['version']!=pin or p.get('record_type')!='ADAPTIVE_V2_SEPARATE_RESEARCH_NOT_ACTIVE_MODEL'))
                        or (family=='nba-v3' and (p['protocol_sha256']!=pin or p['version']!=plan['payload']['policy']['version']))):
                    raise ValueError('PAIRED_AUDIT_PROTOCOL_CONFLICT')
                check_admission(family,folder,plan,p)
                verify_publication(registry,ref['sha256'])
            tip, generated = g['start_ts_utc'], p['prediction_generated_at_utc']
            archived = pub['first_archived_at_utc']
            if (p['actual'] is not None or p.get('production_enabled') is not False or not p['assets'] or
                    label['fixture_start_utc']!=tip or
                    set(label['provider_fixture_ids'])!=set(g['provider_fixture_ids'])):
                raise ValueError('PAIRED_AUDIT_NATIVE_FIXTURE_CONFLICT')
            if p.get('original_model_digest') and p['original_model_digest']!=label['model_digest']:
                raise ValueError('PAIRED_AUDIT_ORIGINAL_MODEL_CONFLICT')
            issued, durable, final = (label.get(k) for k in
                ('prediction_generated_at_utc','first_archived_at_utc','label_available_utc'))
            if (any(type(v) is not int for v in (issued,durable,generated,archived,tip,final))
                    or not 0<issued<=durable<=generated<=archived<tip-PREMATCH_MINIMUM_LEAD_SECONDS<tip<final<=now
                    or not plan['payload']['registered_at_utc']<=generated):
                excluded['UNPROVEN_TIMELINE_OR_LABEL_AVAILABILITY'] += 1
                continue
            for name, q, bands in components(family,p):
                if q.get('scope')!='REGULATION_ONLY':
                    raise ValueError('PAIRED_AUDIT_CANDIDATE_SCOPE')
                assert_projection(q)
                key = (league,g['season'],label['model_version'],label['model_digest'],name,g['canonical_id'])
                rank = (archived,generated)
                old = first.get(key)
                if old is not None and rank==old[0] and old[1]!=ref['sha256']:
                    raise ValueError('PAIRED_AUDIT_AMBIGUOUS_FIRST_CANDIDATE')
                if old is None or rank<old[0]:
                    first[key] = (rank,ref['sha256'],p,q,bands,label,registry)
    pairs = defaultdict(list)
    fits = {}
    for key,(next_rank,candidate_sha,p,q,bands,label,registry) in first.items():
        metadata = q.get('metadata', {})
        if candidate_sha not in fits:
            fit = p.get('parameter_fit_cutoff_utc', metadata.get('fit_cutoff_utc'))
            if family == 'current-assessment':
                registry.validate_assets(p)
            if family == 'adaptive-v2' and p.get('model_artifact_sha256'):
                model_refs = [ref for ref in p['assets'] if ref['file'].startswith('model-')]
                if len(model_refs) != 1:
                    raise ValueError('PAIRED_AUDIT_V2_MODEL_REFERENCE')
                model = registry.read_asset(model_refs[0])
                if model['sha256'] != p['model_artifact_sha256'] or digest(model['payload']) != model['sha256']:
                    raise ValueError('PAIRED_AUDIT_V2_MODEL_PIN')
                fit = model['payload']['cutoff_utc']
            if fit is not None and (type(fit) is not int or not 0 < fit <= p['prediction_generated_at_utc']):
                raise ValueError('PAIRED_AUDIT_MODEL_FIT_CLOCK')
            fits[candidate_sha] = fit
        fit = fits[candidate_sha]
        candidate = dict(label,model_version=key[-2],model_digest=pin,prediction=[q['home'],q['away']],
                         predicted_quarters=q.get('quarters'),predicted_halves=q.get('halves'),
                         winner=q.get('winner'),intervals=bands,
                         prediction_generated_at_utc=p['prediction_generated_at_utc'],
                         candidate_archived_at_utc=next_rank[0],
                         estimated_possessions=metadata.get('box_pace', metadata.get('pace_mean')),
                         parameter_age_seconds=p['prediction_generated_at_utc']-fit if type(fit) is int else None)
        pairs[key[:-1]].append((candidate,label))
    groups = []
    for (league,season,original,model,name), rows in sorted(pairs.items()):
        left = metrics([v[1] for v in rows]); right = metrics([v[0] for v in rows])
        axes = summarize(rows)
        groups.append(dict(league=league,season=season,original=original,original_model_digest=model,
                           candidate=name,n=len(rows),original_total=left['total'],candidate_total=right['total'],
                           original_winner=left.get('winner'),candidate_winner=right.get('winner'),
                           original_period_totals=left.get('period_totals'),candidate_period_totals=right.get('period_totals'),
                           original_half_totals=left.get('half_totals'),candidate_half_totals=right.get('half_totals'),
                           original_total_coverage=left['coverage']['markets'].get('TOTAL'),
                           candidate_total_coverage=right['coverage']['markets'].get('TOTAL'),diagnostics=axes))
    return (dict(family=family,protocol_sha256=pin,publications=scanned,groups=groups,
                 exclusions=dict(excluded),status='PAIRED' if groups else 'NO_MATCHED_PUBLICATIONS'),pairs)


def common_fixture_comparisons(protocols):
    output = []
    for meta, v2 in protocols:
        if meta['family']!='adaptive-v2':
            continue
        for other, newer in protocols:
            if other['family']=='adaptive-v2':
                continue
            for identity, rows in v2.items():
                if identity[-1]!='PACE_EFFICIENCY':
                    continue
                by_id={(base['fixture_id'],base['snapshot_sha256']):(score,base) for score,base in rows}
                for key, candidates in newer.items():
                    if key[:-1]!=identity[:-1]:
                        continue
                    shared=[(score,*by_id[(base['fixture_id'],base['snapshot_sha256'])])
                            for score,base in candidates if (base['fixture_id'],base['snapshot_sha256']) in by_id]
                    if not shared:
                        continue
                    original=metrics([r[2] for r in shared])
                    component=metrics([r[1] for r in shared])
                    updated=metrics([r[0] for r in shared])
                    league,season,_,model,_=key
                    output.append(dict(league=league,season=season,original_model_digest=model,n=len(shared),
                        v2_protocol_sha256=meta['protocol_sha256'],candidate_protocol_sha256=other['protocol_sha256'],
                        candidate_family=other['family'],candidate=key[-1],original_total_mae=original['total']['mae'],
                        v2_total_mae=component['total']['mae'],candidate_total_mae=updated['total']['mae'],
                        total_rmse=[m['total']['rmse'] for m in (original,component,updated)],
                        raw_winner_brier=[m.get('winner',{}).get('brier') for m in (original,component,updated)]))
    return output


def audit(root, reader, *, now=None):
    root = local_path(root)
    current = int(time.time()) if now is None else now
    labels,archives = lookup_labels(reader)
    folders = list(protocols(root))
    if len(folders) > MAX_PROTOCOLS:
        raise ValueError('PAIRED_AUDIT_PROTOCOL_SCAN_BUDGET')
    reviews, comparisons = [], []
    for family,folder in folders:
        try:
            result,pairs=report_protocol(family,folder,labels,current)
            reviews.append(result)
            comparisons.append((result,pairs))
        except REPORT_ERRORS as exc:
            reviews.append(dict(family=family,status='FAILED',reason=failure(exc)))
    return dict(format='PAIRED_PUBLISHED_CANDIDATE_AUDIT_V1',archives=archives,protocols=reviews,
                common_fixtures=common_fixture_comparisons(comparisons),
                unique_chronological_blend=evaluate(comparisons),scope='REGULATION_ONLY',automatic_promotion=False,fit_performed=False,read_only=True)


def render(report, *, compact=False):
    lines = ['ZEYNAL | YAYIMLANMIŞ ADAYLARIN EŞLEŞTİRİLMİŞ HATA DENETİMİ']
    for league, item in report['archives'].items():
        lines.append(f"{league} · uygun sonuçlu maç {item['eligible_fixtures']}" if item['status']=='READ'
                     else f"{league} · Arşiv okunamadı · {item['reason']}")
    for protocol in ([] if compact else report['protocols']):
        key = protocol.get('protocol_sha256','')[:12]
        lines.append(f"\n{protocol['family']} {key} · {protocol['status']}")
        if protocol.get('exclusions'):
            lines.append('Ölçüm dışı yayınlar · ' + ' · '.join(
                f'{reason} {count}' for reason, count in sorted(protocol['exclusions'].items())))
        if protocol.get('reason'):
            lines.append(protocol['reason'])
        for row in protocol.get('groups',[]):
            lines.append(f"{row['league']} · {row['candidate']} · {row['n']} maç · "
                         f"Toplam MAE {row['original_total']['mae']:.2f} → {row['candidate_total']['mae']:.2f}")
            q = row['diagnostics']
            lines.append(f"Toplam sapma {q['original_total_bias']:+.2f} → {q['candidate_total_bias']:+.2f} · "
                         f"RMSE {row['original_total']['rmse']:.2f} → {row['candidate_total']['rmse']:.2f}")
    if not report['protocols']:
        lines.append('Yayımlanmış araştırma protokolü bulunamadı.')
    lines.append('\nİlk tahmin · V2 tempo · Diğer aday | Ortak maçlar')
    for row in ([] if compact else report['common_fixtures']):
        lines.append(f"{row['league']} · {row['n']} maç · {row['v2_protocol_sha256'][:8]} / "
            f"{row['candidate_protocol_sha256'][:8]} · Toplam MAE {row['original_total_mae']:.2f} / "
            f"{row['v2_total_mae']:.2f} / {row['candidate_total_mae']:.2f}")
    if not report['common_fixtures']:
        lines.append('Üç tahminin de doğrulandığı ortak maç henüz yok.')
    blend = report['unique_chronological_blend']
    lines.append('\nBENZERSİZ MAÇ | KRONOLOJİK V1/V2/V3 BİRLEŞİMİ (ARAŞTIRMA)')
    lines.append(f"Ortak benzersiz maç {blend['n']} · Tekrarlı kayıt {blend['duplicate_records']} · Çakışma dışlama {blend['conflicts']}")
    for g in blend['groups']:
        lines.append(f"{g['league']} · {g['season']} · {g['n']} maç · geçmişe dayalı ağırlık {g['trained_n']}")
        for name, m in g['metrics'].items():
            lines.append(f"{name}: Toplam MAE {m['total_mae']:.2f} · RMSE {m['total_rmse']:.2f} · Bias {m['bias']:+.2f} · Takım MAE {m['team_mae']:.2f} · Fark MAE {m['margin_mae']:.2f}")
        for name, m in g['metrics'].items():
            if m['quarter_mae'] is not None:
                lines.append(name+' · Çeyrek MAE '+ ' / '.join(f'{v:.2f}' for v in m['quarter_mae']))
        lines.append(f"Birleşim daha iyi/eşit/kötü (V1): {g['improved']}/{g['unchanged']}/{g['worsened']}")
    lines.append('Geriye dönük kronolojik araştırma; yeni prospektif yayın veya kalibrasyon kanıtı değil.')
    lines.append('Betimsel ölçüm · Normal süre · Her protokol ve ilk tahmin sürümü ayrı')
    return '\n'.join(lines)


def main():
    from hybrid_engine.europe_live import EuropeanRegistry, EuropeanService
    from hybrid_engine.europe_reports import EuropeanReports

    class ReadOnlyEuropeRegistry(EuropeanRegistry):
        def __init__(self,league,path):
            self.root = local_path(path)
            self.league = league

    class ReadOnlyEurope(EuropeanService):
        def __init__(self,league,path):
            self.league=league
            self.registry=ReadOnlyEuropeRegistry(league,path)

    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',type=Path, required=True)
    parser.add_argument('--json',action='store_true')
    parser.add_argument('--compact',action='store_true')
    args=parser.parse_args()
    root=local_path(args.data_directory)

    class Reader:
        def read(self,league,fixture):
            if league=='NBA':
                return RuntimeLedgerReports(root/'live-nba/nba-hybrid.sqlite').read(league,fixture,summarize=False)
            folder=root/'europe'/league.lower()
            if not folder.is_dir():
                raise ValueError('PAIRED_AUDIT_ARCHIVE_UNAVAILABLE')
            return EuropeanReports(ReadOnlyEurope(league,folder)).read(league,fixture)

    result=audit(root,Reader())
    print(json.dumps(result,ensure_ascii=False,allow_nan=False) if args.json else render(result, compact=args.compact))


if __name__=='__main__':
    main()
