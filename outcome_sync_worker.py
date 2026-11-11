"""Bounded, opt-in ESPN outcome reconciliation worker.

One-shot by default. Explicit --apply writes only provider-verified finals via
espn_outcome_sync. This does not bypass HTTP 403 or invent missing outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from espn_outcome_sync import run


def execute(db_path: str, apply: bool = False, limit: int = 20,
            cycles: int = 1, interval_seconds: int = 900,
            sleep=time.sleep) -> list[dict]:
    if not os.path.isfile(db_path):
        raise ValueError("ledger_not_found")
    if not 1 <= cycles <= 96 or not 60 <= interval_seconds <= 86400:
        raise ValueError("invalid_worker_limits")
    reports = []
    for index in range(cycles):
        report = run(db_path, apply=apply, limit=limit)
        reports.append(report)
        print(json.dumps({"cycle": index + 1, **report}, sort_keys=True), flush=True)
        if index + 1 < cycles:
            sleep(interval_seconds)
    return reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        reports = execute(args.database, args.apply, args.limit,
                          args.cycles, args.interval_seconds)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    failures = {"ERROR", "PROVIDER_ACCESS_DENIED", "PROVIDER_HTTP_ERROR"}
    return 1 if any(item.get("status") in failures
                    for report in reports for item in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
