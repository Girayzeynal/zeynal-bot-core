"""Keep incomplete HTML useful without misclassifying it as full evidence."""
import unittest
from unittest.mock import patch

from hybrid_engine.europe_injury_public_sources import request,probe,render
from hybrid_engine.europe_injury_article_source import observe_article


class FakeResponse:
    status_code=200
    headers={"Content-Type":"text/html; charset=utf-8"}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def iter_content(self,chunk_size):
        yield b"<html><head><title>Injury news</title></head><body>"
        yield b"x"*300


class PartialHtmlTests(unittest.TestCase):
    def test_large_html_keeps_only_bounded_prefix(self):
        with patch("hybrid_engine.europe_injury_public_sources.requests.get",
                   return_value=FakeResponse()) as getter:
            row=request("https://www.eurohoops.net/en/euroleague/",limit=128)
        self.assertEqual(row["status"],"RECEIVED_PARTIAL")
        self.assertTrue(row["truncated"])
        self.assertEqual(len(row["body"]),128)
        self.assertTrue(row["body"].startswith(b"<html>"))
        getter.assert_called_once()

    def test_partial_robots_policy_still_denies_source_read(self):
        calls=[]
        def source(url,*,mime,limit):
            calls.append(url)
            return dict(status="RECEIVED_PARTIAL",body=b"User-agent: *\nAllow: /")
        spec=dict(name="EUROHOOPS",url="https://www.eurohoops.net/en/euroleague/",
                  kind="SECONDARY_EDITORIAL")
        row=probe(spec,requester=source,now=1795179600)
        self.assertEqual(row["status"],"SOURCE_ROBOTS_UNAVAILABLE")
        self.assertEqual(len(calls),1)

    def test_partial_index_is_visibly_incomplete_not_player_proof(self):
        def source(url,*,mime,limit):
            if url.endswith("/robots.txt"):
                return dict(status="RECEIVED",body=b"User-agent: *\nAllow: /\n")
            return dict(status="RECEIVED_PARTIAL",
                        body=b"<html><head><title>Injury report</title></head><body>")
        spec=dict(name="EUROHOOPS",url="https://www.eurohoops.net/en/euroleague/",
                  kind="SECONDARY_EDITORIAL")
        row=probe(spec,requester=source,now=1795179600)
        self.assertEqual(row["status"],"SOURCE_INDEX_PARTIAL_CANDIDATES_ONLY")
        self.assertTrue(row["incomplete_html"])
        self.assertFalse(row["player_status_verified"])
        self.assertFalse(row["model_input"])
        self.assertIn("yalnız ilk 256 KB",render(dict(sources=[row])))

    def test_incomplete_article_can_only_produce_text_candidates(self):
        def source(url,*,mime,limit):
            if url.endswith("/robots.txt"):
                return dict(status="RECEIVED",body=b"User-agent: *\nAllow: /\n")
            return dict(status="RECEIVED_PARTIAL",
                        body=b"<html><body><article>Maodo Lo will miss the game.</article></body></html>")
        index=dict(url="https://www.eurohoops.net/en/euroleague/")
        link=dict(url="https://www.eurohoops.net/en/injury-update/")
        row=observe_article(index,link,requester=source,now=1795179600)
        self.assertEqual(row["status"],"ARTICLE_TEXT_PARTIAL_CANDIDATES_ONLY")
        self.assertTrue(row["incomplete_html"])
        self.assertFalse(row["player_status_verified"])
        self.assertFalse(row["model_input"])
        self.assertEqual(row["unverified_player_candidates"][0]["player_name_text"],"Maodo Lo")


if __name__=="__main__":
    unittest.main()
