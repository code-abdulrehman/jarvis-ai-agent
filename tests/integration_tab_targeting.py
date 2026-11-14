"""Manual: .venv/bin/python tests/integration_tab_targeting.py

Uses isolated temporary profiles and localhost pages; never touches user tabs.
Requires Playwright's Chromium test browser (playwright install chromium --no-shell).
"""
import asyncio
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from memory import config_manager as config
from core.browser_bridge import BrowserBridge
from actions.browser_control import _BrowserSession
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright

class Site(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        title='Orca' if self.path.startswith('/orca') else 'GitHub'
        content=f'<title>{title}</title><h1>{title}</h1>'.encode()
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(content)


def extension_test(root,base):
    extension=root/'extension';shutil.copytree(ROOT/'browser-extension',extension)
    # Grant optional restore permission only in this temporary QA profile.
    manifest=json.loads((extension/'manifest.json').read_text())
    manifest['permissions'].append('sessions');manifest.pop('optional_permissions',None)
    (extension/'manifest.json').write_text(json.dumps(manifest))
    b=BrowserBridge();b.start();code=b.new_pairing_code()
    try:
        with sync_playwright() as pw:
            context=pw.chromium.launch_persistent_context(str(root/'extension-profile'),channel='chromium',headless=True,
                args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
            try:
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                github=context.pages[0];github.goto(base+'/github')
                blank=context.new_page()
                orca=context.new_page();orca.goto(base+'/orca');github.bring_to_front()
                pid=worker.evaluate('''async ([port,code])=>{
                    const profileId=crypto.randomUUID();
                    const response=await fetch(`http://127.0.0.1:${port}/pair`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,profileId,name:'QA tabs'})});
                    const data=await response.json();if(!response.ok)throw Error(JSON.stringify(data));
                    await chrome.storage.local.set({profileId,token:data.token,bridgePort:port});await connect();return profileId;
                }''',[b.port,code])
                for _ in range(80):
                    if b.snapshot()['profiles'][0]['connected']:break
                    time.sleep(.1)
                rows=b.request(pid,'list_tabs',{});target=next(t for t in rows if t['title']=='Orca')
                original_id=target['tab_id']
                result=b.request(pid,'close_tab',{'tab_id':original_id,'tab_query':'Orca','expected_url':base+'/orca'})
                assert result['closed'] is True and result['tab_id']==original_id
                # Pump Playwright's sync transport after the external extension action.
                for _ in range(20):
                    github.wait_for_timeout(50)
                    if orca.is_closed():break
                assert not github.is_closed() and not blank.is_closed() and orca.is_closed(), (github.is_closed(),blank.is_closed(),orca.is_closed())
                remaining=b.request(pid,'list_tabs',{});assert len(remaining)==2
                restored=b.request(pid,'restore_tab',{'tab_query':'Orca'})
                assert restored['restored'] and restored['tab_id']!=original_id and restored['url']==base+'/orca'
                try:b.request(pid,'close_tab',{'tab_id':original_id,'tab_query':'Orca'});raise AssertionError('Stale ID succeeded')
                except RuntimeError:pass
                assert not github.is_closed()
                target=next(t for t in b.request(pid,'list_tabs',{}) if t['title']=='GitHub')
                try:b.request(pid,'close_tab',{'tab_id':target['tab_id'],'tab_query':'Orca'});raise AssertionError('Mismatched ID succeeded')
                except RuntimeError:pass
                assert not github.is_closed()
                print('Chrome extension: close exact Orca, restore its session, reject stale/mismatched IDs: PASS',flush=True)
            finally:context.close()
    finally:b.stop()


async def playwright_test(root,base):
    async with async_playwright() as pw:
        context=await pw.chromium.launch_persistent_context(str(root/'pw-profile'),channel='chromium',headless=True)
        session=_BrowserSession('chrome');session._context=context
        try:
            github=context.pages[0];await github.goto(base+'/github')
            blank=await context.new_page()
            orca=await context.new_page();await orca.goto(base+'/orca')
            session._page=github
            rows=await session._tab_rows();target=next(t for t in rows if t['title']=='Orca');old_id=target['tab_id']
            await session.close_tab(tab_id=old_id,tab_query='Orca')
            assert orca.is_closed() and not github.is_closed() and not blank.is_closed()
            await session.restore_tab(tab_query='Orca')
            assert session._tab_id(session._page)!=old_id
            try:await session.close_tab(tab_id=old_id,tab_query='Orca');raise AssertionError('Stale ID succeeded')
            except RuntimeError:pass
            assert not github.is_closed()
            print('Playwright: exact close, explicit URL reopen, and stale ID rejection: PASS',flush=True)
        finally:await context.close()


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Site);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-tab-identity-') as folder:
            root=Path(folder);(root/'config').mkdir()
            with patch.object(config,'BASE_DIR',root),patch.object(config,'CONFIG_DIR',root/'config'),patch.object(config,'CONFIG_FILE',root/'config/api_keys.json'):
                base='http://127.0.0.1:'+str(server.server_port)
                extension_test(root,base)
                asyncio.run(playwright_test(root,base))
    finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
