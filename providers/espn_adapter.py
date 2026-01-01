# providers/espn_adapter.py

import aiohttp
from typing import Optional, Dict

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


class ESPNAdapter:
    """
    ESPN provider adapter
    - Sadece veri çeker
    - Core veya FAZ logic içermez
    """

    name = "ESPN"
    confidence = 0.60  # hızlı ama resmi değil

    async def fetch_team_baseline(self, team_abbr: str) -> Optional[Dict]:
        """
        ESPN team endpoint üzerinden ortalama sayı verilerini alır.

        Returns:
            {
                "pts_for": float,
                "pts_against": float,
                "confidence": float,
                "source": "ESPN"
            }
        """
        url = f"{ESPN_BASE}/teams/{team_abbr}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        items = data.get("team", {}).get("record", {}).get("items", [])
        stats = {}

        for item in items:
            for st in item.get("stats", []):
                stats[st.get("name")] = st.get("value")

        if "avgPointsFor" not in stats or "avgPointsAgainst" not in stats:
            return None

        return {
            "pts_for": float(stats["avgPointsFor"]),
            "pts_against": float(stats["avgPointsAgainst"]),
            "confidence": self.confidence,
            "source": self.name,
        } 
