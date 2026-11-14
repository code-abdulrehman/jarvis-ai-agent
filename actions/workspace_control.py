"""Voice entry point to the same management workspace used by the UI."""
from core import outcome,workspace

def workspace_control(parameters=None,player=None,**kwargs):
    p=parameters or {};action=p.get('action','status')
    try:
        if action=='open':
            if player is None or not callable(getattr(player,'show_workspace',None)):
                return outcome.failed('workspace_control','The desktop workspace is unavailable')
            player.show_workspace();return outcome.done('workspace_control',opened=True)
        if action=='status':
            state=workspace.status()
            return outcome.untrusted('workspace-status',str(state))
        if action=='history':return outcome.untrusted('activity-history',str(workspace.history()[:25]))
        if action=='set':
            key=str(p.get('control',''));enabled=p.get('enabled')
            if key not in workspace.DEFAULTS or key=='allowed_apps' or not isinstance(enabled,bool):
                return outcome.failed('workspace_control','Choose a valid control and enabled true or false')
            if enabled and key not in ('notifications','spoken_alerts','history'):
                from core import confirm
                def enable_control():
                    workspace.set_setting(key,True)
                    return outcome.done('workspace_control',control=key,enabled=True)
                return confirm.request(key='workspace:'+key,title='Enable '+key.replace('_',' '),
                    detail='Allow JARVIS to use this capability? Existing OS permissions still apply.',
                    run=enable_control)
            workspace.set_setting(key,enabled)
            return outcome.done('workspace_control',control=key,enabled=enabled)
        return outcome.failed('workspace_control','Use open, status, history or set')
    except Exception as exc:return outcome.failed('workspace_control',str(exc))

TOOL={'name':'workspace_control','description':'Open the management Workspace, inspect real status/history, or turn controls on/off when the user asks. Security capability enables require a user confirmation. Controls: notifications, spoken_alerts, browser, computer, vision, apps_open, apps_close, terminal, system_settings, codex, tasks, routines, history.',
 'brief':'Manage connections, access and alerts in Workspace.',
 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['open','status','history','set']},'control':{'type':'STRING'},'enabled':{'type':'BOOLEAN'}},'required':['action']},'handler':workspace_control}
