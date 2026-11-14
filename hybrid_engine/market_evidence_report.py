"""Read-only bookmaker observations for research reporting.

This module intentionally lives outside the prepared Bayesian source pin. It does
not change model inputs, parameters, predictions, or historical snapshots.
"""
import json
from pathlib import Path

from hybrid_engine.observed_markets import observe_espn


def observed_market_evidence(assets, sources, fixture_id, prediction_utc, fixture_start_utc):
    """Collect matching pre-tipoff quotes without asserting an actionable edge."""
    latest = {}
    for ref in sources.values():
        try:
            receipt = json.loads((Path(assets) / ref['file']).read_text())
            if '/scoreboard?' not in receipt.get('source_url', ''):
                continue
            observed = observe_espn(receipt, now_utc=prediction_utc)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for quote in observed['quotes']:
            q = quote['payload']
            if (q['fixture_id'] != fixture_id or
                    q['fixture_start_utc'] != fixture_start_utc or
                    q['ingested_at_utc'] > prediction_utc or
                    q['observed_at_utc'] > prediction_utc or
                    q['observed_at_utc'] >= fixture_start_utc):
                continue
            # One latest observation per bookmaker and market; never collapse
            # different books, sides or market types into one quote.
            key = (q['bookmaker_id'], q['market'])
            row = dict(bookmaker=q['bookmaker'], market=q['market'],
                line=q['line'], observed_at_utc=q['observed_at_utc'],
                quote_sha256=quote['sha256'], settlement_scope=q['settlement_scope'],
                status='OBSERVED_NOT_COMPARABLE',
                reason='REGULATION_MODEL_VS_UNKNOWN_MARKET_SETTLEMENT')
            current = latest.get(key)
            if current is None or (row['observed_at_utc'], row['quote_sha256']) > (
                    current['observed_at_utc'], current['quote_sha256']):
                latest[key] = row
    return sorted(latest.values(), key=lambda q:(q['market'], q['bookmaker']))[:24]

def render_quote_line(quote, prediction_utc, report_utc):
    """Present frozen quote provenance separately from current report freshness."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    observed = quote['observed_at_utc']
    timestamp = datetime.fromtimestamp(observed, timezone.utc).astimezone(
        ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M TSİ')
    age_at_prediction = max(0, prediction_utc - observed)
    age_at_report = max(0, report_utc - observed)
    market = quote['market']
    line = quote['line']
    formatted_line = f'{line:+g}' if 'HANDICAP' in market or 'SPREAD' in market else f'{line:g}'
    return (f"{quote['bookmaker']} | {market} {formatted_line} | {timestamp} "
            f"| Tahminde veri yaşı: {age_at_prediction // 60} dk "
            f"| Raporda veri yaşı: {age_at_report // 60} dk "
            f"| KAPSAM BELİRSİZ (ARŞİV GÖZLEMİ)")
