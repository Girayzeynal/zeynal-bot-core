"""Pre-tipoff news and editorial evidence gate; no scraping or inferred facts."""
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

KINDS = {"official_status", "team_statement", "reported_fact", "editorial_opinion"}
SOURCE_CLASSES = {"league", "team", "independent_newsroom", "analyst"}
STATUS = {"out", "doubtful", "questionable", "probable", "available", "unknown"}


@dataclass(frozen=True)
class NewsEvidence:
    fixture_id: str
    team_id: str
    kind: str
    source_class: str
    source_name: str
    url: str
    headline: str
    published_at_utc: int
    observed_at_utc: int
    captured_at_utc: int
    assertion: str
    player_id: str = ""
    availability: str = "unknown"

    def validate(self, prediction_at_utc: int) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.fixture_id, self.team_id, self.source_name, self.headline, self.assertion
        )):
            raise ValueError("missing news identity or content")
        if self.kind not in KINDS or self.source_class not in SOURCE_CLASSES:
            raise ValueError("unknown evidence classification")
        url = urlsplit(self.url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("news source requires public HTTPS URL")
        times = (self.published_at_utc, self.observed_at_utc,
                 self.captured_at_utc, prediction_at_utc)
        if any(type(t) is not int for t in times):
            raise ValueError("invalid UTC timestamp")
        if not (0 < self.published_at_utc <= self.observed_at_utc
                <= self.captured_at_utc <= prediction_at_utc):
            raise ValueError("news not demonstrably available at prediction time")
        if self.availability not in STATUS:
            raise ValueError("unknown player availability")
        if self.kind == "official_status":
            if self.source_class not in {"league", "team"} or not self.player_id:
                raise ValueError("official player status requires primary source and player ID")
        elif self.availability != "unknown":
            raise ValueError("non-official news cannot set authoritative player status")


def summarize_news(evidence, *, fixture_id, prediction_at_utc):
    """Separate official statuses, reported claims, and editorial hypotheses.

    No source count is interpreted as independent confirmation; syndication and
    common upstream reporting require additional provenance checks.
    """
    seen = set()
    accepted = []
    for item in evidence:
        item.validate(prediction_at_utc)
        if item.fixture_id != fixture_id:
            raise ValueError("cross-fixture news contamination")
        key = (item.url, item.published_at_utc, item.assertion)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(item)
    # Use latest observed official update; equal-time contradictions are unsafe.
    latest = {}
    conflicts = set()
    for x in accepted:
        if x.kind != "official_status":
            continue
        key = (x.team_id, x.player_id)
        old = latest.get(key)
        if old is None or x.observed_at_utc > old.observed_at_utc:
            latest[key] = x
            conflicts.discard(key)
        elif x.observed_at_utc == old.observed_at_utc and x.availability != old.availability:
            conflicts.add(key)
    return {
        "fixture_id": fixture_id,
        "official_status_conflicts": [
            {"team_id": team, "player_id": player}
            for team, player in sorted(conflicts)
        ],
        "official_statuses": [
            {"team_id": x.team_id, "player_id": x.player_id,
             "status": x.availability, "url": x.url}
            for key, x in sorted(latest.items()) if key not in conflicts
        ],
        "reported_facts": [x.url for x in accepted if x.kind in {"reported_fact", "team_statement"}],
        "editorial_hypotheses": [x.url for x in accepted if x.kind == "editorial_opinion"],
        "news_observations": len(accepted),
        "independently_confirmed": False,
        "manual_review_required": bool(conflicts),
        "automatic_projection_adjustment": False,
        "reason": "News and opinions require corroboration and measured historical impact before model weighting",
    }
