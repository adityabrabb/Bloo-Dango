import os
import sys
import platform
import subprocess
import tempfile

_TITLE = "Bloo Dango says..."


def show_reminder(task_title):
    """Show a desktop notification using native OS commands.

    Cross-platform: Windows (VBS popup), macOS (osascript),
    Linux (notify-send). Falls back to plyer, then a message box.
    """
    system = platform.system()

    if system == "Windows":
        if _notify_windows(task_title):
            return
    elif system == "Darwin":
        if _notify_macos(task_title):
            return
    elif system == "Linux":
        if _notify_linux(task_title):
            return

    if _notify_plyer(task_title):
        return

    _notify_messagebox(task_title)


def _notify_windows(title):
    """Windows notification via VBScript — works from no-console
    PyInstaller builds with zero extra dependencies."""
    vbs_content = (
        'Set objShell = CreateObject("WScript.Shell")\n'
        f'objShell.Popup "{title}", 60, "{_TITLE}", 64\n'
    )
    try:
        fd, vbs_path = tempfile.mkstemp(suffix='.vbs', prefix='bloo_notif_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(vbs_content)
        subprocess.Popen(
            ["wscript.exe", vbs_path],
            creationflags=0x08000000,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _notify_macos(title):
    """macOS notification via osascript."""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             f'display notification "{title}" with title "{_TITLE}" sound name "default"'],
            timeout=10, capture_output=True, text=True
        )
        return r.returncode == 0
    except Exception:
        return False


def _notify_linux(title):
    """Linux notification via notify-send."""
    try:
        r = subprocess.run(
            ["notify-send", "--urgency=normal", "--icon=dialog-information",
             _TITLE, title],
            timeout=10, capture_output=True, text=True
        )
        return r.returncode == 0
    except Exception:
        return False


def _notify_plyer(title):
    """Plyer fallback."""
    try:
        from plyer import notification
        notification.notify(title=_TITLE, message=title,
                           app_name="Bloo Dango", timeout=8)
        return True
    except Exception:
        return False


def _notify_messagebox(title):
    """Last resort: message box (always works on Windows)."""
    try:
        if platform.system() == "Windows":
            vbs = (
                'Set objShell = CreateObject("WScript.Shell")\n'
                f'objShell.Popup "{title}", 0, "{_TITLE}", 64\n'
            )
            fd, vbs_path = tempfile.mkstemp(suffix='.vbs', prefix='bloo_mb_')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(vbs)
            subprocess.Popen(
                ["wscript.exe", vbs_path],
                creationflags=0x08000000,
            )
        else:
            print(f"{_TITLE} {title}")
    except Exception:
        print(f"{_TITLE} {title}")
