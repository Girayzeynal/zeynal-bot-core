#!/usr/bin/env bash
# Isolated Android/UserLAnd test bot restart. Never touches Fly.io production.
set -Eeuo pipefail
# Run the code from THIS checkout, including a separate integration worktree.
launcher_checkout="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${launcher_checkout}"
test_python="${launcher_checkout}/.venv/bin/python"
if [[ ! -x "${test_python}" ]]; then test_python="${HOME}/zeynal-hybrid-844/.venv/bin/python"; fi
if [[ ! -x "${test_python}" ]]; then echo "ISOLATED_PYTHON_NOT_FOUND" >&2; exit 2; fi
# Diagnostics can run alongside the poller. They neither update Git nor start
# Telegram, and read only dedicated local data-provider credentials.
if [[ "${1:-}" == "--provider-check" ]]; then
  exec "${test_python}" -m hybrid_engine.provider_access --check
fi
# Explicit source inventory, no secrets or network by default.
if [[ "${1:-}" == "--source-inventory" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_SOURCE_INVENTORY_ARGS" >&2; exit 2; fi
  exec "${test_python}" -B -m hybrid_engine.source_inventory
fi
# Explicit robots-gated club entry audit, never player status or model input.
if [[ "${1:-}" == "--club-source-check" ]]; then
  shift
  if [[ "$#" -gt 1 || ( "$#" -eq 1 && "$1" != "--problems-only" ) ]]; then echo "INVALID_CLUB_SOURCE_CHECK_ARGS" >&2; exit 2; fi
  exec "${test_python}" -B -m hybrid_engine.official_all_82_club_batch --live --summary "$@"
fi
# Offline PDF replay is read-only and can run WHILE the isolated bot polls.
# Never refreshes expired medical evidence, never updates git or predictions.
# Explicit synthetic offline PLAYER_BAYES smoke. Never starts Telegram,
# contacts providers, touches first forecasts, or uses production artifacts.
# Can run in a second Android terminal while the Telegram poller is active.
# Read existing native player boxes only. This is a conditional statistical
# research pilot, NOT an authenticated availability or active score model.
if [[ "${1:-}" == "--player-box-pilot" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_PLAYER_PILOT_ARGS" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
  exec "${test_python}" -B -m hybrid_engine.player_box_pilot \
    --data-directory "${HOME}/zeynal-test-isolated/data"
fi
if [[ "${1:-}" == "--player-effect-smoke" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_PLAYER_SMOKE_ARGS" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
  exec "${test_python}" -B -m hybrid_engine.player_effect_smoke \
    --output "${HOME}/zeynal-test-isolated/data/player-effect-smoke.json"
fi
if [[ "${1:-}" == "--roster-pdf-audit" ]]; then
  if [[ "$#" -ne 3 ]]; then echo "INVALID_OFFLINE_PDF_AUDIT_ARGS" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -B -m hybrid_engine.roster_pdf_audit \
    --directory "${HOME}/zeynal-test-isolated/data/official-reports" \
    --matchup "$2" --game-date "$3"
fi
if [[ "${1:-}" == "--settle-results" || "${1:-}" == "--results-review" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  result_args=()
  if [[ "$1" == "--settle-results" ]]; then result_args=(--apply); fi
  exec "${test_python}" -B -m scripts.settle_all_leagues --data-directory "${HOME}/zeynal-test-isolated/data" "${result_args[@]}"
fi
if [[ "${1:-}" == "--verification-review" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -B -m hybrid_engine.device_verification \
    --data-directory "${HOME}/zeynal-test-isolated/data"
fi
if [[ "${1:-}" == "--pipeline-audit" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  exec "${test_python}" -B -m hybrid_engine.pipeline_audit \
    --data-directory "${HOME}/zeynal-test-isolated/data" \
    --nba-model "${HOME}/zeynal-test-isolated/models/nba-prepared-ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e.json" \
    --nba-model-sha ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e
fi
if [[ "${1:-}" == "--issue90-status" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  exec "${test_python}" -B -m hybrid_engine.issue90_research \
    --directory "${HOME}/zeynal-test-isolated/data/nba-research-v3-integrity-v2"
fi
if [[ "${1:-}" == "--issue90-audit" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  exec "${test_python}" -B -m hybrid_engine.nba_failure_audit \
    --ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
    --assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets" \
    --output-directory "${HOME}/zeynal-test-isolated/data/issue90/reports"
fi
# Offline read-only archive/input diagnosis. No token/model bootstrap, Git
# update, network access, fitting, polling, or existing forecast writes.
if [[ "${1:-}" == "--error-review" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  plan_dir="${HOME}/zeynal-test-isolated/data/quality-phase92/calibration-plan"
  plan_args=()
  if compgen -G "${plan_dir}/plan-*.json" >/dev/null; then
    plan_args=(--existing-calibration-plan-directory "${plan_dir}")
  fi
  exec "${test_python}" -m hybrid_engine.quality_report \
    --ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
    --assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets" \
    --output-directory "${HOME}/zeynal-test-isolated/data/quality-phase924/reports" "${plan_args[@]}"
fi
# Read-only automatic capture status can run without stopping the poller.
if [[ "${1:-}" == "--europe-prematch-status" || "${1:-}" == "--nba-overnight-status" || "${1:-}" == "--adaptive-status" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi
  status_directory="europe-prematch"
  if [[ "$1" == "--nba-overnight-status" ]]; then status_directory="nba-overnight"; fi
  if [[ "$1" == "--adaptive-status" ]]; then status_directory="adaptive-v2/attempts"; fi
  exec "${test_python}" -B -m hybrid_engine.europe_prematch \
    --directory "${HOME}/zeynal-test-isolated/data/${status_directory}"
fi
# Read-only first-forecast audit: safe alongside the running test poller.
# No Git fetch, no bot token, no lock, no new forecast, no SQLite write.
if [[ "${1:-}" == "--first-forecast-audit" || "${1:-}" == "--first-forecast-audit-json" ]]; then
  if [[ "$#" -ne 1 ]]; then echo "INVALID_FIRST_FORECAST_AUDIT_ARGS" >&2; exit 2; fi
  ledger_path="${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite"
  if [[ ! -f "${ledger_path}" ]]; then
    echo "FIRST_FORECAST_ARCHIVE_NOT_FOUND: ${ledger_path}" >&2
    exit 2
  fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
  report_args=()
  if [[ "$1" == "--first-forecast-audit-json" ]]; then report_args=(--json); fi
  exec "${test_python}" -B -m hybrid_engine.first_forecast_walkforward \
    --ledger "${ledger_path}" --league NBA "${report_args[@]}"
fi
# One isolated poller per local installation; prevent Telegram getUpdates conflicts.
lock_dir="${HOME}/zeynal-test-isolated"
mkdir -p "${lock_dir}"
if ! command -v flock >/dev/null 2>&1; then
  echo "FLOCK_REQUIRED_FOR_SINGLE_INSTANCE" >&2
  exit 2
fi
exec 9>"${lock_dir}/test-bot.lock"
if ! flock -n 9; then
  echo "TEST_BOT_ALREADY_RUNNING: existing process kept untouched" >&2
  exit 0
fi
branch="$(git branch --show-current)"
case "$branch" in
  feature/hybrid-market-roster-evidence-20261114|feature/issue90-nba-verification-20261118|feature/critical-integrity-audit-20261118|feature/europe-alias-replay-ui-20261118|feature/model-data-pipeline-audit-20261118|feature/issue90-chronological-engine-audit-20261118|feature/integrated-test-bot-20261119|feature/three-league-roster-integration-20261121|fix/telegram-current-panels-20261122|fix/v3-before-slow-v2-20261124|feat/first-forecast-walkforward-20261124|integration/nba-v3-calibration-20261124|feat/first-forecast-paired-diagnostics-20261124|feat/first-forecast-period-errors-20261124|integration/nba-three-axis-release-candidate-20261124) ;;
  *) echo "WRONG_BRANCH: checkout an isolated test branch first" >&2; exit 2 ;;
esac
launcher_path="${PWD}/scripts/run_isolated_test_bot.sh"
launcher_before="$(sha256sum -- "${launcher_path}")"
git fetch origin "${branch}"
if [[ "$(git branch --show-current)" != "${branch}" ]]; then
  echo "WRONG_BRANCH: checkout the test branch first" >&2
  exit 2
fi
git merge --ff-only FETCH_HEAD
if [[ "$(sha256sum -- "${launcher_path}")" != "${launcher_before}" ]]; then
  # Bash can keep reading the old inode/buffer after Git replaces this file.
  # Reload before dispatching the requested mode; close the inherited lock so
  # the new invocation acquires it normally instead of rejecting itself.
  echo "RESTARTING_UPDATED_LAUNCHER" >&2
  exec 9>&-
  exec bash "${launcher_path}" "$@"
fi
case "${1:-}" in
  "")
    if [[ "$#" -ne 0 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi ;;
  --player-inputs-plan|--player-inputs-all|--player-shadow-review|--player-shadow-results|--roster-setup|--challenger-review|--challenger-summary|--challenger-plan|--challenger-capture|--challenger-results|--prepare-europe)
    if [[ "$#" -ne 1 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi ;;
  --europe-data-check)
    if [[ "$#" -ne 3 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi ;;
  --player-inputs|--roster-status|--roster-pdf)
    if [[ "$#" -ne 2 ]]; then echo "INVALID_LAUNCHER_ARGUMENTS" >&2; exit 2; fi ;;
  *)
    echo "UNKNOWN_LAUNCHER_OPTION: update the test checkout and use a documented mode" >&2
    exit 2 ;;
esac
if [[ "${1:-}" == "--europe-data-check" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.europe_data \
    --data-directory "${HOME}/zeynal-test-isolated/data" --league "$2" --fixture-id "$3"
fi
if [[ "${1:-}" == "--prepare-europe" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.europe_models \
    --directory "${HOME}/zeynal-test-isolated/data/europe/models"
fi
if [[ "${1:-}" == "--challenger-plan" || "${1:-}" == "--challenger-capture" || "${1:-}" == "--challenger-results" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  challenger_args=(--directory "${HOME}/zeynal-test-isolated/data/challenger-research/protocol")
  if [[ "$1" != "--challenger-plan" ]]; then
    challenger_args+=(--ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite")
  fi
  if [[ "$1" == "--challenger-capture" ]]; then
    challenger_args+=(--assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets")
  fi
  exec "${test_python}" -m hybrid_engine.challenger_forward "${1#--challenger-}" "${challenger_args[@]}"
fi
if [[ "${1:-}" == "--challenger-summary" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.challenger_summary \
    --directory "${HOME}/zeynal-test-isolated/data/challenger-research/reports"
fi
if [[ "${1:-}" == "--challenger-review" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.challenger_summary --run-review \
    --ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
    --assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets" \
    --output-directory "${HOME}/zeynal-test-isolated/data/challenger-research/reports"
fi
if [[ "${1:-}" == "--roster-pdf" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.official_report_link \
    --url "$2" --directory "${HOME}/zeynal-test-isolated/data/official-reports"
fi
if [[ "${1:-}" == "--roster-status" ]]; then
  if [[ ! "${2:-}" =~ ^[0-9]{1,15}$ ]]; then echo "NUMERIC_ESPN_FIXTURE_REQUIRED" >&2; exit 2; fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.current_roster \
    --fixture-id "$2" --inspect \
    --output-directory "${HOME}/zeynal-test-isolated/data/player-shadow/current-roster"
fi
if [[ "${1:-}" == "--player-inputs-plan" || "${1:-}" == "--player-inputs-all" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  player_args=()
  if [[ "${1}" == "--player-inputs-plan" ]]; then player_args=(--dry-run); fi
  exec "${test_python}" -m hybrid_engine.player_inputs \
    --ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
    --assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets" \
    --all-pending --maximum 4 "${player_args[@]}" \
    --output-directory "${HOME}/zeynal-test-isolated/data/player-shadow"
fi
if [[ "${1:-}" == "--player-inputs" ]]; then
  if [[ ! "${2:-}" =~ ^[0-9]{1,15}$ ]]; then
    echo "Kullanım: run_isolated_test_bot.sh --player-inputs ESPN_MAC_KIMLIGI" >&2
    exit 2
  fi
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.player_inputs \
    --ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite" \
    --assets-directory "${HOME}/zeynal-test-isolated/data/live-nba/assets" \
    --fixture-id "$2" --output-directory "${HOME}/zeynal-test-isolated/data/player-shadow"
fi
if [[ "${1:-}" == "--player-shadow-review" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.player_shadow \
    --directory "${HOME}/zeynal-test-isolated/data/player-shadow"
fi
if [[ "${1:-}" == "--player-shadow-results" ]]; then
  export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
  exec "${test_python}" -m hybrid_engine.player_shadow \
    --directory "${HOME}/zeynal-test-isolated/data/player-shadow" \
    --report-ledger "${HOME}/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite"
fi
if [[ "${1:-}" == "--roster-setup" ]]; then
  # Optional PDF extraction runs in a bounded child, never production main.py.
  "${test_python}" -m pip install -r requirements-injury-research.txt
fi
if [[ ! -f "${HOME}/.zeynal-elite-test-token" ]]; then
  echo "TEST_TOKEN_FILE_MISSING" >&2
  exit 2
fi
model="${HOME}/zeynal-test-isolated/models/nba-prepared-ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e.json"
if [[ ! -f "${model}" ]]; then
  echo "PINNED_MODEL_FILE_MISSING" >&2
  exit 2
fi
export ZEYNAL_TEST_BOT_TOKEN="$(cat "${HOME}/.zeynal-elite-test-token")"
# Dedicated isolated bot identity. Allow private environment overrides.
export ZEYNAL_TEST_BOT_ID="${ZEYNAL_TEST_BOT_ID:-9126277519}"
export ZEYNAL_TEST_BOT_USERNAME="${ZEYNAL_TEST_BOT_USERNAME:-ZeynalEliteTestBot}"
export ZEYNAL_TEST_CHAT_ID="${ZEYNAL_TEST_CHAT_ID:-7032156495}"
export ZEYNAL_RELEASE_SHA="$(git rev-parse --verify HEAD)"
# Bounded public-source index probes, each behind robots.txt; override with 0.
export ZEYNAL_PUBLIC_EURO_NEWS_ENABLED="${ZEYNAL_PUBLIC_EURO_NEWS_ENABLED:-1}"
export PYTHONPATH="$PWD"
exec "${test_python}" -m hybrid_engine.test_bot \
  --archive-directory "${HOME}/zeynal-test-isolated/archive" \
  --data-directory "${HOME}/zeynal-test-isolated/data" \
  --nba-model "${model}" \
  --nba-model-sha ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e \
  --europe-directory "${HOME}/zeynal-test-isolated/data/europe" \
  --result-poll-seconds 300
