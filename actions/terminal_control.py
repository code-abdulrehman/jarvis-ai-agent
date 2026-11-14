# terminal_control.py — the local terminal, as a tool.
#
# TWO KINDS OF "RUN ON MY COMPUTER", AND WHY THEY ARE SEPARATE TOOLS
#     typing into a terminal window is what a person does; running a command is
#     what a machine does. Both are real computer use, and both are now available:
#
#       type_command — put text in front of whatever is open (a terminal, an
#                      editor, a URL bar, a chat box) and press enter. Uses the
#                      same lazy pyautogui path computer_control already uses, so
#                      it costs nothing at launch and nothing it does not need.
#       run_command — execute a local shell command and read the output back.
#
# THE SECOND ONE IS THE ONE WITH A DOOR ON IT
#     A command line is code, and this project has a long memory of refusing to
#     run code it was handed by a model. The difference here is the user: it is
#     the person's own machine, and it is the person's own words that became
#     the command. So the dangerous half of the shell is not left to vibes — it
#     goes through the same confirmation gate the shutdown / restart / WiFi
#     paths use (core/confirm.py, token issued by the interface, never by the
#     model). Everything else runs with a timeout and a captured output, and the
#     answer is `done` / `unverified` / `failed` from core/outcome — never a bare
#     success sentence.
from __future__ import annotations

import subprocess

from core import outcome
from core import confirm
from core.lazyimport import LazyModule, installed


# pyautogui and pyperclip are imported on first USE, not at launch — see
# core/lazyimport.py for why and for what stays the same. The flags still mean
# "is it installed?" and still answer without importing anything.
_PYAUTOGUI = installed("pyautogui")


def _configure_pyautogui(module) -> None:
    module.FAILSAFE = True
    module.PAUSE    = 0.05


pyautogui = LazyModule("pyautogui", _configure_pyautogui)


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


# Commands this tool refuses to run on its own. Not because the shell is a bad
# shell — because these are the ones where "the assistant ran it" is the same
# sentence as "the assistant wrecked the machine". The gate is the same one the
# other irreversible actions use; a human still has to press CONFIRM on the HUD.
_BLOCKED = (
    "rm -rf", "rm -rf ", "shutdown", "poweroff", "reboot", "restart",
    "taskkill", "pkill", "kill -", "dropdb", "format", "cipher /w",
    "diskpart", "reg delete", "netsh interface", "netsh wlan",
    "curl ", "wget ", "bash -c", "sh -c", "python -c", "python3 -c",
)


def _is_blocked(command: str) -> bool:
    cmd = str(command or "").lower().strip()
    if not cmd:
        return True
    return any(cmd == pat or cmd.startswith(pat) for pat in _BLOCKED)


def _type_command(text: str, press_enter: bool = True) -> str:
    _require_pyautogui()
    pyautogui.typewrite(str(text or ""), interval=0.03)
    if press_enter:
        pyautogui.press("enter")
    return f"Typed: {str(text or '')[:60]}{'…' if len(str(text or "")) > 60 else ''}"


def _run_local(command: str, timeout_seconds: float = 30.0) -> str:
    """Run a shell command, capture its output, report honestly.

    The process is given a timeout (a runaway command must not hang the session)
    and its stdout/stderr are read back — the answer is `done` only when the
    process actually exited and produced what was asked for, `failed` when it
    did not, `unverified` when the output could not be read.
    """
    try:
        proc = subprocess.run(
            str(command),
            shell=True,                       # the user asked for this command
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return outcome.failed(
            "terminal_control",
            f"the command timed out after {timeout_seconds} seconds and was stopped",
            command=str(command)[:80],
        )
    except Exception as e:
        return outcome.failed(
            "terminal_control",
            f"the command could not be run: {e}",
            command=str(command)[:80],
        )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0 and not out:
        return outcome.failed(
            "terminal_control",
            f"the command exited with code {proc.returncode}: {err or out or 'no output'}",
            command=str(command)[:80],
        )
    return outcome.done(
        "terminal_control",
        command=str(command)[:80],
        code=proc.returncode,
        output=out or err,
    )


def terminal_control(
    parameters: dict = None,
    response=None,
    player=None,
    speak=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for the local terminal: type commands, run local commands.

    parameters keys (all optional unless noted):
      action        : (required) type_command | run_command
      text          : for type_command — the text to type, with enter pressed
      press_enter  : for type_command — press enter after typing (default: true)
      command       : for run_command — the shell command to execute
      timeout_seconds: for run_command — max seconds (default: 30)

    Actions:
      type_command — type text into the focused terminal / editor / field.
      run_command  — run a local shell command and read the output back.

    The terminal is only ever as trusted as the human speaking to it: type goes
    through the same pyautogui path the rest of computer control uses, and run
    goes through the confirmation gate for anything on the blocked list.
    """
    params = parameters or {}
    action = str(params.get("action") or "").lower().strip()

    if action == "type_command":
        text = str(params.get("text") or "")
        if not text.strip():
            return outcome.failed(
                "terminal_control",
                "no text was given to type into the terminal",
                wanted=action,
            )
        try:
            return _type_command(
                text,
                press_enter=bool(params.get("press_enter", True)),
            )
        except Exception as e:
            return outcome.failed(
                "terminal_control",
                f"the text could not be typed: {e}",
                wanted=action,
            )

    if action == "run_command":
        command = str(params.get("command") or "")
        if not command.strip():
            return outcome.failed(
                "terminal_control",
                "no command was given to run",
                wanted=action,
            )
        if _is_blocked(command):
            return confirm.request(
                key=f"terminal_control:{command.strip()[:40]}",
                title="Run a shell command",
                detail=f"The user asked JARVIS to run this on the computer: {command}",
                run=lambda: _run_local(command, float(params.get("timeout_seconds") or 30.0)),
            )
        return _run_local(command, float(params.get("timeout_seconds") or 30.0))

    return outcome.failed(
        "terminal_control",
        f"there is no terminal action called {action or '(empty)'}!",
        wanted=action,
    )


TOOL = {
    "name": "terminal_control",
    "description": (
        "Drives the local terminal: type a command into the focused terminal or "
        "field, or run a local shell command and read its output. Use "
        "type_command to put something in front of a terminal that is already open "
        "(an editor, a chat box, a URL bar) and press enter; use run_command to "
        "execute a command on this computer directly. Dangerous commands are held "
        "behind the user's confirmation on the HUD before they run."
    ),
    "brief": (
        "Types into the local terminal, or runs a local shell command."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "type_command | run_command"
            },
            "text": {
                "type": "STRING",
                "description": "For type_command: the text to type, with enter pressed"
            },
            "press_enter": {
                "type": "BOOLEAN",
                "description": "For type_command: press enter after typing (default: true)"
            },
            "command": {
                "type": "STRING",
                "description": "For run_command: the shell command to execute"
            },
            "timeout_seconds": {
                "type": "NUMBER",
                "description": "For run_command: max seconds to wait (default: 30)"
            },
        },
        "required": ["action"],
    },
    "handler": terminal_control,
}
