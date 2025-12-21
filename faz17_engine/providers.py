import os
import time
from typing import Any, Dict, Optional
import requests

def faz17_fetch_market(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    Eğer ODDS_API_URL tanımlıysa oradan market çekmeyi dener.
    Yoksa totals_line=None döner (sistem kırılmaz).
    """
    url = os.getenv("ODDS_API_URL", "").strip()
    api_key = os.getenv("ODDS_API_KEY", "").strip()

    if not url:
        return {
            "provider": "none",
            "totals_line": None,
            "over_odds": None,
            "under_odds": None,
            "book": None,
            "ts": int(time.time()),
            "raw": None,
        }

    try:
        params = {
            "league": league,
            "date": date_str,
            "home": home,
            "away": away,
        }
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json() if r.content else {}

        # Beklenen minimal alan: totals_line
        totals_line = data.get("totals_line", None)
        return {
            "provider": "odds_api",
            "totals_line": totals_line,
            "over_odds": data.get("over_odds"),
            "under_odds": data.get("under_odds"),
            "book": data.get("book"),
            "ts": int(time.time()),
            "raw": data,
        }
    except Exception:
        return {
            "provider": "odds_api_error",
            "totals_line": None,
            "over_odds": None,
            "under_odds": None,
            "book": None,
            "ts": int(time.time()),
            "raw": None,
        }
