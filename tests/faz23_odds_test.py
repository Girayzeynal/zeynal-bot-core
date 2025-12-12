from faz23_engine.faz23_odds_debug import debug_fetch_odds

print("=== FAZ23 ODDS DEBUG TEST START ===")

debug_fetch_odds(
    league="EUROLEAGUE",
    date_str="2025-12-12",
    home="Monaco",
    away="Fenerbahçe",
)

print("=== FAZ23 ODDS DEBUG TEST END ===")
