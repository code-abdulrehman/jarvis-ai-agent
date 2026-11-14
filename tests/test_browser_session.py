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
if __name__=='__main__':unittest.main()
