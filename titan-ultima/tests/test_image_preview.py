"""Preview launch, reused viewer focus and Windows input-thread cleanup."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from titan import _image_preview as preview
from titan import _windows_preview as windows


def test_windows_launch_requests_restore_and_focus_every_time(tmp_path, monkeypatch):
    image = tmp_path / "preview.png"
    calls = []
    monkeypatch.setattr(preview.sys, "platform", "win32")
    monkeypatch.setattr(
        preview.os,
        "startfile",
        lambda path, **kwargs: calls.append((path, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        windows, "foreground_preview_window", lambda path: calls.append(path) or True
    )
    assert preview.open_preview(image)
    assert preview.open_preview(image)
    assert calls == [(str(image.resolve()), {"show_cmd": 9}), image.resolve()] * 2


def test_focus_failure_preserves_launch_success_and_prints_path(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(preview.sys, "platform", "win32")
    monkeypatch.setattr(
        preview.os, "startfile", lambda *args, **kwargs: None, raising=False
    )
    monkeypatch.setattr(windows, "foreground_preview_window", lambda path: False)
    assert preview.open_preview(tmp_path / "image.png")
    assert "Windows did not confirm viewer focus" in capsys.readouterr().out


def test_failed_windows_launch_does_not_attempt_focus(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("association unavailable")

    monkeypatch.setattr(preview.sys, "platform", "win32")
    monkeypatch.setattr(preview.os, "startfile", fail, raising=False)
    monkeypatch.setattr(
        windows, "foreground_preview_window", lambda path: pytest.fail("launch failed")
    )
    assert not preview.open_preview(tmp_path / "image.png")


def test_non_windows_keeps_browser_launch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(preview.sys, "platform", "linux")
    monkeypatch.setattr(
        preview.webbrowser, "open", lambda uri: calls.append(uri) or True
    )
    assert preview.open_preview(tmp_path / "image.png")
    assert calls == [(tmp_path / "image.png").as_uri()]


@pytest.mark.parametrize("minimized,show_command", [(True, 9), (False, 5)])
def test_reused_viewer_restored_and_raised_without_always_on_top(
    minimized, show_command
):
    calls = []
    api = SimpleNamespace(
        IsIconic=lambda window: minimized,
        ShowWindowAsync=lambda *args: calls.append(("show", args)),
        SetWindowPos=lambda *args: calls.append(("raise", args)),
        SetForegroundWindow=lambda window: True,
    )
    assert windows._activate_preview_window(api, None, 123)
    assert calls == [
        ("show", (123, show_command)),
        ("raise", (123, 0, 0, 0, 0, 0, 0x43)),
    ]


@pytest.mark.parametrize("result", [True, False, RuntimeError("closed viewer")])
def test_temporary_input_threads_detached_even_on_focus_failure(result):
    attached = []
    attempts = []

    def focus(window):
        attempts.append(window)
        if len(attempts) == 1:
            return False
        if isinstance(result, Exception):
            raise result
        return result

    api = SimpleNamespace(
        IsIconic=lambda window: True,
        ShowWindowAsync=lambda *args: None,
        SetWindowPos=lambda *args: None,
        GetWindowLongW=lambda *args: 0,
        SetForegroundWindow=focus,
        GetForegroundWindow=lambda: 456,
        GetWindowThreadProcessId=lambda window, pid: {123: 2, 456: 3}[window],
        AttachThreadInput=lambda *args: attached.append(args) or True,
    )
    kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError):
            windows._activate_preview_window(api, kernel, 123)
    else:
        assert windows._activate_preview_window(api, kernel, 123) is result
    assert sorted(attached) == [
        (1, 2, False),
        (1, 2, True),
        (1, 3, False),
        (1, 3, True),
    ]


def test_denied_keyboard_focus_raises_viewer_without_leaving_it_topmost():
    positions = []
    api = SimpleNamespace(
        IsIconic=lambda window: False,
        ShowWindowAsync=lambda *args: None,
        SetWindowPos=lambda *args: positions.append(args[1]),
        SetForegroundWindow=lambda window: False,
        GetWindowLongW=lambda *args: 0,
        GetForegroundWindow=lambda: None,
        GetWindowThreadProcessId=lambda *args: 1,
    )
    assert not windows._activate_preview_window(
        api, SimpleNamespace(GetCurrentThreadId=lambda: 1), 123
    )
    assert positions == [0, -1, -2]


def test_matching_store_viewer_in_application_frame_ignores_other_apps(monkeypatch):
    import ctypes

    class Function:
        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args):
            return self.fn(*args)

    titles = {10: "Unrelated application", 20: "Photos", 30: "viewer child"}

    def copy_title(window, buffer, size):
        buffer.value = titles[window]

    def copy_pid(window, pointer):
        ctypes.cast(
            pointer, ctypes.POINTER(windows.wintypes.DWORD)
        ).contents.value = window
        return window

    api = SimpleNamespace(
        GetWindowTextLengthW=lambda window: len(titles[window]),
        GetWindowTextW=copy_title,
        GetWindowThreadProcessId=copy_pid,
        EnumWindows=Function(
            lambda callback, _: [callback(window, 0) for window in (10, 20)]
        ),
        EnumChildWindows=Function(
            lambda window, callback, _: callback(30, 0) if window == 20 else None
        ),
    )
    monkeypatch.setattr(
        windows,
        "_process_preview_package",
        lambda kernel, pid: "photos" if pid == 30 else "other",
    )
    assert (
        windows._matching_preview_window(
            api, Path("preview.png"), kernel32=object(), package="photos"
        )
        == 20
    )
    assert (
        windows._matching_preview_window(
            api, Path("preview.png"), kernel32=object(), package="missing"
        )
        is None
    )


def test_focus_waits_for_the_requested_viewer(monkeypatch):
    windows_found = iter([None, 123])
    calls = []
    monkeypatch.setattr(windows, "_preview_window_api", lambda: (None, None))
    monkeypatch.setattr(windows, "_preview_package_family", lambda path: "")
    monkeypatch.setattr(
        windows, "_matching_preview_window", lambda *args, **kwargs: next(windows_found)
    )
    monkeypatch.setattr(
        windows, "_activate_preview_window", lambda *args: calls.append(args[2]) or True
    )
    monkeypatch.setattr(windows.time, "sleep", lambda delay: None)
    assert windows.foreground_preview_window(Path("preview.png"))
    assert calls == [123]


def test_focus_timeout_does_not_raise_unrelated_windows(monkeypatch):
    monkeypatch.setattr(windows, "_preview_window_api", lambda: (None, None))
    monkeypatch.setattr(windows, "_preview_package_family", lambda path: "")
    monkeypatch.setattr(
        windows, "_matching_preview_window", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        windows,
        "_activate_preview_window",
        lambda *args: pytest.fail("no matching viewer"),
    )
    assert not windows.foreground_preview_window(Path("preview.png"), timeout=0)
