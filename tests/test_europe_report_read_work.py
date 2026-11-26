"""One final witness per fixture, unchanged native validation and OT scope."""
from copy import deepcopy
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.europe_models import season_url
from hybrid_engine.europe_reports import EuropeanReports
from tests import test_europe_integration as native
from tests.test_season_archive_audit import NOW


class EuropeanReportReadWorkTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await native.EuropeanServiceTests.asyncSetUp(self)

    async def test_each_final_is_read_once_for_all_component_labels_without_extra_source_requests(self):
        for code in ('EUROLEAGUE','EUROCUP'):
            self.clock=NOW
            await native.EuropeanServiceTests.analyze(self,code)
            service=self.services[code];registry=service.registry
            first=registry.independent_records()[0];payload=first['payload']
            before=(registry.root/first['publication']['forecast']['file']).read_bytes()
            self.clock=NOW+5*3600
            game=self.sources[code].raw['data'][0];game['played']=True
            for side,ot in (('local',8),('road',12)):
                game[side].update(score=80+ot,partials={
                    **{f'partials{i}':20 for i in range(1,5)},'extraPeriods':{'1':ot}})
            registry.settle(self.sources[code]('EUROLEAGUE_LIVE',season_url(code,2026)),2026)
            outcome=registry.outcome(payload);calls=len(self.sources[code].calls)
            with patch.object(registry,'read_asset',wraps=registry.read_asset) as reads:
                report=EuropeanReports(service).read(code)
            matched=[c for c in reads.call_args_list if c.args[0]==outcome['source']]
            # One validated read supplies both the native final and its clock.
            self.assertEqual(len(matched),1)
            self.assertEqual(len(report['forecasts']),3);self.assertEqual(report['pending'],0)
            for row in report['forecasts']:
                self.assertEqual(row['actual'],[80,80]);self.assertEqual(row['final_with_ot'],[88,92])
                self.assertEqual(row['snapshot_sha256'],digest(payload))
                self.assertEqual(row['label_available_utc'],self.clock)
            self.assertEqual(before,(registry.root/first['publication']['forecast']['file']).read_bytes())
            self.assertEqual(calls,len(self.sources[code].calls))

    async def test_tampered_final_source_still_fails_instead_of_returning_a_cached_result(self):
        code='EUROCUP';await native.EuropeanServiceTests.analyze(self,code)
        registry=self.services[code].registry;payload=registry.independent_records()[0]['payload']
        self.clock=NOW+5*3600;game=self.sources[code].raw['data'][0];game['played']=True
        for side,score in (('local',80),('road',84)):
            game[side].update(score=score,partials={
                **{f'partials{i}':score//4 for i in range(1,5)},'extraPeriods':{}})
        registry.settle(self.sources[code]('EUROLEAGUE_LIVE',season_url(code,2026)),2026)
        reader=EuropeanReports(self.services[code]);reader.read(code)
        outcome=registry.outcome(payload);path=registry.root/outcome['source']['file']
        path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'ASSET_PIN'):reader.read(code)


    async def test_shared_season_receipts_are_indexed_once_with_identical_verified_reports(self):
        from hybrid_engine.europe_models import catalog
        from hybrid_engine.europe_report_assets import EuropeanReportAssets

        for code in ('EUROLEAGUE','EUROCUP'):
            self.clock=NOW
            await native.EuropeanServiceTests.analyze(self,code)
            service=self.services[code];registry=service.registry
            p=registry.independent_records()[0]['payload']
            receipt=registry.read_asset(p['fixture_source'])
            upcoming=[f for f in catalog(receipt,code,2026)['payload']['fixtures'] if not f['completed']]
            second=deepcopy(p)
            second['fixture']=next(f for f in upcoming if f!=p['fixture'])
            registry.record(second)

            self.clock=NOW+5*3600
            for i in (0,21):
                game=self.sources[code].raw['data'][i]; game['played']=True
                for side,score in (('local',80),('road',84)):
                    game[side].update(score=score,partials={
                        **{f'partials{q}':score//4 for q in range(1,5)},'extraPeriods':{}})
            results=self.sources[code]('EUROLEAGUE_LIVE',season_url(code,2026))
            registry.settle(results,2026)

            reader=EuropeanReports(service)
            with patch('hybrid_engine.europe_report_assets.reporting_assets',return_value=None):
                reference=reader.read(code)
            before={f.name:digest(f.read_text()) for f in registry.root.glob('*.json')}
            with patch('hybrid_engine.europe_report_assets.catalog',wraps=catalog) as parsed:
                actual=reader.read(code)
                self.assertEqual(parsed.call_count,2)  # Shared pregame and shared final catalogs.
            self.assertEqual(actual,reference)
            self.assertEqual(actual['unique_fixtures'],2)
            self.assertEqual(actual['pending'],0)
            self.assertEqual(before,{f.name:digest(f.read_text()) for f in registry.root.glob('*.json')})

            # An earlier metadata cache entry must never hide a changed asset.
            scoped=EuropeanReportAssets(registry)
            ref=p['fixture_source']
            scoped.pair(p)
            path=registry.root/ref['file']
            path.write_text(path.read_text().replace('DOCUMENT_RECEIVED','DOCUMENT_REJECTED'))
            with self.assertRaisesRegex(ValueError,'ASSET_PIN'):
                scoped.pair(p)
