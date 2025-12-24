"""
faz22_meta.py - handles environment configuration (loading tokens and API keys) and Flask settings.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env if available
load_dotenv()

# Telegram Bot Token and Odds API Key from environment or default (example values)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8395841768:AAEmrUCXtIr3n2t2Pf2jTw46Py2w9M9AC-A")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "8b4be7b33821ec3702c3a7e2d520179")

# Example usage of .env:
# TELEGRAM_TOKEN=8395841768:AAEmrUCXtIr3n2t2Pf2jTw46Py2w9M9AC-A
# ODDS_API_KEY=8b4be7b33821ec3702c3a7e2d520179

# Default values for region and market in Odds API queries
DEFAULT_REGION = "us"
DEFAULT_MARKET = "h2h"

# Flask app configuration
class Config:
    ENV = "production"
    DEBUG = False
    # Bind to all interfaces on given port (for Fly.io deployment, use environment port)
    # Optionally, set other config like SECRET_KEY if needed for sessions
    # SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret") 
