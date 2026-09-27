# appctl v0.1 — the hands layer

`appctl` is The Architect's **lifecycle adapter**: one typed command vocabulary for
opening, focusing, checking, and closing applications on any OS. The agent calls
`appctl`; it never invents raw shell text for app control.

Single file, stdlib only — drop `appctl.py` on a machine and run it.

## Commands

```
appctl open <app> [--args ...]   start an application
appctl focus <app>               bring its window to the foreground
appctl status <app>              is it running? (pid, window title)
appctl list                      running processes
appctl quit <app> [--force]      close gracefully, or force-kill
```

Exit codes: `0` ok · `1` action failed · `2` usage error.
Every command prints JSON on stdout — the verifier's evidence:

```json
{"ok": true, "action": "status", "app": "obs",
 "evidence": {"running": true,
              "processes": [{"pid": 1234, "name": "obs", "window": "OBS Studio"}]}}
```

## Platform backends

| Command | Windows | macOS | Linux |
|---------|---------|-------|-------|
| open | `Start-Process` | `open -a` | direct exec (detached) |
| focus | user32 `SetForegroundWindow` | `osascript activate` | `wmctrl`/`xdotool` if present |
| status | `Get-Process` | `pgrep` | `pgrep` |
| quit | `CloseMainWindow` → `Stop-Process` | AppleScript quit → `pkill` | `SIGTERM` → confirm (never `pkill -f`: that matches the caller's own command line) |

## Legion install (Windows)

1. Copy `appctl.py` to Legion (needs Python 3.9+ on PATH).
2. Smoke test:
   ```
   python appctl.py status notepad
   python appctl.py open notepad
   python appctl.py focus notepad
   python appctl.py quit notepad
   ```
3. Report back the JSON. Windows `open`/`focus`/`quit` paths are untested —
   Legion is the test box.

## Roadmap

- v0.2: window geometry + screenshot crop per app (observation side)
- v0.3: tool registry (`appctl tools <app>` listing registered typed actions)
- v0.4: CLI-Anything harness generation hooks
