import asyncio
import importlib.util
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from actions import browser_control as m
class BrowserTests(unittest.TestCase):
    def test_about_blank_is_not_rewritten_as_a_domain(self):
        self.assertEqual(m._normalize_url('about:blank'), 'about:blank')
    def test_live_context_reused_without_nonexistent_is_closed(self):
        session=m._BrowserSession('chrome'); session._context=SimpleNamespace(pages=[])
        asyncio.run(session._launch())
        self.assertIsNotNone(session._context)
    def test_navigation_stays_in_controlled_session(self):
        class Session:
            async def go_to(self,url): return 'controlled '+url
            def run(self,coro): return asyncio.run(coro)
        with patch.object(m._registry,'get',return_value=Session()), patch.object(m._registry,'has',return_value=False), patch.object(m,'_open_native',return_value='native'):
            self.assertEqual(m.browser_control({'action':'go_to','url':'https://example.com','browser':'chrome'}),'controlled https://example.com')
    def test_adopt_page_detects_context_close(self):
        session=m._BrowserSession('chrome'); callbacks={}
        context=SimpleNamespace(pages=['page'],on=lambda event,fn: callbacks.update({event:fn}))
        session._context=context
        asyncio.run(session._adopt_page())
        self.assertIn('close',callbacks)
        callbacks['close']()
        self.assertIsNone(session._context)
    def test_inspection_does_not_start_a_new_browser(self):
        for action in ('list_tabs', 'get_text', 'get_url', 'switch_tab', 'click'):
            with self.subTest(action=action), patch.object(m, '_registry', m._SessionRegistry()), patch.object(m._BrowserSession, 'start') as start:
                result = m.browser_control({'action': action, 'browser': 'chrome'})
                self.assertIn('status=failed', result)
                self.assertIn('not connected', result)
                start.assert_not_called()

    def test_list_tabs_without_context_does_not_launch(self):
        session = m._BrowserSession('chrome')
        with patch.object(session, '_launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'not connected'):
                asyncio.run(session.list_tabs())
            launch.assert_not_called()

    def test_missing_debug_endpoint_does_not_create_session(self):
        with patch.object(m, '_registry', m._SessionRegistry()), patch.object(m, '_check_cdp_endpoint', create=True, side_effect=RuntimeError('No listener')), patch.object(m._BrowserSession, 'start') as start:
            result = m.browser_control({'action': 'attach'})
            self.assertIn('status=failed', result)
            self.assertIn('debug_endpoint_unavailable', result)
            start.assert_not_called()

    def test_endpoint_probe_rejects_non_debug_server_and_closes_connection(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.getresponse.return_value.status = 404
        with patch.object(m.http.client, 'HTTPConnection', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'not a Chrome'):
                m._check_cdp_endpoint('http://127.0.0.1:9222')
        connection.close.assert_called_once()

    def test_existing_returns_only_connected_contexts(self):
        registry = m._SessionRegistry()
        registry._active_browser = 'chrome'
        session = SimpleNamespace(_context=None)
        registry._sessions['chrome'] = session
        self.assertIsNone(registry.existing())
        session._context = object()
        self.assertIs(registry.existing(), session)

if __name__=='__main__':unittest.main()
