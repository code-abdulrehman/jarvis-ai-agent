"""
core/popups.py — on-screen popups and notifications for anything JARVIS wants
to say that does not fit in the spoken answer.

WHY THIS EXISTS
    The assistant already talks (TTS), writes to the activity log and shows
    content in the HUD panel. Those cover narration and questions. What they do
    NOT cover is the case the user was waiting for: the task finished, the
    battery is low, the browser is about to be closed, something needs a human.
    For all of those the machine should do something visible on its own — a
    toast on the corner, a dialog in the middle — without JARVIS having to stop
    mid-sentence to describe it.

THE SAME NEVER-CLAIM RULE, APPLIED HERE
    Every helper returns a bool and says nothing on its own. True means "the
    operating system accepted the popup" — on Windows that is win10toast (the
    same library reminder.py already uses, so one code path already existed and
    only the plumbing was missing), on Linux notify-send, on macOS osascript.
    On a system where none of them is available the helper returns False and
    the caller says so; a popup that could not be shown is not a popup that was.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
from typing import Optional


def _os() -> str:
    return platform.system().lower()


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def show(title: str, message: str, urgency: str = "normal") -> bool:
    """Show a notification / toast. True when the OS accepted it.

    urgency: "low" | "normal" | "high" — passed to the platform where it exists
    (notify-send's -u). Anything else is folded into "normal".
    """
    title   = str(title or "J.A.R.V.I.S").strip() or "J.A.R.V.I.S"
    message = str(message or "").strip()
    if not message:
        return False

    os_name = _os()

    if os_name == "windows":
        if not _installed("win10toast"):
            return False
        from win10toast import ToastNotifier          # noqa: PLC0415 — lazy on purpose
        toaster = ToastNotifier()
        try:
            toaster.show_toast(title=title, msg=message, duration=8, threaded=False)
            return True
        except Exception:
            return False

    if os_name == "linux":
        binary = shutil.which("notify-send")
        if not binary:
            return False
        try:
            return subprocess.run(
                [binary, "-u", str(urgency or "normal"), title, message],
                capture_output=True, timeout=10,
            ).returncode == 0
        except Exception:
            return False

    if os_name == "darwin":
        script = (
            f'display notification "{message}" with title "{title}"'
        )
        try:
            return subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=10,
            ).returncode == 0
        except Exception:
            return False

    return False


def alert(title: str, message: str) -> bool:
    """Show a blocking native dialog. True when one was actually shown.

    This is the "stop and ask the person" popup — the one that carries a real
    question or a real warning. It blocks until the person answers or dismisses,
    so the caller runs it on a worker thread and must expect the tool to take as
    long as the person takes (the executor already isolates this from the UI).
    """
    title   = str(title or "J.A.R.V.I.S").strip() or "J.A.R.V.I.S"
    message = str(message or "").strip()
    if not message:
        return False

    os_name = _os()

    if os_name == "windows":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, message, title, 0x00000000,  # MB_OK
            )
            return True
        except Exception:
            return False

    if os_name == "macos":
        script = f'display dialog "{message}" with title "{title}" buttons {{"OK"}} default button "OK"'
        try:
            return subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=30,
            ).returncode == 0
        except Exception:
            return False

    # Linux: zenity is the standard; notify-send cannot carry a question.
    binary = shutil.which("zenity")
    if not binary:
        return False
    try:
        return subprocess.run(
            [binary, "--info", "--text", message, "--title", title],
            capture_output=True, timeout=30,
        ).returncode == 0
    except Exception:
        return False
