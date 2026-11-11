"""Synthetic bounded collection and local publication, never production."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import io
import errno

from season_archive_collect import collect_archives, publish_collection, validate_collection, fetch_document, main
from season_archive_inventory import _hash
from tests.test_season_archive_audit import nba, euro, NOW


def receipt(provider, url, document=None):
    if document is None: document={'events':[nba()]} if provider=='ESPN' else {'total':1,'data':[euro()]}
    return dict(provider=provider,source_url=url,http_status=200,status='DOCUMENT_RECEIVED',
        observed_at_utc=NOW-1,ingested_at_utc=NOW,document=document,document_sha256=_hash(document),body_sha256='a'*64)


class ArchiveCollectionTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)

    def collect(self, fetcher=receipt, **kw):
        options=dict(nba_dates=['20261025'],euroleague=True,live=True,fetcher=fetcher);options.update(kw)
        return collect_archives(**options)

    def test_default_is_no_network_and_plan_validates_before_requests(self):
        fetch=Mock(side_effect=AssertionError('NETWORK'))
        self.assertEqual(collect_archives(['20261025'],fetcher=fetch)['status'],'DRY_RUN_NO_NETWORK')
        for dates in ('20261025',['20260230'],['20250201'],['20261025']*32):
            with self.subTest(dates=dates),self.assertRaises(ValueError):
                self.collect(fetcher=fetch,nba_dates=dates)
        fetch.assert_not_called()
        with self.assertRaises(ValueError): self.collect(nba_dates=[],euroleague=False)

    def test_duplicate_dates_are_requested_once_and_leagues_are_separate(self):
        fetch=Mock(side_effect=receipt)
        b=self.collect(fetcher=fetch,nba_dates=['20261025','20261025'])
        p=b['payload'];self.assertEqual(fetch.call_count,2)
        self.assertEqual(p['leagues']['NBA']['known_completed_fixtures'],1)
        self.assertEqual(p['leagues']['EuroLeague']['known_completed_fixtures'],1)
        self.assertFalse(p['point_in_time_training_eligible']);self.assertEqual(p['prospective_predictions_created'],0)
        self.assertEqual(validate_collection(b,trusted_sha256=b['sha256']),b)

    def test_provider_403_429_and_network_failure_are_unknown_not_empty_dates(self):
        for status in ('SOURCE_ACCESS_DENIED','SOURCE_RATE_LIMITED','SOURCE_NETWORK_ERROR'):
            def fetch(provider,url):
                return dict(status=status) if provider=='ESPN' else receipt(provider,url)
            b=self.collect(fetcher=fetch);p=b['payload']
            with self.subTest(status=status):
                self.assertEqual(p['status'],'PARTIAL_OR_BLOCKED')
                self.assertIsNone(p['leagues']['NBA']['known_completed_fixtures'])
                self.assertEqual(p['leagues']['NBA']['failed_documents'],1)
                self.assertEqual(p['leagues']['EuroLeague']['known_completed_fixtures'],1)
                self.assertEqual(validate_collection(b,trusted_sha256=b['sha256']),b)
        b=self.collect(fetcher=Mock(side_effect=OSError('offline')))
        self.assertIsNone(b['payload']['leagues']['NBA']['known_independent_fixtures'])

    def test_successful_empty_calendar_is_distinct_from_http_failure(self):
        b=self.collect(euroleague=False,fetcher=lambda provider,url:receipt(provider,url,{'events':[]}))
        self.assertEqual(b['payload']['leagues']['NBA']['known_completed_fixtures'],0)
        self.assertEqual(b['payload']['leagues']['NBA']['successful_documents'],1)

    def test_403_or_429_stops_remaining_provider_requests_and_keeps_other_league(self):
        for status in ('SOURCE_ACCESS_DENIED','SOURCE_RATE_LIMITED'):
            fetch=Mock(side_effect=lambda provider,url:dict(status=status) if provider=='ESPN' else receipt(provider,url))
            b=self.collect(fetcher=fetch,nba_dates=['20261025','20261026','20261027'])
            p=b['payload']
            with self.subTest(status=status):
                self.assertEqual(fetch.call_count,2)
                self.assertEqual(p['planned_requests'],4);self.assertEqual(p['request_attempts'],2)
                self.assertEqual(p['receipts'][1]['status'],'SKIPPED_PROVIDER_BLOCKED')
                self.assertIsNone(p['leagues']['NBA']['known_completed_fixtures'])
                self.assertEqual(p['leagues']['EuroLeague']['known_completed_fixtures'],1)
                self.assertEqual(validate_collection(b,trusted_sha256=b['sha256']),b)

    def test_unbound_or_wrong_date_documents_fail_closed(self):
        for kind in ('origin','digest','date','shape'):
            def fetch(provider,url):
                r=receipt(provider,url)
                if kind=='origin':r['source_url']='https://untrusted.invalid/'
                elif kind=='digest':r['document_sha256']='0'*64
                elif kind=='date':r['document']['events'][0]['date']='2026-10-26T23:00:00Z';r['document_sha256']=_hash(r['document'])
                else:r['document']={};r['document_sha256']=_hash(r['document'])
                return r
            b=self.collect(euroleague=False,fetcher=fetch)
            with self.subTest(kind=kind):
                self.assertEqual(b['payload']['receipts'][0]['status'],'SOURCE_VALIDATION_FAILED')
                self.assertIsNone(b['payload']['leagues']['NBA']['known_completed_fixtures'])
                self.assertEqual(validate_collection(b,trusted_sha256=b['sha256']),b)

    def test_utc_midnight_keeps_the_eastern_provider_date(self):
        def fetch(provider,url):
            event=nba();event['date']='2026-10-26T00:30:00Z'
            return receipt(provider,url,{'events':[event]})
        b=self.collect(euroleague=False,fetcher=fetch)
        self.assertEqual(b['payload']['leagues']['NBA']['known_completed_fixtures'],1)

    def test_rehashed_summary_or_training_claim_cannot_replace_source_replay(self):
        b=self.collect()
        for key in ('count','training','source'):
            bad=deepcopy(b)
            if key=='count':bad['payload']['leagues']['NBA']['known_completed_fixtures']=200
            elif key=='training':bad['payload']['point_in_time_training_eligible']=True
            else:bad['payload']['receipts'][0]['receipt']['document_sha256']='0'*64
            bad['sha256']=_hash(bad['payload'])
            with self.subTest(key=key),self.assertRaises(ValueError):validate_collection(bad,trusted_sha256=bad['sha256'])
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):validate_collection(b,trusted_sha256='0'*64)

    def test_failed_native_conflict_never_creates_a_source_matched_sample(self):
        def fetch(provider,url):
            first=nba();second=nba('401000124');second['competitions'][0]['competitors'][1]['team']['id']='3'
            return receipt(provider,url,{'events':[first,second]})
        p=self.collect(euroleague=False,fetcher=fetch)['payload']
        self.assertEqual(p['receipts'][0]['reason'],'same_team_start_conflict')
        self.assertIsNone(p['leagues']['NBA']['known_independent_fixtures'])

    def test_publisher_is_atomic_idempotent_and_does_not_overwrite_corruption(self):
        b=self.collect()
        with TemporaryDirectory() as folder:
            first=publish_collection(folder,b);target=Path(first['path'])
            self.assertTrue(first['created']);self.assertFalse(publish_collection(folder,b)['created'])
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            target.write_text('damaged')
            with self.assertRaisesRegex(ValueError,'ARCHIVE_CONTENT_CONFLICT'):publish_collection(folder,b)
            self.assertEqual(target.read_text(),'damaged')

    def test_publication_failure_has_no_half_manifest_and_concurrent_publish_is_once(self):
        b=self.collect()
        with TemporaryDirectory() as folder:
            with patch('season_archive_collect.os.link',side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):publish_collection(folder,b)
            self.assertEqual(list(Path(folder).iterdir()),[])
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:publish_collection(folder,b),range(2)))
            self.assertEqual(sum(r['created'] for r in results),1)
            self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_production_and_symlink_output_refused_before_network(self):
        with TemporaryDirectory() as folder:
            link=Path(folder)/'link';link.symlink_to(Path(folder),target_is_directory=True)
            for output in ('/data',str(link)):
                with self.subTest(output=output),patch('season_archive_collect.collect_archives',side_effect=AssertionError('NETWORK')):
                    stream=io.StringIO()
                    with redirect_stdout(stream):
                        self.assertEqual(main(['--live','--nba-date','20261025','--output-dir',output]),2)
                    self.assertEqual(json.loads(stream.getvalue())['status'],'COLLECTION_OR_PUBLICATION_NOT_CONFIRMED')

    def test_http_adapter_does_not_follow_redirects_or_retry_denied_sources(self):
        response=Mock(status_code=403)
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('requests.get',return_value=response) as get:
            result=fetch_document('ESPN','https://example.invalid/test')
        self.assertEqual(result['status'],'SOURCE_ACCESS_DENIED');get.assert_called_once()
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_invalid_http_body_oversize_and_timeout_have_explicit_failure_states(self):
        import requests
        for body, expected in ((b'not json','SOURCE_INVALID_JSON'),(b'x'*(4*1024*1024+1),'SOURCE_BODY_LIMIT')):
            response=Mock(status_code=200)
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.iter_content.return_value=iter([body])
            with patch('requests.get',return_value=response),self.subTest(expected=expected):
                self.assertEqual(fetch_document('ESPN','https://example.invalid/test')['status'],expected)
        with patch('requests.get',side_effect=requests.Timeout) as get:
            self.assertEqual(fetch_document('ESPN','https://example.invalid/test')['status'],'SOURCE_NETWORK_ERROR')
            get.assert_called_once()

    def test_disk_full_before_atomic_link_leaves_no_completed_artifact(self):
        b=self.collect()
        with TemporaryDirectory() as folder:
            with patch('season_archive_collect.os.fsync',side_effect=OSError(errno.ENOSPC,'synthetic disk full')):
                with self.assertRaises(OSError):publish_collection(folder,b)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_slow_stream_has_a_total_deadline_not_only_per_read_timeout(self):
        response=Mock(status_code=200)
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=iter([b'{}'])
        with patch('requests.get',return_value=response),patch('season_archive_collect.time.monotonic',side_effect=[0,16]):
            self.assertEqual(fetch_document('ESPN','https://example.invalid/test')['status'],'SOURCE_TOTAL_TIMEOUT')
