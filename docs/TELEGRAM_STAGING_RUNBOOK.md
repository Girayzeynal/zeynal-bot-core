# Telegram staging: operator runbook (not a deployment)

This file documents the **separate** staging environment. None of the steps below
has been executed by adding this file to GitHub.

## Required gates

1. GitHub Python regression and Telegram audit workflows both pass for the
   exact commit intended for staging.
2. Obtain explicit operator approval before creating a potentially billable
   Fly application or volume.
3. Create a separate Telegram bot using BotFather. Never reuse the production
   bot token: two pollers using the same token conflict.
4. Create a dedicated Fly app named `zeynal-bot-core-staging` and a dedicated
   volume named `zeynal_test_data` in `ams`. Verify they are not the
   production app `zeynal-bot-core` or volume `zeynal_data`.
5. Set staging-only `TELEGRAM_BOT_TOKEN` and `API_SPORTS_KEY` as Fly secrets.
   Do not paste secret values into GitHub, chat, screenshots or CI logs.
6. Use `fly.staging.toml` **only with the staging app**. The configured paths
   under `/data/test_*` must resolve to the dedicated staging volume.
7. Verify `/ready` returns success after boot; `/health` alone is not proof
   that Telegram polling is active.
8. In the **test** Telegram bot run `/start`, `/newscheck NBA <real_espn_id>`,
   `/analyze NBA <verified fixture>`, and `/compare NBA <archived fixture>`.
   Do not treat a fabricated fixture ID as a valid end-to-end test.

## Operational restrictions

- No production deployment, PR merge, production secret rotation, machine
  destruction, volume deletion, or snapshot deletion is authorized by this file.
- A green CI result proves only automated test coverage, not a successful
  staging or live provider integration.
- `/newscheck` reads archived news evidence; it does not fetch live news.
- `/compare` requires a verified archived final score and a recorded pregame
  prediction; do not fabricate either to make the command pass.
- Stop staging polling before changing its Telegram token or running a second
  poller for the same staging bot.
- Record the staging app name, volume name, tested commit, command results and
  redacted errors before requesting production rollout approval.
