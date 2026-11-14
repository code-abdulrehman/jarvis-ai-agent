"""Inspect or stop JARVIS's active Wayland screen-sharing session."""
from core import outcome


def screen_sharing(parameters=None, **kwargs):
    from core import wayland_capture
    action = str((parameters or {}).get('action', 'status')).lower()
    if action == 'stop':
        wayland_capture.stop_capture()
        return outcome.done('screen_sharing', stopped=True,
                            note='Sharing stopped. A future screen request needs a new desktop grant.')
    if action == 'status':
        return outcome.done('screen_sharing', active=wayland_capture.is_active())
    return outcome.failed('screen_sharing', 'Use action status or stop')


TOOL = {
    'name': 'screen_sharing',
    'description': 'Check or stop the active Wayland screen-sharing session. Stop closes the portal and releases screen access; future capture needs a new grant.',
    'brief': 'Check or stop screen sharing.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'description': 'status | stop'},
    }},
    'handler': screen_sharing,
}
