# Workspace Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a native management workspace with enforced access switches and real connections.
**Architecture:** Shared workspace service, isolated browser/Codex adapters, Qt dialog using worker signals, existing task/routine engines.
**Tech Stack:** Python stdlib, existing PyQt6/FastAPI/uvicorn, Chrome MV3.
**Spec:** docs/superpowers/specs/2026-11-14-workspace-design.md

## Global Constraints
- No new Python dependencies; preserve existing UI theme and Qt thread rules.
- Persist settings through memory/config_manager.py; no direct credential writes.
- Never bypass OS/browser permissions; user decisions gate approval requests.

## Tasks
- [x] Permissions/status/history: tests first; implement settings, dispatch gates, notification suppression and history.
- [x] Browser bridge: tests first; pair/revoke/select profiles, DOM commands and Chrome extension; preserve Playwright fallback.
- [x] Codex: protocol schema checked locally; tests for JSON-RPC routing, approvals, lifecycle and bounded history.
- [x] Workspace UI: tabs for status, browser, threads, tasks, routines, history; worker-only I/O and signal updates; connect header button.
- [x] Integration: run regression suite, loopback bridge tests, app-server read-only checks and offscreen Qt interactions; document setup; commit in batches and push.
