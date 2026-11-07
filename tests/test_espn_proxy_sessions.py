"""Owned sessions honor deployment proxy settings; injected sessions stay owned by callers."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from providers.espn_adapter import ESPNAdapter
from providers.espn_scoreboard_history import ESPNScoreboardHistory


class ESPNProxySessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_owned_session_uses_environment_proxy(self):
        adapter = ESPNAdapter()
        with patch("providers.espn_adapter.aiohttp.ClientSession") as factory:
            session = factory.return_value
            session.closed = False
            session.close = AsyncMock()
            self.assertIs(await adapter._get_session(), session)
            self.assertIs(await adapter._get_session(), session)
            factory.assert_called_once()
            self.assertIs(factory.call_args.kwargs.get("trust_env"), True)
            self.assertEqual(factory.call_args.kwargs["timeout"].total, 20)
            await adapter.aclose()
            session.close.assert_awaited_once()

    async def test_history_owned_session_uses_environment_proxy(self):
        history = ESPNScoreboardHistory()
        with patch("providers.espn_scoreboard_history.aiohttp.ClientSession") as factory:
            session = factory.return_value
            session.closed = False
            session.close = AsyncMock()
            response = MagicMock(status=200)
            response.json = AsyncMock(return_value={"events": []})
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            self.assertEqual(await history._fetch_day("20261101"), [])
            factory.assert_called_once()
            self.assertIs(factory.call_args.kwargs.get("trust_env"), True)
            self.assertEqual(factory.call_args.kwargs["timeout"].total, 15)
            await history.aclose()
            session.close.assert_awaited_once()

    async def test_caller_sessions_are_reused_and_never_closed(self):
        for cls in (ESPNAdapter, ESPNScoreboardHistory):
            with self.subTest(adapter=cls.__name__):
                session = MagicMock(closed=False)
                session.close = AsyncMock()
                adapter = cls(session=session)
                if isinstance(adapter, ESPNAdapter):
                    self.assertIs(await adapter._get_session(), session)
                await adapter.aclose()
                session.close.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
