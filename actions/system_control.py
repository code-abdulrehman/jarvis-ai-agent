# system_control.py — popups and notifications the assistant wants to show.
#
# THE REASON THIS IS ITS OWN TOOL AND NOT JUST CALLS SCATTERED THROUGH THE CODE
#     is that a popup is a promise: the assistant said something and now the
#     machine has to LOOK like it said it. The spoken answer, the activity log
#     and the HUD panel are three places that already tried to be that; a popup
#     is the fourth, and it exists for exactly the cases those three are worst
#     at — the moment the user is looking AWAY, or the moment they are looking
#     RIGHT THERE and the words are still in the air.
#
# WHAT IT CAN DO
#     notify  — a toast / desktop notification ("JARVIS: the download finished").
#     popup   — a blocking native dialog, for the things that need an answer or
#              a moment of attention before the assistant goes back to talking.
#
# POPUPS ARE NOT QUESTIONS
#     The blocking dialog is an alert, never a questionnaire: the assistant does
#     not put a yes/no into a popup it cannot read back, and a dialog that can
#     not return an answer would just sit there burning attention. Anything that
#     wants a decision goes through the confirmation gate (core/confirm.py),
#     which already does this properly — banner on the HUD, CONFIRM pressed by a
#     human, token issued by the interface.
from __future__ import annotations

from core import outcome
from core import popups


def system_control(
    parameters: dict = None,
    response=None,
    player=None,
    speak=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for system popups and notifications.

    parameters keys (all optional unless noted):
      action  : (required) notify | popup
      title   : popup / notification title (default: J.A.R.V.I.S)
      message : the text to show (default: the spoken answer is not repeated here)
      urgency : notify only — "low" | "normal" | "high" (default: normal)

    Actions:
      notify — show a toast/notification on the user's machine.
      popup  — show a blocking native dialog. For anything that wants a real
               answer, use the confirmation gate instead; this is an alert.
    """
    params = parameters or {}
    action = str(params.get("action") or "").lower().strip()

    if action == "notify":
        title   = str(params.get("title") or "J.A.R.V.I.S").strip() or "J.A.R.V.I.S"
        message = str(params.get("message") or "").strip()
        if not message:
            return outcome.failed(
                "system_control",
                "no message was given to show a popup for",
                wanted=action,
            )
        ok = popups.show(title, message, str(params.get("urgency") or "normal"))
        if ok:
            return outcome.done("system_control", shown=True, wanted=action)
        return outcome.unverified(
            "system_control",
            "no notification system was available on this machine, so the popup "
            "could not be shown",
            wanted=action,
        )

    if action == "popup":
        title   = str(params.get("title") or "J.A.R.V.I.S").strip() or "J.A.R.V.I.S"
        message = str(params.get("message") or "").strip()
        if not message:
            return outcome.failed(
                "system_control",
                "no message was given to show a popup for",
                wanted=action,
            )
        ok = popups.alert(title, message)
        if ok:
            return outcome.done("system_control", shown=True, wanted=action)
        return outcome.unverified(
            "system_control",
            "no native dialog system was available on this machine, so the popup "
            "could not be shown",
            wanted=action,
        )

    return outcome.failed(
        "system_control",
        f"there is no system action called {action or '(empty)'}!",
        wanted=action,
    )


TOOL = {
    "name": "system_control",
    "description": (
        "Shows popups and notifications on this computer. Use it when something "
        "needs the user's attention even though the spoken answer is already on its "
        "way: a task finished, a download complete, a reminder, a warning. action="
        "'notify' shows a toast/notification on the machine; action='popup' shows a "
        "blocking native dialog. Popups are alerts, not questions — if what is being "
        "shown needs a human decision, use the confirmation gate instead of a popup."
    ),
    "brief": (
        "Shows a popup or notification on the user's machine."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "notify | popup"
            },
            "title": {
                "type": "STRING",
                "description": "Popup / notification title (default: J.A.R.V.I.S)"
            },
            "message": {
                "type": "STRING",
                "description": "The text to show in the popup / notification"
            },
            "urgency": {
                "type": "STRING",
                "description": "notify only — low | normal | high (default: normal)"
            },
        },
        "required": ["action"],
    },
    "handler": system_control,
}
