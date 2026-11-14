# permissions.py — what the assistant may run on this computer, and how.
#
# THE PROBLEM THIS SOLVES
#     Every tool in the project now answers through one gate — the per-tool level
#     the user keeps in api_keys.json (memory/config_manager) — plus the older,
#     human-in-the-loop confirmation gate for the genuinely irreversible ones.
#     This tool is how that block is read, and how it is changed. Before it
#     existed the levels lived only in code (core/action_loader reads them via a
#     policy wired from main.py), which meant "make JARVIS ask before it touches
#     the terminal" was a code change and not a setting.
#
# WHAT A LEVEL MEANS
#     allow — run the tool without a human in the loop.
#     ask   — park the tool on the on-screen confirmation gate (core/confirm):
#            the banner goes up, the model says so out loud, the user presses
#            CONFIRM and the token — issued by the interface, never by the model
#            — lets it run.
#     deny  — refuse. The tool answers failed and the assistant says so in the
#            user's language instead of pretending.
#
# THE DEFAULT IS ALLOW
#     An empty permissions block means nothing is restricted, which is the state
#     every install starts in and the behaviour this project had before the gate
#     existed. Only a level the user (or the assistant, for the reversible kinds)
#     actually wrote turns something on.
from __future__ import annotations

from core import outcome
from memory import config_manager


def _levels() -> dict:
    try:
        return {
            str(k): str(v).lower()
            for k, v in (config_manager.get_tool_permissions() or {}).items()
        }
    except Exception:
        return {}


def _set_level(tool_name: str, level: str) -> str:
    if not tool_name:
        return outcome.failed(
            "permissions",
            "no tool name was given to set the permission for",
            wanted="set",
        )
    level = str(level or "").strip().lower()
    if level not in ("allow", "ask", "deny"):
        return outcome.ask(
            "permissions",
            f"what level should '{tool_name}' be — allow, ask, or deny?",
            wanted="set",
        )
    try:
        config_manager.save_tool_permissions({tool_name: level})
    except Exception as e:
        return outcome.failed(
            "permissions",
            f"the permission for '{tool_name}' could not be saved: {e}",
            wanted="set",
        )
    return outcome.done("permissions", shown=True, wanted="set", tool=tool_name, level=level)


def permissions(
    parameters: dict = None,
    response=None,
    player=None,
    speak=None,
    session_memory=None,
) -> str:
    """
    Manage what the assistant may run on this computer.

    parameters keys (all optional unless noted):
      action : (required) list | set
      tool   : tool name, for set — e.g. terminal_control, browser_control
      level  : level, for set — allow | ask | deny

    Actions:
      list — read the current permission block.
      set  — set one tool's level (writes api_keys.json through the config
            manager, the only sanctioned path).
    """
    params = parameters or {}
    action = str(params.get("action") or "").lower().strip()

    if action == "list":
        return "permissions " + (" ".join(
            f"{k}={v}" for k, v in sorted(_levels().items())
        ) if _levels() else "are unset — every tool runs (ask nothing before running).")

    if action == "set":
        return _set_level(str(params.get("tool") or ""), str(params.get("level") or ""))

    return outcome.failed(
        "permissions",
        f"there is no permission action called {action or '(empty)'}!",
        wanted=action,
    )


TOOL = {
    "name": "permissions",
    "description": (
        "Manages which assistant tools may run and how strictly. action='list' "
        "reads the current permission block; action='set' writes one tool's level "
        "to allow, ask or deny. ask means the tool waits for the user to confirm "
        "on the HUD before running; deny means it will not run at all. Unset tools "
        "are allowed."
    ),
    "brief": (
        "Manages which assistant tools may run and how strictly."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | set"
            },
            "tool": {
                "type": "STRING",
                "description": "For set: the tool name to change, e.g. terminal_control"
            },
            "level": {
                "type": "STRING",
                "description": "For set: allow | ask | deny"
            },
        },
        "required": ["action"],
    },
    "handler": permissions,
}
