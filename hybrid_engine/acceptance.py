"""Reproducible strict acceptance audit. Never merges or deploys, regardless of result."""
import argparse
import hashlib
import json
from pathlib import Path

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.walkforward import run_walkforward


def verified_runtime(runtime, source_pins):
    decisions=runtime.get('v1_decisions',[])
    return (runtime.get('status')=='PASS' and runtime.get('address_space_limit_bytes')==[268435456]*2
        and 0<runtime.get('peak_rss_mib',1e9)<256 and runtime.get('requests',0)>=25
        and runtime.get('analyze_replies',0)>=22 and runtime.get('health_ready',{}).get('ready') is True
        and runtime.get('accuracy_replies',0)>=1 and runtime.get('compare_replies',0)>=1
        and runtime.get('actual_v1_analysis') is True and runtime.get('reports_read_only_verified') is True
        and runtime.get('legacy_records_preserved') is True
        and runtime.get('isolated_ledger_integrity',{}).get('snapshots')==2
        and sum(d['league']=='NBA' and d['status']=='ANALYSIS_OK' for d in decisions)>=20
        and any(d['league']=='EUROLEAGUE' and d['status']=='ANALYSIS_OK' for d in decisions)
        and any(d['league']=='EUROCUP' and d['status']=='ABSTAIN' for d in decisions)
        and len(runtime.get('cpu_affinity',[]))==1 and runtime.get('v1_cache_serialized_bytes',0)>=15*1024*1024
        and not runtime.get('native_ml_libraries_loaded')
        and all(runtime.get('runtime_source_pins',{}).get(k)==v for k,v in source_pins.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True); parser.add_argument('--output-directory', required=True)
    parser.add_argument('--runtime-report'); args = parser.parse_args()
    report = run_walkforward(args.manifest, progress=lambda x: print(json.dumps(x), flush=True))
    if args.runtime_report:
        path = local_path(args.runtime_report); raw = path.read_bytes(); runtime = json.loads(raw)
        verified = verified_runtime(runtime,report['source_file_pins'])
        report['combined_runtime'] = dict(passed=verified, file_sha256=hashlib.sha256(raw).hexdigest(),
            evidence=runtime, limitation='LOCAL_TELEGRAM_API_DOUBLE_NOT_REAL_FLY_OR_INTERNET_TELEGRAM_DELIVERY')
        if verified: report['acceptance']['blockers'].remove('COMBINED_TELEGRAM_ML_RESOURCE_RESULT_REQUIRES_SEPARATE_EVIDENCE')
    directory = local_path(args.output_directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/('strict-acceptance-'+digest(report)+'.json'); publish_json(path, report)
    print(json.dumps(dict(path=str(path), acceptance=report['acceptance'])), flush=True)


if __name__ == '__main__': main()
