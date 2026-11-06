"""FAZ41 offline multi-source evidence contract; no live provider access.

Digest proves local integrity, NOT independent source authenticity.
"""
import hashlib
import json
from urllib.parse import urlsplit


TYPES = frozenset({"OFFICIAL_STAT", "OFFICIAL_LINEUP", "INJURY_REPORT",
                   "NEWS_CLAIM", "ANALYST_OPINION", "MARKET_QUOTE"})
LEVELS = frozenset({"OFFICIAL", "SECONDARY", "COMMENTARY"})
USAGE = frozenset({"PERMITTED", "RESTRICTED", "UNKNOWN"})


def _digest(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seal_source_claim(*, league, fixture_id, provider, source_url, data_type,
                      evidence_level, usage_status, published_at_utc,
                      observed_at_utc, ingested_at_utc, claim_key, claim_value):
    if any(not isinstance(v, str) or not v.strip() for v in
           (league, fixture_id, provider, source_url, claim_key)):
        raise ValueError("Missing source or fixture identity")
    url = urlsplit(source_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Source URL must be HTTPS without credentials")
    if data_type not in TYPES or evidence_level not in LEVELS or usage_status not in USAGE:
        raise ValueError("Invalid source classification")
    if data_type in ("OFFICIAL_STAT", "OFFICIAL_LINEUP") and evidence_level != "OFFICIAL":
        raise ValueError("Official data requires official evidence classification")
    if data_type == "ANALYST_OPINION" and evidence_level != "COMMENTARY":
        raise ValueError("Analyst opinion must remain commentary")
    if any(type(v) is not int or v <= 0 for v in
           (published_at_utc, observed_at_utc, ingested_at_utc)):
        raise ValueError("Invalid observation timestamps")
    if not published_at_utc <= observed_at_utc <= ingested_at_utc:
        raise ValueError("Non-monotonic source timestamps")
    if not isinstance(claim_value, (str, int, float, bool, type(None))):
        raise ValueError("Claim value must be scalar")
    payload = dict(schema_version=1, league=league, fixture_id=fixture_id,
                   provider=provider, source_url=source_url, data_type=data_type,
                   evidence_level=evidence_level, usage_status=usage_status,
                   published_at_utc=published_at_utc,
                   observed_at_utc=observed_at_utc, ingested_at_utc=ingested_at_utc,
                   claim_key=claim_key, claim_value=claim_value)
    return {"payload": payload, "sha256": _digest(payload)}


def validate_source_claim(sealed, *, league, fixture_id, prediction_utc,
                          require_permitted=True):
    if type(prediction_utc) is not int or prediction_utc <= 0:
        raise ValueError("Invalid prediction time")
    try:
        p = sealed["payload"]
        expected = seal_source_claim(**{k: v for k, v in p.items() if k != "schema_version"})
        if expected != sealed or p.get("schema_version") != 1:
            raise ValueError("Source claim integrity mismatch")
        if p["league"] != league or p["fixture_id"] != fixture_id:
            raise ValueError("Source claim fixture mismatch")
        if p["ingested_at_utc"] > prediction_utc:
            raise ValueError("Source claim unavailable before prediction")
        if require_permitted and p["usage_status"] != "PERMITTED":
            raise ValueError("Source usage permission not established")
        return p
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed source claim") from exc


def compare_claims(claims, *, league, fixture_id, prediction_utc):
    """Only identical keys and evidence levels can be compared; no truth voting."""
    if not isinstance(claims, list) or not claims:
        raise ValueError("No source claims")
    rows = [validate_source_claim(c, league=league, fixture_id=fixture_id,
                                  prediction_utc=prediction_utc) for c in claims]
    grouped = {}
    for p in rows:
        key = (p["claim_key"], p["evidence_level"])
        grouped.setdefault(key, []).append(p)
    output = []
    for (key, level), group in sorted(grouped.items()):
        # Multiple claims from one provider do not constitute corroboration.
        provider_values = {}
        for p in group:
            provider_values.setdefault(p["provider"], set()).add(
                json.dumps(p["claim_value"], sort_keys=True))
        distinct = set().union(*provider_values.values())
        output.append(dict(claim_key=key, evidence_level=level,
                           independent_providers=len(provider_values),
                           status="CONFLICT" if len(distinct) > 1 else
                                  "MULTI_SOURCE_AGREEMENT" if len(provider_values) > 1 else
                                  "SINGLE_SOURCE"))
    return output
