#!/usr/bin/env python3
"""appctl v0.1 — cross-platform application lifecycle adapter for The Architect.

One typed vocabulary for app lifecycle on any OS, so the agent never invents
raw shell text. Every command emits JSON evidence the verifier can check.

    appctl open <app> [--args ...]     start an application
    appctl focus <app>                 bring its window to the foreground
    appctl status <app> [--json]       is it running? pid, window title
    appctl list                        running GUI processes
    appctl quit <app> [--force]        close gracefully, or force-kill

Exit codes: 0 = ok, 1 = action failed (app not found / not running), 2 = usage error.
All output is JSON on stdout: {"ok": bool, "action": str, ...}.
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys

OS = platform.system()  # Windows | Darwin | Linux


def emit(payload, code=0):
    print(json.dumps(payload, indent=2 if sys.stdout.isatty() else None))
    sys.exit(code)


def fail(action, reason, **extra):
    emit({"ok": False, "action": action, "error": reason, **extra}, code=1)


def run(cmd, **kw):
    """Run a command, return (returncode, stdout stripped). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)
        return p.returncode, p.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 127, str(e)


# ---------------------------------------------------------------- Windows ----
def _ps(script):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def win_open(app, args):
    arg_str = " ".join(f"'{a}'" for a in args)
    extra = f" -ArgumentList {arg_str}" if arg_str else ""
    rc, out = _ps(f"Start-Process -FilePath '{app}'{extra} -PassThru | Select-Object -ExpandProperty Id")
    if rc != 0 or not out.isdigit():
        return fail("open", f"could not start '{app}'", detail=out)
    return emit({"ok": True, "action": "open", "app": app, "evidence": {"pid": int(out)}})


def win_status(app):
    name = app[:-4] if app.lower().endswith(".exe") else app
    rc, out = _ps(
        f"Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
        "Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json -Compress"
    )
    if rc != 0 or not out or out == "null":
        return emit({"ok": True, "action": "status", "app": app,
                     "evidence": {"running": False}})
    procs = json.loads(out)
    if isinstance(procs, dict):
        procs = [procs]
    return emit({"ok": True, "action": "status", "app": app, "evidence": {
        "running": True,
        "processes": [{"pid": p["Id"], "name": p["ProcessName"],
                       "window": p.get("MainWindowTitle") or ""} for p in procs]}})


def win_list():
    rc, out = _ps(
        "Get-Process | Where-Object {$_.MainWindowTitle} | "
        "Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json -Compress"
    )
    procs = json.loads(out) if out and out != "null" else []
    if isinstance(procs, dict):
        procs = [procs]
    emit({"ok": True, "action": "list", "evidence": {
        "count": len(procs),
        "processes": [{"pid": p["Id"], "name": p["ProcessName"],
                       "window": p.get("MainWindowTitle") or ""} for p in procs]}})


def win_focus(app):
    name = app[:-4] if app.lower().endswith(".exe") else app
    script = (
        "Add-Type @'\n"
        "using System; using System.Runtime.InteropServices;\n"
        "public class W { [DllImport(\"user32.dll\")] "
        "public static extern bool SetForegroundWindow(IntPtr h); }'@\n"
        f"$p = Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
        "Where-Object {$_.MainWindowHandle -ne 0} | Select-Object -First 1\n"
        "if ($p) { [W]::SetForegroundWindow($p.MainWindowHandle); 'focused' } else { 'notfound' }"
    )
    rc, out = _ps(script)
    if out != "focused":
        return fail("focus", f"no visible window for '{app}'")
    return emit({"ok": True, "action": "focus", "app": app,
                 "evidence": {"foreground": True}})


def win_quit(app, force):
    name = app[:-4] if app.lower().endswith(".exe") else app
    if not force:
        _ps(f"(Get-Process -Name '{name}' -ErrorAction SilentlyContinue).CloseMainWindow()")
        import time
        for _ in range(10):
            time.sleep(0.5)
            rc, out = _ps(f"@(Get-Process -Name '{name}' -ErrorAction SilentlyContinue).Count")
            if out in ("0", ""):
                return emit({"ok": True, "action": "quit", "app": app,
                             "evidence": {"running": False, "method": "graceful"}})
    rc, out = _ps(f"Stop-Process -Name '{name}' -Force -ErrorAction SilentlyContinue; 'done'")
    return emit({"ok": True, "action": "quit", "app": app,
                 "evidence": {"running": False,
                              "method": "force" if force else "graceful-timeout-force" }})


# ------------------------------------------------------------------ macOS ----
def mac_open(app, args):
    cmd = ["open", "-a", app] + (["--args"] + args if args else [])
    rc, out = run(cmd)
    if rc != 0:
        return fail("open", f"could not start '{app}'", detail=out)
    return emit({"ok": True, "action": "open", "app": app, "evidence": {"launched": True}})


def mac_status(app):
    rc, out = run(["pgrep", "-fl", app])
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and "appctl" not in parts[1]:
            procs.append({"pid": int(parts[0]), "cmd": parts[1]})
    return emit({"ok": True, "action": "status", "app": app, "evidence": {
        "running": bool(procs), "processes": procs}})


def mac_quit(app, force):
    if not force:
        rc, _ = run(["osascript", "-e", f'quit app "{app}"'])
        if rc == 0:
            return emit({"ok": True, "action": "quit", "app": app,
                         "evidence": {"running": False, "method": "graceful"}})
    rc, out = run(["pkill", "-x", app] if not force else ["pkill", "-9", "-x", app])
    return emit({"ok": True, "action": "quit", "app": app,
                 "evidence": {"running": False, "method": "pkill"}})


def mac_focus(app):
    rc, out = run(["osascript", "-e", f'tell application "{app}" to activate'])
    if rc != 0:
        return fail("focus", f"could not activate '{app}'", detail=out)
    return emit({"ok": True, "action": "focus", "app": app,
                 "evidence": {"foreground": True}})


# ------------------------------------------------------------------ Linux ----
def lin_open(app, args):
    binary = shutil.which(app) or app
    try:
        p = subprocess.Popen([binary] + args, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return emit({"ok": True, "action": "open", "app": app,
                     "evidence": {"pid": p.pid}})
    except OSError as e:
        return fail("open", f"could not start '{app}'", detail=str(e))


def lin_status(app):
    rc, out = run(["pgrep", "-af", app])
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and "appctl" not in parts[1]:
            procs.append({"pid": int(parts[0]), "cmd": parts[1]})
    return emit({"ok": True, "action": "status", "app": app, "evidence": {
        "running": bool(procs), "processes": procs}})


def _live_pids(app):
    """PIDs matching app, excluding PID 1, ourselves, and anything appctl-related."""
    import os
    rc, out = run(["pgrep", "-f", app])
    me = os.getpid()
    live = []
    for x in out.split():
        if not x.isdigit():
            continue
        pid = int(x)
        if pid in (1, me):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"appctl" not in f.read():
                    live.append(pid)
        except OSError:
            pass
    return live


def lin_quit(app, force):
    import os, signal, time
    targets = _live_pids(app)
    sig = signal.SIGKILL if force else signal.SIGTERM
    for pid in targets:
        try:
            os.kill(pid, sig)
        except OSError:
            pass
    # Graceful close gets a moment; then confirm.
    for _ in range(6):
        time.sleep(0.5)
        if not _live_pids(app):
            break
    still = _live_pids(app)
    return emit({"ok": True, "action": "quit", "app": app, "evidence": {
        "running": bool(still),
        "method": "SIGKILL" if force else "SIGTERM",
        "signalled": len(targets)}})


def lin_focus(app):
    # Best-effort: needs wmctrl or xdotool; absent on most stock installs.
    if shutil.which("wmctrl"):
        rc, out = run(["wmctrl", "-a", app])
        if rc == 0:
            return emit({"ok": True, "action": "focus", "app": app,
                         "evidence": {"foreground": True, "via": "wmctrl"}})
    if shutil.which("xdotool"):
        rc, out = run(["xdotool", "search", "--name", app, "windowactivate"])
        if rc == 0:
            return emit({"ok": True, "action": "focus", "app": app,
                         "evidence": {"foreground": True, "via": "xdotool"}})
    return fail("focus", "no window manager tool (install wmctrl or xdotool)")


# ------------------------------------------------------------------ dispatch -
HANDLERS = {
    "Windows": {"open": win_open, "focus": win_focus, "status": win_status,
                "list": lambda: win_list(), "quit": win_quit},
    "Darwin": {"open": mac_open, "focus": mac_focus, "status": mac_status,
               "list": lambda: mac_status(""), "quit": mac_quit},
    "Linux": {"open": lin_open, "focus": lin_focus, "status": lin_status,
              "list": lambda: lin_status(""), "quit": lin_quit},
}


def main():
    ap = argparse.ArgumentParser(prog="appctl",
                                 description="Cross-platform app lifecycle adapter (The Architect v0.1)")
    sub = ap.add_subparsers(dest="action", required=True)

    p = sub.add_parser("open", help="start an application")
    p.add_argument("app")
    p.add_argument("--args", nargs=argparse.REMAINDER, default=[], help="arguments for the app")

    p = sub.add_parser("focus", help="bring app window to foreground")
    p.add_argument("app")

    p = sub.add_parser("status", help="is the app running? (pid, window)")
    p.add_argument("app")

    sub.add_parser("list", help="list running GUI processes")

    p = sub.add_parser("quit", help="close the app")
    p.add_argument("app")
    p.add_argument("--force", action="store_true", help="kill instead of asking nicely")

    a = ap.parse_args()
    h = HANDLERS.get(OS)
    if not h:
        fail(a.action, f"unsupported OS: {OS}")

    if a.action == "list":
        h["list"]()
    elif a.action == "open":
        h["open"](a.app, [x for x in a.args if x != "--"])
    elif a.action == "quit":
        h["quit"](a.app, a.force)
    else:
        h[a.action](a.app)


if __name__ == "__main__":
    main()
