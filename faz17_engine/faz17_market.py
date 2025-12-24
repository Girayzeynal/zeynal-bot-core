"""
faz17_market_fetcher.py - functions for fetching and caching sports and odds data from the Odds API.
"""
import time
from faz17_engine import providers

# Simple in-memory cache for sports list and odds
_sports_cache = None
_sports_cache_time = 0
_odds_cache = {}  # cache per sport_key

def get_sports_list():
    """
    Retrieves the list of sports (with caching to minimize API calls).
    Returns: list of sports (dicts) or None on failure.
    """
    global _sports_cache, _sports_cache_time
    # Use cache if last fetched within 1 hour
    if _sports_cache is not None and time.time() - _sports_cache_time < 3600:
        return _sports_cache
    sports = providers.get_sports()
    if sports is None:
        return None
    # Filter to active sports only
    sports_list = [sport for sport in sports if sport.get("active")]
    # Update cache
    _sports_cache = sports_list
    _sports_cache_time = time.time()
    return sports_list

def get_odds_for_sport(sport_key):
    """
    Retrieves odds for upcoming games for the given sport (with simple caching).
    Returns: list of events with odds or None on failure.
    """
    global _odds_cache
    # Use cache if available and data fetched within last 60 seconds
    if sport_key in _odds_cache:
        cached = _odds_cache[sport_key]
        if time.time() - cached['time'] < 60:
            return cached['data']
    data = providers.get_odds(sport_key)
    if data is not None:
        # Update cache
        _odds_cache[sport_key] = {'time': time.time(), 'data': data}
    return data 
