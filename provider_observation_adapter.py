"""Normalize authenticated provider payloads into traceable evidence.

No network access. Caller must authenticate the HTTPS response and explicitly
map the provider's fields. SHA-256 establishes byte integrity, not truthfulness.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from urllib.parse import urlsplit

from multi_source_evidence import Observation


@dataclass(frozen=True)
class SourceEnvelope:
    observation: Observation
    payload_sha256: str
    fetched_at_utc: int
    provider_event_id: str


def normalize_numeric_observation(
    *, provider: str, independent_group: str,
    fixture_id: str, provider_event_id: str,
    field: str, value_path: tuple[str, ...],
    payload: dict, fetched_at_utc: int,
    source_url: str, event_id_path: tuple[str, ...],
) -> SourceEnvelope:
    """Fail closed on missing, ambiguous or malformed provider fields.

    The adapter is responsible for selecting a documented, provider-specific
    value path and event identity path; no inferred field aliases are used.
    """
    for name, value in (
        ("provider", provider), ("independent_group", independent_group),
        ("fixture_id", fixture_id), ("provider_event_id", provider_event_id),
        ("field", field),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Missing " + name)
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Source must be an HTTPS URL without credentials")
    if type(fetched_at_utc) is not int or fetched_at_utc <= 0:
        raise ValueError("Invalid fetch timestamp")
    if not isinstance(payload, dict):
        raise ValueError("Provider payload must be an object")
    if not value_path or not event_id_path or any(
        not isinstance(k, str) or not k for k in value_path + event_id_path
    ):
        raise ValueError("Explicit field paths required")

    def read(path):
        node = payload
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise ValueError("Missing documented provider field")
            node = node[key]
        return node

    if str(read(event_id_path)) != provider_event_id:
        raise ValueError("Provider event identity mismatch")
    number = read(value_path)
    if type(number) not in (int, float) or not math.isfinite(number):
        raise ValueError("Provider value must be a finite numeric type")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    observation = Observation(
        provider=provider, independent_group=independent_group,
        fixture_id=fixture_id, field=field, value=float(number),
        observed_at_utc=fetched_at_utc, source_url=source_url,
    )
    return SourceEnvelope(observation, digest, fetched_at_utc, provider_event_id)
