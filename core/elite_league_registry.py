# core/elite_league_registry.py

def normalize_league_input(raw: str) -> str:
    s = (raw or "").strip().upper()

    aliases = {
        "EL": "EUROLEAGUE",
        "EUROLEAGUE": "EUROLEAGUE",
        "EURO LEAGUE": "EUROLEAGUE",
        "NBA": "NBA",
        "TBL": "TBL",
        "BSL": "TBL",
        "TURKEY": "TBL",
        "CBA": "CBA",
        "CHINA": "CBA",
        "JAPAN": "JAPAN",
        "B.LEAGUE": "JAPAN",
        "B.LEAG": "JAPAN",
        "LEGA": "LEGA",
        "LBA": "LEGA",
        "SERIE A": "LEGA",
    }
    return aliases.get(s, s or "UNKNOWN")
