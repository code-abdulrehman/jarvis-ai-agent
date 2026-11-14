# Workspace

Restart JARVIS after updating. Click **Workspace** in the header, or say
“Open Workspace”. The voice tool is `workspace_control`.

## Status and access

Separate switches control desktop notifications, spoken alerts, browser access,
computer input, vision, app opening, app closing, terminal commands, system
settings, Codex, new background tasks, routines, and activity history.

Changes persist through the existing configuration manager. Disabled capabilities
reject new tool calls. Vision off releases screen sharing and stops camera
preview. Browser off disables paired profiles and closes owned Playwright
contexts; externally attached CDP browsers are detached. Re-enable the global
browser switch and the desired profile to reconnect it.

These are JARVIS dispatch controls, not an OS sandbox. Wayland's global input
limits and browser permission restrictions still apply. A previously started
Codex turn or background task can continue; use Interrupt or Cancel for that
work. Codex disconnect only disconnects this client from the shared server.

Allowed app names restrict the launcher/normal-close tools when the list is
nonempty. Match the names passed to those tools. An empty list permits any app
subject to other permissions. Terminal access remains an independent capability.

Action-tool overrides support allow/ask/deny. Ask uses the existing confirmation
banner and is intended for registered action tools such as `terminal_control`.
Use the dedicated vision switch for inline screen/camera tools. Confirmation
prompts are separate from ordinary notifications and are not muted by the
notification switch. Muting spoken alerts does not mute normal conversation.

## Connect existing Chrome profiles

1. Open **Browser profiles**, enable browser access, and click **Start bridge /
   new pairing code**. The code expires after five minutes and works once.
2. Click **Open extension folder** to locate `browser-extension/`.
3. In the Chrome profile you want to connect, visit `chrome://extensions`, enable
   Developer mode, choose **Load unpacked**, and select that folder.
4. Open **JARVIS Profile Connection** from Chrome's toolbar. Enter a profile
   name, the bridge port shown in JARVIS, and the pairing code.
5. Click **Pair this profile and allow websites**. Chrome asks for site access.
   You can adjust that access later in Chrome's extension settings.
6. Select the connected profile in Workspace and click **Use selected profile**.

Repeat only for profiles you choose. Each profile has separate storage and login
sessions in Chrome; JARVIS does not extract cookies or passwords. Pairing tokens
stay in the extension's local storage; JARVIS stores their hashes in its private
config. Forget a connection to revoke its token. Disable preserves pairing but
blocks commands. Reconnection can take up to 30 seconds after JARVIS starts.

The bridge binds only to `127.0.0.1` (default port 8766; another free port is used
if needed). It is independent of the phone dashboard. Only the selected enabled
profile receives browser commands. A disconnected selected profile reports a
failure instead of silently opening a different browser.

Page text, tabs, clicks, and form inputs use extension APIs. Chrome internal
pages, restricted websites, password entry, and actions requiring trusted native
input can be unavailable. Results distinguish dispatched events from verified
navigation; the agent should read the page again to check its work. Website
access can send page content to the configured model when requested.

**Use separate JARVIS browser** selects the existing Playwright workflow, with a
separate persistent browser profile. CDP attachment remains available for browsers
explicitly started with remote debugging.

## Codex threads and history

Install/login to Codex normally, then click **Connect**. On supported local
installs, Workspace connects to the shared app-server Unix socket, preserving
live session visibility. If no shared socket exists, a local stdio app-server
uses Codex's own history store. The current Codex CLI must expose the app-server
protocol. JARVIS never edits Codex databases or copies auth credentials.

Search active or archived threads, load more results, read recent messages, and
load older message pages. New threads choose a project directory; Resume, Send,
Interrupt, Rename, Fork, Archive and Restore operate through the server. Multiple
threads can run independently. Sending a prompt can consume the configured
Codex account's usage.

Command/file approvals have **Approve once** and **Deny** buttons. Questions can
be answered in the Workspace. Unsupported approval types remain pending for the
native Codex client; **Copy resume command** helps open that session there.
JARVIS's voice tool cannot approve requests. Server errors and disconnected
states are shown instead of claimed success.

## Tasks and routines

Tasks reuse the background task engine: add a self-contained request, select
General or Researcher, set a minute budget, inspect results, finish early, or
cancel. Task results remain in their existing stores and `reports/`.

Routines reuse the scheduler. Add or edit a name, instruction, schedule, agent,
budget, and delivery. Schedules include daily/weekly/monthly/once/interval,
startup and idle triggers. Use Pause/Resume, Run now, Delete, and quiet hours.
Built-in routines can be paused, not deleted. The existing routine engine must
be attached by the main JARVIS app; a standalone UI preview has no running engine.

## Activity history

Up to 500 metadata events are stored in `memory/workspace/activity.jsonl` with
user-only file permissions. Events contain time, kind, tool/control name, and
status, not tool arguments, credentials, screenshots, or conversation transcripts.
Disable saving or clear the log in **Activity history**. This does not delete
Codex conversations, task results, or provider-side data.
