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
if OS == "Windows":
    import ctypes
    from ctypes import wintypes
    import time

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_QUERY_INFORMATION = 0x0400
    WM_CLOSE = 0x0010
    WM_SYSCOMMAND = 0x0112
    SC_CLOSE = 0xF060
    SW_RESTORE = 9
    SW_SHOW = 5
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _DESKTOPENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPWSTR, wintypes.LPARAM)

    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _user32.OpenDesktopW.restype = wintypes.HANDLE
    _user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _user32.OpenInputDesktop.restype = wintypes.HANDLE
    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, _WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumDesktopsW.argtypes = [wintypes.HANDLE, _DESKTOPENUMPROC, wintypes.LPARAM]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    _user32.SetThreadDesktop.restype = wintypes.BOOL
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.LockSetForegroundWindow.argtypes = [wintypes.UINT]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]

    def _win_attach_desktop():
        """Attach current thread to the active input desktop or Default desktop."""
        hdesk = _user32.OpenInputDesktop(0, False, 0x01FF)
        if not hdesk:
            hdesk = _user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            _user32.SetThreadDesktop(hdesk)
            return hdesk
        return None

    _win_attach_desktop()


def _ps(script):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _win_all_processes():
    """Return list of dicts: [{'pid': int, 'name': str}] for all running processes."""
    hSnap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if hSnap == -1 or hSnap == 0:
        return []
    pe = _PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    procs = []
    if _kernel32.Process32FirstW(hSnap, ctypes.byref(pe)):
        while True:
            procs.append({"pid": pe.th32ProcessID, "name": pe.szExeFile})
            if not _kernel32.Process32NextW(hSnap, ctypes.byref(pe)):
                break
    _kernel32.CloseHandle(hSnap)
    return procs


def _win_process_creation_time(pid):
    """Return process creation time as integer (FILETIME 64-bit), or 0 if inaccessible."""
    hProc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hProc:
        hProc = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if hProc:
        ft_create = wintypes.FILETIME()
        ft_exit = wintypes.FILETIME()
        ft_kernel = wintypes.FILETIME()
        ft_user = wintypes.FILETIME()
        if _kernel32.GetProcessTimes(
            hProc, ctypes.byref(ft_create), ctypes.byref(ft_exit),
            ctypes.byref(ft_kernel), ctypes.byref(ft_user)
        ):
            _kernel32.CloseHandle(hProc)
            return (ft_create.dwHighDateTime << 32) | ft_create.dwLowDateTime
        _kernel32.CloseHandle(hProc)
    return 0


def _win_visible_windows():
    """Return list of dicts: [{'hwnd': int, 'pid': int, 'title': str}] for visible titled windows."""
    windows = []
    h_winsta = _user32.GetProcessWindowStation()
    desktop_names = []

    def desk_cb(lpszDesktop, lparam):
        desktop_names.append(lpszDesktop)
        return 1

    _user32.EnumDesktopsW(h_winsta, _DESKTOPENUMPROC(desk_cb), 0)
    if not desktop_names:
        desktop_names = ["Default"]

    def make_cb(desk_windows):
        def wnd_cb(hwnd, lparam):
            if not _user32.IsWindowVisible(hwnd):
                return 1
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return 1
            buff = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            if not title:
                return 1
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            desk_windows.append({"hwnd": hwnd, "pid": pid.value, "title": title})
            return 1
        return _WNDENUMPROC(wnd_cb)

    for dname in desktop_names:
        h_desk = _user32.OpenDesktopW(dname, 0, False, 0x01FF)
        if h_desk:
            desk_windows = []
            cb = make_cb(desk_windows)
            _user32.EnumDesktopWindows(h_desk, cb, 0)
            _user32.CloseDesktop(h_desk)
            windows.extend(desk_windows)

    cb = make_cb(windows)
    _user32.EnumWindows(cb, 0)

    seen = set()
    dedup = []
    for w in windows:
        if w["hwnd"] not in seen:
            seen.add(w["hwnd"])
            dedup.append(w)
    return dedup


def _win_match_procs(app):
    """Find processes matching app name (case-insensitive, with/without .exe)."""
    target = app.lower()
    if target.endswith(".exe"):
        target = target[:-4]
    matches = []
    for p in _win_all_processes():
        pname = p["name"].lower()
        pbase = pname[:-4] if pname.endswith(".exe") else pname
        if (
            pbase == target
            or pbase.startswith(f"{target}64")
            or pbase.startswith(f"{target}32")
            or pbase.startswith(f"{target}-")
            or pbase.startswith(f"{target}_")
            or (len(target) >= 3 and pbase.startswith(target))
        ):
            matches.append(p)
    return matches


class _WinProcess:
    def __init__(self, pid, hProcess, hThread):
        self.pid = pid
        self.hProcess = hProcess
        self.hThread = hThread
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        code = wintypes.DWORD()
        if _kernel32.GetExitCodeProcess(self.hProcess, ctypes.byref(code)):
            if code.value != 259:  # STILL_ACTIVE
                self.returncode = code.value
                return self.returncode
        return None

    def close(self):
        if self.hProcess:
            _kernel32.CloseHandle(self.hProcess)
            self.hProcess = None
        if self.hThread:
            _kernel32.CloseHandle(self.hThread)
            self.hThread = None


def _win_spawn(cmd_list):
    """Spawn a process on the interactive desktop using CreateProcessW, with subprocess fallback."""
    binary = shutil.which(cmd_list[0]) or shutil.which(f"{cmd_list[0]}.exe") or cmd_list[0]
    full_cmd = [binary] + cmd_list[1:]
    cmd_str = subprocess.list2cmdline(full_cmd)

    hdesk = _user32.OpenInputDesktop(0, False, 0x01FF)
    desk_name = "WinSta0\\Default"
    if hdesk:
        buf = ctypes.create_unicode_buffer(256)
        if _user32.GetUserObjectInformationW(hdesk, 2, buf, 512, None) and buf.value:
            desk_name = f"WinSta0\\{buf.value}"
        _user32.CloseDesktop(hdesk)

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(_STARTUPINFOW)
    si.lpDesktop = desk_name
    pi = _PROCESS_INFORMATION()

    if _kernel32.CreateProcessW(None, cmd_str, None, None, False, 0, None, None, ctypes.byref(si), ctypes.byref(pi)):
        return _WinProcess(pi.dwProcessId, pi.hProcess, pi.hThread)

    return subprocess.Popen(
        full_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def win_open(app, args):
    _win_attach_desktop()
    initial_windows = {w["hwnd"] for w in _win_visible_windows()}
    initial_pids = {p["pid"] for p in _win_match_procs(app)}

    try:
        proc = _win_spawn([app] + args)
    except OSError as e:
        return fail("open", f"could not start '{app}'", detail=str(e))

    window_title = ""
    target_pid = proc.pid
    alive = True

    for _ in range(30):
        time.sleep(0.1)

        # 1. Direct PID window match
        for w in _win_visible_windows():
            if w["pid"] == proc.pid:
                window_title = w["title"]
                target_pid = proc.pid
                break
        if window_title:
            break

        # 2. Check for newly appeared window matching app or process
        curr_windows = _win_visible_windows()
        new_windows = [w for w in curr_windows if w["hwnd"] not in initial_windows]
        app_procs = _win_match_procs(app)
        app_pids = {p["pid"] for p in app_procs}
        app_lower = (app[:-4] if app.lower().endswith(".exe") else app).lower()

        for w in new_windows:
            if w["pid"] in app_pids or app_lower in w["title"].lower():
                window_title = w["title"]
                target_pid = w["pid"]
                break
        if window_title:
            break

        # 3. Check process exit
        poll_code = proc.poll()
        if poll_code is not None:
            if poll_code != 0:
                alive = False
                break

    if hasattr(proc, "close"):
        proc.close()

    if not alive:
        return fail("open", f"'{app}' exited immediately (code {proc.poll()})",
                    evidence={"pid": proc.pid})

    if not window_title and proc.poll() == 0:
        current_matches = _win_match_procs(app)
        new_pids = [m["pid"] for m in current_matches if m["pid"] not in initial_pids]
        if new_pids:
            target_pid = new_pids[0]
        elif current_matches:
            target_pid = current_matches[0]["pid"]
        else:
            return fail("open", f"'{app}' exited immediately (code 0)",
                        evidence={"pid": proc.pid})

    evidence = {"pid": target_pid, "verified": bool(window_title)}
    if window_title:
        evidence["window"] = window_title
    return emit({"ok": True, "action": "open", "app": app, "evidence": evidence})


def win_status(app):
    _win_attach_desktop()
    if app.isdigit():
        all_procs = {p["pid"]: p["name"] for p in _win_all_processes()}
        procs = [{"pid": int(app), "name": all_procs.get(int(app), "")}] if int(app) in all_procs else []
    else:
        procs = _win_match_procs(app)

    windows = _win_visible_windows()

    if not procs and not app.isdigit():
        app_lower = (app[:-4] if app.lower().endswith(".exe") else app).lower()
        matching_hwnds = [w for w in windows if app_lower in w["title"].lower()]
        if matching_hwnds:
            all_p = {p["pid"]: p["name"] for p in _win_all_processes()}
            procs = [{"pid": w["pid"], "name": all_p.get(w["pid"], app)} for w in matching_hwnds]

    if not procs:
        return emit({"ok": True, "action": "status", "app": app,
                     "evidence": {"running": False}})

    w_map = {}
    for w in windows:
        if w["pid"] not in w_map:
            w_map[w["pid"]] = w["title"]

    app_lower = (app[:-4] if app.lower().endswith(".exe") else app).lower()
    if not any(w_map.get(p["pid"]) for p in procs):
        for w in windows:
            if app_lower in w["title"].lower():
                w_map[procs[0]["pid"]] = w["title"]
                break

    proc_list = [
        {"pid": p["pid"], "name": p["name"], "window": w_map.get(p["pid"], "")}
        for p in procs
    ]
    return emit({"ok": True, "action": "status", "app": app, "evidence": {
        "running": True, "processes": proc_list}})


def win_list():
    windows = _win_visible_windows()
    all_procs = {p["pid"]: p["name"] for p in _win_all_processes()}
    results = []
    seen = set()
    for w in windows:
        pid = w["pid"]
        if pid in seen:
            continue
        seen.add(pid)
        results.append({
            "pid": pid,
            "name": all_procs.get(pid, ""),
            "window": w["title"],
        })
    emit({"ok": True, "action": "list", "evidence": {
        "count": len(results),
        "processes": results}})


def win_focus(app):
    _win_attach_desktop()
    windows = _win_visible_windows()

    candidates = []
    if app.isdigit():
        candidates = [w for w in windows if w["pid"] == int(app)]
    else:
        app_lower = (app[:-4] if app.lower().endswith(".exe") else app).lower()
        for w in windows:
            if app_lower in w["title"].lower():
                candidates.append(w)
        if not candidates:
            match_pids = {p["pid"] for p in _win_match_procs(app)}
            candidates = [w for w in windows if w["pid"] in match_pids]

    if not candidates:
        return fail("focus", f"no visible window for '{app}'")

    candidates.sort(key=lambda w: _win_process_creation_time(w["pid"]), reverse=True)
    target = candidates[0]
    target_hwnd = target["hwnd"]
    target_pid = target["pid"]
    target_title = target["title"]

    if _user32.IsIconic(target_hwnd):
        _user32.ShowWindow(target_hwnd, SW_RESTORE)
    else:
        _user32.ShowWindow(target_hwnd, SW_SHOW)

    fore_wnd = _user32.GetForegroundWindow()
    fore_tid = _user32.GetWindowThreadProcessId(fore_wnd, None)
    target_tid = _user32.GetWindowThreadProcessId(target_hwnd, None)
    cur_tid = _kernel32.GetCurrentThreadId()

    if fore_tid and fore_tid != cur_tid:
        _user32.AttachThreadInput(cur_tid, fore_tid, True)
    if target_tid and target_tid != cur_tid:
        _user32.AttachThreadInput(cur_tid, target_tid, True)

    _user32.LockSetForegroundWindow(2)  # LSFW_UNLOCK
    _user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
    _user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
    _user32.SetWindowPos(target_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    _user32.SetWindowPos(target_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    _user32.BringWindowToTop(target_hwnd)
    _user32.SetForegroundWindow(target_hwnd)

    if fore_tid and fore_tid != cur_tid:
        _user32.AttachThreadInput(cur_tid, fore_tid, False)
    if target_tid and target_tid != cur_tid:
        _user32.AttachThreadInput(cur_tid, target_tid, False)

    for _ in range(15):
        time.sleep(0.1)
        fg = _user32.GetForegroundWindow()
        if fg == target_hwnd or _user32.GetAncestor(fg, 2) == target_hwnd:
            return emit({"ok": True, "action": "focus", "app": app,
                         "evidence": {"foreground": True, "verified": True,
                                      "pid": target_pid, "window": target_title}})

    actual = _user32.GetForegroundWindow()
    return fail("focus", f"window did not come to foreground for '{app}'",
                evidence={"foreground": False,
                          "expected_hwnd": target_hwnd,
                          "actual_hwnd": actual,
                          "pid": target_pid,
                          "window": target_title})


def win_quit(app, force):
    _win_attach_desktop()
    if app.isdigit():
        pids = [int(app)]
        procs = [p for p in _win_all_processes() if p["pid"] == int(app)]
    else:
        app_lower = (app[:-4] if app.lower().endswith(".exe") else app).lower()
        windows = _win_visible_windows()
        title_windows = [w for w in windows if app_lower in w["title"].lower()]
        if title_windows:
            pids = list({w["pid"] for w in title_windows})
            all_procs = {p["pid"]: p["name"] for p in _win_all_processes()}
            procs = [{"pid": pid, "name": all_procs.get(pid, app)} for pid in pids]
        else:
            procs = _win_match_procs(app)
            pids = [p["pid"] for p in procs]

    if not procs:
        return emit({"ok": True, "action": "quit", "app": app,
                     "evidence": {"running": False, "method": "already-closed"}})

    if not force:
        windows = _win_visible_windows()
        target_hwnds = [w["hwnd"] for w in windows if w["pid"] in pids]
        for hwnd in target_hwnds:
            _user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0)
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        for _ in range(15):
            time.sleep(0.2)
            alive = [p for p in _win_all_processes() if p["pid"] in pids]
            if not alive:
                return emit({"ok": True, "action": "quit", "app": app,
                             "evidence": {"running": False, "method": "graceful"}})

        alive = [p for p in _win_all_processes() if p["pid"] in pids]
        return emit({"ok": True, "action": "quit", "app": app,
                     "evidence": {"running": bool(alive), "method": "graceful"}})

    for pid in pids:
        hProc = _kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if hProc:
            _kernel32.TerminateProcess(hProc, 1)
            _kernel32.CloseHandle(hProc)

    time.sleep(0.2)
    still_alive = [p for p in _win_all_processes() if p["pid"] in pids]
    return emit({"ok": True, "action": "quit", "app": app,
                 "evidence": {"running": bool(still_alive), "method": "force"}})


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
