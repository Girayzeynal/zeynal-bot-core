"""Copyable fixture punctuation, exact dates, and unchanged archive safety."""
from datetime import datetime
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests import test_analyze_input_guard as guard
from hybrid_engine.analyze_input import input_error
from hybrid_engine.fixture_menu import nba_blocks


class FixtureDelimiterTests(TestCase):
    def test_displayed_unicode_separators_parse_all_leagues_without_renaming(self):
        parse=guard.main_module().parse_analyze
        for league,home,away in (
                ('NBA','Orlando Magic','Detroit Pistons'),
                ('EuroLeague','Zalgiris Kaunas','FC Bayern Munich'),
                ('EuroCup','U-BT Cluj-Napoca','Cosea JL Bourg-en-Bresse')):
            for delimiter in ('vs','VS','–','—'):
                command=f'/analyze {league} 2026-11-25 {home} {delimiter}\n{away}'
                with self.subTest(command=command):
                    self.assertEqual(parse(command),(league,'2026-11-25',home,away))
                    self.assertIsNone(input_error(command,parse))

    def test_ambiguous_or_missing_unicode_separator_never_guesses_team_pair(self):
        parse=guard.main_module().parse_analyze
        for command in ('/analyze NBA 2026-11-25 A – B — C',
                        '/analyze NBA 2026-11-25 A B C',
                        '/analyze NBA 2026-11-25 A–B',
                        '/analyze NBA invalid A – B',
                        '/analyze NBA 2026-11-25 A – A'):
            with self.subTest(command=command):
                self.assertIsNotNone(input_error(command,parse))

    def test_explicit_vs_preserves_punctuation_inside_a_team_name(self):
        # Preserve the existing explicit-vs contract even for a name containing
        # an independent punctuation token. Never replace every dash globally.
        parse=guard.main_module().parse_analyze
        self.assertEqual(parse('/analyze EuroCup 2026-11-25 Club – Name vs U-BT Cluj-Napoca')[2:],
                         ('Club – Name','U-BT Cluj-Napoca'))

    def test_finished_or_live_only_list_guides_to_next_tsi_date_without_inventing_games(self):
        start=datetime(2026,11,25,3,tzinfo=ZoneInfo('Europe/Istanbul'))
        games=[dict(home='Orlando Magic',away='Detroit Pistons',start=start,status='Tamamlandı',id='401909314')]
        with patch('time.time',return_value=start.timestamp()+4*3600):
            text='\n'.join(nba_blocks(games,'2026-11-25'))
        self.assertIn('/nba 2026-11-26',text)
        self.assertIn('/compare NBA 401909314',text)
        self.assertNotIn('/analyze NBA',text)
        self.assertNotIn('2026-11-26 Orlando Magic',text)

    def test_future_list_keeps_exact_native_day_and_copyable_vs_command(self):
        start=datetime(2026,11,26,3,tzinfo=ZoneInfo('Europe/Istanbul'))
        games=[dict(home='A-B Club',away='Other Club',start=start,status='Başlamadı',id='123')]
        with patch('time.time',return_value=start.timestamp()-3600):
            text='\n'.join(nba_blocks(games,'2026-11-26'))
        self.assertIn('/analyze NBA 2026-11-26 A-B Club vs Other Club',text)
        self.assertNotIn('/nba 2026-11-27',text)
        empty='\n'.join(nba_blocks([],'2026-12-31'))
        self.assertIn('/nba 2027-01-01',empty)
        self.assertNotIn('/analyze NBA',empty)


class DelimiterRoutingTests(IsolatedAsyncioTestCase):
    asyncSetUp=guard.AnalyzeGuardRoutingTests.asyncSetUp
    send=guard.AnalyzeGuardRoutingTests.send

    async def test_each_pasted_date_reaches_service_unchanged_and_only_once(self):
        before={p:p.read_bytes() for p in self.archive_before}
        for i,day in enumerate(('2026-11-25','2026-11-26'),1):
            self.service.analyze.reset_mock()
            await self.send(f'/analyze NBA {day} Orlando Magic – Detroit Pistons',update_id=i)
            self.service.analyze.assert_awaited_once_with('NBA',day,'Orlando Magic','Detroit Pistons')
        self.assertEqual(self.api.sent,['DATE_GUARD_PRESERVED','DATE_GUARD_PRESERVED'])
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))

    async def test_two_dash_commands_in_one_message_remain_rejected_before_service(self):
        command='/analyze NBA 2026-11-25 Orlando Magic – Detroit Pistons'
        await self.send(command+'\n'+command)
        self.service.analyze.assert_not_awaited()
        self.assertIn('tek mesajda',self.api.sent[0])
