"""Fail-closed configuration for the canonical NBA prediction ledger.

The production ledger must live on a persistent Fly volume. A missing or
unwritable mount is a startup error when ledger persistence is enabled.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LEDGER_PATH = "/data/nba_prediction_ledger.sqlite"


def resolve_prediction_ledger_path(
    *, enabled: bool, configured_path: str | None = None,
    volume_root: str = "/data",
) -> str | None:
    if not enabled:
        return None
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise ValueError("Persistent volume root is required")
    root = Path(volume_root).resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("Persistent volume root is not a directory")
    raw = configured_path if configured_path is not None else DEFAULT_LEDGER_PATH
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Ledger path is required")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("Ledger path must be absolute")
    resolved = path.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise ValueError("Ledger must be inside the persistent volume")
    parent = resolved.parent
    if not parent.is_dir():
        raise RuntimeError("Ledger parent directory does not exist")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise RuntimeError("Ledger volume directory is not writable")
    if resolved.exists() and (not resolved.is_file() or not os.access(resolved, os.W_OK)):
        raise RuntimeError("Ledger database is not writable")
    return str(resolved)
