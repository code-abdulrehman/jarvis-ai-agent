
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import os
import platform
import shutil
import subprocess
import threading
import tempfile
import uuid
import webbrowser
from urllib.parse import urlparse
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from core import appidentity, outcome

# Importing playwright cost 198 ms at every launch, paid by action discovery
# whether or not a browser was ever opened. It is the second-largest import in
# the project after pyautogui, and together the two were 78% of all module
# import time on the boot path.
#
# WHY THIS STILL RAISES WHEN PLAYWRIGHT IS MISSING
#     The eager import had a second job nobody wrote down: when playwright was
#     absent this module failed to load, action_loader dropped it, and the model
#     was never offered a browser tool it could not serve. Deferring the import
#     without keeping that would declare `browser_control` on a machine that
#     cannot run it — the model would call it, get an exception, and describe a
#     page it never opened. Exactly the failure mode this project spent Mark LVI
#     removing from local engines.
#
#     So the check stays at module scope and still stops the module loading; it
#     just asks find_spec instead of executing the package. 1 ms instead of 198,
#     same outcome, and a sentence that says what to install.
if importlib.util.find_spec("playwright") is None:      # pragma: no cover
    raise ImportError(
        "browser_control needs playwright, which is not installed. "
        "Run: pip install playwright  &&  playwright install chromium"
    )

# Annotations only — `from __future__ import annotations` above makes every one
# of them a string, so these names are never looked up at runtime and cost
# nothing outside a type checker.
if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

# WHY THIS FILE DOES NOT USE core/lazyimport.py's LazyModule LIKE THE OTHERS
#     Every other deferral in this project stands a proxy in for a whole module,
#     because the call sites say `pyautogui.press(...)` and a proxy answers that
#     the same way the module would. What this file needs are two SYMBOLS out of
#     a module: a factory function, and an exception class used in `except`.
#
#     `except` will not take a proxy. It requires a real class inheriting from
#     BaseException, checked by the interpreter at the moment the exception is
#     raised, and a LazyModule there raises TypeError instead of catching
#     anything — the original error then disappears underneath a complaint about
#     the except clause. So these two are bound as real globals instead.
#
# PlaywrightTimeout starts as a private class that is never raised, so an
# `except PlaywrightTimeout:` somehow reached before a session exists catches
# nothing rather than failing that same way.
class _PlaywrightNotLoaded(Exception):
    """Placeholder exception — declared so `except` clauses stay valid, and
    deliberately never raised anywhere."""


async_playwright = None
PlaywrightTimeout: type[BaseException] = _PlaywrightNotLoaded


def _load_playwright() -> None:
    """Import playwright and bind the two runtime symbols. Idempotent."""
    global async_playwright, PlaywrightTimeout
    if async_playwright is not None:
        return
    from playwright.async_api import (          # noqa: PLC0415 — deliberate
        async_playwright as _ap,
        TimeoutError as _timeout,
    )
    async_playwright = _ap
    PlaywrightTimeout = _timeout


_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

def _normalize_url(url: str) -> str:
    """
    Bare words like "instagram" → "https://instagram.com"
    Domains like "instagram.com" → "https://instagram.com"
    Full URLs pass through unchanged.
    """
    url = url.strip()
    if url == "about:blank":
        return url
    # Trailing sentence punctuation is never part of an address, and it arrives
    # more often than anyone would guess: a name lifted out of a sentence brings
    # the full stop with it, and youtube.com/@name./videos opens an error page
    # that looks like a page. Stripping it costs nothing and is true of every
    # site in every language.
    url = url.rstrip(".,;:!?'\"")
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    # No dot at all → assume .com  (e.g. "instagram" → "instagram.com")
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _real_profile_dir(browser: str) -> str:
    home  = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam  = os.environ.get("APPDATA", "")

    candidates: list[Path] = []

    if _OS == "Windows":
        m = {
            "chrome":   [Path(local) / "Google"          / "Chrome"          / "User Data"],
            "edge":     [Path(local) / "Microsoft"        / "Edge"            / "User Data"],
            "brave":    [Path(local) / "BraveSoftware"    / "Brave-Browser"   / "User Data"],
            "vivaldi":  [Path(local) / "Vivaldi"          / "User Data"],
            "opera":    [Path(roam)  / "Opera Software"   / "Opera Stable",
                         Path(local) / "Opera Software"   / "Opera Stable"],
            "operagx":  [Path(roam)  / "Opera Software"   / "Opera GX Stable",
                         Path(local) / "Opera Software"   / "Opera GX Stable"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Darwin":
        lib = home / "Library" / "Application Support"
        m = {
            "chrome":   [lib / "Google"             / "Chrome"],
            "edge":     [lib / "Microsoft Edge"],
            "brave":    [lib / "BraveSoftware"       / "Brave-Browser"],
            "vivaldi":  [lib / "Vivaldi"],
            "opera":    [lib / "com.operasoftware.Opera"],
            "operagx":  [lib / "com.operasoftware.OperaGX"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Linux":
        cfg = home / ".config"
        m = {
            "chrome":   [cfg / "google-chrome", cfg / "chromium"],
            "edge":     [cfg / "microsoft-edge"],
            "brave":    [cfg / "BraveSoftware" / "Brave-Browser"],
            "vivaldi":  [cfg / "vivaldi"],
            "opera":    [cfg / "opera"],
            "operagx":  [cfg / "opera-gx"],
        }
        candidates = m.get(browser, [])

    for p in candidates:
        if p.exists():
            print(f"[Browser] ✅ Real profile found for {browser}: {p}")
            return str(p)

    fallback = home / ".jarvis_profiles" / browser
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"[Browser] ⚠️  Real profile not found for {browser}, using: {fallback}")
    return str(fallback)

def _firefox_profile_dir() -> Optional[str]:
    home = Path.home()

    if _OS == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    elif _OS == "Darwin":
        base = home / "Library" / "Application Support" / "Firefox"
    else:
        base = home / ".mozilla" / "firefox"

    ini = base / "profiles.ini"
    if not ini.exists():
        return None

    current: dict[str, str] = {}
    default_path: Optional[str] = None

    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            p = current.get("Path", "")
            if p and current.get("Default") == "1":
                is_rel = current.get("IsRelative", "1") == "1"
                default_path = str(base / p) if is_rel else p
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    p = current.get("Path", "")
    if p and current.get("Default") == "1":
        is_rel = current.get("IsRelative", "1") == "1"
        default_path = str(base / p) if is_rel else p

    if default_path and Path(default_path).exists():
        print(f"[Browser] Firefox real profile: {default_path}")
        return default_path
    return None

def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            print(f"[Browser] Opera found at: {p}")
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass

    return shutil.which("opera") or None

def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        if not exe:
            print(f"[Browser] ⚠️  Opera executable not found on Windows.")
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Darwin":
        app_names = {
            "chrome":  ["Google Chrome.app"],
            "edge":    ["Microsoft Edge.app"],
            "firefox": ["Firefox.app"],
            "opera":   ["Opera.app", "Opera GX.app"],
            "brave":   ["Brave Browser.app"],
            "vivaldi": ["Vivaldi.app"],
        }
        for app in app_names.get(name, []):
            app_dir = Path("/Applications") / app / "Contents" / "MacOS"
            if app_dir.exists():
                found_bins = list(app_dir.iterdir())
                if found_bins:
                    exe = str(found_bins[0])
                    break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
        elif _OS == "Darwin":
            out = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "safari", "chrome", "edge"):
                if kw in out:
                    return kw
        elif _OS == "Linux":
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "chrome", "edge"):
                if kw in out:
                    return kw
    except Exception:
        pass
    return "chrome"


def _list_profiles(browser_name: str) -> str:
    """Names of the profiles available to this browser, on this machine.

    Reads the profile directories themselves (Default, Profile 1, Profile 2, ...)
    — the same places launch_persistent_context looks — so the answer is about
    what is really there, not about a hardcoded list. Falls back to the JARVIS
    automation profiles when no real browser profile directory is found.

    Only names that are actually PROFILES are accepted — Default, or one of the
    numbered ones Chrome hands out — never cache or state directories that happen
    to sit in the same place.
    """
    home = Path.home()
    ud = Path(_real_profile_dir(browser_name or "chrome"))

    names: list[str] = []
    if ud.exists():
        for child in sorted(ud.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or not (
                child.name == "Default" or child.name.startswith("Profile ")
            ):
                continue
            names.append(child.name)

    if not names:
        jarvis = home / ".jarvis_profiles" / (browser_name or "chrome")
        if jarvis.exists():
            names = sorted(p.name for p in jarvis.iterdir() if p.is_dir())

    if not names:
        return f"no profiles were readable for {browser_name} on this machine"

    return (f"status={outcome.DONE} profiles " + ", ".join(names)
            + " — tell the user which profile this is and which one to use next.")


_SEARCH_ENGINES: dict[str, str] = {
    "google":     "https://www.google.com/search?q=",
    "bing":       "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "yandex":     "https://yandex.com/search/?text=",
}

_MAC_APP_NAMES: dict[str, str] = {
    "chrome":  "Google Chrome",
    "edge":    "Microsoft Edge",
    "firefox": "Firefox",
    "opera":   "Opera",
    "operagx": "Opera GX",
    "brave":   "Brave Browser",
    "vivaldi": "Vivaldi",
    "safari":  "Safari",
}

# Windows registry lookup names for browsers whose spec has no explicit binary
_WIN_EXE_HINTS: dict[str, str] = {"chrome": "chrome", "edge": "msedge"}


# Chromium builds the accessibility tree for a PAGE only when it believes
# something is listening. Nothing an outside program can do convinces it — both
# a UIA walk and a WM_GETOBJECT probe were tried against a running browser and
# returned the same empty panes.
#
# But the browser we START is ours to configure, and one flag changes the whole
# picture. Measured on Edge, same page, same profile:
#
#     plain                                21 elements, page text: 4
#     --force-renderer-accessibility       25 elements, page text: 7,
#                                          including a clickable link
#
# That is the difference between a page the assistant can read and click by
# name, in the user's OWN signed-in browser, and one it has to guess at from a
# screenshot or drive from a second window where nobody is logged in.
#
# It applies only when this launches the browser. A browser already running
# ignores the flag and simply takes the URL, which is correct: we are not
# restarting somebody's browser to gain a feature.
_CHROMIUM_FAMILY = frozenset({"chrome", "edge", "opera", "operagx", "brave",
                              "vivaldi"})


def _launch_flags(name: str) -> list[str]:
    return (["--force-renderer-accessibility"]
            if name in _CHROMIUM_FAMILY else [])


def _native_outcome(name: str, url: str) -> str:
    """What a native launch actually established, as opposed to what it asked for.

    THIS RETURNED A SENTENCE SAYING "Opened", AND IT WAS NOT TRUE ENOUGH
        Handing a URL to a browser executable proves one thing: the executable
        started. It proves nothing about the page. The address may 404, redirect
        to a sign-in wall, or - the case that exposed this - be an address the
        model invented because it did not know the real one.

        Asked to open a user's own YouTube channel, the model guessed a path
        that does not exist. The browser opened it, this function answered
        "Opened in operagx: <that address>", and the assistant reported the
        channel as open while the screen showed an error page. A bare success
        sentence is exactly the invitation to invent the rest that the rest of
        this project spent a release removing.

    The browser itself CAN be confirmed, cheaply, from the process table, so
    that part is reported as fact and the page is reported as unconfirmed. Two
    different things, said separately, which is the whole point of the outcome
    vocabulary.
    """
    running = bool(appidentity.running(name))
    if not url:
        if running:
            return outcome.done("browser_control", browser=name, opened=True,
                                verified=True)
        return outcome.unverified(
            "browser_control",
            "the browser was launched but has not appeared in the process list "
            "yet", browser=name)
    return outcome.unverified(
        "browser_control",
        "the address was handed to the browser, which does not report back - "
        "whether the page actually loaded, redirected or does not exist is NOT "
        "known, so it must not be described as open",
        browser=name, url=url, browser_running=running)


def _open_native(url: str, browser_name: Optional[str]) -> str:
    """
    Opens the user's REAL browser normally — with their own profile,
    logged-in accounts and extensions. No automation attaches, so an
    about:blank tab or a blank profile NEVER shows up.
    If url is empty the browser starts with no URL (its own start page /
    session restore) — exactly as if the user had opened it themselves.
    Works on all three of Windows / macOS / Linux.
    """
    url = _normalize_url(url) if url and url.strip() else ""
    if url == "about:blank":
        url = ""

    name = None
    if browser_name:
        name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
    elif not url:
        # No URL → only a window will open; needs the default browser's exe
        name = _detect_default_browser()

    # Specific browser → launch its own executable, exactly like the user would.
    if name:
        if _OS == "Darwin":
            app = _MAC_APP_NAMES.get(name)
            if app:
                cmd = ["open", "-a", app] + ([url] if url else [])
                try:
                    subprocess.run(cmd, check=True, timeout=10)
                    return _native_outcome(name, url)
                except Exception as e:
                    print(f"[Browser] 'open -a {app}' failed ({e}), trying binary…")

        spec = _resolve_browser(name)
        exe  = spec.get("exe") if spec else None
        if not exe and _OS == "Windows":
            if name in ("opera", "operagx"):
                exe = _find_opera_windows()
            else:
                exe = _find_exe_windows(_WIN_EXE_HINTS.get(name, name))
        if exe:
            try:
                subprocess.Popen(
                    [exe] + _launch_flags(name) + ([url] if url else []),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return _native_outcome(name, url)
            except Exception as e:
                print(f"[Browser] Native launch failed for {name}: {e}")
        print(f"[Browser] '{name}' not found — falling back to default browser.")

    if not url:
        return outcome.failed(
            "browser_control",
            "no browser was found and no address was given to open")

    # Default browser via the OS — exactly like the user clicking a link.
    try:
        if _OS == "Windows":
            os.startfile(url)                       # ShellExecute → default browser
        elif _OS == "Darwin":
            subprocess.run(["open", url], check=True, timeout=10)
        else:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        # HANDED TO THE OPERATING SYSTEM, NOT CONFIRMED.
        #
        # os.startfile / open / xdg-open all return as soon as the request is
        # accepted. None of them waits for a browser, and none reports whether
        # the page loaded — the same gap that made open_app say "Opened
        # Spotify." off the back of a shell starting. Unlike the playwright
        # path above there is no page object here to read a url from, so this
        # says what it actually knows.
        return outcome.unverified(
            "browser_control",
            "the address was handed to the system's default browser, which "
            "does not report back - the page is not confirmed open",
            url=url)
    except Exception:
        try:
            if webbrowser.open(url):
                return outcome.unverified(
                    "browser_control",
                    "the address was handed to the default browser, which does "
                    "not report back - the page is not confirmed open",
                    url=url)
        except Exception:
            pass
        return outcome.failed(
            "browser_control",
            "no browser on this system could be opened", url=url)


class _BrowserSession:
    """
    A full session for one browser instance.
    Browser actions share one persistent automation context. Existing Chromium
    sessions can be attached explicitly through a loopback CDP endpoint.

    HEADLESS SESSIONS
        The user's own browser is the interesting one, but there are jobs that
        should not need a human watching a window at all — a background research
        fetch, a page a model has to read, a form that has to be filled while the
        user is doing something else. Those go through a headless context, which
        Playwright runs without a window: same engine, same page object protocol,
        but nothing on screen and nothing for a person to see.

        A headless context lives under a profile directory JARVIS owns
        (~/.jarvis_profiles/<browser>/...), optionally a NAMED one, so a
        headless automation can be pointed at the same persona the user's real
        browser uses without ever opening their window.
    """

    def __init__(self, browser_name: str, headless: bool = False, profile_name: str = ""):
        self.browser_name = browser_name
        self.headless     = headless
        self.profile_name = (profile_name or "").strip()
        self._spec        = _resolve_browser(browser_name)

        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()

        self._pw:      Playwright     | None = None
        self._context: BrowserContext | None = None
        self._page:    Page           | None = None
        # "real" when the user's own browser profile was opened, "separate"
        # when their browser was already running and a private automation
        # profile had to be used instead. The difference is every sign-in they
        # have, so it is reported rather than only printed.
        self.profile_kind: str = ""
        self._attached = False
        self._init_error = None
        self._screenshot_dir = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        if not self._ready.wait(timeout=20):
            raise RuntimeError("Browser automation initialization timed out")
        if self._init_error is not None:
            raise RuntimeError(f"Browser automation could not initialize: {self._init_error}")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_init())
        except Exception as exc:
            self._init_error = exc
            self._ready.set()
            self._loop.close()
            return
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        # The one door into a live session: nothing in this class reaches
        # async_playwright or PlaywrightTimeout without coming through here
        # first, so binding them at this point is enough for the whole file.
        _load_playwright()
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        if self._context and not self._attached:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = self._page = None
        self._attached = False
        if self._screenshot_dir is not None:
            self._screenshot_dir.cleanup()
            self._screenshot_dir = None

    async def _adopt_page(self) -> Page:
        """
        launch_persistent_context already opens a starting tab.
        Instead of opening a new blank tab (about:blank), it adopts that tab —
        so the user never sees an extra blank tab.
        """
        context = self._context
        def closed(*args):
            if self._context is context:
                self._context = self._page = None
        context.on("close", closed)
        pages = context.pages
        return pages[-1] if pages else await context.new_page()

    async def _launch(self):
        """
        Launches or reuses the browser's automation profile.
        Does nothing if the context is already open — and relaunches if the one
        it holds is closed, because a context that has been closed (browser
        crash, explicit close, a session that outlived its browser) would
        otherwise answer every later call in exactly the way the user just saw
        from the console: a context that is not None, but not usable.
        """
        if self._context is not None:
            return

        if self._spec is None:
            raise RuntimeError(
                f"'{self.browser_name}' bu platformda ({_OS}) desteklenmiyor."
            )

        engine_name = self._spec["engine"]
        exe         = self._spec["exe"]
        channel     = self._spec["channel"]
        engine_obj  = getattr(self._pw, engine_name)

        if engine_name == "firefox":
            profile = _firefox_profile_dir() or str(
                Path.home() / ".jarvis_profiles" / "firefox"
            )
            kwargs: dict = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            if exe:
                kwargs["executable_path"] = exe
            try:
                self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            except Exception as e:
                print(f"[Browser] Firefox real profile failed ({e}), using JARVIS profile")
                jarvis = str(Path.home() / ".jarvis_profiles" / "firefox_jarvis")
                Path(jarvis).mkdir(parents=True, exist_ok=True)
                self._context = await engine_obj.launch_persistent_context(jarvis, **kwargs)

            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Firefox launched")
            return

        if engine_name == "webkit":
            safari_profile = str(Path.home() / ".jarvis_profiles" / "safari")
            Path(safari_profile).mkdir(parents=True, exist_ok=True)
            kwargs = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            self._context = await engine_obj.launch_persistent_context(safari_profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Safari launched")
            return

        if self.headless:
            # A headless context gets a profile directory of our own — never the
            # user's real one (a person is not watching this window) — and a named
            # profile when the caller asked for one, so "the automation that does
            # what the user asked" can be pointed at a persona without opening the
            # user's actual browser.
            headless_root = Path.home() / ".jarvis_profiles" / self.browser_name
            profile = str(headless_root / (self.profile_name or "default"))
            headless_root.mkdir(parents=True, exist_ok=True)
        else:
            profile = _real_profile_dir(self.browser_name)

        kwargs = {
            "headless":    self.headless,
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "timeout":     25_000,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--no-default-browser-check",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        label = (
            f"{self.browser_name}"
            + (f"/{channel}" if channel else "")
            + (f" @ {exe}" if exe else "")
        )

        # Modern Chrome blocks automation of its default data directory.
        # Use one persistent JARVIS profile for every navigation and interaction.
        jarvis_profile = profile if self.headless else str(
            Path.home() / ".jarvis_profiles" / self.browser_name / "interactive")
        Path(jarvis_profile).mkdir(parents=True, exist_ok=True)

        try:
            self._context = await engine_obj.launch_persistent_context(jarvis_profile, **kwargs)
            self._page = await self._adopt_page()
            self.profile_kind = "separate"
            print(f"[Browser] ✅ Launched [{label}] with JARVIS profile "
                  f"(sign-ins persist across sessions)")
        except Exception as e2:
            raise RuntimeError(f"Could not launch {self.browser_name}: {e2}") from e2


    async def attach(self, endpoint: str) -> str:
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https", "ws", "wss") or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Use a loopback Chrome debugging endpoint")
        if self._context is not None:
            raise RuntimeError("Close the existing JARVIS browser session before attaching another browser")
        browser = await self._pw.chromium.connect_over_cdp(endpoint, timeout=5000)
        if not browser.contexts:
            raise RuntimeError("Connected browser has no usable context")
        self._context = browser.contexts[0]
        self._attached = True
        self.profile_kind = "attached"
        self._page = await self._adopt_page()
        return await self.list_tabs()

    async def list_tabs(self) -> str:
        await self._launch()
        rows = []
        for index, page in enumerate(self._context.pages):
            rows.append(f"{index}: {await page.title()} | {page.url}" + (" [selected]" if page is self._page else ""))
        return "\n".join(rows) or "No browser tabs"

    async def switch_tab(self, index: int) -> str:
        await self._launch()
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            return "Invalid tab index; use list_tabs first"
        self._page = pages[index]
        await self._page.bring_to_front()
        return f"Selected tab {index}: {self._page.url}"

    async def _get_page(self) -> Page:
        await self._launch()
        # If somehow page got closed, open a fresh one
        if self._page is None or self._page.is_closed():
            pages = self._context.pages
            self._page = pages[-1] if pages else await self._context.new_page()
            await asyncio.sleep(0.2)
        return self._page

    async def go_to(self, url: str) -> str:

        url      = _normalize_url(url)
        page     = await self._get_page()
        prev_url = page.url

        async def _do_goto(p: Page) -> str:
            """Attempt navigation and return the resulting URL (may still be blank)."""
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(0.3)
            except PlaywrightTimeout:
                pass   # page may have partially loaded — check URL below
            except Exception as e:
                print(f"[Browser] goto exception (non-fatal): {e}")
            return p.url

        result_url = await _do_goto(page)

        if result_url in ("about:blank", "", None, prev_url) and prev_url in ("about:blank", "", None):
            print(f"[Browser] Still blank after goto — retrying on new tab: {url}")
            try:
                new_page   = await self._context.new_page()
                self._page = new_page
                result_url = await _do_goto(new_page)
            except Exception as e:
                print(f"[Browser] New-tab retry failed: {e}")

        if result_url and result_url not in ("about:blank", "", None):
            # Verified, and cheaply: this is the page's OWN url read back after
            # navigation, not the one we asked for. A redirect, a login wall or
            # a captive portal all show up here as a different address, which
            # is exactly what the user needs to hear about.
            #
            # The profile is reported for the same reason. When the user's
            # browser was already running its profile is locked, so the page
            # opens in a separate one where they are signed in to nothing —
            # and a Gmail that asks them to log in looks like a broken
            # assistant unless somebody says why.
            return outcome.done("browser_control", opened=result_url,
                                profile=self.profile_kind or "real",
                                verified=True,
                                note="JARVIS automation profile; sign in here if needed" if self.profile_kind == "separate" else "")
        return outcome.failed(
            "browser_control",
            "the page stayed blank - the address may be wrong, or the site may "
            "not have answered", url=url)

    async def search(self, query: str, engine: str = "google") -> str:
        base = _SEARCH_ENGINES.get(engine.lower(), _SEARCH_ENGINES["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8_000)
                return f"Clicked text: '{text}'"
            if selector:
                await page.click(selector, timeout=8_000)
                return f"Clicked selector: {selector}"
            return outcome.failed("browser_control",
                                  "no element was named to click")
        except PlaywrightTimeout:
            return outcome.failed(
                "browser_control",
                "no element matching that appeared on the page in time",
                selector=selector or text)
        except Exception as e:
            return f"Click error: {e}"

    async def type_text(self, selector: str = None, text: str = "",
                        clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            el = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=50)
            # playwright raises when the field is not there, so reaching this
            # line means the text went into a real input.
            return outcome.done("browser_control", typed=True, verified=True)
        except Exception as e:
            return f"Type error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4_000]
        except Exception as e:
            return f"Could not get page text: {e}"

    async def get_url(self) -> str:
        page = await self._get_page()
        return page.url

    async def fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        for role in ("button", "link", "searchbox", "textbox", "menuitem", "tab"):
            try:
                loc = page.get_by_role(role, name=description)
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    return f"Clicked ({role}): '{description}'"
            except Exception:
                pass
        for attempt in (
            lambda: page.get_by_text(description, exact=False).first.click(timeout=5_000),
            lambda: page.get_by_placeholder(description, exact=False).first.click(timeout=5_000),
            lambda: page.locator(
                f'[alt*="{description}" i],[title*="{description}" i],'
                f'[aria-label*="{description}" i]'
            ).first.click(timeout=5_000),
        ):
            try:
                await attempt()
                return f"Clicked: '{description}'"
            except Exception:
                pass
        return f"Could not find element: '{description}'"

    async def smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        candidates = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox", name=description)),
            ("searchbox",   page.get_by_role("searchbox")),
            ("combobox",    page.get_by_role("combobox", name=description)),
        ]
        for method, loc in candidates:
            try:
                el = loc.first
                if await el.count() == 0:
                    continue
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"

    async def new_tab(self, url: str = "") -> str:
        page = await self._get_page()
        ctx  = page.context
        new  = await ctx.new_page()
        self._page = new
        if url:
            return await self.go_to(url)
        return "New tab opened."

    async def close_tab(self) -> str:
        page = self._page
        if page and not page.is_closed():
            ctx   = page.context
            await page.close()
            pages = ctx.pages
            self._page = pages[-1] if pages else None
            return "Tab closed."
        return "No active tab to close."

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        try:
            if path:
                save_path = path
            else:
                if self._screenshot_dir is None:
                    self._screenshot_dir = tempfile.TemporaryDirectory(
                        prefix="jarvis-browser-", dir="/tmp" if _OS == "Linux" else None)
                save_path = str(Path(self._screenshot_dir.name) / (uuid.uuid4().hex + ".png"))
            await page.screenshot(path=save_path, full_page=False)
            return f"Screenshot saved: {save_path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def back(self) -> str:
        page = await self._get_page()
        try:
            await page.go_back(timeout=10_000)
            return f"Navigated back: {page.url}"
        except Exception as e:
            return f"Back error: {e}"

    async def forward(self) -> str:
        page = await self._get_page()
        try:
            await page.go_forward(timeout=10_000)
            return f"Navigated forward: {page.url}"
        except Exception as e:
            return f"Forward error: {e}"

    async def reload(self) -> str:
        page = await self._get_page()
        try:
            await page.reload(timeout=15_000)
            return f"Page reloaded: {page.url}"
        except Exception as e:
            return f"Reload error: {e}"

    async def close_browser(self) -> str:
        attached = self._attached
        await self._async_close()
        return f"{self.browser_name} detached." if attached else f"{self.browser_name} closed."

class _SessionRegistry:
    """Manages all active browser sessions."""

    def __init__(self):
        self._sessions:        dict[str, _BrowserSession] = {}
        self._active_browser:  str                        = ""
        self._lock             = threading.Lock()
        self._last_native_url: str                        = ""
        # Headless automation sessions live beside the interactive ones, keyed
        # by browser — a headless "chrome" and a user-driven "chrome" are very
        # different programs wearing the same name.
        self._headless_sessions: dict[str, _BrowserSession] = {}
        self._headless_active:   str                        = ""

    def has(self, browser_name: str | None = None, headless: bool = False) -> bool:
        """Is there an active automation session for this browser (or any)?

        `headless` selects the headless automation namespace; the default keeps
        the historical interactive behaviour.
        """
        with self._lock:
            store = self._headless_sessions if headless else self._sessions
            if not browser_name:
                return bool(store)
            name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
            return name in store

    def note_native_url(self, url: str) -> None:
        self._last_native_url = url

    def pop_native_url(self) -> str:
        """Returns the last natively-opened URL once (consumed to avoid repeats)."""
        url, self._last_native_url = self._last_native_url, ""
        return url

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
                print(f"[Registry] New session: {browser_name}")
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def get_headless(self, browser_name: str, profile_name: str = "") -> _BrowserSession:
        """Open (or reuse) a headless automation session for this browser.

        A headless session is opened on a profile directory under
        ~/.jarvis_profiles, named after the caller when they asked for a persona
        ("Profile 1") and "default" otherwise. An existing session for the same
        browser is reused — unless the caller named a different profile, in which
        case the old context is closed first and the new one opened on the new
        profile.
        """
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        with self._lock:
            existing = self._headless_sessions.get(browser_name)
            if existing is not None and (not profile_name or existing.profile_name == profile_name):
                self._headless_active = browser_name
                return existing
            if existing is not None:
                try:
                    existing.close()
                except Exception:
                    pass
                del self._headless_sessions[browser_name]

        sess = _BrowserSession(browser_name, headless=True, profile_name=profile_name)
        sess.start()
        with self._lock:
            self._headless_sessions[browser_name] = sess
            self._headless_active = browser_name
        return sess

    def switch_headless(self, browser_name: str, profile_name: str) -> str:
        """Point the headless session of a browser at another profile."""
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        with self._lock:
            sess = self._headless_sessions.get(browser_name)
            if sess is None:
                return f"No headless session for: {browser_name}"
            try:
                sess.close()
            except Exception:
                pass
            del self._headless_sessions[browser_name]
        sess = _BrowserSession(browser_name, headless=True, profile_name=profile_name)
        sess.start()
        with self._lock:
            self._headless_sessions[browser_name] = sess
            self._headless_active = browser_name
        return f"Switched {browser_name} to headless profile '{profile_name}'."

    def _close_headless_locked(self, browser_name: str) -> None:
        """Drop a headless session for this browser, closing it. Caller holds _lock."""
        sess = self._headless_sessions.pop(browser_name, None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
        if self._headless_active == browser_name:
            self._headless_active = ""

    def close_headless(self, browser_name: str) -> str:
        with self._lock:
            sess = self._headless_sessions.pop(browser_name, None)
            was = (self._headless_active == browser_name)
            self._headless_active = ""
        if sess is None:
            return f"No headless session for: {browser_name}"
        try:
            sess.close()
        except Exception:
            pass
        return f"{browser_name} headless closed."

    def switch(self, browser_name: str) -> str:
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        self._get_or_create(browser_name)
        self._active_browser = browser_name
        return f"Active browser → {browser_name}"

    def close_one(self, browser_name: str) -> str:
        with self._lock:
            sess = self._sessions.pop(browser_name, None)
        if sess:
            attached = sess._attached
            sess.close()
            if self._active_browser == browser_name:
                self._active_browser = ""
            return f"{browser_name} detached." if attached else f"{browser_name} closed."
        # No interactive session for this browser — but a headless automation may
        # be the one that is actually open, so offer closing that instead of
        # reporting "no session" when there plainly is one.
        with self._lock:
            headless = self._headless_sessions.get(browser_name)
        if headless is not None:
            self._close_headless_locked(browser_name)
            return f"{browser_name} closed."
        return f"No active session for: {browser_name}"

    def close_all(self) -> str:
        with self._lock:
            names    = list(self._sessions.keys())
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
            headless_names = list(self._headless_sessions.keys())
            headless_sessions = list(self._headless_sessions.values())
            self._headless_sessions.clear()
            self._headless_active = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        for s in headless_sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed: " + (", ".join(names + headless_names) if (names or headless_names) else "none")

    def list_sessions(self) -> str:
        with self._lock:
            if not self._sessions:
                return "No active browser sessions."
            lines = []
            for name in self._sessions:
                marker = " ◀ active" if name == self._active_browser else ""
                lines.append(f"  • {name}{marker}")
            return "Open browsers:\n" + "\n".join(lines)


_registry = _SessionRegistry()

# Every action this tool answers to. One list, used by the failure message and
# by nothing else — it exists so that being told "that is not an action" also
# tells you what the actions ARE.
_ACTIONS = (
    "go_to", "search", "new_tab", "close_tab",
    "click", "smart_click", "type", "smart_type", "fill_form", "press",
    "scroll", "get_text", "get_url", "screenshot",
    "back", "forward", "reload",
    "switch", "list_browsers", "close", "close_all",
    "open_headless", "close_headless", "list_profiles", "switch_profile",
)


def _unknown_action(action: str) -> str:
    """Refuse an action this tool does not have, and say what it does have.

    THE OLD ANSWER WAS A SENTENCE, AND A SENTENCE IS NOT A FAILURE
        `f"Unknown browser action: '{action}'"` is a plain string. Nothing above
        this file could tell it apart from a success: it does not start with a
        status, so `outcome.is_problem` reads it as fine, the screen agent's
        loop counted the step as performed, and the assistant said the browser
        control function "couldn't understand the action" only because the model
        happened to read the English.

        Worse, it taught nothing. A caller told "unknown action 'open'" and
        nothing else has exactly one move available, which is to guess again.
        Observed doing precisely that: open, then "", then open.

    So this is a real failure with the valid list attached. A planner that
    reads it can correct itself on the next attempt instead of re-rolling.
    """
    return outcome.failed(
        "browser_control",
        f"there is no browser action called {action or '(empty)'!r}",
        valid_actions=", ".join(_ACTIONS))


def browser_control(
    parameters:    dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = _unknown_action(action)

    if action == "switch":
        target = browser or params.get("target", "").lower().strip()
        result = _registry.switch(target) if target else "Please specify a browser."
        _log(player, result)
        return result

    if action == "list_browsers":
        result = _registry.list_sessions()
        _log(player, result)
        return result

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    if action == "close":
        target = browser or _registry._active_browser
        result = _registry.close_one(target) if target else "No browser specified."
        _log(player, result)
        return result

    # Navigation and interaction must use the SAME controlled browser context.
    if action in ("go_to", "search", "new_tab"):
        try:
            sess = _registry.get(browser)
            if action == "search":
                result = sess.run(sess.search(params.get("query", ""), params.get("engine", "google")))
            elif action == "new_tab":
                result = sess.run(sess.new_tab(params.get("url", "")))
            else:
                result = sess.run(sess.go_to(params.get("url", "")))
        except Exception as exc:
            result = f"Browser error ({action}): {exc}"
        _log(player, result)
        return result

    if action == "attach":
        try:
            sess = _registry.get(browser or "chrome")
            result = sess.run(sess.attach(params.get("cdp_url") or "http://127.0.0.1:9222"))
        except Exception as exc:
            result = f"Could not attach to browser: {exc}. Existing Chrome must be started with remote debugging and a separate user-data-dir; ordinary Chrome tabs cannot be attached automatically."
        _log(player, result)
        return result

    # ── Headless + profile actions ──────────────────────────────────────────
    # Headless is the "nobody is watching" browser: same engine, same page
    # protocol, no window, profile under ~/.jarvis_profiles. It exists for the
    # background jobs a person is not part of — a page a model has to read, a
    # fetch that should not light up a window the user is using for something
    # else.
    if action == "open_headless":
        target = browser or _detect_default_browser()
        url = str(params.get("url") or "about:blank")
        try:
            sess = _registry.get_headless(target, str(params.get("profile") or ""))
            result = sess.run(sess.go_to(url))
        except concurrent.futures.TimeoutError:
            result = f"Headless browser action 'open_headless' timed out (60s)."
        except Exception as e:
            result = f"Headless browser error (open_headless): {e}"
        _log(player, result)
        return result

    if action == "close_headless":
        target = browser or _registry._headless_active
        result = _registry.close_headless(target) if target else "No headless browser is open."
        _log(player, result)
        return result

    if action == "list_profiles":
        target = browser or _detect_default_browser()
        result = _list_profiles(target)
        _log(player, result)
        return result

    if action == "switch_profile":
        target = browser or _detect_default_browser()
        pname = str(params.get("profile_name") or params.get("profile") or "").strip()
        if not pname:
            result = "Please specify a profile name to switch to."
            _log(player, result)
            return result
        result = _registry.switch_headless(target, pname)
        _log(player, result)
        return result

    # ── Interactive actions (click/type/read…) ───────────────────────────────
    # These require a physically controllable browser; the automation window
    # only opens here, and as soon as it opens it goes to the user's last
    # navigated page — it doesn't sit on a blank page.
    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        last = _registry.pop_native_url()
        if last:
            try:
                sess.run(sess.go_to(last))
            except Exception as e:
                print(f"[Browser] Could not resume last page ({last}): {e}")

        if action == "list_tabs":
            result = sess.run(sess.list_tabs())
        elif action == "switch_tab":
            result = sess.run(sess.switch_tab(int(params.get("tab_index", 0))))
        elif action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(
                params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "fill_form":
            result = sess.run(sess.fill_form(params.get("fields", {})))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "smart_type":
            result = sess.run(sess.smart_type(params.get("description", ""), params.get("text", "")))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "close_tab":
            result = sess.run(sess.close_tab())
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "back":
            result = sess.run(sess.back())
        elif action == "forward":
            result = sess.run(sess.forward())
        elif action == "reload":
            result = sess.run(sess.reload())
        else:
            result = _unknown_action(action)

    except concurrent.futures.TimeoutError:
        result = f"Browser action '{action}' timed out (60s)."
    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    # ONE line, once. This printed the same string twice whenever a player was
    # attached - which is always, in the real app - and the second copy read in
    # the terminal like a second navigation. "Opened in operagx: <url>" twice in
    # a row looks exactly like the browser being opened twice, and time was
    # spent looking for a double-open that had never happened.
    print(f"[Browser] {str(text)[:80]}")


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "browser_control",
    "description": (
        "Controls the web browser and everything INSIDE a web page: open an "
        "address, search, click, type, scroll, read the page, manage tabs, go "
        "back and forward. Anything happening on a website is this tool - it "
        "reads the page itself, which nothing else in the assistant can do. "
        "THIS TOOL OPENS THE BROWSER ITSELF. Never call open_app for the "
        "browser first. 'Open Chrome and "
        "go to YouTube' is ONE call to this tool. "
        "NEVER INVENT AN ADDRESS. Only pass a url you actually know. Anything "
        "belonging to the user personally - their own channel, profile, "
        "account page, inbox or playlist - has an address you do NOT know, and "
        "guessing a path produces an error page that looks like a working one. "
        "When the exact address is not known: open the site's own address "
        "(youtube.com, instagram.com) and get to the rest with smart_click on "
        "what the page shows, or use action='search', or ask the user. A "
        "guessed path is never acceptable. "
        "TO CLICK OR TYPE ON A PAGE, PREFER action='smart_click' or "
        "action='smart_type' with a 'description' of what the thing SAYS on "
        "screen - the visible label, in the page's own language. They search "
        "the page by role, label, placeholder and text and find it. Plain "
        "'click' with a 'selector' needs a CSS selector that is exactly right "
        "for that site's markup, which is not something to guess at; use it "
        "only when the selector is known. "
        "Use get_text, list_tabs and get_url to inspect browser state directly; "
        "do not capture the desktop merely to read a web page. list_tabs uses "
        "zero-based indices; switch_tab selects one. attach connects to an "
        "existing Chromium debugging endpoint (cdp_url), never an ordinary "
        "browser without remote debugging. New sessions use a persistent "
        "JARVIS profile; the user's normal Chrome tabs and logins are separate. "
        "For multi-step web tasks, continue in this same browser session and "
        "verify with get_text/get_url after each action. "
        "Headless jobs use action='open_headless' - the same browser, engine and "
        "page protocol, with no window and no person watching; the address goes in "
        "'url', the browser in 'browser', and a named profile in 'profile' when "
        "the automation should use one the user's real browser also has. "
        "action='list_profiles' answers which profiles exist for a browser; "
        "action='switch_profile' moves a headless session to another one. "
        "Read the status it returns. 'done' means it was confirmed - for an "
        "open, the url reported back is the page's OWN address, so if it "
        "differs from what was asked for the site redirected and the user "
        "should be told. 'unverified' means the address was handed to a browser "
        "that does not report back: whether the page loaded, redirected or does "
        "not exist is unknown, so say it was opened but NOT confirmed and never "
        "that the page is up. 'failed' means nothing happened."
    ),
    "brief": (
        "Controls the web browser: open a URL, navigate, click, read the page."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "attach | list_tabs | switch_tab | go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all | open_headless | close_headless | list_profiles | switch_profile"
            },
            "cdp_url": {"type": "STRING", "description": "Loopback Chrome debugging endpoint for attach; default http://127.0.0.1:9222"},
            "tab_index": {"type": "INTEGER", "description": "Zero-based tab index from list_tabs"},
            "browser": {
                "type": "STRING",
                "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."
            },
            "url": {
                "type": "STRING",
                "description": "URL for go_to / new_tab action"
            },
            "query": {
                "type": "STRING",
                "description": "Search query for search action"
            },
            "engine": {
                "type": "STRING",
                "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"
            },
            "selector": {
                "type": "STRING",
                "description": "CSS selector for click/type"
            },
            "text": {
                "type": "STRING",
                "description": "Text to click or type"
            },
            "description": {
                "type": "STRING",
                "description": "Element description for smart_click/smart_type"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down for scroll"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount in pixels (default: 500)"
            },
            "key": {
                "type": "STRING",
                "description": "Key name for press action (e.g. Enter, Escape, F5)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            },
            "incognito": {
                "type": "BOOLEAN",
                "description": "Open in private/incognito mode"
            },
            "profile": {
                "type": "STRING",
                "description": "For open_headless / switch_profile: the named browser profile to use (e.g. 'Default', 'Profile 1'). Headless sessions live under a JARVIS profile directory, named after this."
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": browser_control,
}
