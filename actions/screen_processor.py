"""
Screen & webcam capture for JARVIS vision.

Provides the two capture entry points main.py uses — `_capture_screen()` and
`_capture_camera()` — plus their helpers (compression, camera auto-detection,
config access). main.py grabs a frame here on demand, then injects it into the
main Gemini Live session; there is no separate vision session here.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from core.lazyimport import LazyModule, installed

# OpenCV is 224 ms and is only ever touched by the webcam path — see
# core/lazyimport.py. Screen capture, which is what this action does on almost
# every call, never reaches it. numpy above stays eager: main.py already
# imports it for audio, so it is in memory before this file is read.
_CV2 = installed("cv2")

cv2 = LazyModule("cv2")

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        cfg = _load_config()
        cfg[key] = value
        _CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Vision] ⚠️  Could not save config key '{key}': {e}")


def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()


_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 82


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"



# Use Ubuntu's system Python for Gio; the application's virtualenv need not
# contain PyGObject. This process creates no GUI: the desktop portal owns UI.
_PORTAL_SCREENSHOT_SCRIPT = r"""
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, unquote
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
token = "jarvis_" + uuid.uuid4().hex
sender = bus.get_unique_name()[1:].replace(".", "_")
request = "/org/freedesktop/portal/desktop/request/" + sender + "/" + token
result = {}

def response(conn, sender, path, interface, signal, params):
    code, values = params.unpack()
    result.update(code=code, values=values)
    loop.quit()

def timeout():
    result["error"] = "Screen capture permission timed out; try again and accept the desktop dialog."
    loop.quit()
    return False

subscription = bus.signal_subscribe(
    "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
    "Response", request, None, Gio.DBusSignalFlags.NONE, response)
timer = GLib.timeout_add_seconds(55, timeout)
try:
    reply = bus.call_sync(
        "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Screenshot", "Screenshot",
        GLib.Variant("(sa{sv})", ("", {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", False),
        })), GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 10000, None)
    if reply.unpack()[0] != request:
        raise RuntimeError("Portal returned an unexpected request handle")
    loop.run()
    if "error" in result:
        try:
            bus.call_sync("org.freedesktop.portal.Desktop", request,
                "org.freedesktop.portal.Request", "Close", None, None,
                Gio.DBusCallFlags.NONE, 2000, None)
        except Exception:
            pass
        raise RuntimeError(result["error"])
    code = result.get("code", 2)
    if code == 1:
        raise RuntimeError("Screen capture cancelled or permission denied. Allow JARVIS in the desktop sharing dialog.")
    if code != 0:
        raise RuntimeError("Desktop portal could not capture the screen (response %s)." % code)
    uri = urlparse(result["values"].get("uri", ""))
    if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        raise RuntimeError("Portal returned no local screenshot file")
    screenshot = Path(unquote(uri.path))
    try:
        data = screenshot.read_bytes()
    finally:
        # The portal chooses the source location; leave no screenshot behind.
        screenshot.unlink(missing_ok=True)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Portal returned an invalid PNG screenshot")
    sys.stdout.buffer.write(data)
except Exception as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
finally:
    bus.signal_unsubscribe(subscription)
    if "error" not in result:
        GLib.source_remove(timer)
"""


def _capture_via_portal() -> bytes:
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-c", _PORTAL_SCREENSHOT_SCRIPT],
            capture_output=True, timeout=70,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Wayland screenshot portal unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Wayland screen capture failed: {detail or 'portal helper failed'}")
    if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Wayland screenshot portal returned no usable PNG")
    return result.stdout


def _capture_via_cli() -> bytes:
    """Legacy command fallback for X11 and other supported desktops.

    These commands are not a replacement for GNOME's Wayland portal.
    """
    with tempfile.TemporaryDirectory(prefix="jarvis-capture-", dir="/tmp" if sys.platform.startswith("linux") else None) as capture_dir:
        out = Path(capture_dir) / "screen.png"
        attempted: list[str] = []
        ok, data = False, b""
        for cmd in (
            ["scrot", str(out)],
            ["gnome-screenshot", "-f", str(out)],
            ["import", "-window", "root", str(out)],
            ["grim", str(out)],
        ):
            if not shutil.which(cmd[0]):
                attempted.append(f"{cmd[0]}=not-installed")
                continue
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=20)
                if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    frame = out.read_bytes()
                    if not _frame_is_black(frame, "image/png"):
                        ok, data = True, frame
                        break
                    attempted.append(f"{cmd[0]}=black-frame")
                else:
                    attempted.append(f"{cmd[0]}=rc{r.returncode}")
            except Exception as e:
                attempted.append(f"{cmd[0]}=error:{e}")
            try:
                out.unlink()
            except Exception:
                pass
        if not ok:
            raise RuntimeError(
                "screenshot CLI backends failed: " + (", ".join(attempted) or "none ran")
            )
        try:
            out.unlink()
        except Exception:
            pass
        return data


def _frame_is_black(data: bytes, mime: str) -> bool:
    """Is this frame a picture at all, or an empty/black capture?

    An all-black frame is not a screenshot the model can use — feeding one to the
    vision pipeline is how the agent ends up answering "the screen is black" when
    the real screen was showing something. So a backend that returns one is treated
    as a failure and the next backend is tried instead.
    """
    if not _PIL:
        return False
    try:
        img = PIL.Image.open(io.BytesIO(data)).convert("RGB")
        small = img.resize((8, 8))
        pixels = list(small.getdata())
        mean = sum(sum(p[:3]) for p in pixels) / (len(pixels) * 3)
        return mean < 12.0
    except Exception:
        return False


def _capture_once() -> tuple[bytes, str]:
    """One capture attempt, through whichever backend can serve it.

    Returns (data, mime) for a real frame; raises RuntimeError with the reason
    when every backend failed — or answered black — so the failure is always
    heard as a sentence, never as a black image pretending to be a screen.
    """
    problems: list[str] = []
    if _MSS:
        try:
            with mss.mss() as sct:
                monitors = sct.monitors          # [0] = all combined, [1..n] = real screens
                target   = monitors[1] if len(monitors) > 1 else monitors[0]
                shot     = sct.grab(target)
                png      = mss.tools.to_png(shot.rgb, shot.size)
            data, mime = _compress(png, "PNG")
            if not _frame_is_black(data, mime):
                return data, mime
            problems.append("mss returned a black frame")
        except Exception as e:
            problems.append(f"mss failed: {e}")

    try:
        data = _capture_via_cli()
        if not _frame_is_black(data, "image/png"):
            return data, "image/png"
        problems.append("screenshot CLI returned a black frame")
    except Exception as e:
        problems.append(f"screenshot CLI failed: {e}")

    raise RuntimeError(
        "screen capture failed — no backend produced a usable frame ("
        + "; ".join(problems)
        + ")"
    )


def capture_screen() -> tuple[bytes, str]:
    """The desktop as (image bytes, mime), retried once before giving up.

    A capture reads a live framebuffer, and a read that comes back black a
    single time is usually a blip in the display server rather than a fact about
    the screen — so the attempt is simply made again before the failure is
    allowed to reach the model. Only a second failure is reported.
    """
    # X11 tools cannot read GNOME's Wayland desktop. Ask the desktop portal
    # directly, and never repeat a user cancellation/denial automatically.
    if sys.platform.startswith("linux") and (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or (not os.environ.get("XDG_SESSION_TYPE") and os.environ.get("WAYLAND_DISPLAY"))
    ):
        return _compress(_capture_via_portal(), "PNG")

    last: Exception | None = None
    for attempt in (1, 2):
        try:
            return _capture_once()
        except Exception as e:
            last = e
            if attempt == 1:
                time.sleep(0.35)
    raise last


def _capture_screen() -> tuple[bytes, str]:
    return capture_screen()


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _CV2:
        return 0
    os_name = _get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    backend = _cv2_backend()
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in range(6):
        if _probe_camera(idx, backend):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    print("[Vision] ⚠️  No camera found — defaulting to index 0")
    _save_config_key("camera_index", 0)
    return 0


def _get_camera_index() -> int:
    cfg = _load_config()
    if "camera_index" in cfg:
        return int(cfg["camera_index"])
    return _detect_camera_index()


def _capture_camera() -> tuple[bytes, str]:
    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"
