"""Codex shared app-server client; history stays in Codex's own store."""
from __future__ import annotations
import atexit
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

class CodexConnection:
    def __init__(self):
        self._process=None
        self._socket=None
        self._socket_context=None
        self.transport=""
        self._lock=threading.RLock()
        self._write_lock=threading.Lock()
        self._connect_lock=threading.Lock()
        self._pending={}
        self._approvals={}
        self._events=deque(maxlen=300)
        self._stderr=deque(maxlen=8)
        self._counter=0
        self.error=''
        self.connected=False
        self._turns={}
        self._owned=set()

    def _write(self, message):
        with self._write_lock:
            if self._socket is not None:
                self._socket.send(json.dumps(message))
                return
            if not self._process or self._process.poll() is not None:
                raise RuntimeError('Codex is disconnected')
            self._process.stdin.write(json.dumps(message)+'\n');self._process.stdin.flush()

    def _handle(self,message):
        with self._lock:
            if 'method' in message:
                if 'id' in message:
                    self._approvals[str(message['id'])]=message
                else:
                    self._events.append({'time':time.time(),**message})
                    params=message.get('params') or {}
                    tid=params.get('threadId');turn=params.get('turn') or {}
                    if message['method']=='turn/started' and tid:self._turns[tid]=turn.get('id')
                    if message['method']=='turn/completed' and tid:self._turns.pop(tid,None)
                return
            pending=self._pending.get(str(message.get('id')))
            if pending:pending.put(message)

    def _reader(self,process):
        try:
            for line in process.stdout:
                if self._process is not process:break
                try:self._handle(json.loads(line))
                except (ValueError,TypeError):continue
        except (OSError, ValueError):
            pass
        finally:
            if self._process is process:
                with self._lock:
                    self.connected=False
                    self.error='Codex connection ended. '+ '; '.join(self._stderr)[-600:]
                    for q in self._pending.values():q.put({'error':{'message':self.error}})

    def _socket_reader(self, connection):
        try:
            for message in connection:
                if self._socket is not connection:break
                try:self._handle(json.loads(message))
                except (ValueError,TypeError):continue
        except Exception as exc:
            if self._socket is connection:self.error=str(exc)[:500]
        finally:
            if self._socket is connection:
                self.connected=False
                with self._lock:
                    for q in self._pending.values():q.put({'error':{'message':'Codex disconnected'}})

    def _errors(self,process):
        for line in process.stderr:self._stderr.append(line.strip()[-300:])

    def connect(self):
        from core.workspace import require
        require('codex')
        with self._connect_lock:
            if self.connected:return self.snapshot()
            self.disconnect()
            exe=shutil.which('codex')
            if not exe:raise RuntimeError('Codex CLI is not installed or is not on PATH')
            self.error='';self._stderr.clear()
            codex_home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')
            socket_path=codex_home/'app-server-control'/'app-server-control.sock'
            if socket_path.exists():
                from websockets.sync.client import unix_connect
                self._socket_context=unix_connect(str(socket_path),uri='ws://localhost/',open_timeout=5,max_size=16*1024*1024)
                self._socket=self._socket_context.__enter__()
                self.transport='shared local server'
                threading.Thread(target=self._socket_reader,args=(self._socket,),daemon=True,name='CodexMessages').start()
            else:
                self._process=subprocess.Popen([exe,'app-server','--stdio'],stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
                process=self._process
                self.transport='local stdio server'
                threading.Thread(target=self._reader,args=(process,),daemon=True,name='CodexMessages').start()
                threading.Thread(target=self._errors,args=(process,),daemon=True,name='CodexErrors').start()
            try:
                self.rpc('initialize',{'clientInfo':{'name':'jarvis_workspace','title':'JARVIS Workspace','version':'1.0.0'}},timeout=10,ensure=False)
                self._write({'method':'initialized','params':{}})
                self.connected=True
            except Exception as exc:
                self.disconnect();self.error=str(exc)
                raise RuntimeError('Could not connect to local Codex. Start its shared server with `codex app-server daemon start`. '+str(exc)) from exc
            return self.snapshot()

    def disconnect(self):
        connection,self._socket=self._socket,None
        if connection:
            try:
                if self._socket_context is not None:self._socket_context.__exit__(None,None,None)
                else:connection.close()
            except Exception:pass
        self._socket_context=None
        process,self._process=self._process,None
        self.connected=False
        if process:
            try:
                process.stdin.close();process.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            finally:
                process.stdout.close();process.stderr.close()
        with self._lock:
            for pending in self._pending.values():pending.put({'error':{'message':'Codex disconnected'}})
            self._approvals.clear()

    def rpc(self,method,params=None,timeout=20,ensure=True):
        from core.workspace import require
        require('codex')
        if ensure and not self.connected:self.connect()
        with self._lock:
            self._counter+=1;key=str(self._counter);response=queue.Queue()
            self._pending[key]=response
        try:
            self._write({'id':int(key),'method':method,'params':params or {}})
            try:message=response.get(timeout=timeout)
            except queue.Empty:raise TimeoutError(f'Codex {method} timed out') from None
            if message.get('error'):raise RuntimeError(message['error'].get('message','Codex request failed'))
            require('codex')
            return message.get('result') or {}
        finally:
            with self._lock:self._pending.pop(key,None)

    def threads(self,search='',archived=False,cursor=None):
        params={'limit':60,'archived':bool(archived),'sortKey':'updated_at','sortDirection':'desc','modelProviders':[],'sourceKinds':['cli','vscode','appServer','exec','subAgent','subAgentReview','subAgentCompact','subAgentThreadSpawn','subAgentOther','unknown']}
        if search:params['searchTerm']=search
        if cursor:params['cursor']=cursor
        return self.rpc('thread/list',params)

    def read(self,tid,cursor=None):
        result=self.rpc('thread/read',{'threadId':tid,'includeTurns':False})
        params={'threadId':tid,'limit':30,'itemsView':'full','sortDirection':'desc'}
        if cursor:params['cursor']=cursor
        page=self.rpc('thread/turns/list',params)
        result['thread']['turns']=list(reversed(page.get('data',[])))
        result['historyCursor']=page.get('nextCursor')
        return result

    def resume(self,tid):
        self.rpc('thread/resume',{'threadId':tid,'excludeTurns':True})
        self._owned.add(tid)
        return self.read(tid)

    def new(self,cwd,name=''):
        path=Path(cwd).expanduser().resolve()
        if not path.is_dir():raise ValueError('Choose an existing project directory')
        result=self.rpc('thread/start',{'cwd':str(path),'approvalPolicy':'on-request','sandbox':'workspace-write'})
        tid=result['thread']['id'];self._owned.add(tid)
        if name:self.rename(tid,name)
        return result

    def send(self,tid,text):
        if not str(text).strip():raise ValueError('Enter a message')
        result=self.rpc('turn/start',{'threadId':tid,'input':[{'type':'text','text':str(text),'text_elements':[]}]})
        if result.get('turn',{}).get('id'):self._turns[tid]=result['turn']['id']
        return result

    def rename(self,tid,name):
        if not str(name).strip():raise ValueError('Enter a thread name')
        return self.rpc('thread/name/set',{'threadId':tid,'name':str(name).strip()})

    def archive(self,tid,archived=True):
        return self.rpc('thread/archive' if archived else 'thread/unarchive',{'threadId':tid})

    def fork(self,tid):
        result=self.rpc('thread/fork',{'threadId':tid})
        self._owned.add(result['thread']['id']);return result

    def interrupt(self,tid):
        turn=self._turns.get(tid)
        if not turn:
            read=self.read(tid).get('thread',{})
            turn=next((t['id'] for t in reversed(read.get('turns',[])) if t.get('status')=='inProgress'),None)
        if not turn:raise ValueError('No active turn found for this thread')
        return self.rpc('turn/interrupt',{'threadId':tid,'turnId':turn})

    def approve(self,request_id,accept):
        with self._lock:request=self._approvals.get(str(request_id))
        if not request:raise ValueError('Approval request is no longer pending')
        method=request['method']
        if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
            result={'decision':'accept' if accept else 'decline'}
        elif method in ('execCommandApproval','applyPatchApproval'):
            result={'decision':'approved' if accept else 'denied'}
        else:raise ValueError('This request needs a specific response; inspect it and use the native Codex client')
        self._write({'id':request['id'],'result':result})
        with self._lock:self._approvals.pop(str(request_id),None)

    def answer(self,request_id,answers):
        with self._lock:request=self._approvals.get(str(request_id))
        if not request or request['method']!='item/tool/requestUserInput':raise ValueError('Not a user-input request')
        self._write({'id':request['id'],'result':{'answers':answers}})
        with self._lock:self._approvals.pop(str(request_id),None)

    def snapshot(self):
        with self._lock:
            return {'connected':self.connected,'transport':self.transport,'error':self.error,'approvals':list(self._approvals.values()),
                    'events':list(self._events),'turns':dict(self._turns)}

    @staticmethod
    def transcript(result):
        thread=result.get('thread',result);lines=[]
        for turn in thread.get('turns',[]):
            for item in turn.get('items',[]):
                kind=item.get('type','')
                if kind=='userMessage':
                    text='\n'.join(x.get('text','') for x in item.get('content',[]) if isinstance(x,dict) and x.get('type')=='text')
                    lines.append('You\n'+text)
                elif kind=='agentMessage':lines.append('Codex\n'+item.get('text',''))
                elif kind=='commandExecution':lines.append('Command\n'+str(item.get('command',''))+'\n'+str(item.get('aggregatedOutput') or '')[:3000])
        return '\n\n'.join(lines)[-80000:] or 'No saved messages in this thread.'

_CLIENT=CodexConnection()
def client():return _CLIENT
atexit.register(_CLIENT.disconnect)
