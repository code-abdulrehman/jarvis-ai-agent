"""Paired, loopback-only Chrome profile connections. No cookie copying."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
from memory import config_manager as config

_SINGLETON = None
_SINGLETON_LOCK = threading.Lock()
COMMANDS = {'list_closed_tabs','restore_tab','list_tabs','switch_tab','go_to','search','new_tab','close_tab','get_text','get_url',
            'click','smart_click','type','smart_type','fill_form','scroll','press','back','forward','reload'}

class BrowserBridge:
    def __init__(self):
        self._lock = threading.RLock()
        self._profiles = {p['id']:p for p in config.get_browser_connections() if isinstance(p,dict) and p.get('id')}
        self._connections = {}
        self._pending = {}
        self._pair_code = ''
        self._pair_until = 0
        self._loop = None
        self._server = None
        self._thread = None
        self.port = 0
        self.error = ''

    def _save(self):
        config.save_browser_connections(list(self._profiles.values()))

    def new_pairing_code(self):
        with self._lock:
            self._pair_code = secrets.token_urlsafe(24)
            self._pair_until = time.monotonic()+300
            return self._pair_code

    def pair(self, code, profile_id, name):
        from core.workspace import require
        require('browser')
        with self._lock:
            if not self._pair_code or time.monotonic()>self._pair_until or not hmac.compare_digest(str(code),self._pair_code):
                raise PermissionError('Pairing code is invalid or expired')
            if not isinstance(profile_id,str) or not 1<=len(profile_id)<=100:
                raise ValueError('Invalid profile ID')
            self._disconnect(profile_id)
            token=secrets.token_urlsafe(32)
            self._profiles[profile_id]={'id':profile_id,'name':str(name or 'Chrome profile')[:80],
                'enabled':True,'token_hash':hashlib.sha256(token.encode()).hexdigest()}
            self._pair_code=''
            self._save()
            config.save_workspace_settings({'active_browser_profile':profile_id})
            return {'token':token,'profileId':profile_id}

    def snapshot(self):
        with self._lock:
            return {'running':bool(self._server and self._server.started),'port':self.port,'error':self.error,
                'active':config.get_workspace_settings().get('active_browser_profile',''),
                'profiles':[{'id':p['id'],'name':p['name'],'enabled':p.get('enabled',False),
                    'connected':p['id'] in self._connections} for p in self._profiles.values()]}

    def select(self, profile_id):
        from core.workspace import require
        require('browser')
        with self._lock:
            if profile_id and profile_id not in self._profiles:raise ValueError('Unknown browser profile')
            config.save_workspace_settings({'active_browser_profile':profile_id})

    def enable(self, profile_id, enabled):
        with self._lock:
            if profile_id not in self._profiles:raise ValueError('Unknown browser profile')
            self._profiles[profile_id]['enabled']=bool(enabled)
            self._save()
            if not enabled:self._disconnect(profile_id)

    def _disconnect(self, profile_id):
        ws=self._connections.pop(profile_id,None)
        if ws is not None and self._loop:
            asyncio.run_coroutine_threadsafe(ws.close(code=1000),self._loop)
        for pending_id,p in list(self._pending.items()):
            if p['profile']==profile_id:
                p['error']='Browser profile disconnected';p['event'].set()

    def revoke(self, profile_id):
        with self._lock:
            self._disconnect(profile_id)
            self._profiles.pop(profile_id,None);self._save()
            if config.get_workspace_settings().get('active_browser_profile')==profile_id:
                config.save_workspace_settings({'active_browser_profile':''})

    def revoke_all(self):
        with self._lock:
            for p in self._profiles.values():p['enabled']=False
            for pid in list(self._connections):self._disconnect(pid)
            self._save()

    def request(self, profile_id, command, payload, timeout=20):
        from core.workspace import require,record
        require('browser')
        if command not in COMMANDS:raise ValueError('Unsupported browser bridge action')
        if command in ('click','smart_click','type','smart_type','fill_form','press','go_to','search','new_tab','close_tab','back','forward','reload','scroll','switch_tab'):
            require('browser')
        with self._lock:
            profile=self._profiles.get(profile_id)
            ws=self._connections.get(profile_id)
            if not profile or not profile.get('enabled') or ws is None or self._loop is None:
                raise RuntimeError('Browser profile is not connected or is disabled')
            key=secrets.token_hex(12);item={'profile':profile_id,'event':threading.Event()}
            self._pending[key]=item
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json({'id':key,'command':command,'parameters':payload}),self._loop).result(3)
            if not item['event'].wait(timeout):raise TimeoutError('Browser profile did not answer in time')
            if item.get('error'):raise RuntimeError(item['error'])
            require('browser')
            record('browser',command,'completed')
            return item.get('result')
        finally:
            with self._lock:self._pending.pop(key,None)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():return self.snapshot()
            from fastapi import FastAPI,WebSocket,HTTPException
            from fastapi.middleware.cors import CORSMiddleware
            import uvicorn
            app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
            app.add_middleware(CORSMiddleware,allow_origin_regex=r'chrome-extension://[a-p]{32}',
                allow_methods=['POST'],allow_headers=['Content-Type'])
            @app.post('/pair')
            async def pairing(body:dict):
                try:return self.pair(body.get('code'),body.get('profileId'),body.get('name'))
                except (ValueError,PermissionError) as exc:raise HTTPException(403,str(exc))
            # No annotations from local imports: FastAPI resolves them globally.
            async def profile_socket(ws):
                await ws.accept();profile_id=None
                try:
                    auth=await asyncio.wait_for(ws.receive_json(),timeout=5)
                    profile_id=auth.get('profileId');token=str(auth.get('token') or '')
                    from core.workspace import settings
                    with self._lock:
                        profile=self._profiles.get(profile_id)
                        valid=(settings().get('browser',True) and profile and profile.get('enabled') and
                            hmac.compare_digest(profile.get('token_hash',''),hashlib.sha256(token.encode()).hexdigest()))
                        if valid:
                            self._disconnect(profile_id)
                            self._connections[profile_id]=ws
                    if not valid:
                        await ws.send_json({'error':'Profile is unpaired or disabled'});await ws.close(code=1008);return
                    await ws.send_json({'connected':True})
                    while True:
                        message=await ws.receive_json()
                        if message.get('ping'):
                            await ws.send_json({'pong':True});continue
                        key=message.get('id')
                        with self._lock:
                            item=self._pending.get(key)
                            if item and item['profile']==profile_id:
                                if message.get('error'):item['error']=str(message['error'])[:500]
                                else:item['result']=message.get('result')
                                item['event'].set()
                except Exception:
                    pass  # Disconnect status is surfaced in the Workspace.
                finally:
                    with self._lock:
                        if self._connections.get(profile_id) is ws:self._disconnect(profile_id)
            profile_socket.__annotations__={'ws':WebSocket}
            app.websocket('/profile')(profile_socket)
            sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:sock.bind(('127.0.0.1',8766))
            except OSError:sock.bind(('127.0.0.1',0))
            sock.listen(16);self.port=sock.getsockname()[1]
            self._server=uvicorn.Server(uvicorn.Config(app,log_level='error',ws_max_size=2*1024*1024))
            def run():
                self._loop=asyncio.new_event_loop();asyncio.set_event_loop(self._loop)
                try:self._loop.run_until_complete(self._server.serve(sockets=[sock]))
                except Exception as exc:self.error=str(exc)
                finally:
                    sock.close()
                    self._loop.close()
                    self._loop=None
            self._thread=threading.Thread(target=run,daemon=True,name='BrowserProfiles');self._thread.start()
        for _ in range(50):
            if self._server.started or self.error:break
            time.sleep(.02)
        return self.snapshot()

    def stop(self):
        with self._lock:
            for pid in list(self._connections):self._disconnect(pid)
            if self._server:self._server.should_exit=True
        if self._thread:self._thread.join(timeout=3)


def bridge():
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:_SINGLETON=BrowserBridge()
        return _SINGLETON
