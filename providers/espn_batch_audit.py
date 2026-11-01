"""Offline ESPN NBA ingestion batch report with explicit rejection accounting."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable

from prediction_ledger import PredictionLedger
from providers.espn_pipeline import ingest_espn_payload

STATUSES = (
    "accepted",
    "invalid_or_incomplete_event",
    "unmatched_or_conflicting_fixture",
    "invalid_observation_time",
)


def ingest_espn_batch(
    ledger: PredictionLedger,
    items: Iterable[Dict[str, Any]],
    observed_at_utc: int,
) -> dict:
    """Process supplied local-fixture/event pairs and report every disposition.

    The input must already map each ESPN event to an independently
    pre-registered local fixture; no identity is inferred from team names.
    """
    counts: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            counts["invalid_input"] += 1
            continue
        fixture_id = item.get("fixture_id")
        event = item.get("event")
        if not isinstance(fixture_id, str) or not fixture_id.strip() or not isinstance(event, dict):
            counts["invalid_input"] += 1
            continue
        status = ingest_espn_payload(ledger, fixture_id, event, observed_at_utc)
        counts[status] += 1
    total = sum(counts.values())
    accepted = counts["accepted"]
    return {
        "total": total,
        "accepted": accepted,
        "rejected": total - accepted,
        "acceptance_rate": accepted / total if total else None,
        "statuses": {key: counts[key] for key in (*STATUSES, "invalid_input")},
        "ledger_audit": ledger.audit_provenance("NBA"),
    }
