"""Read-only deployment preflight for persistent NBA predictions.

Run inside the target image with the target environment and mounted volume.
No database is created or modified.
"""
import os
from pathlib import Path
import sys


def inspect(env=None, exists=None, is_mount=None):
    env = os.environ if env is None else env
    exists = Path.exists if exists is None else exists
    is_mount = os.path.ismount if is_mount is None else is_mount
    problems = []
    enabled = env.get("NBA_LEDGER_ENABLED", "false").strip().lower() == "true"
    path = Path(env.get("NBA_LEDGER_PATH", "/data/nba_prediction_ledger.sqlite"))
    if not enabled:
        problems.append("NBA_LEDGER_ENABLED is not true")
    if not path.is_absolute() or path.suffix != ".sqlite":
        problems.append("NBA_LEDGER_PATH must be an absolute .sqlite path")
    else:
        # Reject paths escaping the volume, including ../ and symlink escapes.
        resolved = path.resolve(strict=False)
        volume = Path("/data").resolve(strict=False)
        if volume not in resolved.parents:
            problems.append("NBA_LEDGER_PATH must resolve inside /data")
    if not is_mount("/data"):
        problems.append("/data is not a mounted persistent volume")
    if not exists(path.parent):
        problems.append("ledger parent directory does not exist")
    required = ("prediction_ledger.py", "ledger_storage_config.py",
                "prematch_ledger_bridge.py", "telegram_result_audit.py")
    root = Path(__file__).resolve().parent
    for module in required:
        if not exists(root / module):
            problems.append("missing module: " + module)
    return problems


def main():
    problems = inspect()
    if problems:
        for issue in problems:
            print("FAIL:", issue, file=sys.stderr)
        return 1
    print("PASS: ledger configuration, volume mount and modules present")
    print("NOTE: this does not verify Telegram polling or real prediction writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
