# network_control.py — network state and Wi-Fi awareness for the assistant.
#
# WHY THIS IS A TOOL AND NOT JUST HELPER CALLS SPREAD AROUND
#     The assistant can already switch Wi-Fi off and on (computer_settings), but
#     it had no way to KNOW what the network was doing: is it connected, to what,
#     with what address, and what is available to join. Network state is exactly
#     the kind of thing a personal assistant is expected to hold in its head, and
#     it is also what makes every other capability honest — a browser that cannot
#     reach the internet is a browser that opened nothing.
#
# READS ONLY
#     This tool reads network state and lists networks. It deliberately does NOT
#     change anything itself (Wi-Fi switching lives in computer_settings, behind
#     the human confirmation gate); changing the network is exactly the kind of
#     thing this project counts in irreversible.
from __future__ import annotations

import platform
import subprocess

from core import outcome


def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _wifi_networks() -> list[str]:
    """Known Wi-Fi networks on this machine, by interface.

    Best effort per OS; an empty list means "the assistant could not read them"
    and that is reported, not papered over.
    """
    os_name = platform.system().lower()
    names: list[str] = []

    if os_name == "windows":
        out = _run(["netsh", "wlan", "show", "networks", "mode=bssid"])
        for line in out.splitlines():
            line = line.strip()
            if line.lower().startswith("ssid"):
                ssid = line.split(":", 1)[1].strip() if ":" in line else line
                if ssid and ssid not in names:
                    names.append(ssid)
    elif os_name == "linux":
        out = _run(["nmcli", "-B", "device", "wifi", "list"])
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("DEVICE") and not line.startswith("RADIO"):
                parts = line.split()
                if parts and parts[0].lower() != "cell" and len(parts) >= 2:
                    ssid = parts[0]
                    if ssid not in names:
                        names.append(ssid)
    elif os_name == "darwin":
        out = _run(["airport", "-s"])
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] != "SSID":
                ssid = parts[0]
                if ssid and ssid != "--" and ssid not in names:
                    names.append(ssid)

    return names


def _network_status() -> str:
    """A short, human-readable snapshot of this machine's network."""
    os_name = platform.system().lower()

    if os_name == "windows":
        out = _run(["netsh", "wlan", "show", "interfaces"])
        ssid = ""
        for line in out.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[1].strip()
        return f"windows network status — ssid={ssid or 'disconnected'}"

    if os_name == "linux":
        addr = _run(["ip", "-4", "addr", "show"])
        route = _run(["ip", "route", "show", "default"])
        return f"linux network status — {addr.splitlines()[0] if addr else 'no address info'} | {route}"

    if os_name == "darwin":
        ssid = _run(["ipconfig", "getssid", "en0"])
        return f"mac network status — ssid={ssid or 'disconnected'}"

    return f"{os_name} network status — no reader for this platform"


def network_control(
    parameters: dict = None,
    response=None,
    player=None,
    speak=None,
    session_memory=None,
) -> str:
    """
    Read this computer's network state and list nearby Wi-Fi networks.

    parameters keys (all optional unless noted):
      action : (required) status | scan

    Actions:
      status — current connection / address summary.
      scan   — the Wi-Fi networks available on this machine.

    This tool is read-only. Switching networks is computer_settings' job, and
    that one already asks the user before it changes anything.
    """
    params = parameters or {}
    action = str(params.get("action") or "").lower().strip()

    if action == "status":
        return outcome.done("network_control", detail=_network_status(), wanted="status")

    if action == "scan":
        nets = _wifi_networks()
        return outcome.done(
            "network_control",
            found=len(nets),
            wanted="scan",
            available=", ".join(nets) if nets else "",
        )

    return outcome.failed(
        "network_control",
        f"there is no network action called {action or '(empty)'}!",
        wanted=action,
    )


TOOL = {
    "name": "network_control",
    "description": (
        "Reads the computer's network state and lists nearby Wi-Fi networks. "
        "Use it to answer 'is the internet up', 'what network am I on', 'what "
        "Wi-Fi is available'. Read-only; switching networks is a different tool."
    ),
    "brief": (
        "Reads network status and lists nearby Wi-Fi networks."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | scan"
            },
        },
        "required": ["action"],
    },
    "handler": network_control,
}
