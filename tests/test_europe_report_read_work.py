"""One final witness per fixture, unchanged native validation and OT scope."""
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
            # One native outcome verification, then one shared label clock.
            self.assertEqual(len(matched),2)
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
