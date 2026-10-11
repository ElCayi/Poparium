"""Unfinished writing, kept on disk until it reaches the notebook."""
import os
from pathlib import Path


class Drafts:
    """Unfinished writing, kept next to the notebook until it reaches it.

    A draft is only deleted once its content is saved in the database (or
    deliberately thrown away), so closing the app, the tmux pane or the
    whole session at any moment loses nothing that was typed.
    """

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.folder.chmod(0o700)

    def path(self, name, suffix=".md"):
        return self.folder / f"{name}{suffix}"

    def autosave_path(self, name):
        """Where the editor copies every change, separate from the real file."""
        return self.path(name, ".autosave.md")

    def write(self, name, text, suffix=".md"):
        path = self.path(name, suffix)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def recover(self, name, suffix=".md"):
        """The newest unsaved text: the editor's autosave beats the last :w."""
        candidates = [self.autosave_path(name)] if suffix == ".md" else []
        for path in candidates + [self.path(name, suffix)]:
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def drop_autosave(self, name):
        self.autosave_path(name).unlink(missing_ok=True)

    def discard(self, name, suffix=".md"):
        self.path(name, suffix).unlink(missing_ok=True)
        if suffix == ".md":
            self.drop_autosave(name)

    def pending(self):
        """Names of unsaved documents ("nuevo", "acuerdo-7"), oldest first."""
        files = sorted(self.folder.glob("*.md"), key=lambda f: f.stat().st_mtime)
        return list(dict.fromkeys(f.name.split(".")[0] for f in files))
