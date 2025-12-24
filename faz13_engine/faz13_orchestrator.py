"""
faz13_orchestrator.py - handles incoming Telegram updates and routes commands to appropriate handlers.
"""
from faz17_engine import faz17_market_fetcher as fetcher
from faz17_engine import providers

def handle_update(update):
    """
    Process a Telegram update (dictionary) and respond to commands.
    """
    if not update:
        return
    message = update.get("message")
    if not message:
        # If there's no message (could be an edit or callback), we ignore
        return
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    if not chat_id or text is None:
        # Nothing to do if no chat or no text content
        return
    text = text.strip()
    # Determine command and take action
    if text.startswith("/start") or text.startswith("/help"):
        # Send a welcome/help message
        help_text = (
            "Welcome to OddsBot!\n"
            "Available commands:\n"
            "/sports - List available sports\n"
            "/odds <sport_key> - Show odds for upcoming games of the given sport\n"
        )
        providers.send_message(chat_id, help_text)
    elif text.startswith("/sports"):
        sports = fetcher.get_sports_list()
        if sports is None:
            providers.send_message(chat_id, "⚠️ Unable to fetch sports list at the moment. Please try again later.")
        elif len(sports) == 0:
            providers.send_message(chat_id, "No sports data available.")
        else:
            # Prepare sports list message
            lines = []
            for sport in sports:
                key = sport.get("key")
                title = sport.get("title")
                # Append "group" or description if needed
                lines.append(f"{title} (key: {key})")
            message_text = "🏅 Available Sports:\n" + "\n".join(lines)
            providers.send_message(chat_id, message_text)
    elif text.startswith("/odds"):
        parts = text.split()
        if len(parts) < 2:
            # User did not provide sport key
            providers.send_message(chat_id, "Usage: /odds <sport_key>\nExample: /odds soccer_epl")
        else:
            sport_key = parts[1]
            data = fetcher.get_odds_for_sport(sport_key)
            if data is None:
                providers.send_message(chat_id, f"⚠️ Could not retrieve odds for '{sport_key}'.")
            elif len(data) == 0:
                providers.send_message(chat_id, f"No upcoming games found for sport '{sport_key}'.")
            else:
                lines = []
                max_events = 3  # limit to first 3 events for brevity
                for event in data[:max_events]:
                    home_team = event.get("home_team")
                    away_team = event.get("away_team")
                    # If no teams info, skip
                    if not home_team or not away_team:
                        continue
                    bookmakers = event.get("bookmakers", [])
                    if not bookmakers:
                        continue
                    # Take the first bookmaker's odds
                    book = bookmakers[0]
                    book_name = book.get("title") or book.get("key")
                    # Find odds for home and away in outcomes
                    odds_home = odds_away = None
                    outcomes = []
                    if book.get("markets"):
                        outcomes = book["markets"][0].get("outcomes", [])
                    for outcome in outcomes:
                        if outcome.get("name") == home_team:
                            odds_home = outcome.get("price")
                        elif outcome.get("name") == away_team:
                            odds_away = outcome.get("price")
                    if odds_home is not None and odds_away is not None:
                        line = f"{away_team} @ {home_team}:\n {book_name} odds → {away_team}: {odds_away}, {home_team}: {odds_home}"
                    else:
                        line = f"{away_team} @ {home_team}: odds data not available"
                    lines.append(line)
                if len(data) > max_events:
                    lines.append(f"(and {len(data) - max_events} more events)")
                message_text = "\n\n".join(lines)
                providers.send_message(chat_id, message_text)
    else:
        # Unrecognized text message (not a command)
        providers.send_message(chat_id, "🤖 Send /help to see available commands.") 
