"""Deterministic pregame news evidence bundle for archival alongside forecasts.

The bundle is separate from the FAZ13 numeric input snapshot: news is not
claimed to have changed a model forecast until the model actually consumes it.
"""
from dataclasses import asdict
import hashlib
import json

from basketball_news_intelligence import NewsItem, assess_news


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def seal_news_context(items, *, league: str, fixture_id: str,
                      prediction_utc: int, max_age_seconds: int = 172800):
    """Seal only eligible pregame evidence; never archive excluded article bodies."""
    assessment = assess_news(
        items, league=league, fixture_id=fixture_id,
        prediction_utc=prediction_utc, max_age_seconds=max_age_seconds)
    # Stable order prevents arrival-order differences from changing the digest.
    accepted = sorted((asdict(item) for item in assessment.accepted),
                      key=lambda item: (item["source_group"], item["source_id"],
                                        item["subject_id"], item["claim"], item["url"]))
    payload = {
        "schema_version": 1,
        "league": league,
        "fixture_id": fixture_id,
        "prediction_utc": prediction_utc,
        "status": assessment.status,
        "items": accepted,
        "corroborated_claims": list(assessment.corroborated_claims),
        "excluded_reasons": sorted(reason for _, reason in assessment.excluded),
        "model_consumed_news": False,
    }
    return {"payload": payload,
            "sha256": hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()}


def validate_news_context(bundle, *, league: str, fixture_id: str,
                          prediction_utc: int, max_age_seconds: int = 172800):
    """Re-evaluate every item, including publication-time eligibility."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("payload"), dict):
        raise ValueError("Missing news context bundle")
    payload = bundle["payload"]
    if (type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or payload.get("league") != league
            or payload.get("fixture_id") != fixture_id
            or payload.get("prediction_utc") != prediction_utc
            or payload.get("model_consumed_news") is not False):
        raise ValueError("News context identity mismatch")
    expected = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if bundle.get("sha256") != expected:
        raise ValueError("News context digest mismatch")
    try:
        items = [NewsItem(**item) for item in payload["items"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed archived news items") from exc
    result = seal_news_context(items, league=league, fixture_id=fixture_id,
                               prediction_utc=prediction_utc,
                               max_age_seconds=max_age_seconds)
    if (result["payload"]["items"] != payload["items"]
            or result["payload"]["status"] != payload.get("status")
            or result["payload"]["corroborated_claims"] != payload.get("corroborated_claims")):
        raise ValueError("Archived news is not eligible or internally consistent")
    return True
