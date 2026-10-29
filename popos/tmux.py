"""tmux: Popo's face in the status line and the cyan tab while popOS runs."""
import os
import re
import subprocess
from pathlib import Path


TAB_CYAN = "#00d7ff"  # the app's cyan (xterm 45)


def tmux_tab(on):
    """While popOS runs, its tmux tab wears the app's cyan instead of the theme's
    accent. Only that window, and only window-level options: unsetting them
    (on=False, when the app closes) gives the tab back its usual look."""
    pane = os.environ.get("TMUX_PANE")
    if not (os.environ.get("TMUX") and pane):
        return
    tmux = lambda *args: subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=2).stdout
    try:
        if not on:
            for option in ("window-status-current-format", "window-status-format"):
                tmux("set", "-wu", "-t", pane, option)
            return
        current = tmux("show", "-gv", "window-status-current-format").rstrip("\n")
        other = tmux("show", "-gv", "window-status-format").rstrip("\n")
        base = re.search(r"bg=(#[0-9a-fA-F]{6})", tmux("show", "-gv", "window-status-style"))
        # The theme's accent: the background the current tab uses that the bar itself doesn't
        accents = [c.lower() for c in re.findall(r"bg=(#[0-9a-fA-F]{6})", current)
                   if not base or c.lower() != base.group(1).lower()]
        if accents:
            current = re.sub(re.escape(max(set(accents), key=accents.count)), TAB_CYAN, current, flags=re.I)
        else:
            current = current.replace("#W", f"#[fg={TAB_CYAN}]#W", 1)
        other = other.replace("#W", f"#[fg={TAB_CYAN}]#W", 1)
        tmux("set", "-w", "-t", pane, "window-status-current-format", current)
        tmux("set", "-w", "-t", pane, "window-status-format", other)
    except (OSError, subprocess.SubprocessError):
        pass


FACE = "(^ᴗ^)"
# The tmux option the status line reads with #{@popos-status}. Its default
# (the bare face) is set by the tmux config, not here.
STATUS_OPTION = "@popos-status"


def status_face(unsaved):
    """Popo's face, glad as always, and ✎ while a draft is unsaved. Faces
    only, never titles: anyone can see the status line."""
    return FACE + " ✎" if unsaved else FACE


def unsaved_drafts(db_path):
    """Whether the notebook at db_path has unsaved drafts. Never creates a
    notebook that doesn't exist, and never fails: no answer is "no"."""
    try:
        path = Path(db_path).expanduser()
        drafts = path.with_name(path.stem + ".drafts")
        return drafts.is_dir() and any(drafts.glob("*.md"))
    except Exception:  # noqa: BLE001 - see docstring
        return False


def tmux_status(db_path):
    """One short line for a status bar that polls: `#(popos --tmux-status)`."""
    return status_face(unsaved_drafts(db_path))


def push_status(unsaved):
    """Write the face into the tmux server's @popos-status, so the status line
    shows it with #{@popos-status} instead of re-running a command every
    status-interval. Setting an option redraws every client's status line,
    so the change is on screen at once. With no tmux or no server running,
    nothing happens: the face is decoration, never a reason to fail."""
    try:
        subprocess.run(["tmux", "set", "-gq", STATUS_OPTION, status_face(unsaved)],
                       capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass
