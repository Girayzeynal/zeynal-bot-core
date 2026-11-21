"""Deterministic separate research protocol namespaces for isolated test runs.

An old plan.json/plan-*.json permanently belongs to its original policy and
source code pins. A new source implementation must NOT mutate or adopt it.
Each experiment family receives a fresh subdirectory only if its own policy
or source SHA changes. The raw provider input directory remains separate.

A namespace label is NOT proof of external source authenticity, player-model
calibration, or promotion eligibility.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import json

FAMILIES=("adaptive-v2","nba-v3","current-assessment")


def namespace(root, family, *, policy, source_pins):
    if family not in FAMILIES:
        raise ValueError("RESEARCH_VERSION_UNKNOWN_FAMILY")
    if not isinstance(policy,dict) or not isinstance(source_pins,dict) or not source_pins:
        raise ValueError("RESEARCH_VERSION_POLICY_AND_SOURCE_PINS_REQUIRED")
    if any(type(v) is not str or len(v)!=64 or
           any(c not in "0123456789abcdef" for c in v)
           for v in source_pins.values()):
        # Issue90 V1/V2 pins may be nested maps; authenticate exact canonical
        # *structure* in the parent signed research plan instead.
        if not all(isinstance(v,(dict,str)) for v in source_pins.values()):
            raise ValueError("RESEARCH_VERSION_PINS_CONTRACT")
    payload=dict(family=family,policy=policy,source_pins=source_pins)
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
    pin=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    base=Path(root).expanduser().absolute()
    if base.is_symlink():
        raise ValueError("RESEARCH_VERSION_SYMLINK_ROOT_REFUSED")
    # No directory write: constructors create their own only when actually
    # enabled by the isolated Telegram test process.
    return base/"research-protocols"/family/("protocol-"+pin[:20])
