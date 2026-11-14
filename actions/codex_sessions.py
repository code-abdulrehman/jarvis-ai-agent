"""Voice access to local Codex threads; approvals remain in the user's UI."""
from core import outcome,workspace
from core.codex_connection import client

def codex_sessions(parameters=None,**kwargs):
    p=parameters or {};action=p.get('action','list');tid=str(p.get('thread_id',''))
    try:
        workspace.require('codex');c=client()
        if action=='list':result=c.threads(p.get('search',''),p.get('archived',False),p.get('cursor'))
        elif action=='read':return outcome.untrusted('codex-history',c.transcript(c.read(tid)))
        elif action=='resume':result=c.resume(tid)
        elif action=='new':result=c.new(p.get('cwd',''),p.get('name',''))
        elif action=='send':c.resume(tid);result=c.send(tid,p.get('text',''))
        elif action=='interrupt':result=c.interrupt(tid)
        elif action=='rename':result=c.rename(tid,p.get('name',''))
        elif action=='fork':result=c.fork(tid)
        elif action=='archive':result=c.archive(tid,True)
        elif action=='restore':result=c.archive(tid,False)
        else:return outcome.failed('codex_sessions','Unknown thread action')
        workspace.record('codex',action,'completed')
        if action=='list':
            result={'threads':[{'id':t['id'],'name':t.get('name') or t.get('preview'),'cwd':t.get('cwd'),'status':t.get('status')} for t in result.get('data',[])],'nextCursor':result.get('nextCursor')}
        elif isinstance(result,dict) and result.get('thread'):
            result={'id':result['thread']['id'],'status':result['thread'].get('status')}
        return outcome.untrusted('codex-result',str(result)[:14000])
    except Exception as exc:return outcome.failed('codex_sessions',str(exc))

TOOL={'name':'codex_sessions','description':'Manage installed local Codex threads: list/read history, resume, create a thread in an existing cwd, send a user-requested task, interrupt, rename, fork, archive or restore. Use actual thread IDs returned by list. Never create or send work unless requested by the user. Approval requests are displayed in Workspace for the human; this tool cannot approve them.',
 'brief':'Manage local Codex threads and history.',
 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['list','read','resume','new','send','interrupt','rename','fork','archive','restore']},'thread_id':{'type':'STRING'},'cwd':{'type':'STRING'},'name':{'type':'STRING'},'text':{'type':'STRING'},'search':{'type':'STRING'},'archived':{'type':'BOOLEAN'},'cursor':{'type':'STRING'}},'required':['action']},'handler':codex_sessions}
