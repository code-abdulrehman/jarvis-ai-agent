"""Report OS-level input limits separately from portal and browser access.

Wayland blocks the legacy global input APIs used here, while approved portal
screen sharing and Playwright browser DOM actions remain available.
"""
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field


@dataclass
class Support:
    """What is possible here. Every field is a fact about THIS machine."""

    os_name: str
    can_control_input: bool = True      # type, click, hotkeys
    can_capture_screen: bool = True     # screenshots, vision
    can_focus_windows: bool = True      # raise another app's window
    notes: list[str] = field(default_factory=list)

    @property
    def fully_capable(self) -> bool:
        return (self.can_control_input and self.can_capture_screen
                and self.can_focus_windows)


def _linux_session() -> str:
    """'wayland', 'x11', or '' when there is no graphical session at all."""
    session = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if session in ("wayland", "x11"):
        return session
    # XDG_SESSION_TYPE is not always set — a compositor's own variable is the
    # reliable second opinion, and DISPLAY is the last one.
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return ""


def detect() -> Support:
    """Work out what this machine permits. Never raises, never blocks.

    Deliberately cheap — environment variables and `shutil.which` — because it
    runs at startup and because the expensive way to find out is to try the
    action and watch it silently do nothing, which is the problem.
    """
    system = platform.system()

    if system == "Windows":
        return Support(os_name="Windows")

    if system == "Darwin":
        support = Support(os_name="macOS")
        # There is no reliable way to READ the Accessibility permission without
        # a native extension, so this cannot be a hard answer — it is a warning
        # attached to the thing people actually get wrong.
        support.notes.append(
            "macOS asks for two permissions before an assistant can drive the "
            "computer: Accessibility (to type and click) and Screen Recording "
            "(to see the screen), both under System Settings > Privacy & "
            "Security. Until they are granted, those actions appear to succeed "
            "and do nothing."
        )
        return support

    # ── Linux ────────────────────────────────────────────────────────────────
    session = _linux_session()
    support = Support(os_name="Linux")

    if not session:
        support.can_control_input = False
        support.can_capture_screen = False
        support.can_focus_windows = False
        support.notes.append(
            "No graphical session was found, so nothing on this machine can be "
            "typed, clicked, captured or focused. Voice, memory, files and the "
            "web still work."
        )
        return support

    if session == "wayland":
        support.can_control_input = False
        support.can_capture_screen = True  # Portal consent/dependencies checked at capture.
        support.can_focus_windows = False
        support.notes.append(
            "Wayland: screen capture uses a user-approved ScreenCast portal "
            "session. Keyboard/mouse control of arbitrary desktop apps is "
            "unavailable through the legacy input tools. Browser page reading "
            "and interaction through browser_control still work."
        )
        return support

    # X11: everything is possible, but two small tools carry window focus.
    if not (shutil.which("xdotool") or shutil.which("wmctrl")):
        support.can_focus_windows = False
        support.notes.append(
            "Neither xdotool nor wmctrl is installed, so an application that "
            "is already running cannot be brought to the front — it will be "
            "launched again instead. Install either one to fix that."
        )
    return support


def describe_for_model(support: Support) -> list[str]:
    """The limits, phrased for `_describe_limits` in main.py.

    Written as facts about the machine rather than as refusals, because a model
    told "you cannot do X here, and this is why" explains it to the user; a
    model told "do not do X" invents a reason.
    """
    lines: list[str] = []
    if not support.can_control_input:
        lines.append(
            "- Global keyboard/mouse automation of arbitrary desktop apps is "
            "unavailable through the legacy input tools in this session. "
            "This does NOT prevent browser_control DOM reading, clicking or "
            "typing inside its controlled browser, or terminal_control shell "
            "commands. Use those tools when appropriate.")
    if not support.can_capture_screen:
        lines.append(
            "- You CANNOT see the screen in this session, for the same reason. "
            "Say so rather than describing anything.")
    if not support.can_focus_windows and support.can_control_input:
        lines.append(
            "- You cannot bring an already-running application to the front "
            "here; opening it starts another window instead.")
    return lines


def describe_for_user(support: Support) -> list[str]:
    """One line per note, for the activity log at startup."""
    return [f"SYS: {note}" for note in support.notes]
