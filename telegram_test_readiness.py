"""Offline Telegram readiness checks without touching production secrets or Fly volumes."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Readiness:
    status: str
    blockers: tuple[str, ...]
    notes: tuple[str, ...]


def assess_telegram_test_readiness(*, env=None, test_token_present=None,
                                   isolated_storage=None, ci_passed=False):
    """Explicit evidence only: missing proof is a blocker, not a guessed success.

    The caller should pass token presence and storage isolation after checking
    the *test* deployment. Token values are never read or returned.
    """
    env = os.environ if env is None else env
    blockers = []
    if ci_passed is not True:
        blockers.append("CI_NOT_VERIFIED")
    if test_token_present is not True:
        blockers.append("SEPARATE_TEST_TELEGRAM_TOKEN_NOT_VERIFIED")
    if isolated_storage is not True:
        blockers.append("TEST_STORAGE_ISOLATION_NOT_VERIFIED")
    if str(env.get("NBA_LEDGER_ENABLED", "false")).lower() != "true":
        blockers.append("TEST_LEDGER_NOT_ENABLED")
    path = str(env.get("NBA_LEDGER_PATH", ""))
    if not path or not os.path.isabs(path):
        blockers.append("TEST_LEDGER_PATH_NOT_ABSOLUTE")
    if path and os.path.isabs(path):
        # Normalize traversal and symlinks before checking protected locations.
        resolved = Path(path).resolve(strict=False)
        if resolved == Path("/data/nba_prediction_ledger.sqlite"):
            blockers.append("PRODUCTION_LEDGER_FILENAME_NOT_ALLOWED_FOR_TEST")
        if resolved == Path("/data") or resolved == Path("/data/nba_prediction_ledger.sqlite"):
            blockers.append("TEST_LEDGER_NOT_ISOLATED")
    elif path == "/data/nba_prediction_ledger.sqlite":
        blockers.append("PRODUCTION_LEDGER_FILENAME_NOT_ALLOWED_FOR_TEST")
    baseline = str(env.get("BASELINE_DIR", ""))
    if baseline and Path(baseline).resolve(strict=False) == Path("/data/baselines"):
        blockers.append("PRODUCTION_BASELINE_PATH_NOT_ALLOWED_FOR_TEST")
    faz23 = str(env.get("FAZ23_STORAGE", ""))
    if faz23 and Path(faz23).resolve(strict=False) == Path("/data/faz23_storage.sqlite"):
        blockers.append("PRODUCTION_FAZ23_PATH_NOT_ALLOWED_FOR_TEST")
    return Readiness(
        status="READY_FOR_ISOLATED_TEST" if not blockers else "BLOCKED",
        blockers=tuple(blockers),
        notes=("No Telegram polling or provider calls performed",
               "No Fly deployment or volume changes performed"))
