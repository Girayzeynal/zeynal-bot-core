"""Fail-closed pregame basketball news evidence classification.

No article scraping, provider authentication or prediction-weight inference.
Adapters must independently authenticate publishers and source timestamps.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NewsItem:
    source_id: str
    source_group: str
    url: str
    league: str
    fixture_id: str
    subject_type: str
    subject_id: str
    category: str
    claim: str
    published_at_utc: int
    retrieved_at_utc: int
    evidence_type: str
    authenticated: bool


@dataclass(frozen=True)
class NewsAssessment:
    status: str
    accepted: tuple[NewsItem, ...]
    excluded: tuple[tuple[str, str], ...]
    corroborated_claims: tuple[str, ...]


def assess_news(items, *, league: str, fixture_id: str,
                prediction_utc: int, max_age_seconds: int = 172800) -> NewsAssessment:
    """Keep opinion distinct from facts; independent corroboration is explicit.

    No unverified or post-prediction item can enter accepted pregame context.
    An editorial interpretation is never promoted to an official fact.
    """
    if (not league or not fixture_id or type(prediction_utc) is not int
            or prediction_utc <= 0 or type(max_age_seconds) is not int
            or max_age_seconds < 0):
        raise ValueError("Invalid news assessment context")
    accepted, excluded = [], []
    allowed_subjects = {"TEAM", "PLAYER", "COACH"}
    allowed_types = {"OFFICIAL", "REPORTING", "EDITORIAL"}
    allowed_categories = {"INJURY", "LINEUP", "MINUTES", "ROTATION",
                          "TACTICS", "FATIGUE", "AVAILABILITY", "OTHER"}
    for item in items:
        if not isinstance(item, NewsItem):
            excluded.append(("", "INVALID_ITEM"))
            continue
        reason = None
        parsed = urlsplit(item.url)
        if (not item.authenticated or not item.source_id.strip()
                or not item.source_group.strip() or parsed.scheme != "https"
                or not parsed.hostname or parsed.username or parsed.password):
            reason = "UNAUTHENTICATED_SOURCE"
        elif (item.league != league or item.fixture_id != fixture_id
              or item.subject_type not in allowed_subjects
              or not item.subject_id.strip() or item.category not in allowed_categories
              or item.evidence_type not in allowed_types or not item.claim.strip()):
            reason = "INVALID_CONTEXT"
        elif (type(item.published_at_utc) is not int
              or type(item.retrieved_at_utc) is not int
              or not 0 < item.published_at_utc <= item.retrieved_at_utc <= prediction_utc):
            reason = "FUTURE_OR_INVALID_TIMESTAMP"
        elif prediction_utc - item.published_at_utc > max_age_seconds:
            reason = "STALE_NEWS"
        if reason:
            excluded.append((item.source_id, reason))
        else:
            accepted.append(item)
    # Only independently reported, identical factual claims can corroborate.
    groups = {}
    for item in accepted:
        if item.evidence_type != "REPORTING":
            continue
        key = (item.subject_type, item.subject_id, item.category, item.claim)
        groups.setdefault(key, set()).add(item.source_group)
    corroborated = tuple(sorted(
        f"{subject_type}:{subject_id}:{category}:{claim}"
        for (subject_type, subject_id, category, claim), sources in groups.items()
        if len(sources) >= 2
    ))
    status = "EVIDENCE_AVAILABLE" if accepted else "NO_VERIFIED_NEWS"
    return NewsAssessment(status, tuple(accepted), tuple(excluded), corroborated)
