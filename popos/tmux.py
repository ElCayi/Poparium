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


def tmux_status(db_path):
    """One short line for tmux's status bar: Popo's face, glad as always, and ✎
    while a draft is unsaved. Faces only, never titles: anyone can see it.

    Never creates a notebook that doesn't exist, and never fails: a status
    line that prints a traceback every 5 seconds would be worse than none.
    """
    try:
        face = "(^ᴗ^)"
        path = Path(db_path).expanduser()
        drafts = path.with_name(path.stem + ".drafts")
        if drafts.is_dir() and any(drafts.glob("*.md")):
            face += " ✎"
        return face
    except Exception:  # noqa: BLE001 - see docstring
        return "(^ᴗ^)"
