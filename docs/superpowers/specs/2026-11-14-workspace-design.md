# JARVIS Workspace

Approved scope: a single native Workspace with status/alerts, browser profiles,
computer/vision/app permissions, Codex threads and history, tasks, and routines.
Reuse existing PyQt6 UI and local engines. Keep voice conversation available.

Browser profiles pair through a Chrome MV3 extension in each chosen profile.
Use a token-paired loopback bridge; pages and commands are scoped to the selected
approved profile. Existing Chrome logins stay in Chrome. Never copy credentials.
Keep the existing Playwright browser as a separate connection option.

Codex uses the installed app-server's JSON-RPC protocol. List/read/resume/fork/
rename/archive threads and start/interrupt turns. Show live events and pending
approvals; approval decisions come from the user. Never edit Codex databases.

Status controls persist through config_manager. Apply capability gates to all
tool dispatch paths; off means blocked, including already paired browser calls.
Vision off releases screen sharing. App permissions distinguish open and close.
Notifications and unsolicited spoken alerts have independent switches. Keep
confirmation prompts and errors available. History records metadata, not keys or
full captured images. User can clear local activity history.

Use existing task and routine engines for add/cancel/results, edit schedules,
pause/resume, and run now. No fake connected states. Blocking work runs off Qt's
main thread; workers communicate with widgets via signals only.
