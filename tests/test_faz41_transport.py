"""No real network calls; bounded failure behaviours."""
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock
from urllib.error import HTTPError,URLError

from faz41_transport import fetch,MAX_BYTES

URL='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=1'


class TransportTests(TestCase):
    def opener(self,body=b'{}',media='application/json',url=URL):
        response=Mock();response.status=200;response.geturl.return_value=url;response.read.return_value=body
        response.headers={'Content-Type':media,'Date':'Fri, 06 Nov 2026 12:00:00 GMT'}
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        return Mock(open=Mock(return_value=response))

    def test_success_has_observation_clock_and_unknown_usage(self):
        o=self.opener();result=fetch(URL,provider='ESPN',opener=o)
        self.assertEqual(result['status'],'DOCUMENT_RECEIVED');self.assertEqual(result['usage_status'],'UNKNOWN')
        self.assertLessEqual(result['started_at_utc'],result['observed_at_utc'])
        o.open.return_value.read.assert_called_once_with(MAX_BYTES+1)

    def test_403_429_and_other_http_errors_remain_distinct_without_retries(self):
        for status in (403,429,500):
            o=Mock();o.open.side_effect=HTTPError(URL,status,'error',{'Retry-After':'120'},BytesIO())
            result=fetch(URL,provider='ESPN',opener=o)
            self.assertEqual(result['status'],{403:'HTTP_403',429:'HTTP_429'}.get(status,'HTTP_ERROR'))
            self.assertEqual(result['retry_after'],'120');self.assertFalse(result['automatic_retry'])
            o.open.assert_called_once()

    def test_network_timeout_is_not_provider_data(self):
        for ex in (TimeoutError(),URLError('offline')):
            o=Mock();o.open.side_effect=ex;r=fetch(URL,provider='ESPN',opener=o)
            self.assertEqual(r['status'],'TRANSPORT_FAILED');self.assertNotIn('payload',r)

    def test_bad_json_html_wrong_mime_and_oversize_are_rejected(self):
        for body,media in [(b'bad','application/json'),(b'[]','application/json'),(b'<html/>','text/html'),(b'x'*(MAX_BYTES+1),'application/json')]:
            self.assertEqual(fetch(URL,provider='ESPN',opener=self.opener(body,media))['status'],'INVALID_DOCUMENT')

    def test_redirect_and_unregistered_destination_are_rejected(self):
        self.assertEqual(fetch(URL,provider='ESPN',opener=self.opener(url='https://evil.test/'))['status'],'INVALID_DOCUMENT')
        o=Mock()
        with self.assertRaises(ValueError):fetch('https://evil.test/',provider='ESPN',opener=o)
        o.open.assert_not_called()

    def test_news_fetch_requires_explicit_permission_before_connection(self):
        o=Mock()
        with self.assertRaises(ValueError):fetch(URL,provider='ESPN',data_type='NEWS_CLAIM',format='rss',opener=o)
        o.open.assert_not_called()
