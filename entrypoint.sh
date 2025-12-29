#!/bin/bash
set -e

echo "🚀 Dynamic Scheduler başlatılıyor..."
python dynamic_scheduler.py &

echo "🤖 Telegram Bot (main.py) başlatılıyor..."
python main.py
