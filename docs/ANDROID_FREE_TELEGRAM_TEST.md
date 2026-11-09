# Zero-new-Fly-cost Telegram smoke test (Android/UserLAnd)

This is an operator procedure, **not** a claim that a Telegram test ran.
Use a dedicated test bot token from BotFather, never the production token.

## 1. Clone the exact feature branch

```sh
git clone --branch feature/telegram-result-audit-issue74 --single-branch https://github.com/Girayzeynal/zeynal-bot-core.git zeynal-telegram-test
cd zeynal-telegram-test
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
```

Check the commit with `git rev-parse HEAD` and compare with the latest
GitHub CI commit. Do not proceed if dependencies or unit tests fail.

## 2. Separate secrets and local state

```sh
mkdir -p "$HOME/zeynal-staging/baselines"
export BASELINE_DIR="$HOME/zeynal-staging/baselines"
export FAZ23_STORAGE="$HOME/zeynal-staging/faz23.sqlite"
export SCHEDULER_DB="$HOME/zeynal-staging/scheduler.sqlite"
export NBA_LEDGER_ENABLED=true
export NBA_LEDGER_PATH="$HOME/zeynal-staging/nba_prediction_ledger.sqlite"
```

Enter the **test bot** token and API key in your private terminal without
posting them in chat or committing them. For example, use a hidden prompt:

```sh
read -rs -p 'TEST Telegram token: ' TELEGRAM_BOT_TOKEN; echo
export TELEGRAM_BOT_TOKEN
read -rs -p 'API sports key: ' API_SPORTS_KEY; echo
export API_SPORTS_KEY
```

`API_SPORTS_KEY` is currently required by `main.py` at startup.
Do not use the production bot token. Check that no other process polls
the test bot token.

## 3. Start local polling

```sh
python main.py
```

The Android/UserLAnd session must remain running and connected.
In the **test bot** chat run `/start`, then `/newscheck NBA <real ESPN
fixture ID>`. `/compare` needs a verified archived prediction and
final score; an empty ledger should report missing evidence, not invent
results. `/analyze` requires valid fixture data and working providers.

## 4. Shutdown

Stop the process with Ctrl+C. The test data remains under
`$HOME/zeynal-staging`. This procedure never creates a Fly app or
touches the production `zeynal_data` volume.

**Limitations:** Android can suspend UserLAnd. This is a temporary
smoke-test environment, not a 24/7 hosting replacement. GitHub Actions
free usage is subject to repository visibility and account limits.
