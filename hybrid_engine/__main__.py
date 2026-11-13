"""Explicit offline entry points; no network or production mutation in evaluation."""
import argparse
import json
from core.team_identity import digest

from hybrid_engine.boxes import publish_json
from hybrid_engine.data import ASSUMED, STRICT, local_path
from hybrid_engine.evaluation import run_research


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--assume-historical-availability', action='store_true')
    args = parser.parse_args()
    report = run_research(args.manifest, mode=ASSUMED if args.assume_historical_availability else STRICT,
        progress=lambda value: print(json.dumps(value), flush=True))
    directory = local_path(args.output_directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('evaluation-'+digest(report)+'.json')
    publish_json(path, report)
    print(json.dumps(dict(report_path=str(path), promotion_gate=report['promotion_gate'])), flush=True)


if __name__ == '__main__': main()
