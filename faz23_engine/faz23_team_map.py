# -*- coding: utf-8 -*-

"""
FAZ-23 Team Name Mapper
Amaç:
- Kullanıcıdan gelen takım adını
- API-SPORTS / ODDS API'nin anlayacağı forma dönüştürmek
"""

NBA_TEAM_MAP = {
    "milwaukee": {
        "api_sports": "Milwaukee Bucks",
        "odds": "Milwaukee Bucks",
    },
    "boston": {
        "api_sports": "Boston Celtics",
        "odds": "Boston Celtics",
    },
    "los angeles lakers": {
        "api_sports": "Los Angeles Lakers",
        "odds": "LA Lakers",
    },
    "chicago": {
        "api_sports": "Chicago Bulls",
        "odds": "Chicago Bulls",
    },
    # gerektiğinde genişletilir
}

def normalize_team_name(name: str) -> str:
    return name.lower().strip()

def map_team(team_name: str, provider: str) -> str | None:
    key = normalize_team_name(team_name)
    data = NBA_TEAM_MAP.get(key)
    if not data:
        return None
    return data.get(provider)
