"""Reproducible strict acceptance audit. Never merges or deploys, regardless of result."""
import argparse
import hashlib
import json
from pathlib import Path

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.walkforward import run_walkforward


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True); parser.add_argument('--output-directory', required=True)
    parser.add_argument('--runtime-report'); args = parser.parse_args()
    report = run_walkforward(args.manifest, progress=lambda x: print(json.dumps(x), flush=True))
    if args.runtime_report:
        path = local_path(args.runtime_report); raw = path.read_bytes(); runtime = json.loads(raw)
        verified = (runtime.get('status') == 'PASS' and runtime.get('address_space_limit_bytes') == [268435456]*2
            and runtime.get('peak_rss_mib', 1e9) < 256 and runtime.get('requests', 0) >= 21
            and runtime.get('analyze_replies', 0) >= 20 and runtime.get('health_ready', {}).get('ready') is True
            and len(runtime.get('cpu_affinity', [])) == 1 and runtime.get('v1_cache_serialized_bytes', 0) >= 15*1024*1024
            and not runtime.get('native_ml_libraries_loaded') and
            all(runtime.get('runtime_source_pins', {}).get(k) == v for k, v in report['source_file_pins'].items()))
        report['combined_runtime'] = dict(passed=verified, file_sha256=hashlib.sha256(raw).hexdigest(),
            evidence=runtime, limitation='LOCAL_API_DOUBLE_AND_HOST_MOUNTED_RUNTIME_NOT_REAL_FLY_OR_TELEGRAM_DELIVERY')
        if verified: report['acceptance']['blockers'].remove('COMBINED_TELEGRAM_ML_RESOURCE_RESULT_REQUIRES_SEPARATE_EVIDENCE')
    directory = local_path(args.output_directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/('strict-acceptance-'+digest(report)+'.json'); publish_json(path, report)
    print(json.dumps(dict(path=str(path), acceptance=report['acceptance'])), flush=True)


if __name__ == '__main__': main()
