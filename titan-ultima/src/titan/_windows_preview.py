"""Restore and foreground the Windows viewer belonging to a requested preview file."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


def _preview_window_api() -> tuple[Any, Any]:
    """Declare pointer-sized Win32 handles before calling from 64-bit Python."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "GetForegroundWindow": ([], wintypes.HWND),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": (
            [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
            ctypes.c_int,
        ),
        "IsIconic": ([wintypes.HWND], wintypes.BOOL),
        "ShowWindowAsync": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
        "GetWindowLongW": ([wintypes.HWND, ctypes.c_int], wintypes.LONG),
        "SetWindowPos": (
            [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.BOOL,
        ),
        "GetWindowThreadProcessId": (
            [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
            wintypes.DWORD,
        ),
        "AttachThreadInput": (
            [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes = arguments
        function.restype = result
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetPackageFamilyName.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.UINT),
        wintypes.LPWSTR,
    ]
    kernel32.GetPackageFamilyName.restype = wintypes.LONG
    return user32, kernel32


def _preview_package_family(path: Path) -> str:
    """Read the selected file association's Store-app identity without changing it."""
    import winreg

    try:
        key_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{path.suffix}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\Application") as key:
            identity = winreg.QueryValueEx(key, "AppUserModelID")[0]
        return identity.split("!", 1)[0]
    except OSError:
        return ""


def _process_preview_package(kernel32: Any, process_id: int) -> str:
    """Inspect package identity using read-only process access and close the handle."""
    process = kernel32.OpenProcess(0x1000, False, process_id)
    if not process:
        return ""
    try:
        length = wintypes.UINT(256)
        text = ctypes.create_unicode_buffer(length.value)
        if kernel32.GetPackageFamilyName(process, ctypes.byref(length), text) == 0:
            return text.value
        return ""
    finally:
        kernel32.CloseHandle(process)


def _matching_preview_window(
    user32: Any, path: Path, *, kernel32: Any = None, package: str = ""
) -> int | None:
    """Find filename artwork or its configured Store viewer, including Photos hosts."""
    matches = []
    packaged = []
    process_packages: dict[int, str] = {}
    callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def belongs_to_package(window: int, _: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if process_id.value not in process_packages:
            process_packages[process_id.value] = _process_preview_package(
                kernel32, process_id.value
            )
        if process_packages[process_id.value] == package:
            packaged.append(parent[0])
            return False
        return True

    parent = [0]

    def inspect(window: int, _: int) -> bool:
        length = user32.GetWindowTextLengthW(window)
        if length:
            text = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(window, text, length + 1)
            title = text.value.casefold()
            if path.name.casefold() in title or (
                len(path.stem) >= 8 and path.stem.casefold() in title
            ):
                matches.append(window)
            elif package and kernel32 is not None:
                parent[0] = window
                if belongs_to_package(window, 0):
                    user32.EnumChildWindows(
                        window, callback_type(belongs_to_package), 0
                    )
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    if package:
        user32.EnumChildWindows.argtypes = [
            wintypes.HWND,
            callback_type,
            wintypes.LPARAM,
        ]
        user32.EnumChildWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback_type(inspect), 0)
    return matches[0] if matches else packaged[0] if packaged else None


def _activate_preview_window(user32: Any, kernel32: Any, window: int) -> bool:
    """Restore minimized artwork and request focus without leaving it always on top."""
    user32.ShowWindowAsync(window, 9 if user32.IsIconic(window) else 5)
    user32.SetWindowPos(window, 0, 0, 0, 0, 0, 0x43)  # show, retain size/position
    if user32.SetForegroundWindow(window):
        return True
    # Reused viewers can belong to another input thread. Release every successful
    # temporary attachment even when focus is denied or the viewer closes.
    current = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    threads = {
        user32.GetWindowThreadProcessId(window, None),
        user32.GetWindowThreadProcessId(foreground, None) if foreground else 0,
    } - {0, current}
    attached = []
    try:
        for thread in threads:
            if user32.AttachThreadInput(current, thread, True):
                attached.append(thread)
        focused = bool(user32.SetForegroundWindow(window))
        if not focused and not user32.GetWindowLongW(window, -20) & 0x8:
            # Windows can reject keyboard focus. Briefly raise above normal
            # windows, then immediately remove topmost so the preview is visible
            # without staying pinned over the user's other applications.
            try:
                user32.SetWindowPos(window, -1, 0, 0, 0, 0, 0x43)
            finally:
                user32.SetWindowPos(window, -2, 0, 0, 0, 0, 0x43)
        return focused
    finally:
        for thread in reversed(attached):
            user32.AttachThreadInput(current, thread, False)


def foreground_preview_window(path: Path, *, timeout: float = 3.0) -> bool:
    """Wait briefly for this preview's viewer, then restore and bring it forward."""
    user32, kernel32 = _preview_window_api()
    package = _preview_package_family(path)
    deadline = time.monotonic() + timeout
    while True:
        window = _matching_preview_window(
            user32, path, kernel32=kernel32, package=package
        )
        if window is not None:
            return _activate_preview_window(user32, kernel32, window)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
