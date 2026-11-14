"""Workspace settings, enforced tool access, and local activity metadata."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from memory import config_manager as config

DEFAULTS = {
    'notifications': True, 'spoken_alerts': True, 'browser': True,
    'computer': True, 'vision': True, 'apps_open': True, 'apps_close': True,
    'terminal': True, 'system_settings': True, 'codex': True,
    'tasks': True, 'routines': True, 'history': True, 'allowed_apps': [],
}
_LOCK = threading.RLock()
_runtime = None


def settings() -> dict:
    return {**DEFAULTS, **config.get_workspace_settings()}


def bind_runtime(ui):
    global _runtime
    _runtime = ui
    if settings().get('browser', True):
        def start_bridge():
            try:
                from core.browser_bridge import bridge
                bridge().start()
            except Exception as exc:
                print(f'[Workspace] Browser bridge: {exc}')
        threading.Thread(target=start_bridge, daemon=True, name='WorkspaceConnections').start()


def set_setting(key: str, value):
    if key not in DEFAULTS:
        raise ValueError('Unknown workspace setting')
    if key == 'allowed_apps':
        if not isinstance(value, list):
            raise ValueError('Allowed apps must be a list')
        value = [str(x).strip().casefold() for x in value if str(x).strip()]
    elif not isinstance(value, bool):
        raise ValueError('This setting must be on or off')
    if key == 'codex' and not value:
        from core.codex_connection import client
        client().disconnect()
    config.save_workspace_settings({key: value})
    if not value and key in ('vision', 'browser'):
        if key == 'vision':
            from core.wayland_capture import stop_capture
            stop_capture()
            if _runtime is not None:
                _runtime.stop_camera_stream()
        else:
            from core.browser_bridge import bridge
            bridge().revoke_all()
            # Close owned Playwright windows and detach external CDP contexts.
            from actions.browser_control import _registry
            _registry.close_all()
    if key == 'browser' and value:
        from core.browser_bridge import bridge
        bridge().start()
    record('setting', key, 'on' if value is True else 'off' if value is False else 'updated')
    return settings()


def denial(tool: str, parameters: dict | None = None) -> str | None:
    p = parameters or {}
    action = str(p.get('action', '')).lower()
    cfg = settings()
    category = None
    if tool in ('screen_sharing',) and action in ('stop', 'status'):
        return None
    if tool == 'close_camera':
        return None
    if tool == 'browser_control':
        if action in ('close', 'close_all', 'close_headless'):
            return None
        category = 'browser'
        if action == 'screenshot' and not cfg.get('vision', True):
            return 'Vision is disabled in Workspace.'
    elif tool == 'screen_process' or (tool == 'computer_control' and action in ('screenshot', 'screen_find')):
        category = 'vision'
    elif tool == 'open_app':
        category = 'apps_close' if action in ('close', 'close_app', 'quit') else 'apps_open'
    elif tool == 'computer_control' and action in ('close_app', 'close_application', 'quit_app'):
        category = 'apps_close'
    elif tool in ('computer_control', 'desktop', 'desktop_control', 'screen_agent'):
        category = 'computer'
    elif tool == 'terminal_control':
        category = 'computer' if action == 'type_command' else 'terminal'
    elif tool in ('computer_settings', 'network_control'):
        category = 'system_settings'
    elif tool == 'background_tasks':
        category = 'tasks' if action in ('start', 'steer') else None
    elif tool == 'routines':
        category = 'routines' if action in ('add', 'run', 'run_now', 'enable') else None
    elif tool == 'codex_sessions':
        category = 'codex'
    elif tool == 'system_control' and action in ('notify', 'popup'):
        category = 'notifications'
    if category and not cfg.get(category, True):
        return f'{category.replace("_", " ").capitalize()} is disabled in Workspace.'
    allowed = cfg.get('allowed_apps', [])
    if category in ('apps_open', 'apps_close') and allowed:
        app = str(p.get('app_name') or p.get('app') or p.get('name') or '').strip().casefold()
        if app not in allowed:
            return 'This app is not in the Workspace allowed-app list.'
    permissions = config.get_tool_permissions()
    if permissions.get(tool) == 'deny':
        return f'{tool} is denied in tool permissions.'
    return None


def require(category: str):
    if not settings().get(category, True):
        raise PermissionError(f'{category.replace("_", " ").capitalize()} is disabled in Workspace')


def _history_path() -> Path:
    return config.BASE_DIR / 'memory' / 'workspace' / 'activity.jsonl'


def record(kind: str, name: str, status: str):
    if not settings().get('history', True):
        return
    try:
        with _LOCK:
            path = _history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {'time': time.time(), 'kind': str(kind)[:40], 'name': str(name)[:120], 'status': str(status)[:200]}
            old = path.read_text().splitlines()[-499:] if path.exists() else []
            temp = path.with_suffix('.tmp')
            with temp.open('w', encoding='utf-8') as stream:
                os.chmod(temp, 0o600)
                stream.write('\n'.join(old + [json.dumps(row)]) + '\n')
            temp.replace(path)
    except OSError as exc:
        print(f'[Workspace] Activity history: {exc}')


def history() -> list[dict]:
    with _LOCK:
        path = _history_path()
        if not path.exists():
            return []
        rows = []
        for line in path.read_text().splitlines()[-500:]:
            try: rows.append(json.loads(line))
            except ValueError: pass
        return list(reversed(rows))


def clear_history():
    with _LOCK:
        _history_path().unlink(missing_ok=True)


def status() -> dict:
    from core.platform_support import detect
    from core import wayland_capture
    from core.browser_bridge import bridge
    support = detect()
    return {'settings': settings(), 'os': support.os_name,
            'input_available': support.can_control_input,
            'screen_sharing': wayland_capture.is_active(),
            'browser': bridge().snapshot(), 'notes': support.notes}


def task_list():
    from core.tasks import desktop
    return desktop.ensure().list(limit=100)


def start_task(text, agent='general', minutes=10):
    require('tasks')
    from core.tasks import desktop
    task = desktop.ensure().start(text, agent=agent, minutes=int(minutes))
    record('task', task.get('title') or 'New task', 'started')
    return task


def task_action(tid, action):
    from core.tasks import desktop
    eng = desktop.ensure()
    if action in ('cancel', 'finish'):
        return eng.cancel(tid, finish=action == 'finish')
    if action == 'result':
        return eng.get(tid)
    raise ValueError('Unknown task action')


def routine_engine():
    from core.routines import desktop
    eng = desktop.engine()
    if eng is None:
        raise RuntimeError('Routines become available after the JARVIS voice session connects')
    return eng


def save_routine(payload: dict, rid=''):
    from actions.routines import _trigger
    eng = routine_engine()
    trigger = _trigger(payload)
    if trigger is None:
        raise ValueError('Choose a valid schedule')
    fields = {k: payload[k] for k in ('name','text','deliver','agent','minutes','enabled') if k in payload}
    fields['trigger'] = trigger
    if rid:
        result = eng.update(rid, **fields)
    else:
        require('routines')
        result = eng.add(kind=payload.get('kind','prompt'), **fields)
    record('routine', result['name'], 'saved')
    return result
