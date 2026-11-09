"""Read-only, explainable pregame news audit for an archived forecast.

This module reports evidence coverage, not estimated point impacts or accuracy.
No live network calls, model rewrites, or historical-news backfilling.
"""
from dataclasses import dataclass

from prediction_news_ledger import load_news_context


@dataclass(frozen=True)
class NewsAudit:
    status: str
    fixture_id: str
    total_items: int
    official_items: int
    reporting_items: int
    editorial_items: int
    corroborated_claims: int
    model_consumed_news: bool
    warnings: tuple[str, ...]


def audit_prediction_news(ledger, *, league: str, fixture_id: str) -> NewsAudit:
    bundle = load_news_context(ledger, league=league, fixture_id=fixture_id)
    if bundle is None:
        return NewsAudit("NO_NEWS_SNAPSHOT", fixture_id, 0, 0, 0, 0, 0, False,
                         ("NEWS_EVIDENCE_NOT_ARCHIVED",))
    payload = bundle["payload"]
    items = payload["items"]
    counts = {kind: sum(x["evidence_type"] == kind for x in items)
              for kind in ("OFFICIAL", "REPORTING", "EDITORIAL")}
    warnings = []
    if not items:
        warnings.append("NO_ELIGIBLE_PREGAME_NEWS")
    if counts["EDITORIAL"]:
        warnings.append("EDITORIAL_IS_NOT_VERIFIED_FACT")
    if counts["REPORTING"] and not payload["corroborated_claims"]:
        warnings.append("REPORTING_NOT_INDEPENDENTLY_CORROBORATED")
    if payload["model_consumed_news"] is False:
        warnings.append("NEWS_NOT_CONSUMED_BY_PREDICTION_MODEL")
    return NewsAudit(
        "NEWS_EVIDENCE_ARCHIVED", fixture_id, len(items), counts["OFFICIAL"],
        counts["REPORTING"], counts["EDITORIAL"],
        len(payload["corroborated_claims"]), False, tuple(warnings))
