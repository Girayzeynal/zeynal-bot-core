#!/usr/bin/env bash
# Isolated Android/UserLAnd test bot restart. Never touches Fly.io production.
set -Eeuo pipefail
cd "${HOME}/zeynal-hybrid-844"
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
branch="feature/hybrid-market-roster-evidence-20261114"
git fetch origin "${branch}"
if [[ "$(git branch --show-current)" != "${branch}" ]]; then
  echo "WRONG_BRANCH: checkout the test branch first" >&2
  exit 2
fi
git merge --ff-only FETCH_HEAD
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
export PYTHONPATH="$PWD"
exec .venv/bin/python -m hybrid_engine.test_bot \
  --archive-directory "${HOME}/zeynal-test-isolated/archive" \
  --data-directory "${HOME}/zeynal-test-isolated/data" \
  --nba-model "${model}" \
  --nba-model-sha ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e \
  --result-poll-seconds 300
