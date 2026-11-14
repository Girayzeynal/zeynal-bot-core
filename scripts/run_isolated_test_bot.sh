#!/usr/bin/env bash
# Isolated Android/UserLAnd test bot restart. Never touches Fly.io production.
set -Eeuo pipefail
cd "${HOME}/zeynal-hybrid-844"
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
# Identity variables must be supplied by the private local environment.
: "${ZEYNAL_TEST_BOT_ID:?TEST_BOT_ID_REQUIRED}"
: "${ZEYNAL_TEST_BOT_USERNAME:?TEST_BOT_USERNAME_REQUIRED}"
: "${ZEYNAL_TEST_CHAT_ID:?TEST_CHAT_ID_REQUIRED}"
export PYTHONPATH="$PWD"
exec .venv/bin/python -m hybrid_engine.test_bot \
  --archive-directory "${HOME}/zeynal-test-isolated/archive" \
  --data-directory "${HOME}/zeynal-test-isolated/data" \
  --nba-model "${model}" \
  --nba-model-sha ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e \
  --result-poll-seconds 300
