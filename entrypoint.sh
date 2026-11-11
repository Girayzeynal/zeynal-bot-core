#!/bin/bash
set -e

# Exactly one process owns Telegram polling. The verified command application
# owns its optional scheduler lifecycle; never start a second Telegram bot.
exec python -u main.py
