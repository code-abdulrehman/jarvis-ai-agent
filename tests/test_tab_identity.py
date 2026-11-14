import asyncio,unittest
from actions.browser_control import _BrowserSession
class Page:
 def __init__(self,title,url):self.name=title;self.url=url;self.closed=False;self.context=None
 async def title(self):return self.name
 def is_closed(self):return self.closed
 async def close(self):self.closed=True;self.context.pages.remove(self)
 async def bring_to_front(self):pass
 async def evaluate(self,expression):return False
class TabIdentityTests(unittest.TestCase):
 def session(self):
  from types import SimpleNamespace
  s=_BrowserSession('chrome');pages=[Page('GitHub','https://github.com/'),Page('New tab','about:blank'),Page('Orca','https://orca.dev/')]
  s._context=SimpleNamespace(pages=pages)
  for p in pages:p.context=s._context
  s._page=pages[0]
  return s,pages.copy()
 def test_named_close_does_not_close_selected_github(self):
  s,p=self.session();asyncio.run(s.close_tab(tab_query='orca'))
  self.assertFalse(p[0].closed);self.assertFalse(p[1].closed);self.assertTrue(p[2].closed)
 def test_stale_id_never_closes_another_tab(self):
  s,p=self.session();asyncio.run(s.list_tabs());identity=s._tab_id(p[2])
  asyncio.run(s.close_tab(tab_id=identity,tab_query='orca'))
  with self.assertRaisesRegex(RuntimeError,'exist|stale|found'):asyncio.run(s.close_tab(tab_id=identity,tab_query='orca'))
  self.assertFalse(p[0].closed)
 def test_target_id_must_match_title_or_url(self):
  s,p=self.session();asyncio.run(s.list_tabs())
  with self.assertRaisesRegex(RuntimeError,'match'):asyncio.run(s.close_tab(tab_id=s._tab_id(p[0]),tab_query='orca'))
  self.assertFalse(p[0].closed)
 def test_duplicate_names_and_missing_target_fail(self):
  s,p=self.session();extra=Page('Orca docs','https://orca.dev/docs');extra.context=s._context;s._context.pages.append(extra)
  with self.assertRaisesRegex(RuntimeError,'multiple|Ambiguous'):asyncio.run(s.close_tab(tab_query='orca'))
  with self.assertRaisesRegex(RuntimeError,'target|Specify'):asyncio.run(s.close_tab())
  self.assertEqual(len(s._context.pages),4)
 def test_index_uses_last_observed_identity_after_reorder(self):
  s,p=self.session();asyncio.run(s.list_tabs());s._context.pages.reverse()
  asyncio.run(s.switch_tab(2));self.assertIs(s._page,p[2])
if __name__=='__main__':unittest.main()
