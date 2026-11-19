"""Manufactured provider failures and read-only archive tests, not real API proof."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

from core.team_identity import digest
from hybrid_engine.provider_diagnostics import failure,fixture_diagnostic,readonly_snapshot
from hybrid_engine.provider_bridge import ProviderBridge,render,matches
from hybrid_engine.provider_access import ProviderAccess
from tests.test_provider_bridge import FakeProvider,SNAPSHOT,NOW,SECRET,event,iso,receipt


class ProviderDiagnosticTests(unittest.TestCase):
    def test_same_teams_time_difference_is_reported_never_accepted(self):
        e=event();e['commence_time']=iso(SNAPSHOT['fixture_start_utc']+600)
        d=fixture_diagnostic([e],SNAPSHOT)
        self.assertEqual(d['reason'],'MATCHING_TEAMS_DIFFERENT_START')
        self.assertEqual(d['candidates'][0]['delta_seconds'],600)
        self.assertFalse(matches(e,SNAPSHOT));self.assertFalse(d['equivalence_inferred'])

    def test_reversed_home_away_is_not_a_match(self):
        e=event();e['home_team'],e['away_team']=e['away_team'],e['home_team']
        d=fixture_diagnostic([e],SNAPSHOT)
        self.assertEqual(d['reason'],'ONLY_REVERSED_PAIR_FOUND');self.assertEqual(d['exact_matches'],0)

    def test_empty_and_missing_pair_differ(self):
        self.assertEqual(fixture_diagnostic([],SNAPSHOT)['reason'],'EMPTY_PROVIDER_EVENT_LIST')
        e=event();e['away_team']='Different Team'
        self.assertEqual(fixture_diagnostic([e],SNAPSHOT)['reason'],'NO_TEAM_PAIR_IN_RETURNED_EVENTS')

    def test_duplicate_exact_fixture_is_ambiguous(self):
        self.assertEqual(fixture_diagnostic([event(),event()],SNAPSHOT)['reason'],'AMBIGUOUS_EXACT_MATCH')

    def test_timezone_offset_and_naive_dates(self):
        e=event();e['commence_time']=e['commence_time'].replace('Z','+00:00')
        self.assertEqual(fixture_diagnostic([e],SNAPSHOT)['reason'],'EXACT_MATCH')
        e['commence_time']=e['commence_time'].removesuffix('+00:00')
        self.assertEqual(fixture_diagnostic([e],SNAPSHOT)['invalid_rows'],1)

    def test_native_errors_classified_without_exposing_values(self):
        for errors,expected in [({'plan':'Free plans cannot access this season '+SECRET},'PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED'),
                                ({'requests':'You reached the request limit for the day '+SECRET},'QUOTA_OR_RATE_LIMIT_REPORTED'),
                                ({'season':'The Season field is required '+SECRET},'QUERY_PARAMETER_ERROR_REPORTED')]:
            r=failure(receipt(dict(errors=errors)),'FIXTURE_QUERY')
            self.assertIn(expected,r['error_codes']);self.assertNotIn(SECRET,json.dumps(r))
            self.assertEqual(r['operation'],'FIXTURE_QUERY');self.assertFalse(r['native_error_text_exposed'])

    def test_unclassified_error_never_echoes_unknown_fields(self):
        r=failure(receipt(dict(errors={SECRET:SECRET})),'LEAGUE_DISCOVERY')
        self.assertEqual(r['error_codes'],['UNCLASSIFIED_PROVIDER_ERROR'])
        self.assertNotIn(SECRET,json.dumps(r))

    def test_diagnostic_does_not_request_odds_or_statistics_and_sends_season(self):
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            fake=FakeProvider();access=ProviderAccess({'THE_ODDS_API':SECRET,'API_BASKETBALL':SECRET},getter=fake,clock=lambda:NOW)
            bridge=ProviderBridge(access,Path(tmp)/'evidence',clock=lambda:NOW,diagnostic_only=True)
            p=deepcopy(SNAPSHOT);before=digest(p);r=bridge.collect(p)
            self.assertEqual(r['providers']['THE_ODDS_API']['status'],'EXACT_FIXTURE_MATCH_CONFIRMED')
            self.assertTrue(r['diagnostic_only']);self.assertEqual(digest(p),before)
            self.assertFalse(any('/odds?' in u or '/statistics?' in u for _,u in fake.calls))
            url=next(u for _,u in fake.calls if '/games?' in u)
            self.assertEqual(parse_qs(urlsplit(url).query)['season'],['2026-2027'])

    def test_league_error_records_stage_and_pin_and_no_games_request(self):
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            fake=FakeProvider()
            def getter(provider,url,key,**kw):
                if '/leagues?' in url:
                    fake.calls.append((provider,url))
                    return receipt(dict(errors={'requests':'Request limit reached'}),provider,url)
                return fake(provider,url,key,**kw)
            access=ProviderAccess({'API_BASKETBALL':SECRET},getter=getter,clock=lambda:NOW)
            r=ProviderBridge(access,Path(tmp)/'evidence',clock=lambda:NOW).collect(SNAPSHOT)
            row=r['providers']['API_BASKETBALL']
            self.assertEqual(row['operation'],'LEAGUE_DISCOVERY');self.assertIn('source_pin',row)
            self.assertFalse(any('/games?' in u for _,u in fake.calls))
            self.assertIn('Kaynak hata sınıfı:',render(r))

    def test_readonly_archived_snapshot_lookup_keeps_db_bytes(self):
        from tests.test_phase91 import ten_game_ledger
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger.sqlite';ledger,games=ten_game_ledger(path,count=2)
            before=path.read_bytes();p=readonly_snapshot(path,games[1]['provider_fixture_ids'][0])
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(p['fixture_id'],games[1]['canonical_id'])

    def test_missing_snapshot_does_not_create_db(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.sqlite'
            with self.assertRaises(ValueError):readonly_snapshot(path,'401909994')
            self.assertFalse(path.exists())


if __name__=='__main__':unittest.main()
