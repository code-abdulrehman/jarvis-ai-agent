"""Session-scoped, consent-based Wayland capture; frames never touch disk.

The worker uses Ubuntu's system Python/GStreamer, avoiding PyGObject in the
application virtualenv. One portal grant and PipeWire connection serve all
captures until JARVIS exits, stop_capture() is called, or sharing is revoked.
"""
from __future__ import annotations

import atexit
import base64
import json
import selectors
import subprocess
import sys
import threading
from pathlib import Path

_process = None
_lock = threading.Lock()
_diagnostics = []


def _drain_errors(pipe):
    for line in pipe:
        text = line.decode('utf-8', errors='replace').strip()
        if text:
            _diagnostics.append(text[-500:])
            del _diagnostics[:-8]


def _stop_locked():
    global _process
    process, _process = _process, None
    if process is None:
        return
    try:
        process.stdin.close()  # EOF makes worker close portal and PipeWire.
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    finally:
        process.stdout.close()
        process.stderr.close()


def is_active() -> bool:
    with _lock:
        if _process is None or _process.poll() is not None:
            return False
        try:
            _process.stdin.write(b'status\n')
            _process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(_process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=3):
                    raise RuntimeError('Screen sharing status timed out')
            active = bool(json.loads(_process.stdout.readline()).get('active'))
            if not active:
                _stop_locked()
            return active
        except Exception:
            _stop_locked()
            return False


def stop_capture():
    with _lock:
        _stop_locked()


def capture_frame() -> bytes:
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            _stop_locked()
            _diagnostics.clear()
            _process = subprocess.Popen(
                ['/usr/bin/python3', '-u', str(Path(__file__).resolve()), '--worker'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            threading.Thread(target=_drain_errors, args=(_process.stderr,), daemon=True).start()
        try:
            _process.stdin.write(b'capture\n')
            _process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(_process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=70):
                    raise RuntimeError('Screen sharing timed out; accept the desktop sharing dialog and try again.')
            line = _process.stdout.readline(24 * 1024 * 1024)
            if not line:
                raise RuntimeError('Screen sharing stopped: ' + '; '.join(_diagnostics))
            response = json.loads(line)
            if 'error' in response:
                raise RuntimeError(response['error'])
            frame = base64.b64decode(response['png'], validate=True)
            if not frame.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('Screen sharing returned an invalid frame')
            return frame
        except Exception:
            _stop_locked()
            raise


atexit.register(stop_capture)


def _worker():
    import os
    import uuid
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gio, GLib, Gst
    Gst.init(None)
    for name in ('pipewiresrc', 'videoconvert', 'videorate', 'pngenc', 'appsink'):
        if not Gst.ElementFactory.find(name):
            raise RuntimeError(f'GStreamer {name} missing; install gstreamer1.0-pipewire and gstreamer1.0-plugins-good')
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    destination = 'org.freedesktop.portal.Desktop'
    root = '/org/freedesktop/portal/desktop'
    interface = 'org.freedesktop.portal.ScreenCast'
    sender = bus.get_unique_name()[1:].replace('.', '_')
    session = None
    pipeline = None
    remote_fd = None
    closed = threading.Event()
    background_loop = None
    subscriptions = []

    def request(method, signature, args, options):
        token = 'jarvis_' + uuid.uuid4().hex
        path = root + '/request/' + sender + '/' + token
        options = dict(options, handle_token=GLib.Variant('s', token))
        result = {}
        loop = GLib.MainLoop()
        def response(conn, sender, path, interface, signal, params):
            code, values = params.unpack()
            result.update(code=code, values=values)
            loop.quit()
        def timeout():
            result['error'] = 'Screen sharing permission timed out'
            loop.quit()
            return False
        sub = bus.signal_subscribe(destination, 'org.freedesktop.portal.Request',
                                   'Response', path, None, Gio.DBusSignalFlags.NONE, response)
        timer = GLib.timeout_add_seconds(55, timeout)
        try:
            reply = bus.call_sync(destination, root, interface, method,
                GLib.Variant(signature, (*args, options)), GLib.VariantType.new('(o)'),
                Gio.DBusCallFlags.NONE, 10000, None)
            if reply.unpack()[0] != path:
                raise RuntimeError('Unexpected screen sharing request handle')
            loop.run()
            if 'error' in result:
                try:
                    bus.call_sync(destination, path, 'org.freedesktop.portal.Request', 'Close',
                                  None, None, Gio.DBusCallFlags.NONE, 2000, None)
                except Exception as exc:
                    print(f'Portal close: {exc}', file=sys.stderr)
                raise RuntimeError(result['error'])
            if result.get('code') != 0:
                raise RuntimeError('Screen sharing cancelled, denied, or unavailable; no capture was taken')
            return result['values']
        finally:
            bus.signal_unsubscribe(sub)
            if 'error' not in result:
                GLib.source_remove(timer)

    try:
        for command in sys.stdin:
            if command.strip() == 'status':
                print(json.dumps({'active': session is not None and not closed.is_set()}), flush=True)
                continue
            if command.strip() != 'capture':
                continue
            try:
                if closed.is_set():
                    raise RuntimeError('Screen sharing was stopped from the desktop; start a new capture to request access again')
                if session is None:
                    result = request('CreateSession', '(a{sv})', (), {
                        'session_handle_token': GLib.Variant('s', 'jarvis_' + uuid.uuid4().hex)})
                    session = result['session_handle']
                    sub = bus.signal_subscribe(destination, 'org.freedesktop.portal.Session',
                        'Closed', session, None, Gio.DBusSignalFlags.NONE,
                        lambda *args: closed.set())
                    subscriptions.append(sub)
                    request('SelectSources', '(oa{sv})', (session,), {
                        'types': GLib.Variant('u', 1), 'multiple': GLib.Variant('b', False)})
                    result = request('Start', '(osa{sv})', (session, ''), {})
                    streams = result.get('streams', [])
                    if not streams:
                        raise RuntimeError('No screen selected for sharing')
                    reply, fds = bus.call_with_unix_fd_list_sync(destination, root, interface,
                        'OpenPipeWireRemote', GLib.Variant('(oa{sv})', (session, {})),
                        GLib.VariantType.new('(h)'), Gio.DBusCallFlags.NONE, 10000, None, None)
                    remote_fd = fds.get(reply.unpack()[0])
                    node, props = streams[0]
                    target = props.get('pipewire-serial', node)
                    pipeline = Gst.parse_launch(
                        f'pipewiresrc fd={remote_fd} path={node} do-timestamp=true keepalive-time=500 ! '
                        'videoconvert ! videorate drop-only=true ! video/x-raw,framerate=2/1 ! '
                        'pngenc compression-level=1 ! appsink name=frames max-buffers=1 drop=true sync=false')
                    if 'pipewire-serial' in props:
                        source = pipeline.get_by_name('pipewiresrc0')
                        if source is not None and source.find_property('target-object'):
                            source.set_property('target-object', str(target))
                    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                        raise RuntimeError('PipeWire screen stream could not start')
                    background_loop = GLib.MainLoop()
                    threading.Thread(target=background_loop.run, daemon=True).start()
                sink = pipeline.get_by_name('frames')
                # Discard queued data so a new request never returns an old screen.
                sink.emit('try-pull-sample', 0)
                sample = sink.emit('try-pull-sample', 8 * Gst.SECOND)
                if closed.is_set():
                    raise RuntimeError('Screen sharing was revoked')
                if sample is None:
                    message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                    detail = str(message.parse_error()[0]) if message else 'no fresh frame within 8 seconds'
                    raise RuntimeError('PipeWire capture failed: ' + detail)
                buffer = sample.get_buffer()
                data = buffer.extract_dup(0, buffer.get_size())
                print(json.dumps({'png': base64.b64encode(data).decode('ascii')}), flush=True)
            except Exception as exc:
                print(json.dumps({'error': str(exc)}), flush=True)
                break
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        if remote_fd is not None:
            os.close(remote_fd)
        for sub in subscriptions:
            bus.signal_unsubscribe(sub)
        if session is not None:
            try:
                bus.call_sync(destination, session, 'org.freedesktop.portal.Session', 'Close',
                              None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except Exception as exc:
                print(f'Portal session cleanup: {exc}', file=sys.stderr)
        if background_loop is not None:
            background_loop.quit()


if __name__ == '__main__' and '--worker' in sys.argv:
    try:
        _worker()
    except Exception as exc:
        print(json.dumps({'error': f'Wayland sharing unavailable: {exc}'}), flush=True)
        sys.exit(1)
