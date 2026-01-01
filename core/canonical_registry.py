# NBA için TEK gerçeklik katmanı

NBA_TEAMS = {
    134: {
        "abbr": "BKN",
        "name": "Brooklyn Nets",
        "providers": {
            "espn": {"abbr": "bkn", "team_id": 17},
        }
    },
    142: {
        "abbr": "HOU",
        "name": "Houston Rockets",
        "providers": {
            "espn": {"abbr": "hou", "team_id": 10},
        }
    },
    # ŞİMDİLİK: sadece bu iki takım
    # Sonra 30'a tamamlanacak
}

def get_nba_team(canonical_team_id: int):
    return NBA_TEAMS.get(canonical_team_id)
