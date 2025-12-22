# -*- coding: utf-8 -*-
"""
FAZ-23 Team Name Mapper (ELITE LEAGUES)

Amaç:
- Kullanıcıdan gelen takım adını normalize etmek
- Provider'ın (API-SPORTS / ODDS) anlayacağı formata dönüştürmek

Not:
- Lig zaten /mac komutunda geliyor -> lig tespiti yok.
"""

from __future__ import annotations
from typing import Optional, Dict

def normalize_team_name(name: str) -> str:
    return (name or "").lower().strip()

# Elite leagues priority keys
# NBA, EUROLEAGUE, ACB, BSL, VTB, BBL, LBA, LNB, ABA, A1, NBL, LKL, CBA
TEAM_MAP: Dict[str, Dict[str, Dict[str, str]]] = {
    "NBA": {
        "boston": {"api_sports": "Boston Celtics", "odds": "Boston Celtics"},
        "indiana": {"api_sports": "Indiana Pacers", "odds": "Indiana Pacers"},
        "denver": {"api_sports": "Denver Nuggets", "odds": "Denver Nuggets"},
        "utah": {"api_sports": "Utah Jazz", "odds": "Utah Jazz"},
        "milwaukee": {"api_sports": "Milwaukee Bucks", "odds": "Milwaukee Bucks"},
        "los angeles lakers": {"api_sports": "Los Angeles Lakers", "odds": "LA Lakers"},
        "lakers": {"api_sports": "Los Angeles Lakers", "odds": "LA Lakers"},
        "phoenix": {"api_sports": "Phoenix Suns", "odds": "Phoenix Suns"},
        "suns": {"api_sports": "Phoenix Suns", "odds": "Phoenix Suns"},
    },

    "EUROLEAGUE": {
        "fenerbahce": {"api_sports": "Fenerbahce", "odds": "Fenerbahce"},
        "anadolu efes": {"api_sports": "Anadolu Efes", "odds": "Anadolu Efes"},
        "olympiacos": {"api_sports": "Olympiacos", "odds": "Olympiacos"},
        "panathinaikos": {"api_sports": "Panathinaikos", "odds": "Panathinaikos"},
        "real madrid": {"api_sports": "Real Madrid", "odds": "Real Madrid"},
        "barcelona": {"api_sports": "Barcelona", "odds": "Barcelona"},
    },

    # Diğer ligler: başlangıç. Genişletilebilir.
    "ACB": {},
    "BSL": {},
    "VTB": {},
    "BBL": {},
    "LBA": {},
    "LNB": {},
    "ABA": {},
    "A1": {},
    "NBL": {},
    "LKL": {},
    "CBA": {},
}

def map_team(league: str, team_name: str, provider: str) -> Optional[str]:
    lg = (league or "").upper().strip()
    key = normalize_team_name(team_name)
    provider = (provider or "").strip()

    table = TEAM_MAP.get(lg, {})
    data = table.get(key)
    if not data:
        # fallback: provider aynı ismi kabul edebilir
        # "None/Unknown" istemiyorsun -> bu yüzden ham ismi döndürürüz.
        # Provider kabul etmezse providers katmanı zaten hata verir.
        return team_name.strip()
    return data.get(provider) or team_name.strip() 
