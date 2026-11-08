"""Append-only SQLite market observations; never manufacture an opening quote."""
from __future__ import annotations
import sqlite3
from math import isfinite
from sharp_guard import MarketSnapshot


class MarketSnapshotStore:
    def __init__(self, path: str):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_key TEXT NOT NULL, bookmaker TEXT NOT NULL,
                market TEXT NOT NULL, line REAL NOT NULL,
                decimal_over REAL NOT NULL, decimal_under REAL NOT NULL,
                observed_utc INTEGER NOT NULL, source TEXT NOT NULL,
                UNIQUE(fixture_key,bookmaker,market,observed_utc,source)
            )""")

    def append(self, fixture_key: str, quote: MarketSnapshot) -> bool:
        if not fixture_key or not fixture_key.strip() or not quote.bookmaker.strip() or not quote.source.strip():
            raise ValueError('missing quote identity')
        if quote.market not in ('TOTAL', 'SPREAD') or type(quote.observed_utc) is not int or quote.observed_utc <= 0:
            raise ValueError('invalid market or timestamp')
        if not all(isfinite(x) for x in (quote.line, quote.decimal_over, quote.decimal_under)) or min(quote.decimal_over, quote.decimal_under) <= 1:
            raise ValueError('invalid quote prices')
        with sqlite3.connect(self.path) as db:
            row = db.execute("""SELECT line, decimal_over, decimal_under FROM market_snapshots
                WHERE fixture_key=? AND bookmaker=? AND market=? AND observed_utc=? AND source=?""",
                (fixture_key, quote.bookmaker, quote.market, quote.observed_utc, quote.source)).fetchone()
            if row is not None:
                if row != (quote.line, quote.decimal_over, quote.decimal_under):
                    raise ValueError('conflicting immutable quote at same timestamp')
                return False
            db.execute("""INSERT INTO market_snapshots
                (fixture_key,bookmaker,market,line,decimal_over,decimal_under,observed_utc,source)
                VALUES (?,?,?,?,?,?,?,?)""",
                (fixture_key,quote.bookmaker,quote.market,quote.line,quote.decimal_over,quote.decimal_under,quote.observed_utc,quote.source))
            return True

    def history(self, fixture_key: str, bookmaker: str, market: str, source: str) -> list[MarketSnapshot]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("""SELECT bookmaker,market,line,decimal_over,decimal_under,observed_utc,source
                FROM market_snapshots WHERE fixture_key=? AND bookmaker=? AND market=? AND source=?
                ORDER BY observed_utc ASC""", (fixture_key,bookmaker,market,source)).fetchall()
        return [MarketSnapshot(*row) for row in rows]
