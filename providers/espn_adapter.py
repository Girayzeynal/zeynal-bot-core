# providers/espn_adapter.py

import aiohttp

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

class ESPNAdapter:
    name = "ESPN"
    confidence = 0.60

    async def team_baseline(self, espn_abbr: str):
        url = f"{BASE}/teams/{espn_abbr}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                data = await resp.json()

        items = data.get("team", {}).get("record", {}).get("items", [])
        stats = {}

        for item in items:
            for st in item.get("stats", []):
                stats[st["name"]] = st.get("value")

        if "avgPointsFor" not in stats or "avgPointsAgainst" not in stats:
            return None

        return {
            "pts_for": float(stats["avgPointsFor"]),
            "pts_against": float(stats["avgPointsAgainst"]),
            "confidence": self.confidence,
            "source": self.name
        }
