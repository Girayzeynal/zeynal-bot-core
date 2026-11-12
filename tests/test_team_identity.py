"""Synthetic participant lists, not hand-coded production team identities."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from unittest import TestCase
from unittest.mock import Mock,patch

from core.league_identity import resolve_league,league_catalog,normalize_name
from core.team_identity import TeamIdentityRegistry,digest,IdentityRefusal
from providers.season_participants import parse_participants,participant_urls,SeasonParticipantProvider,ParticipantSourceError
from tests.test_season_archive_audit import NOW


def clubs():
    return [dict(code='PRS',name='Paris Basketball',abbreviatedName='Paris Basketball',editorialName='Paris',
                 clubPermanentName='Paris Basketball',clubPermanentAlias='Paris Basketball',city='Paris',isVirtual=False),
            dict(code='ULK',name='Fenerbahce New Sponsor Istanbul',abbreviatedName='Fenerbahce',editorialName='Fenerbahce',
                 clubPermanentName='Fenerbahce Beko Istanbul',clubPermanentAlias='Fenerbahce',city='Istanbul',isVirtual=False),
            dict(code='PAR',name='Partizan Sponsor Belgrade',abbreviatedName='Partizan',editorialName='Partizan',
                 clubPermanentName='Partizan Sponsor Belgrade',clubPermanentAlias='Partizan',city='BELGRADE',isVirtual=False),
            dict(code='BAS',name='Sponsor Baskonia',abbreviatedName='Baskonia',editorialName='Baskonia',
                 clubPermanentName='Saski Baskonia',clubPermanentAlias='Baskonia',city='VITORIA',isVirtual=False)]


def nba_names():
    return [dict(id='1',displayName='Synthetic Hawks',shortDisplayName='Hawks',name='Hawks',abbreviation='SH'),
            dict(id='2',displayName='Synthetic Bears',shortDisplayName='Bears',name='Bears',abbreviation='SB')]


def documents(league='EUROLEAGUE',year=2026,at=NOW-1,rows=None):
    spec=resolve_league(league);urls=participant_urls(league,year)
    if spec.code=='NBA':
        teams=nba_names() if rows is None else rows
        raw=dict(membership=dict(count=len(teams),pageCount=1,pageIndex=1,items=[{'$ref':f'http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year+1}/teams/'+t['id']} for t in teams]),
            names={'sports':[{'leagues':[dict(slug='nba',year=year+1,season={'year':year+1},teams=[{'team':t} for t in teams])]}]})
    else:
        rows=clubs() if rows is None else rows
        raw=dict(season=dict(code=spec.competition_code+str(year),competitionCode=spec.competition_code,year=year),clubs=dict(total=len(rows),data=rows))
    return {name:dict(provider=spec.provider,source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
        observed_at_utc=at-1,ingested_at_utc=at,document=raw[name],document_sha256=digest(raw[name])) for name,url in urls.items()}


def snapshot(league='EUROLEAGUE',year=2026,at=NOW-1,rows=None):
    return parse_participants(league,year,documents(league,year,at,rows))


class TeamIdentityTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)
        self.registry=TeamIdentityRegistry();self.source=snapshot()
        self.registry.ingest(self.source,trusted_sha256=self.source['sha256'])

    def resolve(self,name,**kw):
        options=dict(league='EUROLEAGUE',season='2026/2027',asof_utc=NOW);options.update(kw)
        return self.registry.resolve(name=name,**options)

    def test_unicode_turkish_accents_case_punctuation_and_source_abbreviations(self):
        variants=['Fenerbahçe Beko','FENERBAHÇE BEKO','fenerbahce-beko','Fenerbahc\u0327e Beko']
        ids={self.resolve(s).internal_id for s in variants}
        self.assertEqual(len(ids),1)
        self.assertEqual(self.resolve('Partizan Belgrade').provider_ids,(('EUROLEAGUE_LIVE','PAR'),))
        self.assertEqual(self.resolve('Baskonia').provider_ids,(('EUROLEAGUE_LIVE','BAS'),))
        with self.assertRaises(ValueError):normalize_name('!!!')

    def test_ids_come_from_provider_identity_not_mutable_sponsor_names(self):
        old=self.resolve('Fenerbahçe Beko');changed=clubs();changed[1]['name']='Fenerbahce Another Sponsor Istanbul'
        new=snapshot(at=NOW,rows=changed);self.registry.ingest(new,trusted_sha256=new['sha256'])
        self.assertEqual(self.resolve('Fenerbahce Another Sponsor').internal_id,old.internal_id)
        self.assertEqual(self.source['payload']['participants'],snapshot()['payload']['participants'])

    def test_alias_validity_and_snapshot_availability_prevent_backdating(self):
        with self.assertRaisesRegex(IdentityRefusal,'UNAVAILABLE_AT_CUTOFF'):self.resolve('Paris Basketball',asof_utc=NOW-2)
        bad=deepcopy(self.source)
        for t in bad['payload']['participants']:
            if t['provider_id']=='PRS':
                for a in t['aliases']:a['valid_until_utc']=NOW
        bad['sha256']=digest(bad['payload']);r=TeamIdentityRegistry();r.ingest(bad,trusted_sha256=bad['sha256'])
        self.assertEqual(r.resolve('EUROLEAGUE','2026/2027','Paris Basketball',asof_utc=NOW-1).official_name,'Paris Basketball')
        with self.assertRaisesRegex(IdentityRefusal,'NOT_REGISTERED'):r.resolve('EUROLEAGUE','2026/2027','Paris Basketball',asof_utc=NOW)

    def test_seasons_and_leagues_do_not_share_membership_or_guess_names(self):
        with self.assertRaisesRegex(IdentityRefusal,'UNAVAILABLE'):self.resolve('Paris Basketball',season='2025/2026')
        u=snapshot('EUROCUP',rows=[dict(code='OTHER',name='Paris Basketball',isVirtual=False)])
        self.registry.ingest(u,trusted_sha256=u['sha256'])
        other=self.resolve('Paris Basketball',league='EUROCUP')
        self.assertNotEqual(other.internal_id,self.resolve('Paris Basketball').internal_id)
        with self.assertRaisesRegex(IdentityRefusal,'NOT_REGISTERED'):self.resolve('Paris Basketbal')

    def test_ambiguous_names_are_refused_and_logged_instead_of_first_match(self):
        rows=clubs();rows[0]['editorialName']=rows[1]['editorialName']='Shared Club'
        b=snapshot(at=NOW,rows=rows);self.registry.ingest(b,trusted_sha256=b['sha256'])
        with self.assertRaisesRegex(IdentityRefusal,'AMBIGUOUS_TEAM_ALIAS'):self.resolve('Shared Club')
        self.assertEqual(len(self.registry.refusals[-1]['candidates']),2)

    def test_records_are_immutable_and_repeat_ingestion_is_idempotent(self):
        team=self.resolve('Paris Basketball');before=deepcopy(self.source)
        self.registry.ingest(self.source,trusted_sha256=self.source['sha256'])
        self.assertEqual(len(self.registry.participants('EUROLEAGUE','2026/2027',asof_utc=NOW)),4)
        with self.assertRaises(FrozenInstanceError):team.official_name='changed'
        self.assertEqual(self.source,before)

    def test_same_provider_id_is_stable_across_seasons_without_leaking_membership(self):
        old=snapshot(year=2025);self.registry.ingest(old,trusted_sha256=old['sha256'])
        self.assertEqual(self.resolve('Baskonia',season='2025/2026').internal_id,self.resolve('Baskonia').internal_id)

    def test_legacy_lookup_never_fabricates_a_two_team_registry(self):
        from core.canonical_registry import get_nba_team,NBA_TEAMS
        self.assertFalse(NBA_TEAMS);self.assertIsNone(get_nba_team(134))
        b=snapshot('NBA');self.registry.ingest(b,trusted_sha256=b['sha256'])
        team=self.registry.resolve('NBA','2026/2027','SH',asof_utc=NOW)
        row=get_nba_team(team.internal_id,registry=self.registry,season='2026/2027',asof_utc=NOW)
        self.assertEqual(row['providers']['espn']['team_id'],'1')

    def test_pin_duplicate_provider_ids_and_conflicting_snapshot_are_rejected(self):
        with self.assertRaisesRegex(IdentityRefusal,'PIN_MISMATCH'):self.registry.ingest(self.source,trusted_sha256='0'*64)
        b=deepcopy(self.source);b['payload']['participants'].append(b['payload']['participants'][0]);b['payload']['participant_count']+=1;b['sha256']=digest(b['payload'])
        with self.assertRaisesRegex(IdentityRefusal,'ID_CONFLICT'):self.registry.ingest(b,trusted_sha256=b['sha256'])
        b=deepcopy(self.source);b['payload']['participants'][0]['official_name']='Changed';b['sha256']=digest(b['payload'])
        with self.assertRaisesRegex(IdentityRefusal,'SAME_CLOCK'):self.registry.ingest(b,trusted_sha256=b['sha256'])

    def test_every_configured_or_requested_league_has_an_explicit_capability(self):
        for code,spec in league_catalog().items():
            self.assertEqual(resolve_league(code),spec)
            if not spec.provider:
                with self.subTest(code=code),self.assertRaisesRegex(ParticipantSourceError,'NOT_CONFIGURED'):participant_urls(code,2026)
        self.assertNotEqual(resolve_league('FIBA EuroCup'),resolve_league('EuroCup'))
        self.assertEqual(resolve_league('Italy Serie A').code,'LBA')

    def test_provider_numeric_ids_are_namespaced_and_coverage_is_not_model_accuracy(self):
        from core.league_identity import LeagueIdentity
        from team_identity_audit import audit_teams
        self.assertNotEqual(LeagueIdentity('NBA',(),provider='ESPN').identity_namespace,LeagueIdentity('NBL',(),provider='ESPN').identity_namespace)
        provider=Mock(side_effect=AssertionError('NETWORK'))
        r=audit_teams(provider=provider)
        self.assertTrue(r['match_coverage_is_not_prediction_accuracy']);self.assertEqual(r['prospective_predictions_created'],0)
        self.assertIsNone(r['leagues']['KBL']['participants']);provider.load.assert_not_called()


class NativeParticipantTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)

    def test_nba_membership_is_season_bound_and_not_a_sample_game_list(self):
        b=snapshot('NBA');self.assertEqual(b['payload']['participant_count'],2)
        d=documents('NBA');d['membership']['document']['items'][0]['$ref']=d['membership']['document']['items'][0]['$ref'].replace('/2027/','/2026/')
        d['membership']['document_sha256']=digest(d['membership']['document'])
        with self.assertRaisesRegex(ParticipantSourceError,'REF_INVALID'):parse_participants('NBA',2026,d)

    def test_incomplete_pages_stale_name_season_and_competition_mix_fail_closed(self):
        for league,kind in [('NBA','page'),('NBA','nameyear'),('EUROCUP','competition'),('EUROLEAGUE','page')]:
            d=documents(league)
            if kind=='page':d['membership' if league=='NBA' else 'clubs']['document']['count' if league=='NBA' else 'total']+=1
            elif kind=='nameyear':d['names']['document']['sports'][0]['leagues'][0]['year']=2026
            else:d['season']['document']['competitionCode']='E'
            for r in d.values():r['document_sha256']=digest(r['document'])
            with self.subTest(league=league,kind=kind),self.assertRaises(ValueError):parse_participants(league,2026,d)

    def test_provider_errors_are_not_missing_teams_and_never_fall_back_to_espn(self):
        fetch=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED'))
        with self.assertRaisesRegex(ParticipantSourceError,'SOURCE_ACCESS_DENIED'):
            SeasonParticipantProvider(fetch).load('EUROCUP',2026)
        self.assertEqual(fetch.call_args.args[0],'EUROLEAGUE_LIVE')
        fetch.reset_mock()
        with self.assertRaisesRegex(ParticipantSourceError,'NOT_CONFIGURED'):SeasonParticipantProvider(fetch).load('KBL',2026)
        fetch.assert_not_called()

    def test_registry_source_urls_and_clocks_are_validated(self):
        d=documents();d['clubs']['source_url']='https://wrong.invalid/'
        with self.assertRaisesRegex(ParticipantSourceError,'BINDING'):parse_participants('EUROLEAGUE',2026,d)
        d=documents();d['clubs']['ingested_at_utc']=NOW+1
        with self.assertRaisesRegex(ParticipantSourceError,'CLOCK'):parse_participants('EUROLEAGUE',2026,d)

    def test_cache_is_bounded_by_season_and_has_no_external_writes(self):
        d=documents();fetch=Mock(side_effect=lambda provider,url:next(r for r in d.values() if r['source_url']==url))
        provider=SeasonParticipantProvider(fetch);first=provider.load('EUROLEAGUE',2026)
        self.assertEqual(provider.load('EUROLEAGUE',2026),first);self.assertEqual(fetch.call_count,2)

    def test_historical_nba_uses_all_season_member_details_not_current_team_names(self):
        year=2025;d=documents('NBA',year=year)
        d['names']['document']['sports'][0]['leagues'][0]['year']=2027
        d['names']['document_sha256']=digest(d['names']['document'])
        def fetch(provider,url):
            for r in d.values():
                if r['source_url']==url:return deepcopy(r)
            pid=url.rsplit('/',1)[-1];team=dict(id=pid,displayName='Historical Team '+pid,isAllStar=False,abbreviation='H'+pid)
            team['$ref']=url
            return dict(provider=provider,source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
                document=team,document_sha256=digest(team),observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        wrapped=Mock(side_effect=fetch);b=SeasonParticipantProvider(wrapped).load('NBA',year)
        self.assertEqual(wrapped.call_count,4);self.assertEqual(b['payload']['participant_count'],2)
        self.assertTrue(all(t['official_name'].startswith('Historical Team') for t in b['payload']['participants']))
        registry=TeamIdentityRegistry();registry.ingest(b,trusted_sha256=b['sha256'])
        with self.assertRaisesRegex(IdentityRefusal,'UNAVAILABLE_AT_CUTOFF'):
            registry.resolve('NBA','2025/2026','H1',asof_utc=NOW-100)
