# JARVIS AI Agent — Mark LVII

A desktop voice assistant with screen and webcam vision, browser automation,
terminal commands, memory, background tasks, and reminders. Supports Windows,
macOS, and Linux, with capabilities depending on OS permissions.

Originally created by [FatihMakes](https://www.youtube.com/@FatihMakes).

## Setup

Python 3.11–3.13 is the tested range listed by the setup script. Newer versions
may work, but dependency compatibility can vary.

```bash
git clone https://github.com/code-abdulrehman/jarvis-ai-agent.git
cd jarvis-ai-agent
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies and launch:

```bash
python setup.py
python main.py
```

`setup.py` installs platform-specific dependencies and Playwright browsers.
Enter your Gemini API key on first launch, or configure a local/hosted engine
under **Settings → ENGINE & PROVIDERS**. Choose your microphone and speakers in
settings; use the microphone test to check input.

Optional local speech recognition, neural voices, and wake-word dependencies
can be installed from their settings panels.

## Capabilities and permissions

| Capability | How it works |
|---|---|
| Voice | Microphone input and spoken replies; device selection, mute, and push-to-talk are available. |
| Screen and webcam vision | Captures an image for the active vision conversation. Screen permissions depend on the desktop. |
| Terminal | `terminal_control` runs shell commands and returns output. Some commands require confirmation. |
| Browser | `browser_control` uses Playwright for navigation and page interaction. Browser availability and profile state affect access. |
| Desktop | App launching, windows, keyboard, and mouse actions; support varies by display server and OS permissions. |
| Files and memory | Reads and manages files, stores preferences, and supports undo for supported actions. |
| Tasks and routines | Runs background research, writes reports, and schedules reminders and recurring work. |
| Plugins | Discovers tools from `actions/` and plugins from `plugins/` at startup. |
| Phone dashboard | Provides remote access through the dashboard's pairing flow. |

Tool permissions use `allow`, `ask`, or `deny`. Unset tools default to `allow`.
Use the `permissions` tool to list or change them. App permissions do not override
OS permissions or grant administrator access.

Example requests:

- “What is open on my screen?”
- “Run `pwd` in the terminal.”
- “Open this website.”
- “Research this topic for ten minutes.”
- “Remind me every Friday at 17:00.”

## Linux screen capture

On **GNOME Wayland**, screen capture uses the XDG Screenshot portal. Allow the
capture when the desktop presents a permission dialog. Cancellation is reported
without automatically asking again. Ubuntu's `/usr/bin/python3` must have
PyGObject (`gi`, Gio, and GLib), and a working desktop portal must be running.

On **Xorg**, capture uses `mss` with screenshot-command fallbacks. GNOME 50 does
not provide the old GNOME Xorg session; an Xorg-capable desktop such as XFCE is
needed if you choose that route. Installing XFCE does not switch an active
Wayland session to Xorg.

Check your current session:

```bash
echo $XDG_SESSION_TYPE
```

`wayland` and `x11` identify the active display server. Wayland screen capture
support does not enable unrestricted mouse, keyboard, or window automation.
On macOS, grant Screen Recording and Accessibility permissions as needed.

Restart JARVIS after updating capture code.

## Screenshot storage and data handling

- On Linux, command-based screenshot fallbacks use a private
  `/tmp/jarvis-capture-…/` directory. Files are removed after reading, including
  normal failure paths; JARVIS does not write these captures to Desktop.
- The Wayland portal chooses its screenshot location. JARVIS reads the returned
  file and deletes it immediately afterward.
- `mss` frames and images awaiting analysis are held in memory. Captures are not
  intentionally archived for the session. An abrupt process termination can
  interrupt cleanup of temporary files.
- Images used for vision can be sent to the configured AI service. Deleting a
  local file does not delete a provider's retained data.
- Gemini Live sends voice to Google during active voice use. Other hosted
  providers receive the inputs used by their configured features. Local models
  can reduce external processing; web search and other online tools still make
  network requests when used.

| Local data | Location |
|---|---|
| API keys and settings | `config/api_keys.json` — plaintext; keep private |
| Long-term memory | `memory/long_term.json` |
| Task checkpoints and saved sources | `memory/tasks/` |
| Research reports | `reports/` |
| Routines | `memory/routines.json` |
| Dashboard certificates | `config/certs/` |

Review files before committing; `.gitignore` does not remove previously tracked
secrets. Revoke credentials if they were exposed.

## Project layout

| Path | Purpose |
|---|---|
| `main.py` | Voice session and tool dispatch |
| `ui.py`, `gui/` | Desktop interface |
| `actions/` | Built-in tools, including capture, browser, and terminal control |
| `plugins/` | Additional tools |
| `core/` | Shared runtime, tasks, confirmations, and loaders |
| `providers/` | Alternative speech and model engines |
| `agents/` | Background-agent instructions |
| `memory/`, `config/`, `reports/` | Local state, settings, and generated reports |

Contributors should read [AGENTS.md](AGENTS.md) before changing code.

## Credits and license

Original project: [FatihMakes/Mark-LVII](https://github.com/FatihMakes/Mark-LVII).
Licensed under [CC BY-NC 4.0](LICENSE); commercial use is not permitted.

`core/face_model.obj` uses the MediaPipe canonical face model under Apache 2.0:
[MediaPipe](https://github.com/google-ai-edge/mediapipe).
