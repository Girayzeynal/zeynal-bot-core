from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.native_market_history import inspect

class NativeMarketHistoryTests(TestCase):
    def test_local_repeated_quotes_not_opening_or_closing_and_no_writes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'current-market-reviews';folder.mkdir()
            for published,price,captured in [(1000,1.9,1001),(1000,1.9,1002),(1050,1.8,1051)]:
                review=dict(fixture=dict(league='NBA',season='2026/2027',fixture_id='fixture',tipoff_utc=2000),
                    source=dict(method='NATIVE_RETRIEVAL',provider_id='THE_ODDS_API',captured_at_utc=captured,published_at_utc=published),
                    available_at_utc=captured,decision_utc=captured+1,bookmaker=dict(id='book'),
                    observation_sha256='a'*64,rows=[dict(period='FULL',market='TOTAL',line=200.5,
                    prices=dict(under=price,over=1.9),quote_sha256='b'*64,reasons=[])])
                m=dict(format='CURRENT_MARKET_REVIEW_BATCH_V1',reviews=[review])
                p=dict(m,recorded_at_utc=captured+2,record_class='PREGAME_CURRENT_REVIEW',eligible_for_current_prematch_metrics=False)
                key=digest(m);publish_json(folder/('review-'+key+'.json'),dict(payload=p,sha256=digest(p),manifest_sha256=key))
            before={p:p.read_bytes() for p in folder.iterdir()}
            r=inspect(root,'NBA','fixture')
            self.assertEqual(r['series'][0]['observation_count'],2)
            self.assertEqual(r['series'][0]['decimal_price_change']['under'],-.1)
            self.assertFalse(r['opening_verified']);self.assertFalse(r['closing_verified'])
            self.assertEqual(before,{p:p.read_bytes() for p in folder.iterdir()})
