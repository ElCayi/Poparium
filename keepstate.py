#!/usr/bin/env python3
"""popOS, Personal Operating System: a tiny, private, dependency-free terminal notebook.

Run it as `popos` (the Nix package), or `python3 keepstate.py`, inside tmux or any UTF-8 terminal.
"""
from __future__ import annotations

import argparse
import base64
import curses
import datetime as dt
import difflib
import hashlib
import json
import locale
import os
import random
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import struct
import subprocess
import sys
import textwrap
import time
import zlib

APP = "popOS"
VERSION = "v0.1"
TAGLINE = "Personal Operating System"

# The Popo above the name: (frame, ms). Frames: 0 still, 1-2 breathing, 3
# eyes closed, 4 opening. He breathes slowly all the time, a movement small
# enough not to tire; the blink only comes now and then, sometimes double.
BREATH = [(0, 1400), (1, 450), (2, 700), (1, 450)]
LOGO_TIMELINE = (BREATH * 4 + [(3, 140), (4, 90)] + BREATH * 3
                 + [(3, 140), (0, 160), (3, 140), (4, 90)])
LOGO_CYCLE = sum(ms for _, ms in LOGO_TIMELINE)


# kitty's graphics protocol, Unicode placeholder method: the image is sent once,
# then each cell of its area holds U+10EEEE plus two combining marks (row,
# column), coloured with the image id. It is plain text to curses and tmux, so
# it survives redraws and tmux places it right; kitty paints the image there.
KITTY_PLACEHOLDER = "\U0010EEEE"
# First entries of kitty's rowcolumn-diacritics.txt: mark n means row/column n
KITTY_DIACRITICS = [0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
                    0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357]
# Ids under 256 can be given as a 256-colour foreground index
KITTY_LOGO_IDS = range(241, 246)


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


def kitty_graphics():
    """Whether the terminal at the far end is kitty, and tmux (if any) lets its escapes through.

    POPOS_GRAPHICS=0/1 overrides the guess.
    """
    forced = os.environ.get("POPOS_GRAPHICS")
    if forced in ("0", "1"):
        return forced == "1"
    if os.environ.get("TMUX"):
        try:
            out = subprocess.run(["tmux", "display", "-p", "#{client_termname} #{allow-passthrough}"],
                                 capture_output=True, text=True, timeout=2).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return False
        return len(out) == 2 and "kitty" in out[0] and out[1] in ("on", "all")
    return "kitty" in os.environ.get("TERM", "") or bool(os.environ.get("KITTY_WINDOW_ID"))


def kitty_escape(keys, payload=""):
    """One graphics command, wrapped for tmux's passthrough when inside tmux."""
    command = f"\x1b_G{keys};{payload}\x1b\\" if payload else f"\x1b_G{keys}\x1b\\"
    if os.environ.get("TMUX"):
        command = "\x1bPtmux;" + command.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return command


def kitty_upload(image_id, png_base64, cols, rows):
    """Send a PNG and give it a virtual placement of cols x rows cells, in 4 KB chunks."""
    chunks = [png_base64[i:i + 4096] for i in range(0, len(png_base64), 4096)] or [""]
    out = []
    for n, chunk in enumerate(chunks):
        more = int(n < len(chunks) - 1)
        keys = f"a=T,U=1,f=100,i={image_id},c={cols},r={rows},C=1,q=2,m={more}" if n == 0 else f"m={more}"
        out.append(kitty_escape(keys, chunk))
    return "".join(out)


def kitty_placeholder_row(row, cols, high=0):
    """One row of placeholders. `high`, the image id's top byte, rides as a third mark."""
    mark = chr(KITTY_DIACRITICS[row])
    third = chr(KITTY_DIACRITICS[high]) if high else ""
    return "".join(KITTY_PLACEHOLDER + mark + chr(KITTY_DIACRITICS[col]) + third for col in range(cols))


def farm_image_id(belly, integrated, frame):
    """kitty image id of a meadow Popo: top byte 11-15 by belly, low byte by frame."""
    return ((11 + belly) << 24) | (100 + frame + 5 * integrated)


def popo_png(rgba, frame, belly=1.0, stretch=1.0, zoom=4):
    """One logo frame as a PNG (base64), zoomed and, as he grows, wider or taller."""
    w, h = rgba["size"]
    out_w, out_h = round(w * zoom * belly), round(h * zoom * stretch)
    return base64.b64encode(png_bytes(out_w, out_h, scale_rgba(rgba["frames"][frame], w, h, out_w, out_h))).decode("ascii")


def logo_frame(now_ms):
    """Which frame shows at this moment, and how many ms until the next one."""
    t = now_ms % LOGO_CYCLE
    for frame, ms in LOGO_TIMELINE:
        if t < ms:
            return frame, ms - t
        t -= ms
    return 0, 1


# The name drawn in block letters, 8 px tall: "pop" in Popo's cream, "OS" in
# the app's cyan. Each letter: (color, 8 rows); "#" is a pixel.
WORDMARK = [
    ("cream", ["....", "....", "###.", "#..#", "#..#", "###.", "#...", "#..."]),
    ("cream", ["....", "....", ".##.", "#..#", "#..#", ".##.", "....", "...."]),
    ("cream", ["....", "....", "###.", "#..#", "#..#", "###.", "#...", "#..."]),
    ("a", [".###.", "#...#", "#...#", "#...#", "#...#", ".###.", ".....", "....."]),
    ("a", [".###", "#...", ".##.", "...#", "...#", "###.", "....", "...."]),
]


def wordmark_cells():
    """The wordmark as 4 rows of (char, color) half-block cells, one column gap between letters."""
    rows = []
    for y in range(0, 8, 2):
        row = []
        for i, (color, glyph) in enumerate(WORDMARK):
            for top, bottom in zip(glyph[y], glyph[y + 1]):
                char = {("#", "#"): "█", ("#", "."): "▀", (".", "#"): "▄"}.get((top, bottom), " ")
                row.append((char, color))
            if i < len(WORDMARK) - 1:
                row.append((" ", color))
        rows.append(row)
    return rows
POPO_FILE = Path(__file__).resolve().parent / "assets" / "popo.json"
TABS = ["OVERVIEW", "ACUERDOS", "CALENDARIO", "BITÁCORA", "REVIEW", "POPARIUM"]
# A commitment is a title (required), a pinned note (optional: what to see at
# a glance in its page) and free Markdown text. No fixed sections: writing
# costs, and a two-line conclusion shouldn't have to cross ten empty headings.
TEXT_FIELDS = ["title", "pinned", "body"]
FIELD_HEADINGS = {"title": "TITLE", "pinned": "NOTA", "body": "TEXTO"}
# Sections offered on demand (Ctrl+G in the editor): plain Markdown once
# inserted, to rename, move or delete. WHY first: the reasons are what keep a
# decision from being argued again from scratch
SUGGESTIONS = [
    ("Por qué me importa", "qué hay en juego para mí"),
    ("Contexto", "qué ocurrió y en qué circunstancias"),
    ("Impacto", "qué consecuencias tuvo y a quién afectó"),
    ("Perspectivas", "argumentos, objeciones y desacuerdos"),
    ("Conclusiones", "qué hemos comprendido o decidido"),
    ("Compromiso", "qué conducta quiero mantener"),
    ("Límites y excepciones", "cuándo se aplica y qué matices tiene"),
    ("Desencadenantes", "qué situaciones lo activan"),
    ("Comprobación", "cómo reconocer que funciona"),
    ("Recuperación", "qué hacer si aparecen dificultades"),
]
# Before 0.3 a commitment had fixed sections. Their columns stay (nothing is
# ever dropped); their text became the free text, each under its heading, and
# COMMITMENT the pinned note
LEGACY_SECTIONS = [("context", "Contexto"), ("reason", "Por qué me importa"), ("reasoning", "Razonamiento"),
                   ("exceptions", "Límites y excepciones"), ("plan", "Próxima acción"), ("cue", "Desencadenantes"),
                   ("success", "Comprobación"), ("recovery", "Recuperación")]
LEGACY_COLUMNS = ["tracking", "agreement"] + [column for column, _ in LEGACY_SECTIONS]
LEGACY_TRACKING = {"periodic": "periódico", "once": "puntual", "reflective": "reflexivo"}


def legacy_document(old):
    """title/pinned/body for a commitment (or a version snapshot) in the old sections."""
    get = lambda key: (old.get(key) if isinstance(old, dict) else old[key] if key in old.keys() else "") or ""
    parts = [f"## {name}\n\n{get(column).strip()}" for column, name in LEGACY_SECTIONS if get(column).strip()]
    if get("tracking") in LEGACY_TRACKING:
        parts.insert(0, f"## Seguimiento\n\n{LEGACY_TRACKING[get('tracking')]}")
    return {"title": get("title"), "pinned": get("agreement").strip(), "body": "\n\n".join(parts)}


# The notebook keeps the folder it was born in (the app was called keepstate);
# POPOS_DB, or the older KEEPSTATE_DB, points to another one
DEFAULT_DB = Path(os.environ.get("POPOS_DB") or os.environ.get("KEEPSTATE_DB")
                  or "~/.local/share/keepstate/keepstate.db").expanduser()


def stamp():
    # Siempre en UTC: el texto ISO se ordena bien aunque cambie la hora (verano/invierno)
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def display_date(value):
    try:
        return dt.datetime.fromisoformat(value).astimezone().strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return str(value)[:16]


def short_hash(*parts):
    """Seven hex chars, like `git log --oneline`. Same content, same hash."""
    return hashlib.sha1("\n".join(map(str, parts)).encode("utf-8")).hexdigest()[:7]


def init_hash(c):
    return short_hash("init", c["id"], c["created_at"])


def review_hash(r):
    return short_hash("review", r["id"], r["commitment_id"], r["learned"], r["adjustment"], r["created_at"])


def version_hash(v):
    return short_hash("version", v["id"], v["commitment_id"], v["note"], v["created_at"])


def version_label(index):
    """v1.0 is the commitment as first written; each edit adds one."""
    return f"v1.{index}"


TITLE_HEADING = "## TITLE · el nombre del acuerdo (obligatorio)"
NOTE_HEADING = "## NOTA · opcional: lo que verás en la ficha (borra la sección si no la quieres)"
LEGACY_TITLE = re.compile(r"^#(?!#)\s*(.*)$")  # drafts from before TITLE was a section
HEADING = re.compile(r"^##\s+([A-Z][A-Z ]*?)\s*(?:·.*)?$")


def glance(c, lines=3, width=60):
    """What to show of a commitment at a glance: its pinned note, or the first
    lines of its text (without headings) when it has none. (text, is_note)."""
    if c["pinned"]:
        return c["pinned"], True
    plain = [line.strip() for line in (c["body"] or "").splitlines() if line.strip() and not line.startswith("#")]
    return " ".join(plain)[:lines * width], False


def to_markdown(c):
    """The commitment as the document opened in the editor: TITLE, NOTA, a rule,
    and free text under it."""
    return "\n".join([TITLE_HEADING, "", c.get("title") or "", "", NOTE_HEADING, "", c.get("pinned") or "",
                      "", "---", "", c.get("body") or ""]).rstrip() + "\n"


def from_markdown(text):
    """Back from the editor: the first line under TITLE is the title, what is under
    NOTA up to the rule (or the next heading) is the pinned note, the rest is free text.

    Deleting the NOTA section is fine (no note); any other heading is just text.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    title, legacy_title, pinned, body = "", "", [], []
    mode = None  # None (before TITLE), "title", "pinned", "body"
    for line in text.splitlines():
        match = HEADING.match(line)
        key = match.group(1) if match else None
        if key == "TITLE":
            mode = "title"
            continue
        if key in ("NOTA", "NOTE"):
            mode = "pinned"
            continue
        if mode == "title":
            if not title and line.strip():
                title = line.strip().lstrip("#").strip()
                continue
            if not line.strip():
                continue
            mode = "body"
            if line.strip() == "---":
                continue
        elif mode == "pinned":
            if line.strip() == "---":
                mode = "body"
                continue
            if line.startswith("#"):
                mode = "body"
            else:
                pinned.append(line)
                continue
        elif mode is None:
            if line.startswith("> popOS"):  # the help line of older drafts
                continue
            if not legacy_title and LEGACY_TITLE.match(line):
                legacy_title = LEGACY_TITLE.match(line).group(1).strip()
                continue
        body.append(line)
    return {"title": title or legacy_title, "pinned": "\n".join(pinned).strip(), "body": "\n".join(body).strip()}


def version_diff(old, new):
    """What changed between two snapshots, per section, as unified diff lines."""
    out = []
    for column in TEXT_FIELDS:
        before, after = old.get(column) or "", new.get(column) or ""
        if before == after:
            continue
        out.append(f"## {FIELD_HEADINGS[column]}")
        out += [line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1)
                if not line.startswith(("---", "+++"))]
    return out


def commit_graph(events):
    """Lay out events (newest first) as `git log --graph` lanes, one per commitment.

    Returns (top, below, head, event) per event: top/below are lists of
    (char, commitment_id) cells for the commit row and the row under it;
    head marks the commitment's newest commit, where its lane starts.
    """
    oldest = {}
    for i, e in enumerate(events):
        oldest[e["commitment_id"]] = i
    columns, rows = [], []
    for i, e in enumerate(events):
        cid = e["commitment_id"]
        head = cid not in columns
        if head:
            if None in columns:
                columns[columns.index(None)] = cid
            else:
                columns.append(cid)
        top = [("*" if c == cid else "│" if c is not None else " ", c) for c in columns]
        if i == oldest[cid]:
            columns[columns.index(cid)] = None
            while columns and columns[-1] is None:
                columns.pop()
        below = [("│" if c is not None else " ", c) for c in columns]
        rows.append((top, below, head, e))
    return rows


def load_popo(path=POPO_FILE):
    """Popo's frames from tools/popo_assets.py output; None when the art is missing."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        states = {name: [zlib.decompress(base64.b64decode(f)) for f in frames]
                  for name, frames in data["states"].items()}
    except (OSError, ValueError, KeyError, zlib.error):
        return None
    # logo: rows of [char, fg, bg] half-block cells, None where empty
    # logo_rgba: the same frames as raw pixels, to make PNGs for kitty at any width
    rgba = data.get("logo_rgba")
    if rgba:
        rgba = {"size": tuple(rgba["size"]), "frames": [zlib.decompress(base64.b64decode(f)) for f in rgba["frames"]]}
    return {"size": data["size"], "ms": data["ms"], "states": states, "logo": data.get("logo"), "logo_rgba": rgba}


def scale_rgba(raw, w, h, out_w, out_h):
    """Nearest-neighbour resize of raw RGBA: pixel art stays crisp, even stretched."""
    cols = [min(w - 1, x * w // out_w) for x in range(out_w)]
    lines = {}
    rows = []
    for oy in range(out_h):
        sy = min(h - 1, oy * h // out_h)
        if sy not in lines:
            line = raw[sy * w * 4:(sy + 1) * w * 4]
            lines[sy] = b"".join(line[c * 4:c * 4 + 4] for c in cols)
        rows.append(lines[sy])
    return rows


def png_bytes(width, height, rows):
    """A minimal RGBA PNG from rows of raw pixels (no imaging library needed)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# Popo is always glad to be there: what he does never reacts to the last thing
# logged (an obstacle is not a sad Popo, a success is not a prouder one). What
# changes is his belly, which grows with every experience, and the stretch he
# gets when a commitment becomes INTEGRADO.
PLAYFUL = ["idle", "hello", "think", "reading", "coding", "comfort"]
STATUS_NAMES = {"active": "activo", "integrated": "integrado", "archived": "archivado"}
GROWTH = [0, 3, 8, 15, 25]  # experiences for each belly size
BELLY = [1.0, 1.08, 1.16, 1.24, 1.32]  # how much wider he gets
STRETCH = 1.18  # how much taller an INTEGRADO Popo is
# The farm: a meadow where the Popos wander on their own. A first sketch: the
# rules are simple on purpose, to grow from
FARM_TICK = 0.2  # seconds per step of the herd
FARM_POPO = (12, 6)  # a Popo's base size in the meadow, in cells


def growth(experiences):
    """Belly size 0-4 for a number of experiences."""
    return max(i for i, need in enumerate(GROWTH) if experiences >= need)


def popo_look(commitment, experiences):
    """(animation, words under him) for a commitment's Popo."""
    if commitment["status"] == "archived":
        return "sleep", "descansando"
    if commitment["status"] == "integrated":
        return "hello", "integrado ♡"
    words = f"{experiences} experiencia" + ("" if experiences == 1 else "s")
    return PLAYFUL[commitment["id"] % len(PLAYFUL)], words


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


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS commitments (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT '',
                cue TEXT NOT NULL DEFAULT '',
                success TEXT NOT NULL DEFAULT '',
                recovery TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                kind TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                learned TEXT NOT NULL,
                adjustment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_journal_time ON journal(created_at DESC);
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                note TEXT NOT NULL DEFAULT '',
                snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        # Older notebooks: add the columns they lack, empty
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(commitments)")}
        missing = [column for column in TEXT_FIELDS + LEGACY_COLUMNS if column not in have]
        if missing and self.db.execute("SELECT COUNT(*) FROM commitments").fetchone()[0]:
            self.backup("pre-0.2" if "context" in missing else "pre-0.3")
        for column in missing:
            self.db.execute(f"ALTER TABLE commitments ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        # 0.3: the fixed sections become free text, once (user_version marks it done)
        if self.db.execute("PRAGMA user_version").fetchone()[0] < 3:
            for c in self.db.execute("SELECT * FROM commitments WHERE pinned='' AND body=''").fetchall():
                doc = legacy_document(c)
                self.db.execute("UPDATE commitments SET pinned=?, body=? WHERE id=?", (doc["pinned"], doc["body"], c["id"]))
            self.db.execute("PRAGMA user_version = 3")
        # ...and give each older commitment its v1.0
        for c in self.db.execute("""SELECT * FROM commitments WHERE id NOT IN
                (SELECT commitment_id FROM versions)""").fetchall():
            self._snapshot(c["id"], "Acuerdo inicial", c["created_at"])
        # An obstacle can get, later, how it was put right
        journal = {r["name"] for r in self.db.execute("PRAGMA table_info(journal)")}
        for column in ("repair", "repaired_at"):
            if column not in journal:
                self.db.execute(f"ALTER TABLE journal ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        # Every entry and review remembers the version of its commitment in force
        # when it happened, so a change of strategy can be judged by what followed
        for table in ("journal", "reviews"):
            if "version_id" not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN version_id INTEGER REFERENCES versions(id)")
                self.db.execute(f"""UPDATE {table} SET version_id = (SELECT v.id FROM versions v
                    WHERE v.commitment_id = {table}.commitment_id AND v.created_at <= {table}.created_at
                    ORDER BY v.created_at DESC, v.id DESC LIMIT 1)""")
        self.db.commit()

    def backup(self, tag):
        """A private copy of the whole notebook next to it, before changing its format."""
        target = self.path.with_name(f"{self.path.stem}.{tag}.db")
        if not target.exists():
            fd = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            with sqlite3.connect(target) as copy:
                self.db.backup(copy)
        return target

    def _snapshot(self, identifier, note, when):
        row = self.db.execute("SELECT * FROM commitments WHERE id=?", (identifier,)).fetchone()
        snapshot = json.dumps({k: row[k] for k in TEXT_FIELDS}, ensure_ascii=False)
        self.db.execute("INSERT INTO versions (commitment_id, note, snapshot, created_at) VALUES (?, ?, ?, ?)",
                        (identifier, note, snapshot, when))

    def create(self, title, pinned="", body="", **legacy):
        """A new commitment. Old-style sections (reason=..., plan=...) still work: they
        become free text, as in a migrated notebook."""
        now = stamp()
        if legacy and not body:
            doc = legacy_document({"title": title, **legacy})
            body, pinned = doc["body"], pinned or doc["pinned"]
        # reason is NOT NULL without a default in notebooks from before 0.3
        values = {"title": title, "pinned": pinned, "body": body, "reason": ""}
        with self.db:
            identifier = self.db.execute(
                f"INSERT INTO commitments ({', '.join(values)}, status, created_at, updated_at) "
                f"VALUES ({', '.join('?' * len(values))}, 'active', ?, ?)",
                (*values.values(), now, now)).lastrowid
            self._snapshot(identifier, "Acuerdo inicial", now)
        return identifier

    def revise(self, identifier, fields, note):
        """Save an edit as a new version; returns its label, or None if nothing changed."""
        current = self.db.execute("SELECT * FROM commitments WHERE id=?", (identifier,)).fetchone()
        changed = {k: fields[k] for k in TEXT_FIELDS if k in fields and fields[k] != current[k]}
        if not changed:
            return None
        now = stamp()
        with self.db:
            self.db.execute("UPDATE commitments SET " + ", ".join(f"{k}=?" for k in changed) + ", updated_at=? WHERE id=?",
                            (*changed.values(), now, identifier))
            self._snapshot(identifier, note, now)
        return version_label(len(self.versions(identifier)) - 1)

    def versions(self, identifier):
        """Oldest first, each with its snapshot decoded; old-style snapshots read as
        the new document, so a diff across 0.3 shows only what really changed."""
        out = []
        for r in self.db.execute("SELECT * FROM versions WHERE commitment_id=? ORDER BY created_at, id", (identifier,)):
            snapshot = json.loads(r["snapshot"])
            if "body" not in snapshot:
                snapshot = legacy_document(snapshot)
            out.append(dict(r, snapshot=snapshot))
        return out

    def update(self, identifier, **fields):
        allowed = (*TEXT_FIELDS, *LEGACY_COLUMNS, "status")
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = stamp()
        sql = "UPDATE commitments SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?"
        with self.db:
            self.db.execute(sql, (*fields.values(), identifier))

    def active(self):
        """What is still being lived: active and integrated, not archived."""
        return self.db.execute("SELECT * FROM commitments WHERE status != 'archived' ORDER BY id DESC").fetchall()

    def all_commitments(self):
        return self.db.execute("SELECT * FROM commitments ORDER BY id DESC").fetchall()

    def entries(self, limit=100):
        return self.db.execute("""SELECT j.*, c.title FROM journal j
            JOIN commitments c ON c.id = j.commitment_id
            ORDER BY j.created_at DESC, j.id DESC LIMIT ?""", (limit,)).fetchall()

    def delete_entry(self, entry_id):
        """Remove one log entry; returns what restore() needs to put it back."""
        return self._remove([("journal", "id", entry_id)])

    def delete_commitment(self, identifier):
        """Remove a commitment with its log, reviews and versions; returns them for restore()."""
        return self._remove([("journal", "commitment_id", identifier), ("reviews", "commitment_id", identifier),
                             ("versions", "commitment_id", identifier), ("commitments", "id", identifier)])

    def _remove(self, where):
        removed = []
        with self.db:
            # Children before their commitment: foreign keys are on
            for table, column, value in where:
                rows = [dict(r) for r in self.db.execute(f"SELECT * FROM {table} WHERE {column}=?", (value,))]
                self.db.execute(f"DELETE FROM {table} WHERE {column}=?", (value,))
                removed.append((table, rows))
        return removed

    def restore(self, removed):
        """Undo a delete: every row comes back with its own id and dates."""
        with self.db:
            for table, rows in reversed(removed):
                for row in rows:
                    self.db.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                    tuple(row.values()))

    def version_in_force(self, identifier, when=None):
        """The version of a commitment that was current at `when` (default: now)."""
        row = self.db.execute("""SELECT id FROM versions WHERE commitment_id=? AND created_at <= ?
            ORDER BY created_at DESC, id DESC LIMIT 1""", (identifier, when or stamp())).fetchone()
        if not row:  # logged for a day before the commitment existed: its first version
            row = self.db.execute("SELECT MIN(id) id FROM versions WHERE commitment_id=?", (identifier,)).fetchone()
        return row["id"] if row else None

    def log(self, identifier, kind, note="", when=None):
        """A new entry; `when` (UTC ISO) for something remembered from another day."""
        when = when or stamp()
        with self.db:
            self.db.execute("INSERT INTO journal (commitment_id, kind, note, created_at, version_id) VALUES (?, ?, ?, ?, ?)",
                            (identifier, kind, note, when, self.version_in_force(identifier, when)))

    def repair(self, entry_id, text):
        with self.db:
            self.db.execute("UPDATE journal SET repair=?, repaired_at=? WHERE id=?",
                            (text, stamp() if text else "", entry_id))

    def review(self, identifier, learned, adjustment=""):
        now = stamp()
        with self.db:
            rowid = self.db.execute("INSERT INTO reviews (commitment_id, learned, adjustment, created_at, version_id) "
                                    "VALUES (?, ?, ?, ?, ?)",
                                    (identifier, learned, adjustment, now, self.version_in_force(identifier))).lastrowid
        return review_hash({"id": rowid, "commitment_id": identifier, "learned": learned,
                            "adjustment": adjustment, "created_at": now})

    def latest_reviews(self, limit=100):
        return self.db.execute("""SELECT r.*, c.title FROM reviews r
            JOIN commitments c ON c.id = r.commitment_id
            ORDER BY r.created_at DESC, r.id DESC LIMIT ?""", (limit,)).fetchall()

    def history(self):
        """Each commitment's creation, its edits and its reviews as commits, newest first."""
        events = []
        for c in self.all_commitments():
            events.append({"kind": "init", "hash": init_hash(c), "commitment_id": c["id"],
                           "title": c["title"], "created_at": c["created_at"], "order": (0, c["id"]),
                           "message": "init · " + c["title"], "detail": glance(c)[0]})
        for c in self.all_commitments():
            for index, v in enumerate(self.versions(c["id"])[1:], start=1):
                events.append({"kind": "version", "hash": version_hash(v), "commitment_id": c["id"],
                               "title": c["title"], "created_at": v["created_at"], "order": (2, v["id"]),
                               "message": f"{version_label(index)} · {v['note']}", "detail": ""})
        for r in self.latest_reviews(limit=-1):
            events.append({"kind": "review", "hash": review_hash(r), "commitment_id": r["commitment_id"],
                           "title": r["title"], "created_at": r["created_at"], "order": (1, r["id"]),
                           "message": r["learned"], "detail": r["adjustment"]})
        events.sort(key=lambda e: (e["created_at"], e["order"]), reverse=True)
        return events

    def events_between(self, first_day, last_day):
        """Everything that happened from first_day to last_day (local dates, both included).

        Log entries, reviews, new commitments and their edits, oldest first,
        each with the local date it belongs to.
        """
        start = dt.datetime.combine(first_day, dt.time()).astimezone().astimezone(dt.timezone.utc)
        end = dt.datetime.combine(last_day + dt.timedelta(days=1), dt.time()).astimezone().astimezone(dt.timezone.utc)
        bounds = (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
        rows = self.db.execute("""
            SELECT j.kind, j.note AS note, j.created_at, c.title, c.id AS commitment_id, j.repair FROM journal j
                JOIN commitments c ON c.id = j.commitment_id WHERE j.created_at >= ? AND j.created_at < ?
            UNION ALL SELECT 'review', r.learned, r.created_at, c.title, c.id, '' FROM reviews r
                JOIN commitments c ON c.id = r.commitment_id WHERE r.created_at >= ? AND r.created_at < ?
            UNION ALL SELECT CASE WHEN v.id = (SELECT MIN(id) FROM versions WHERE commitment_id = v.commitment_id)
                    THEN 'init' ELSE 'version' END, v.note, v.created_at, c.title, c.id, '' FROM versions v
                JOIN commitments c ON c.id = v.commitment_id WHERE v.created_at >= ? AND v.created_at < ?
            ORDER BY 3""", bounds * 3).fetchall()
        return [dict(r, day=dt.datetime.fromisoformat(r["created_at"]).astimezone().date()) for r in rows]

    def last_events(self):
        """{commitment_id: (kind, created_at)} of the newest log entry, review or edit."""
        rows = self.db.execute("""SELECT commitment_id, kind, created_at FROM (
                SELECT commitment_id, kind, created_at, 0 src, id FROM journal
                UNION ALL SELECT commitment_id, 'review', created_at, 1, id FROM reviews
                UNION ALL SELECT commitment_id, 'version', created_at, 2, id FROM versions
                    WHERE id NOT IN (SELECT MIN(id) FROM versions GROUP BY commitment_id))
            ORDER BY created_at, src, id""").fetchall()
        return {r["commitment_id"]: (r["kind"], r["created_at"]) for r in rows}

    def experience_counts(self):
        """{commitment_id: {kind: n}} over all time, reviews included. A commitment
        doesn't expire, so nothing here is a "last 7 days" window."""
        counts = {}
        for r in self.db.execute("""SELECT commitment_id, kind, COUNT(*) n FROM journal GROUP BY commitment_id, kind
                UNION ALL SELECT commitment_id, 'review', COUNT(*) FROM reviews GROUP BY commitment_id"""):
            counts.setdefault(r["commitment_id"], {})[r["kind"]] = r["n"]
        return counts

    def recent(self, limit=8, commitment_id=None):
        """The newest log entries and reviews, all commitments or one."""
        where, args = ("WHERE c.id = ?", (commitment_id, commitment_id)) if commitment_id else ("", ())
        return self.db.execute(f"""SELECT * FROM (
                SELECT j.id, j.kind, j.note, j.repair, j.created_at, c.title, c.id cid FROM journal j
                    JOIN commitments c ON c.id = j.commitment_id {where}
                UNION ALL SELECT r.id, 'review', r.learned, '', r.created_at, c.title, c.id FROM reviews r
                    JOIN commitments c ON c.id = r.commitment_id {where})
            ORDER BY created_at DESC, id DESC LIMIT ?""", (*args, limit)).fetchall()

    def export(self):
        out = self.path.parent / ("popos-export-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md")
        lines = [f"# {APP} / copia de mi bitácora", "", "Documento personal. Los acuerdos son revisables, no verdades absolutas.", ""]
        for c in self.all_commitments():
            versions = self.versions(c["id"])
            lines.extend([f"## {c['title']}  (#{c['id']}, {version_label(len(versions) - 1)}, {c['status']})", ""])
            if c["pinned"]:
                lines.extend([f"> {line}" for line in c["pinned"].splitlines()] + [""])
            if c["body"]:
                # The free text's own headings, one level down
                lines.extend([("#" + line if line.startswith("#") else line) for line in c["body"].splitlines()] + [""])
            lines.extend(["### Historial del acuerdo", ""])
            for index, v in reversed(list(enumerate(versions))):
                lines.append(f"- `{version_hash(v)}` {version_label(index)} · {display_date(v['created_at'])} · {v['note']}")
            lines.extend(["", "### Avances y obstáculos", ""])
            for j in self.db.execute("SELECT * FROM journal WHERE commitment_id=? ORDER BY id", (c["id"],)):
                lines.append(f"- {display_date(j['created_at'])} · {j['kind']}: {j['note']}")
            lines.extend(["", "### Revisiones", ""])
            for r in self.db.execute("SELECT * FROM reviews WHERE commitment_id=? ORDER BY id", (c["id"],)):
                lines.append(f"- `{review_hash(r)}` {display_date(r['created_at'])} · Aprendí: {r['learned']} · Ajusto: {r['adjustment']}")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        out.chmod(0o600)
        return out

    def close(self):
        self.db.close()


# Colors: cyan, lavender, green, amber, muted, white, selected, border
COLOR = {"a": 1, "b": 2, "good": 3, "warm": 4, "dim": 5, "main": 6, "select": 7, "edge": 8}


def setup_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    palette = [
        (1, 45, -1), (2, 141, -1), (3, 84, -1), (4, 215, -1),
        # Selected text: 233, the grey ramp's near-black. Not 16: base16 themes
        # (Stylix) repaint 16-21 with their extra colours, and 16 becomes orange
        (5, 244, -1), (6, 255, -1), (7, 233, 45), (8, 60, -1),
    ] if curses.COLORS >= 256 else [
        (1, curses.COLOR_CYAN, -1), (2, curses.COLOR_MAGENTA, -1),
        (3, curses.COLOR_GREEN, -1), (4, curses.COLOR_YELLOW, -1),
        (5, curses.COLOR_BLUE, -1), (6, curses.COLOR_WHITE, -1),
        (7, curses.COLOR_BLACK, curses.COLOR_CYAN), (8, curses.COLOR_BLUE, -1),
    ]
    for ident, fg, bg in palette:
        try:
            curses.init_pair(ident, fg, bg)
        except curses.error:
            pass


LANE_COLORS = ("a", "b", "good", "warm")


def lane_style(commitment_id, bold=False):
    """Each commitment keeps the same lane color, like branches in a git GUI."""
    return style(LANE_COLORS[(commitment_id or 0) % len(LANE_COLORS)], bold)


def style(name, bold=False):
    attr = curses.color_pair(COLOR.get(name, 6)) if curses.has_colors() else 0
    # The selection is always bold: dark letters on cyan need the weight
    if bold or name == "select":
        attr |= curses.A_BOLD
    return attr


def put(win, y, x, message, attr=0, maxlen=None):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w or x < 0:
        return
    width = min(w - x - 1, maxlen if maxlen is not None else w)
    if width <= 0:
        return
    text = str(message).replace("\n", " ").replace("\t", "  ")
    try:
        win.addnstr(y, x, text, width, attr)
    except (curses.error, ValueError):
        pass


def rule(win, y, x, width):
    put(win, y, x, "─" * max(0, width), style("edge"), width)


def box(win, y, x, height, width, title="", title_attr=None, edge=None):
    """A rounded panel with its title on the top border.

    Returns the inside as (y, x, height, width), one column of padding on each side.
    """
    if height < 2 or width < 6:
        return y, x, 0, 0
    edge = style("edge") if edge is None else edge
    put(win, y, x, "╭" + "─" * (width - 2) + "╮", edge, width)
    for row in range(y + 1, y + height - 1):
        put(win, row, x, "│", edge)
        put(win, row, x + width - 1, "│", edge)
    put(win, y + height - 1, x, "╰" + "─" * (width - 2) + "╯", edge, width)
    if title:
        put(win, y, x + 2, f" {title} ", style("a", True) if title_attr is None else title_attr, width - 4)
    return y + 1, x + 2, height - 2, width - 4


def fit_figures(figures, width, gaps=(7, 4, 2)):
    """Lay out (n, name, short name, colour) figures so they never break their box.

    Tries the full names with a generous gap, then tighter, then the short
    names (EXP for EXPERIENCIAS...), and only then spreads them over more rows.
    Returns rows of (column, "07", name, colour).
    """
    for use_short in (False, True):
        for gap in gaps:
            cells = [(f"{n:02}", short if use_short else name, color) for n, name, short, color in figures]
            if sum(3 + len(name) for _, name, _ in cells) + gap * (len(cells) - 1) <= width:
                row, col = [], 0
                for number, name, color in cells:
                    row.append((col, number, name, color))
                    col += 3 + len(name) + gap
                return [row]
    rows, row, col = [], [], 0
    for n, _, short, color in figures:
        if row and col + 3 + len(short) > width:
            rows.append(row)
            row, col = [], 0
        row.append((col, f"{n:02}", short, color))
        col += 3 + len(short) + 2
    return rows + [row]


def draw_figures(win, y, x, rows):
    for r, row in enumerate(rows):
        for col, number, name, color in row:
            put(win, y + r, x + col, number, style(color, True))
            put(win, y + r, x + col + 3, name, style(color))


def wrap_lines(text, width):
    out = []
    for paragraph in (str(text or "—").split("\n")):
        out.extend(textwrap.wrap(paragraph, width=max(8, width), break_long_words=True) or [""])
    return out


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


def ask(screen, heading, prompt, default="", required=False, drafts=None):
    """Return a single-line UTF-8 value; None means cancelled.

    With drafts, every keystroke is kept on disk and comes back the next
    time this same question is asked, until it's answered or cancelled.
    """
    name = "linea-" + short_hash(heading, prompt)
    recovered = drafts.recover(name, ".txt") if drafts else None
    value = list(recovered if recovered is not None else default)
    if recovered is not None:
        heading += " · recuperado"
    cursor = len(value)
    scroll = 0
    curses.curs_set(1)
    try:
        while True:
            h, w = screen.getmaxyx()
            if h < 12 or w < 45:
                curses.curs_set(0)
                return None
            bw = min(78, w - 4)
            bx = (w - bw) // 2
            by = max(3, (h - 9) // 2)
            screen.erase()
            for y in range(by, by + 9):
                put(screen, y, bx, " " * (bw - 1), style("main"), bw - 1)
            put(screen, by, bx, "╭" + "─" * (bw - 3) + "╮", style("a"))
            put(screen, by + 1, bx + 2, heading.upper(), style("a", True), bw - 4)
            put(screen, by + 2, bx + 2, prompt, style("main", True), bw - 4)
            put(screen, by + 4, bx + 2, "▸ " + "·" * (bw - 7), style("edge"), bw - 4)
            visible = bw - 9
            if cursor < scroll:
                scroll = cursor
            if cursor >= scroll + visible:
                scroll = cursor - visible + 1
            content = "".join(value[scroll:scroll + visible])
            put(screen, by + 4, bx + 4, content.ljust(visible), style("main"), visible)
            put(screen, by + 6, bx + 2, "ENTER guardar   ESC cancelar   CTRL+U limpiar", style("dim"), bw - 4)
            put(screen, by + 8, bx, "╰" + "─" * (bw - 3) + "╯", style("a"))
            try:
                screen.move(by + 4, bx + 4 + cursor - scroll)
            except curses.error:
                pass
            screen.refresh()
            key = screen.get_wch()
            if key in ("\n", "\r", curses.KEY_ENTER):
                output = "".join(value).strip()
                if output or not required:
                    if drafts:
                        drafts.discard(name, ".txt")
                    return output
                curses.beep()
            elif key in ("\x1b",):
                if drafts:
                    drafts.discard(name, ".txt")
                return None
            elif key in ("\x15",):
                value, cursor, scroll = [], 0, 0
            elif key in ("\x7f", "\b", curses.KEY_BACKSPACE):
                if cursor:
                    value.pop(cursor - 1)
                    cursor -= 1
            elif key == curses.KEY_DC:
                if cursor < len(value):
                    value.pop(cursor)
            elif key == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_RIGHT:
                cursor = min(len(value), cursor + 1)
            elif key == curses.KEY_HOME:
                cursor = 0
            elif key == curses.KEY_END:
                cursor = len(value)
            elif isinstance(key, str) and key.isprintable() and len(value) < 450:
                value.insert(cursor, key)
                cursor += 1
            if drafts and key not in ("\n", "\r", curses.KEY_ENTER):
                drafts.write(name, "".join(value), ".txt")
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def choose(screen, heading, options):
    """A one-key choice in a box: returns the key pressed, or None for ESC."""
    h, w = screen.getmaxyx()
    bw = min(70, w - 4)
    bx, by = (w - bw) // 2, max(3, (h - 6) // 2)
    for row in range(by, by + 5):  # an opaque box over whatever is behind it
        put(screen, row, bx, " " * bw, style("main"), bw)
    y, x, _, iw = box(screen, by, bx, 5, bw, heading.upper())
    put(screen, y, x, " " * iw, style("main"), iw)
    put(screen, y + 1, x, options, style("main", True), iw)
    put(screen, y + 2, x, "una tecla · ESC cancelar", style("dim"), iw)
    screen.refresh()
    key = screen.get_wch()
    return None if key == "\x1b" else key


def confirm(screen, question):
    reply = ask(screen, "Confirmación", question + "  (escribe SI)")
    return reply is not None and reply.strip().lower() in ("si", "sí")


def find_editor():
    """$VISUAL, then $EDITOR, then the first editor installed."""
    chosen = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if chosen:
        return shlex.split(chosen)
    found = next((shutil.which(e) for e in ("nvim", "vim", "vi", "nano") if shutil.which(e)), None)
    return [found] if found else None


def vim_escape(path):
    return re.sub(r'([ \\%#|"])', r"\\\1", str(path))


def nvim_helpers(folder):
    """A Lua file for nvim, only for popOS documents: a fixed help bar on top and
    Ctrl+G, a list of suggested sections to insert (buffer-local, so the
    user's own nvim is untouched)."""
    items = ", ".join("{%s, %s}" % (json.dumps(name, ensure_ascii=False), json.dumps(question, ensure_ascii=False))
                      for name, question in SUGGESTIONS)
    lua = f"""vim.opt_local.winbar = " popOS · escribe libre bajo la raya ── · Ctrl+G sección sugerida · ZZ guardar · ZQ salir sin guardar"
local items = {{ {items} }}
local function insert(choice)
  if not choice then return end
  local row = vim.api.nvim_win_get_cursor(0)[1]
  vim.api.nvim_buf_set_lines(0, row, row, false, {{"", "## " .. choice[1] .. " · " .. choice[2], "", ""}})
  vim.api.nvim_win_set_cursor(0, {{row + 4, 0}})
  vim.cmd("startinsert")
end
local function pick()
  vim.ui.select(items, {{prompt = "Sección sugerida (ESC: ninguna)",
    format_item = function(i) return i[1] .. " · " .. i[2] end}}, insert)
end
vim.keymap.set("n", "<C-g>", pick, {{buffer = true, desc = "popOS: sección sugerida"}})
vim.keymap.set("i", "<C-g>", function() vim.cmd("stopinsert"); vim.schedule(pick) end, {{buffer = true}})
"""
    path = Path(folder) / "popos-nvim.lua"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(lua)
    return path


def edit_in_editor(screen, path, autosave=None):
    """Hand the terminal to the editor on `path`; True if the file was saved.

    vim and nvim also copy every change to `autosave` as it happens, without
    touching `path` itself, so :q! still means "save nothing".
    """
    editor = find_editor()
    command = [*editor]
    if autosave and Path(editor[0]).name in ("nvim", "vim"):
        # -n: no swap file. The autosave already covers a crash, and nvim's own
        # "ATTENTION: swap file found" prompt would only confuse the recovery
        command += ["-n", "-c", "autocmd TextChanged,TextChangedI,InsertLeave <buffer> silent! keepalt write! "
                    + vim_escape(autosave)]
    if Path(editor[0]).name == "nvim":
        # An auto-save plugin would write even on :q!, and :q! must keep meaning "save nothing"
        command += ["-c", "lua pcall(function() require('auto-save').off() end)",
                    "-c", "luafile " + vim_escape(nvim_helpers(path.parent))]
    before = path.stat().st_mtime_ns
    curses.def_prog_mode()
    curses.endwin()
    try:
        subprocess.call([*command, str(path)])
    except OSError:
        return False
    finally:
        curses.reset_prog_mode()
        screen.refresh()
    return path.stat().st_mtime_ns != before


# Fallback when no editor is installed: one line per field
FIELDS = [
    ("title", "Nombre del acuerdo (breve)", True),
    ("pinned", "Nota destacada, la que verás en la ficha (opcional)", False),
    ("body", "Texto libre (opcional; en un editor no tiene límite)", False),
]


JOURNAL_LIMIT = 200  # newest entries the BITÁCORA tab shows

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
# The kinds of experience. A commitment isn't a task that gets done: it stays,
# and experiences pile up on it.
#   done      Aplicación      put it into practice in a real situation
#   progress  Avance          noticed it comes easier than it used to
#   obstacle  Obstáculo       something got in the way (a repair can follow)
#   insight   Descubrimiento  understood something about how I act
#   review    Revisión        reconsidered the strategy (R, a commit)
EVENT_LABELS = {"done": ("APLICACIÓN", "good"), "progress": ("AVANCE", "good"), "obstacle": ("OBSTÁCULO", "warm"),
                "insight": ("DESCUBRIMIENTO", "b"), "review": ("REVISIÓN", "b"), "init": ("NUEVO", "a"),
                "version": ("VERSIÓN", "a")}
LABEL_W = 15
# The calendar's dots: what kind of thing happened that day. Soft colours, and
# a day with no dots is just a quiet day
DAY_KINDS = [
    ("práctica", ("done", "progress"), "good"),
    ("obstáculo", ("obstacle",), "warm"),
    ("descubrimiento", ("insight", "review"), "b"),
    ("cambio", ("init", "version"), "a"),
]
# One key and ENTER: the note is always optional. Writing costs; noting that
# it happened is already worth it
# The four experiences as they are offered (+ or Space): key, kind, name,
# what it means, colour. Also the line at the bottom of a commitment's page
EXPERIENCES = [
    ("d", "done", "Aplicación", "lo he puesto en práctica", "good"),
    ("p", "progress", "Avance", "me cuesta menos que antes", "good"),
    ("b", "obstacle", "Obstáculo", "algo lo dificultó", "warm"),
    ("i", "insight", "Descubrimiento", "he comprendido algo", "b"),
]
LOG_PROMPTS = {
    "done": "Aplicación · ¿qué pasó? (opcional, ENTER y listo)",
    "progress": "Avance · ¿qué notas distinto? (opcional)",
    "obstacle": "Obstáculo · ¿qué ocurrió? (opcional; S en BITÁCORA añade cómo lo reparaste)",
    "insight": "Descubrimiento · ¿qué has comprendido? (opcional)",
}
# What Popo says when something is logged: company, never a verdict
POPO_SAYS = {
    "done": "Popo: «¡Otra experiencia para la barriguita! ♡»",
    "progress": "Popo: «¡Se nota! Lo guardo.»",
    "obstacle": "Popo: «¡Gracias por contármelo! Ahora podemos investigarlo :3»",
    "insight": "Popo: «¡Apuntado! Esto lo guardo con cariño.»",
}


def month_grid(day):
    """The Monday-first weeks (lists of 7 dates) that show the month of `day`."""
    first = day.replace(day=1)
    following = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    monday = first - dt.timedelta(days=first.weekday())
    weeks = []
    while monday < following:
        weeks.append([monday + dt.timedelta(days=i) for i in range(7)])
        monday += dt.timedelta(days=7)
    return weeks

# Below SIDEBAR_W columns the sidebar folds into a tab row on top.
# SIDE_W: the sidebar panels (whose inside fits the 25-column name) plus a gap
MIN_W, MIN_H, SIDEBAR_W, SIDE_W = 50, 20, 86, 30
# Wider than this, the app stops stretching and sits centred: its longest
# lines (sidebar + the widest panel text) set the size, not the screen
MAX_W = 120

# The CALENDARIO tab gives the arrows to the days
MENU_HINTS = [
    "↑↓ menú  ENTER entrar  + añadir experiencia (D/P/B/I)  N nuevo acuerdo  ? ayuda",
    "↑↓ menú  ENTER entrar  + experiencia  N nuevo  ? ayuda",
    "↑↓ menú  ENTER entrar  ? ayuda",
]
CALENDAR_INSIDE_HINTS = [
    "←→↑↓ día  [ ] mes  T hoy  ESC menú  D/P/B/I apuntar en este día  ? ayuda",
    "←→↑↓ día  [ ] mes  T hoy  ESC menú",
]

# Longest first; draw() shows the first one that fits the window width
KEY_HINTS = [
    "↑↓ elegir  ENTER leer  ESC menú  + añadir experiencia (D/P/B/I)  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  R retro  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  ? ayuda",
]


class App:
    def __init__(self, store):
        self.store = store
        self.tab = 0
        self.selected = 0
        self.message = "Datos locales y privados. Nadie supervisa tus avances."
        self.archive = False
        self.drafts = Drafts(store.path.with_name(store.path.stem + ".drafts"))
        waiting = self.describe_drafts()
        if waiting:
            self.message = "✎ Borradores sin guardar: " + waiting + ". Se recuperan al abrirlos otra vez."
        self.popo = load_popo()
        self.logo_at = None  # (row, col) of the sidebar Popo while it's on screen
        self.kitty_logo = False  # True once the logo PNGs are in kitty: draw placeholders, not blocks
        self.entry_selected = 0  # cursor in the BITÁCORA tab
        self.cal_day = dt.date.today()  # the day chosen in the CALENDARIO tab
        # Where the arrows go: the menu (NAV, ↑↓ change tab) or, after ENTER, the
        # tab's content (↑↓ choose in it; in the calendar the arrows move the days). ESC: back
        self.inside = False
        self.kitty_popos = set()  # (belly, integrated) sizes of the ficha Popo already sent to kitty
        self.kitty_farm = set()  # (belly, integrated) sizes of the meadow's Popos already sent
        self.herd = {}  # commitment id -> where its Popo is in the meadow and what it's doing
        self.herd_clock = time.monotonic()
        self.ficha_popo = None  # where the ficha's Popo is drawn, for the animation between keys
        self.undo = None  # (removed rows, what they were) of the last delete, until the app closes
        self.pairs = {}  # (fg, bg) -> curses pair id, handed out from 9 on

    def pair(self, fg, bg):
        """Color pair for a sprite cell; the plain text color once pairs run out."""
        key = (fg, bg)
        if key not in self.pairs:
            ident = 9 + len(self.pairs)
            # Attributes only hold 8 bits of pair number
            if ident > min(255, curses.COLOR_PAIRS - 1):
                return style("main")
            try:
                curses.init_pair(ident, fg, bg)
            except curses.error:
                return style("main")
            self.pairs[key] = ident
        return curses.color_pair(self.pairs[key])

    @property
    def cal_focus(self):
        return self.inside and self.tab == TABS.index("CALENDARIO")

    def current(self):
        items = self.store.all_commitments() if self.archive else self.store.active()
        if items:
            self.selected = max(0, min(self.selected, len(items) - 1))
            return items[self.selected]
        self.selected = 0
        return None

    def current_items(self):
        return self.store.all_commitments() if self.archive else self.store.active()

    def ask(self, scr, heading, prompt, default="", required=False):
        return ask(scr, heading, prompt, default, required, drafts=self.drafts)

    def describe_drafts(self):
        names = []
        titles = {c["id"]: c["title"] for c in self.store.all_commitments()}
        for name in self.drafts.pending():
            if name == "nuevo":
                names.append("un acuerdo nuevo (N)")
            elif name.startswith("acuerdo-") and name[8:].isdigit() and int(name[8:]) in titles:
                names.append(f"«{titles[int(name[8:])]}» (E)")
        return ", ".join(names)

    def write_document(self, scr, name, initial):
        """Edit a document as the draft `name`; returns the text to save, or None.

        The draft stays on disk until the caller has saved it and calls
        self.drafts.discard(name).
        """
        recovered = self.drafts.recover(name)
        path = self.drafts.write(name, recovered if recovered is not None else initial)
        saved = edit_in_editor(scr, path, self.drafts.autosave_path(name))
        # The editor came back on its own: its autosave isn't needed any more
        self.drafts.drop_autosave(name)
        text = path.read_text(encoding="utf-8")
        if saved:
            return text
        if recovered is not None and confirm(scr, "Era un borrador recuperado. ¿Lo guardo en el acuerdo?"):
            return text
        self.drafts.discard(name)
        return None

    def new(self, scr):
        if not find_editor():
            return self.new_by_lines(scr)
        text = self.write_document(scr, "nuevo", to_markdown({}))
        if text is None:
            self.message = "Creación cancelada: no se guardó nada."
            return
        fields = from_markdown(text)
        if not fields["title"]:
            # Never throw away what was written just for a missing title
            fields["title"] = self.ask(scr, "Nuevo acuerdo", "Falta el título (la sección TITLE)", required=True) or "Sin título"
        self.store.create(**fields)
        self.drafts.discard("nuevo")
        self.selected = 0
        self.tab = 1
        self.message = "Acuerdo creado · v1.0. ENTER para leerlo entero."

    def new_by_lines(self, scr):
        data = {}
        for key, title, required in FIELDS:
            entry = self.ask(scr, "Nuevo acuerdo · " + str(len(data) + 1) + f"/{len(FIELDS)}", title, required=required)
            if entry is None:
                self.message = "Creación cancelada: no se guardó nada."
                return
            data[key] = entry
        self.store.create(**data)
        self.selected = 0
        self.tab = 1
        self.message = "Acuerdo creado. Sin editor instalado, las secciones largas no están disponibles."

    def edit(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero crea un acuerdo con N."
            return
        name = f"acuerdo-{item['id']}"
        if find_editor():
            text = self.write_document(scr, name, to_markdown(dict(item)))
            if text is None:
                self.message = "Edición cancelada: no se guardaron cambios."
                return
            fields = from_markdown(text)
            fields["title"] = fields["title"] or item["title"]
        else:
            fields = {}
            for key, title, required in FIELDS:
                entry = self.ask(scr, "Editar acuerdo #" + str(item["id"]), title, default=item[key], required=required)
                if entry is None:
                    self.message = "Edición cancelada: no se guardaron cambios."
                    return
                fields[key] = entry
        if all(fields.get(k, item[k]) == item[k] for k in TEXT_FIELDS):
            self.drafts.discard(name)
            self.message = "Sin cambios: el acuerdo sigue igual."
            return
        next_label = version_label(len(self.store.versions(item["id"])))
        # ESC here still keeps the edit: the note is optional, the text is not.
        # Until revise() returns, the edit only lives in the draft
        note = self.ask(scr, f"Versión nueva · {next_label}", "¿Qué cambió y por qué?") or "Actualizado"
        label = self.store.revise(item["id"], fields, note)
        self.drafts.discard(name)
        self.message = f"{label} · {note}"

    def log(self, scr, kind):
        item = self.current()
        if not item:
            self.message = "Elige un acuerdo antes de registrar una experiencia."
            return
        # Inside the calendar, what's logged goes to the chosen day: the way to
        # add what was not noted at the time
        when, on = None, ""
        if self.tab == TABS.index("CALENDARIO") and self.cal_focus and self.cal_day != dt.date.today():
            noon = dt.datetime.combine(self.cal_day, dt.time(12)).astimezone()
            when = noon.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
            on = f" · apuntado el {self.cal_day.day} de {MONTHS[self.cal_day.month - 1]}"
        note = self.ask(scr, f"{item['title']}{on}", LOG_PROMPTS[kind])
        if note is None:
            self.message = "Registro cancelado."
            return
        self.store.log(item["id"], kind, note, when)
        self.message = POPO_SAYS[kind] + on

    def choose_experience(self, scr):
        """+ or Space: the four kinds of experience, explained, one key to pick."""
        item = self.current()
        if not item:
            self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
            return
        h, w = scr.getmaxyx()
        bw = min(64, w - 4)
        bx, by = (w - bw) // 2, max(2, (h - 8) // 2)
        for row in range(by, by + 8):  # opaque over what is behind
            put(scr, row, bx, " " * bw, style("main"), bw)
        y, x, _, iw = box(scr, by, bx, 8, bw, f"AÑADIR EXPERIENCIA · {item['title']}", style("a", True))
        for i, (key, _, name, meaning, color) in enumerate(EXPERIENCES):
            put(scr, y + i, x, key.upper(), style(color, True))
            put(scr, y + i, x + 3, name, style(color, True), iw - 3)
            put(scr, y + i, x + 20, meaning, style("main"), iw - 20)
        put(scr, y + 5, x, "una tecla · luego ENTER (la nota es opcional) · ESC cancelar", style("dim"), iw)
        scr.refresh()
        key = scr.get_wch()
        kind = next((kind for k, kind, *_ in EXPERIENCES if isinstance(key, str) and key.lower() == k), None)
        if kind:
            self.log(scr, kind)

    def add_repair(self, scr):
        """S on an obstacle in BITÁCORA: how it was put right (or what will be done)."""
        entries = self.store.entries(limit=JOURNAL_LIMIT)
        if self.tab != TABS.index("BITÁCORA") or not entries:
            self.message = "S añade una reparación a un obstáculo: elígelo en BITÁCORA."
            return
        entry = entries[min(self.entry_selected, len(entries) - 1)]
        if entry["kind"] != "obstacle":
            self.message = "S es para obstáculos: este registro no lo es."
            return
        text = self.ask(scr, f"Reparación · {entry['title']}", "¿Cómo lo reparé, o qué haré? (vacío lo quita)",
                        default=entry["repair"])
        if text is None:
            return
        self.store.repair(entry["id"], text)
        self.message = "Popo: «Reparar también es avanzar.»" if text else "Reparación quitada."

    def review(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero selecciona un acuerdo."
            return
        learned = self.ask(scr, "Retrospectiva", "¿Qué aprendí del experimento?", required=True)
        if learned is None:
            return
        adjustment = self.ask(scr, "Retrospectiva", "¿Qué voy a cambiar para la próxima vez?")
        if adjustment is None:
            return
        commit = self.store.review(item["id"], learned, adjustment)
        self.tab = TABS.index("REVIEW")
        self.message = f"commit {commit} · {learned}"

    def change_status(self, scr):
        """X: active, integrated or archived, with one key. Nothing is lost either way."""
        item = self.current()
        if not item:
            return
        options = [("1", "active", "activo"), ("2", "integrated", "integrado"), ("3", "archived", "archivado")]
        key = choose(scr, f"Estado · {item['title']}", "  ".join(f"{k} {name}" for k, _, name in options))
        status = next((value for k, value, _ in options if key == k), None)
        if not status or status == item["status"]:
            return
        self.store.update(item["id"], status=status)
        self.message = {"active": "Activo de nuevo.",
                        "integrated": "¡Integrado! Ya forma parte de ti. Popo pega un estirón 🐾",
                        "archived": "Archivado: guardado con toda su historia (A para verlo)."}[status]

    def delete(self, scr):
        """Supr: the selected entry in BITÁCORA, the selected commitment in OVERVIEW/ACUERDOS."""
        if self.tab == TABS.index("BITÁCORA"):
            entries = self.store.entries(limit=JOURNAL_LIMIT)
            if not entries:
                self.message = "No hay entradas que borrar."
                return
            self.entry_selected = min(self.entry_selected, len(entries) - 1)
            self.undo = (self.store.delete_entry(entries[self.entry_selected]["id"]), "La entrada")
            self.entry_selected = max(0, min(self.entry_selected, len(entries) - 2))
            self.message = "Entrada borrada. U para deshacer."
        elif self.tab in (TABS.index("OVERVIEW"), TABS.index("ACUERDOS")):
            item = self.current()
            if not item:
                self.message = "No hay acuerdos que borrar."
                return
            title = item["title"] if len(item["title"]) <= 28 else item["title"][:27] + "…"
            if not confirm(scr, f"¿Borrar «{title}» y todo su historial?"):
                self.message = "No se ha borrado nada."
                return
            self.undo = (self.store.delete_commitment(item["id"]), f"«{item['title']}»")
            self.selected = 0
            self.message = "Acuerdo borrado. U para deshacer mientras no cierres la app; X archiva sin borrar."
        else:
            self.message = "Supr borra entradas en BITÁCORA (3) y acuerdos en OVERVIEW o ACUERDOS (1-2)."

    def undo_delete(self):
        if not self.undo:
            self.message = "No hay nada que deshacer."
            return
        removed, what = self.undo
        self.store.restore(removed)
        self.undo = None
        self.message = f"{what} ha vuelto."

    def render_sidebar(self, scr, h, w):
        """The brand (Popo and the name, the one part with no panel), then two
        panels: the tabs, and where the data lives.

        Returns the first column of the main area.
        """
        width = SIDE_W - 1
        logo = self.popo and self.popo.get("logo")
        colors = curses.has_colors() and curses.COLORS >= 256
        wordmark = wordmark_cells()
        system_h, nav_min = 5, len(TABS) + 2
        # The biggest brand that still leaves room for the other two panels
        options = []
        if logo and colors:
            options.append((len(logo[0]) + 1 + len(wordmark) + 1, True, True))
        if colors:
            options.append((len(wordmark) + 1, False, True))
        options.append((2, False, False))
        inside, with_logo, with_mark = next(
            (o for o in options if o[0] + 2 + nav_min + system_h <= h - 1), options[-1])
        # Same inside as a panel, so everything lines up, but no border
        y, x, iw = 1, 3, width - 4
        self.logo_at = None
        if with_logo:
            self.logo_at = (y, x + (iw - len(logo[0][0])) // 2)
            self.draw_logo(scr)
            y += len(logo[0]) + 1
        if with_mark:
            cream = self.pair(230, -1)
            for row, cells in enumerate(wordmark):
                for col, (char, color) in enumerate(cells):
                    if char != " ":
                        put(scr, y + row, x + col, char, cream if color == "cream" else style(color, True))
            # The version sits in the empty space beside the p's tails
            put(scr, y + len(wordmark) - 1, x + iw - len(VERSION), VERSION, style("dim"))
            y += len(wordmark)
        else:
            put(scr, y, x, f"{APP} {VERSION}", style("a", True), iw)
            y += 1
        put(scr, y, x, TAGLINE, style("dim"), iw)
        # NAV is just as tall as its tabs (one blank row around them), its list
        # centred in it; the space it leaves sits above SISTEMA
        nav_top = inside + 2
        room = h - 1 - system_h - nav_top
        step = 2 if len(TABS) * 2 + 3 <= room else 1
        nav_h = min(room, (len(TABS) - 1) * step + 1 + 4)
        y, x, ih, iw = box(scr, nav_top, 1, nav_h, width, "NAV",
                           edge=None if self.inside else style("a", True))
        labels = [f"{i + 1:02}  {name}" for i, name in enumerate(TABS)]
        lx = x + max(0, (iw - 2 - max(len(t) for t in labels)) // 2)
        ly = y + max(0, (ih - (len(TABS) - 1) * step - 1) // 2)
        for i, text in enumerate(labels):
            chosen = self.tab == i
            put(scr, ly + i * step, lx, ("► " if chosen else "  ") + text,
                style("a", True) if chosen else style("dim"), iw - (lx - x))
        y, x, _, iw = box(scr, h - 1 - system_h, 1, system_h, width, "SISTEMA")
        put(scr, y, x, "offline / personal", style("good"), iw)
        put(scr, y + 1, x, "sqlite / sin nube", style("dim"), iw)
        put(scr, y + 2, x, "? ayuda   q salir", style("dim"), iw)
        return SIDE_W + 1

    def draw_logo(self, scr):
        """Popo's current frame: kitty's real image if it has it, half blocks otherwise."""
        top, x = self.logo_at
        index = logo_frame(int(time.monotonic() * 1000))[0]
        if self.kitty_logo:
            rows, cols = len(self.popo["logo"][0]), len(self.popo["logo"][0][0])
            attr = self.pair(KITTY_LOGO_IDS[index], -1)
            for row in range(rows):
                try:
                    scr.addstr(top + row, x, kitty_placeholder_row(row, cols), attr)
                except curses.error:
                    pass
            return
        frame = self.popo["logo"][index]
        for row, cells in enumerate(frame):
            for col, cell in enumerate(cells):
                put(scr, top + row, x + col, cell[0] if cell else " ",
                    self.pair(cell[1], cell[2]) if cell else 0)

    def render_tabbar(self, scr, w):
        """Compact layout: the sidebar becomes a single row of tabs."""
        names = [f"{i + 1} {name}" for i, name in enumerate(TABS)]
        if sum(len(n) + 2 for n in names) > w - 4:
            # Too narrow for every name: only the current tab keeps its own
            names = [n if i == self.tab else n.split()[0] for i, n in enumerate(names)]
        brand = f"{APP} {VERSION}  "
        x = 2
        if len(brand) + sum(len(n) + 2 for n in names) <= w - 4:
            put(scr, 0, x, brand, style("a", True))
            x += len(brand)
        for i, name in enumerate(names):
            chosen = self.tab == i
            put(scr, 0, x, f" {name} ", style("select") if chosen else style("dim"))
            x += len(name) + 3

    def list_commitments(self, scr, y, x, width, rows):
        """Up to `rows` commitments from y, scrolled so the selected one shows."""
        items = self.current_items()
        if not items:
            put(scr, y, x, "No hay acuerdos todavía. Pulsa N para crear uno.", style("dim"), width)
            return
        top = max(0, self.selected - rows + 1)
        for pos, item in enumerate(items[top:top + rows], start=top):
            chosen = pos == self.selected
            name = ("▸ " if chosen else "  ") + f"#{item['id']:03} " + item["title"]
            if item["status"] != "active":
                name += f"  [{STATUS_NAMES[item['status']]}]"
            attr = (style("select") if self.inside else style("main", True)) if chosen else style("main")
            put(scr, y + pos - top, x, name.ljust(width), attr, width)

    def render_ficha(self, scr, top, left, width, height):
        """The commitment's page, each part in its own panel: its Popo, its
        current conclusion, how many experiences it has gathered, and the latest
        ones. Everything else is a key away (the line at the bottom)."""
        item = self.current()
        if not item:
            return
        counts = self.store.experience_counts().get(item["id"], {})
        experiences = sum(counts.values())
        label = version_label(len(self.store.versions(item["id"])) - 1)
        title = f"#{item['id']:03} · {item['title']} · {label} · {STATUS_NAMES[item['status']].upper()}"
        if f"acuerdo-{item['id']}" in self.drafts.pending():
            title += " · ✎ borrador: E"
        y, x, ih, iw = box(scr, top, left, height, width, title, style("b", True))
        last = y + ih - 1
        room = ih - 2  # the last two rows: how to add an experience, and the other keys
        self.ficha_popo = None
        # POPO, on the left: him (wider as he grows, taller once integrated) and his words
        belly, integrated = growth(experiences), item["status"] == "integrated"
        cols = round(12 * BELLY[belly])
        words = popo_look(item, experiences)[1]
        column = max(cols, len(words))
        popo_h = 6 + integrated + 1 + 2
        with_popo = bool(self.popo and self.popo.get("logo")) and room >= popo_h and iw >= column + 30
        pw = column + 4 if with_popo else 0
        rx, rw = (x + pw + 1, iw - pw - 1) if with_popo else (x, iw)
        # CONCLUSIÓN ACTUAL and EXPERIENCIAS, on the right
        text, is_note = glance(item, 3, rw - 4)
        conclusion = wrap_lines(text or "Sin nota todavía · E para escribirla", rw - 4)[:3]
        number_rows = fit_figures([(counts.get("done", 0), "aplicaciones", "apl", "good"),
                                   (counts.get("progress", 0), "avances", "av", "good"),
                                   (counts.get("obstacle", 0), "obstáculos", "obs", "warm"),
                                   (counts.get("insight", 0) + counts.get("review", 0), "descubrimientos", "desc", "b")],
                                  rw - 4, gaps=(3, 2))
        conclusion_h, numbers_h = len(conclusion) + 2, len(number_rows) + 2
        top_h = max(popo_h if with_popo else 0, conclusion_h + numbers_h)
        numbers_h = top_h - conclusion_h  # the right column ends where POPO does
        if with_popo:
            py, px, _, _ = box(scr, y, x, top_h, pw, "POPO")
            self.ficha_popo = (py, px + (column - cols) // 2, belly, integrated, cols)
            self.draw_ficha_popo(scr)
            put(scr, py + 6 + integrated, px + (column - len(words)) // 2, words, style("dim"), column)
        cy, cx, _, cw = box(scr, y, rx, conclusion_h, rw, "NOTA" if is_note else "NOTA · aún sin nota, del texto:",
                            style("b", True))
        for i, line in enumerate(conclusion):
            put(scr, cy + i, cx, line, style("main", True) if is_note else style("dim"), cw)
        ny, nx0, _, _ = box(scr, y + conclusion_h, rx, numbers_h, rw, "EXPERIENCIAS", style("b", True))
        draw_figures(scr, ny, nx0, number_rows)
        # ÚLTIMAS EXPERIENCIAS, across the bottom
        if room - top_h >= 3:
            ly, lx, lh, lw = box(scr, y + top_h, x, room - top_h, iw, "ÚLTIMAS EXPERIENCIAS", style("b", True))
            recent = self.store.recent(limit=lh, commitment_id=item["id"])
            if not recent:
                hint = ("¿Ha pasado algo con este acuerdo? Pulsa + para añadir una experiencia "
                        "(o directamente D, P, B o I). La nota es opcional.")
                for i, line in enumerate(wrap_lines(hint, lw)[:lh]):
                    put(scr, ly + i, lx, line, style("dim"), lw)
            for i, e in enumerate(recent):
                name, color = EVENT_LABELS.get(e["kind"], ("", "dim"))
                when = dt.datetime.fromisoformat(e["created_at"]).astimezone()
                put(scr, ly + i, lx, f"{when.day:>2} {MONTHS[when.month - 1][:3]}", style("dim"), 7)
                put(scr, ly + i, lx + 7, name.capitalize(), style(color), LABEL_W)
                note = (e["note"] or "—") + ("  ✓ reparado" if e["repair"] else "")
                put(scr, ly + i, lx + 7 + LABEL_W, note, style("main"), max(1, lw - 7 - LABEL_W))
        # How to add an experience, always in sight; short names when narrow
        long_line = 12 + sum(4 + len(name) for _, _, name, _, _ in EXPERIENCES)
        ex = x
        put(scr, last - 1, ex, "+", style("a", True))
        put(scr, last - 1, ex + 2, "añadir ·", style("a"))
        ex += 12
        for key, _, name, _, color in EXPERIENCES:
            label = name.lower() if long_line <= iw else name[:4].lower()
            put(scr, last - 1, ex, key.upper(), style(color, True))
            put(scr, last - 1, ex + 2, label, style(color))
            ex += len(label) + 4
        put(scr, last, x, "ENTER leer · E editar · V versiones · R revisar · X estado", style("dim"), iw)

    def draw_ficha_popo(self, scr):
        """The ficha's Popo: kitty's real image (wider as he grows, taller when
        integrated) or half blocks stretched the same way."""
        y, x, belly, integrated, cols = self.ficha_popo
        index = logo_frame(int(time.monotonic() * 1000))[0]
        rows = 6 + integrated
        if self.kitty_logo and self.popo.get("logo_rgba"):
            high = 1 + belly + 5 * integrated
            if (belly, integrated) not in self.kitty_popos:
                data = "".join(kitty_upload((high << 24) | color,
                                            popo_png(self.popo["logo_rgba"], frame, BELLY[belly],
                                                     STRETCH if integrated else 1.0), cols, rows)
                               for frame, color in enumerate(KITTY_LOGO_IDS))
                os.write(sys.stdout.fileno(), data.encode("ascii"))
                self.kitty_popos.add((belly, integrated))
            attr = self.pair(KITTY_LOGO_IDS[index], -1)
            for row in range(rows):
                try:
                    scr.addstr(y + row, x, kitty_placeholder_row(row, cols, high), attr)
                except curses.error:
                    pass
            return
        frame = self.popo["logo"][index]
        width = len(frame[0])
        for row, cells in enumerate(frame):
            for col in range(cols):
                cell = cells[min(width - 1, col * width // cols)]
                put(scr, y + row, x + col, cell[0] if cell else " ", self.pair(cell[1], cell[2]) if cell else 0)

    def list_and_detail(self, scr, top, bottom, left, width, title, list_rows, note=None):
        """A panel listing the commitments and, if it fits, the SELECTED panel under it."""
        space = bottom - top + 1
        extra = 1 if note else 0
        list_h = min(space, list_rows + 2 + extra)
        y, x, ih, iw = box(scr, top, left, list_h, width, title, edge=style("a", True) if self.inside else None)
        if note:
            put(scr, y, x, note, style("dim"), iw)
        self.list_commitments(scr, y + extra, x, iw, max(1, ih - extra))
        if space - list_h >= 5:
            self.render_ficha(scr, top + list_h, left, width, space - list_h)

    def render_overview(self, scr, top, bottom, left, width):
        """Totals since the beginning (a commitment doesn't expire), the
        commitments, and the latest memories of all of them."""
        living = self.store.active()
        counts = self.store.experience_counts()
        experiences = sum(sum(c.values()) for c in counts.values())
        learned = sum(c.get("insight", 0) + c.get("review", 0) for c in counts.values())
        integrated = sum(1 for c in living if c["status"] == "integrated")
        figures = fit_figures([(len(living), "ACUERDOS", "ACU", "a"), (experiences, "EXPERIENCIAS", "EXP", "good"),
                               (learned, "DESCUBRIMIENTOS", "DESC", "b"), (integrated, "INTEGRADOS", "INT", "warm")],
                              width - 4)
        y, x, _, iw = box(scr, top, left, 4, width, "OVERVIEW · Memoria persistente entre sesiones 🐾")
        draw_figures(scr, y, x, figures[:2])
        if len(figures) == 1:  # a second row of figures takes the motto's place
            put(scr, y + 1, x, "Toda experiencia cuenta para aprender. ♡", style("dim"), iw)
        space = bottom - (top + 4) + 1
        rows = max(1, min(len(self.current_items()), 6))
        list_h = min(space, rows + 2)
        ly, lx, lh, lw = box(scr, top + 4, left, list_h, width, "FOCUS · Mis acuerdos",
                             edge=style("a", True) if self.inside else None)
        self.list_commitments(scr, ly, lx, lw, lh)
        if space - list_h < 3:
            return
        y, x, ih, iw = box(scr, top + 4 + list_h, left, space - list_h, width, "ÚLTIMOS RECUERDOS", style("b", True))
        recent = self.store.recent(limit=ih)
        if not recent:
            steps = ["Aún no hay recuerdos. Para añadir una experiencia:",
                     "1. ENTER y elige un acuerdo con ↑↓",
                     "2. pulsa + (o directamente D, P, B o I)",
                     "3. ENTER: la nota es opcional"]
            for i, line in enumerate(steps[:ih]):
                put(scr, y + i, x, line, style("dim") if i else style("main"), iw)
        for i, e in enumerate(recent):
            name, color = EVENT_LABELS.get(e["kind"], ("", "dim"))
            when = dt.datetime.fromisoformat(e["created_at"]).astimezone()
            put(scr, y + i, x, f"↳ {when.day:>2} {MONTHS[when.month - 1][:3]}", style("dim"), 9)
            put(scr, y + i, x + 10, name.capitalize(), style(color), LABEL_W)
            text = e["title"] + (f": {e['note']}" if e["note"] else "")
            put(scr, y + i, x + 10 + LABEL_W, text, style("main"), max(1, iw - 10 - LABEL_W))

    def render_agreements(self, scr, top, bottom, left, width):
        rows = max(1, min(len(self.current_items()), max(3, min(9, (bottom - top) // 3))))
        note = "A  /  " + ("Todos, incluso archivados" if self.archive else "Solo activos")
        self.list_and_detail(scr, top, bottom, left, width, "ACUERDOS · Contratos conmigo mismo · siempre revisables",
                             rows, note)

    def render_calendar(self, scr, top, bottom, left, width):
        """The month as a grid of days with a dot per kind of thing that happened,
        the month in numbers under it, and what happened on the chosen day beside
        (or under) them."""
        day, today = self.cal_day, dt.date.today()
        weeks = month_grid(day)
        events = self.store.events_between(weeks[0][0], weeks[-1][-1])
        by_day = {}
        for e in events:
            by_day.setdefault(e["day"], []).append(e)
        cell = 7
        grid_w = 7 * cell + 4
        space = bottom - top + 1
        beside = width >= grid_w + 32
        # Days header, the weeks, a blank row and the legend in two rows
        grid_h = min(space, len(weeks) + 6)
        title = f"CALENDARIO · {MONTHS[day.month - 1].capitalize()} {day.year}"
        if self.cal_focus:
            title += " · ESC salir"
        y, x, ih, iw = box(scr, top, left, grid_h, grid_w if beside else width, title,
                           edge=style("a", True) if self.cal_focus else None)
        # A narrow window gets narrower days (down to 5 columns: the number and 2 dots)
        cell = max(5, min(7, iw // 7))
        x += max(0, (iw - 7 * cell) // 2)  # the grid (and its legend) centred in its box
        for i, name in enumerate("LMXJVSD"):
            put(scr, y, x + i * cell + 1, name.rjust(2), style("dim"))
        for row, week in enumerate(weeks):
            for col, date in enumerate(week):
                cx, cy = x + col * cell, y + 1 + row
                if cy > y + ih - 1:
                    break
                number = f"{date.day:>2}"
                if date == day:
                    attr = style("select")
                elif date.month != day.month:
                    attr = style("edge")
                else:
                    attr = style("main", date == today)
                put(scr, cy, cx + 1, number, attr)
                kinds = {e["kind"] for e in by_day.get(date, [])}
                dots = [color for _, members, color in DAY_KINDS if kinds & set(members)][:cell - 3]
                for k, color in enumerate(dots):
                    put(scr, cy, cx + 3 + k, "•", style(color, True))
        legend_y = y + len(weeks) + 2
        for i, (name, _, color) in enumerate(DAY_KINDS):
            ly, lx = legend_y + i // 2, x + 1 + (i % 2) * 22
            if ly <= y + ih - 1:
                put(scr, ly, lx, "• " + name, style(color))
        month = [e for e in events if e["day"].month == day.month and e["kind"] not in ("init", "version")]
        if beside:
            if space - grid_h >= 5:
                self.render_month(scr, top + grid_h, space - grid_h, left, grid_w, day, month)
            self.render_day(scr, top, space, left + grid_w + 1, width - grid_w - 1, by_day.get(day, []))
        elif space - grid_h >= 4:
            self.render_day(scr, top + grid_h, space - grid_h, left, width, by_day.get(day, []))

    def render_month(self, scr, top, height, left, width, day, events):
        """What the month held, in numbers: only what was noted, never what "should" have been."""
        y, x, ih, iw = box(scr, top, left, height, width, f"RESUMEN DE {MONTHS[day.month - 1].upper()}",
                           style("b", True))
        count = lambda *kinds: sum(1 for e in events if e["kind"] in kinds)
        obstacles = count("obstacle")
        repaired = sum(1 for e in events if e["kind"] == "obstacle" and e["repair"])
        rows = [(count("done"), "aplicaciones", "good"), (count("progress"), "avances", "good"),
                (obstacles, "obstáculos" + (f" · {repaired} reparado" + ("s" if repaired != 1 else "")
                                            if repaired else ""), "warm"),
                (count("insight", "review"), "descubrimientos", "b"),
                (len({e["commitment_id"] for e in events}), "acuerdos con experiencias", "a")]
        for i, (n, name, color) in enumerate(rows):
            if i >= ih:
                break
            put(scr, y + i, x, f"{n:02}", style(color, True))
            put(scr, y + i, x + 3, name, style(color), iw - 3)
        if len(rows) < ih:
            put(scr, y + ih - 1, x, "Un mes sin registros no es un mes vacío. ♡" if not events
                else "Toda experiencia cuenta para aprender. ♡", style("dim"), iw)

    def render_day(self, scr, top, height, left, width, events):
        day = self.cal_day
        y, x, ih, iw = box(scr, top, left, height, width,
                           f"{WEEKDAYS[day.weekday()].capitalize()} {day.day} de {MONTHS[day.month - 1]}",
                           style("b", True))
        last = y + ih - 1
        if not events:
            put(scr, y, x, "Un día tranquilo: sin registros.", style("dim"), iw)
            return
        for e in events:
            if y > last:
                break
            label, color = EVENT_LABELS.get(e["kind"], ("LOG", "dim"))
            label = label.capitalize()
            time_of_day = dt.datetime.fromisoformat(e["created_at"]).astimezone().strftime("%H:%M")
            put(scr, y, x, time_of_day, style("dim"), 5)
            put(scr, y, x + 6, label, style(color, True), iw - 6)
            if 6 + len(label) + 3 + len(e["title"]) <= iw:
                put(scr, y, x + 6 + len(label), " · " + e["title"], style("main"), iw - 6 - len(label))
            else:  # a narrow column: the commitment gets its own lines
                for line in wrap_lines(e["title"], iw - 6)[:2]:
                    if y + 1 > last:
                        break
                    y += 1
                    put(scr, y, x + 6, line, style("main"), iw - 6)
            y += 1
            if e["note"] and y <= last:
                put(scr, y, x + 6, "↳ " + e["note"], style("dim"), iw - 6)
                y += 1
            y += 1

    def move_day(self, days=0, months=0):
        day = self.cal_day
        if months:
            month = day.month - 1 + months
            year, month = day.year + month // 12, month % 12 + 1
            following = dt.date(year + (month == 12), month % 12 + 1, 1)
            day = dt.date(year, month, min(day.day, (following - dt.timedelta(days=1)).day))
        self.cal_day = day + dt.timedelta(days=days)

    def render_journal(self, scr, top, bottom, left, width):
        """↑↓ choose an entry here (Supr deletes it), not a commitment."""
        y, x, ih, iw = box(scr, top, left, bottom - top + 1, width,
                           "BITÁCORA · Todo el recorrido · S repara un obstáculo · Supr borra",
                           edge=style("a", True) if self.inside else None)
        last = y + ih - 1
        items = self.store.entries(limit=JOURNAL_LIMIT)
        if not items:
            put(scr, y, x, "Aún no hay entradas. Desde inicio: D, P, B o I.", style("dim"), iw)
            return
        self.entry_selected = min(self.entry_selected, len(items) - 1)
        # Entries take up to 3 rows: start early enough for the cursor to be on screen
        start = max(0, self.entry_selected - max(1, ih // 3) + 1)
        for index, entry in enumerate(items[start:], start=start):
            if y > last:
                break
            chosen = index == self.entry_selected
            label, color = EVENT_LABELS.get(entry["kind"], ("LOG", "dim"))
            put(scr, y, x, display_date(entry["created_at"]),
                (style("select") if self.inside else style("main", True)) if chosen else style("dim"), 12)
            put(scr, y, x + 13, label, style(color, True), LABEL_W)
            put(scr, y, x + 13 + LABEL_W, entry["title"], style("main", chosen), max(1, iw - 13 - LABEL_W))
            y += 1
            if entry["note"] and y <= last:
                put(scr, y, x + 13, "↳ " + entry["note"], style("dim"), iw - 13)
                y += 1
            if entry["repair"] and y <= last:
                put(scr, y, x + 13, "✓ reparado: " + entry["repair"], style("good"), iw - 13)
                y += 1
            y += 1

    def render_review(self, scr, top, bottom, left, width):
        space = bottom - top + 1
        rows = max(1, min(len(self.current_items()), max(2, min(4, space // 5))))
        list_h = rows + 2
        y, x, ih, iw = box(scr, top, left, list_h, width, "REVIEW · R hace commit de una revisión del acuerdo seleccionado",
                           edge=style("a", True) if self.inside else None)
        self.list_commitments(scr, y, x, iw, ih)
        y, x, ih, iw = box(scr, top + list_h, left, space - list_h, width, "$ git log --graph", style("b", True))
        last = y + ih - 1
        rows = commit_graph(self.store.history())
        if not rows:
            put(scr, y, x, "Sin commits todavía. Crea un acuerdo con N: será tu primer commit.", style("dim"), iw)
            return
        graph_w = max(len(cells) for cells, _, _, _ in rows) * 2
        right = x + iw
        for i, (cells, below, head, event) in enumerate(rows):
            if y > last:
                break
            self.draw_lanes(scr, y, x, cells)
            cx = x + graph_w + 1
            put(scr, y, cx, event["hash"], style("warm"), right - cx)
            cx += 8
            if head:
                label = "(" + ("HEAD → " if i == 0 else "") + event["title"] + ") "
                put(scr, y, cx, label, lane_style(event["commitment_id"], True), max(1, right - cx))
                cx += len(label)
            # The branch label already names the commitment: a bare "init" is enough
            message = "init" if head and event["kind"] == "init" else event["message"]
            put(scr, y, cx, message, style("main"), max(1, right - cx))
            y += 1
            if event["detail"] and y <= last:
                self.draw_lanes(scr, y, x, below)
                prefix = "→ " if event["kind"] == "review" else "¿por qué? "
                put(scr, y, x + graph_w + 3, prefix + event["detail"], style("dim"), max(1, right - x - graph_w - 3))
                y += 1

    def render_farm(self, scr, top, bottom, left, width):
        """The meadow: every commitment's Popo wanders about on its own. Wider
        with experiences, taller once integrated; the archived ones (A) sleep."""
        y, x, ih, iw = box(scr, top, left, bottom - top + 1, width, "POPARIUM · los Popos andan a su aire",
                           edge=style("a", True) if self.inside else None)
        items = self.current_items()
        if not items:
            put(scr, y, x, "El Poparium está vacío. Cada acuerdo nuevo (N) trae su Popo.", style("dim"), iw)
            return
        counts = self.store.experience_counts()
        experiences = {item["id"]: sum(counts.get(item["id"], {}).values()) for item in items}
        field_h = ih - 1  # the last row tells who the chosen Popo is
        base_w, base_h = FARM_POPO
        if not (self.popo and self.popo.get("logo")) or field_h < base_h + 1 or iw < round(base_w * BELLY[-1]) + 2:
            put(scr, y, x, "Agranda la ventana para ver el prado.", style("warm"), iw)
            for i, item in enumerate(items[:ih - 2]):
                chosen = i == self.selected
                put(scr, y + 2 + i, x, ("▸ " if chosen else "  ") + f"🐾 {item['title']} · "
                    f"{popo_look(item, experiences[item['id']])[1]}", style("select") if chosen else style("main"), iw)
            return
        # Grass: the same few blades every time, scattered over the meadow
        blades = random.Random(iw * 1000 + field_h)
        for _ in range(iw * field_h // 45):
            put(scr, y + blades.randrange(field_h), x + blades.randrange(iw), blades.choice("',.\""), style("good"))
        # Each Popo's size, then one step of the herd for every FARM_TICK gone by
        sizes = {}
        for item in items:
            belly = growth(experiences[item["id"]])
            sizes[item["id"]] = (round(base_w * BELLY[belly]), base_h + (item["status"] == "integrated"), belly)
        self.walk_herd(items, sizes, iw, field_h)
        # Draw the far ones first, so the near ones (lower) overlap them
        chosen_id = items[min(self.selected, len(items) - 1)]["id"]
        now_ms = int(time.monotonic() * 1000)
        for item in sorted(items, key=lambda i: self.herd[i["id"]]["y"]):
            spot = self.herd[item["id"]]
            cols, rows, belly = sizes[item["id"]]
            # Out of step with each other: each breathes on its own clock
            frame = 0 if item["status"] == "archived" else logo_frame(now_ms + item["id"] * 1700)[0]
            self.draw_meadow_popo(scr, y + spot["y"], x + int(spot["x"]), cols, rows, belly,
                                  item["status"] == "integrated", frame)
            if item["id"] == chosen_id and spot["y"] > 0:
                name = item["title"][:cols + 8]
                put(scr, y + spot["y"] - 1, x + int(spot["x"]) + max(0, (cols - len(name)) // 2), name, style("select"))
        chosen = next(i for i in items if i["id"] == chosen_id)
        put(scr, y + ih - 1, x, f"▸ {chosen['title']} · {popo_look(chosen, experiences[chosen_id])[1]}"
            "  ·  ↑↓ elegir  ENTER leer", style("dim"), iw)

    def walk_herd(self, items, sizes, field_w, field_h):
        """Move every Popo one step per FARM_TICK since the last time: walk on,
        sometimes stop to breathe, turn round or drift a row. Archived ones sleep."""
        alive = {item["id"] for item in items}
        for gone in set(self.herd) - alive:
            del self.herd[gone]
        for item in items:
            cols, rows, _ = sizes[item["id"]]
            if item["id"] not in self.herd:
                start = random.Random(item["id"])
                self.herd[item["id"]] = {"x": float(start.randrange(max(1, field_w - cols))),
                                         "y": start.randrange(max(1, field_h - rows + 1)),
                                         "dx": start.choice((-1, 1)), "pause": start.randrange(10)}
        now = time.monotonic()
        steps = min(25, int((now - self.herd_clock) / FARM_TICK))
        self.herd_clock += steps * FARM_TICK
        if steps == 25:
            self.herd_clock = now
        for item in items:
            spot = self.herd[item["id"]]
            cols, rows, _ = sizes[item["id"]]
            for _ in range(steps if item["status"] != "archived" else 0):
                if spot["pause"]:
                    spot["pause"] -= 1
                    continue
                roll = random.random()
                if roll < 0.03:
                    spot["pause"] = random.randint(5, 25)  # stops to breathe a while
                elif roll < 0.05:
                    spot["dx"] = -spot["dx"]
                elif roll < 0.07:
                    spot["y"] += random.choice((-1, 1))
                spot["x"] += spot["dx"]
                if spot["x"] <= 0 or spot["x"] >= field_w - cols:
                    spot["dx"] = 1 if spot["x"] <= 0 else -1
            spot["x"] = min(max(0.0, spot["x"]), float(max(0, field_w - cols)))
            spot["y"] = min(max(0, spot["y"]), max(0, field_h - rows))

    def draw_meadow_popo(self, scr, y, x, cols, rows, belly, integrated, frame):
        """A Popo in the meadow: kitty's real image, or half blocks stretched as wide."""
        rgba = self.popo.get("logo_rgba")
        if self.kitty_logo and rgba:
            if (belly, integrated) not in self.kitty_farm:
                data = "".join(kitty_upload(farm_image_id(belly, integrated, f),
                                            popo_png(rgba, f, BELLY[belly], STRETCH if integrated else 1.0), cols, rows)
                               for f in range(len(KITTY_LOGO_IDS)))
                os.write(sys.stdout.fileno(), data.encode("ascii"))
                self.kitty_farm.add((belly, integrated))
            image = farm_image_id(belly, integrated, frame)
            attr = self.pair(image & 0xFF, -1)
            for row in range(rows):
                try:
                    scr.addstr(y + row, x, kitty_placeholder_row(row, cols, image >> 24), attr)
                except curses.error:
                    pass
            return
        cells_frame = self.popo["logo"][frame]
        width = len(cells_frame[0])
        for row, cells in enumerate(cells_frame):
            for col in range(cols):
                cell = cells[min(width - 1, col * width // cols)]
                if cell:
                    put(scr, y + row, x + col, cell[0], self.pair(cell[1], cell[2]))

    def draw_lanes(self, scr, y, x, cells):
        for col, (char, cid) in enumerate(cells):
            put(scr, y, x + col * 2, char, lane_style(cid, char == "*"))

    def draw_sprite(self, scr, y, x, pixels, size, belly=1.0):
        """Two pixels per cell with half blocks: ▀ paints the top one, the cell color the bottom.
        `belly` widens him (nearest neighbour), as he grows."""
        for row in range(0, size, 2):
            for col in range(round(size * belly)):
                src = min(size - 1, int(col / belly))
                top, bottom = pixels[row * size + src], pixels[(row + 1) * size + src]
                if top:
                    put(scr, y + row // 2, x + col, "▀", self.pair(top, bottom or -1))
                elif bottom:
                    put(scr, y + row // 2, x + col, "▄", self.pair(bottom, -1))

    def pager(self, scr, title, build, hint, keys=()):
        """Full-screen reading view. build(width) -> [(text, attr)].

        Returns the key in `keys` that closed it, or None for ESC/q/←.
        """
        top = 0
        while True:
            h, w = scr.getmaxyx()
            scr.erase()
            y, x, body, iw = box(scr, 0, 1, h - 1, w - 2, title)
            lines = build(max(20, iw))
            body = max(1, body)
            top = max(0, min(top, len(lines) - body))
            for i, (text, attr) in enumerate(lines[top:top + body]):
                put(scr, y + i, x, text, attr, iw)
            where = f"  {top + 1}-{min(len(lines), top + body)}/{len(lines)}" if len(lines) > body else ""
            put(scr, h - 1, 1, hint + where, style("a"), w - 2)
            scr.refresh()
            key = scr.get_wch()
            if key in (curses.KEY_UP, "k"):
                top -= 1
            elif key in (curses.KEY_DOWN, "j"):
                top += 1
            elif key in (curses.KEY_PPAGE, "b"):
                top -= body - 1
            elif key in (curses.KEY_NPAGE, " "):
                top += body - 1
            elif key in (curses.KEY_HOME, "g"):
                top = 0
            elif key in (curses.KEY_END, "G"):
                top = len(lines)
            elif key in ("\x1b", "q", "Q", curses.KEY_LEFT):
                return None
            elif isinstance(key, str) and key.lower() in keys:
                return key.lower()

    def detail_lines(self, item, width):
        """Reading level: the title, the pinned note, and the free text, its
        headings set apart (a suggested one's question, after ·, dimmer)."""
        versions = self.store.versions(item["id"])
        status = STATUS_NAMES[item["status"]].capitalize()
        lines = [(f"◇ AGREEMENT #{item['id']:03} · {version_label(len(versions) - 1)} · {status}", style("dim")),
                 ("", 0), (item["title"], style("main", True)), ("", 0)]
        if item["pinned"]:
            for line in wrap_lines(item["pinned"], width - 2):
                lines.append(("▌ " + line, style("b", True)))
            lines.append(("", 0))
        if not item["body"]:
            lines.append(("Sin texto todavía · E para escribir (Ctrl+G sugiere secciones)", style("dim")))
            return lines
        for paragraph in item["body"].split("\n"):
            if not paragraph.strip():
                lines.append(("", 0))
            elif paragraph.startswith("#"):
                name, _, question = paragraph.lstrip("#").strip().partition(" · ")
                lines.append((name.upper() if paragraph.startswith("## ") else name, style("a", True)))
                if question:
                    lines += [(line, style("dim")) for line in wrap_lines(question, width)]
            elif paragraph.lstrip().startswith(">"):
                lines += [(line, style("dim")) for line in wrap_lines(paragraph, width)]
            else:
                lines += [(line, style("main")) for line in wrap_lines(paragraph, width)]
        return lines

    def history_lines(self, item, width):
        """Each version, newest first, with what it changed from the one before."""
        versions = self.store.versions(item["id"])
        lines = []
        for index in range(len(versions) - 1, -1, -1):
            v = versions[index]
            lines.append((f"{version_label(index)} · {v['note']}", style("good", True)))
            lines.append((f"{version_hash(v)} · {display_date(v['created_at'])}", style("dim")))
            if index:
                diff = version_diff(versions[index - 1]["snapshot"], v["snapshot"])
            else:
                diff = ["## NOTA"] + ["  " + line for line in (v["snapshot"].get("pinned") or "—").splitlines()]
            for line in diff:
                attr = (style("b", True) if line.startswith("## ") else style("good") if line.startswith("+")
                        else style("warm") if line.startswith("-") else style("dim"))
                lines += [(part, attr) for part in wrap_lines(line, width)]
            lines.append(("", 0))
        return lines

    def open_detail(self, scr):
        while self.current():
            item = self.current()
            key = self.pager(scr, f"◇ {APP} / {item['title']}", lambda width: self.detail_lines(item, width),
                             "↑↓ leer  E editar en el editor  V versiones  ESC volver", ("e", "v"))
            if key == "e":
                self.edit(scr)
            elif key == "v":
                self.open_history(scr)
            else:
                return

    def open_history(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero selecciona un acuerdo."
            return
        self.pager(scr, f"◇ AGREEMENT HISTORY / {item['title']}", lambda width: self.history_lines(item, width),
                   "↑↓ leer  ESC volver   + añadido  - quitado")

    def frame(self, screen):
        """The window the app draws in: the whole screen up to MAX_W columns,
        centred beyond that. It shares the screen's memory (derwin)."""
        h, w = screen.getmaxyx()
        if getattr(self, "_frame_for", None) != (h, w):
            fw = min(w, MAX_W)
            self._frame = screen.derwin(h, fw, 0, (w - fw) // 2)
            self._frame.keypad(True)
            self._frame_for = (h, w)
        return self._frame

    def draw(self, screen):
        screen.erase()
        scr = self.win = self.frame(screen)
        h, w = scr.getmaxyx()
        if h < MIN_H or w < MIN_W:
            put(scr, 2, 2, f"Ventana pequeña: mínimo {MIN_W}x{MIN_H}", style("warm", True))
            put(scr, 4, 2, f"Ahora: {w}x{h} · agranda el panel", style("dim"))
            put(scr, 6, 2, "q para salir", style("main"))
            screen.refresh()
            return
        self.logo_at = self.ficha_popo = None
        if w >= SIDEBAR_W:
            left, top = self.render_sidebar(scr, h, w), 0
        else:
            self.render_tabbar(scr, w)
            left, top = 1, 1
        width = w - 1 - left
        # Rows top..h-5 for the tab's panels, h-4..h-2 for the status panel, h-1 for the keys
        render = (self.render_overview, self.render_agreements, self.render_calendar, self.render_journal,
                  self.render_review, self.render_farm)[self.tab]
        render(scr, top, h - 5, left, width)
        y, x, _, iw = box(scr, h - 4, left, 3, width)
        put(scr, y, x, self.message, style("dim"), iw)
        hints = CALENDAR_INSIDE_HINTS if self.cal_focus else KEY_HINTS if self.inside else MENU_HINTS
        hint = next((k for k in hints if len(k) <= w - 3), hints[-1])
        put(scr, h - 1, 1, hint, style("a"), w - 2)
        screen.refresh()

    def help(self, scr):
        h, w = scr.getmaxyx()
        lines = [
            f"{APP} {VERSION}  /  MAPA DE TECLAS", "",
            "↑↓     En el menú: cambiar de pestaña (también ←→, TAB o 1-6)",
            "ENTER  Entrar en la pestaña: ↑↓ eligen dentro · ESC vuelve al menú",
            "       Dentro de una lista, ENTER abre el acuerdo entero",
            "N      Nuevo acuerdo, en tu editor", "E      Editar: cada cambio es una versión nueva",
            "V      Versiones: qué cambió y por qué",
            "+      Añadir una experiencia: elige el tipo (también Espacio)",
            "D      Aplicación: lo he puesto en práctica", "P      Avance: me cuesta menos que antes",
            "B      Obstáculo: algo lo dificultó (S en BITÁCORA: cómo lo reparé)",
            "I      Descubrimiento: algo que he comprendido", "R      Revisar la estrategia (un commit)",
            "       (dentro del CALENDARIO, D/P/B/I apuntan en el día elegido)",
            "X      Estado: activo, integrado o archivado", "A      Ver archivados",
            "Supr   Borrar la entrada (BITÁCORA) o el acuerdo seleccionado",
            "U      Deshacer el último borrado",
            "M      Exportar una copia Markdown", "Q      Salir", "",
            "3      CALENDARIO: dentro, ←→↑↓ día, [ ] mes, T hoy",
            "6      POPARIUM: los Popos de tus acuerdos, a su aire", "",
            "Tu herramienta. Tu ritmo. Los acuerdos pueden revisarse.",
            "No es un sistema para que otra persona te supervise.", "",
            "Pulsa cualquier tecla para volver..."
        ]
        scr.erase()
        width = min(76, w - 2)
        height = min(len(lines) + 1, h)
        y, x, _, iw = box(scr, max(0, (h - height) // 2), (w - width) // 2, height, width, lines[0])
        for i, line in enumerate(lines[2:]):
            put(scr, y + i, x, line, style("main"), iw)
        scr.refresh()
        scr.get_wch()

    def send_logo_to_kitty(self):
        rgba = self.popo and self.popo.get("logo_rgba")
        if not rgba or not curses.has_colors() or curses.COLORS < 256 or not kitty_graphics():
            return
        rows, cols = len(self.popo["logo"][0]), len(self.popo["logo"][0][0])
        data = "".join(kitty_upload(image_id, popo_png(rgba, frame), cols, rows)
                       for frame, image_id in enumerate(KITTY_LOGO_IDS))
        os.write(sys.stdout.fileno(), data.encode("ascii"))
        self.kitty_logo = True

    def forget_logo_in_kitty(self):
        if self.kitty_logo:
            ids = list(KITTY_LOGO_IDS) + [((1 + belly + 5 * integrated) << 24) | color
                                          for belly, integrated in self.kitty_popos for color in KITTY_LOGO_IDS]
            ids += [farm_image_id(belly, integrated, frame)
                    for belly, integrated in self.kitty_farm for frame in range(len(KITTY_LOGO_IDS))]
            data = "".join(kitty_escape(f"a=d,d=I,i={i},q=2") for i in ids)
            os.write(sys.stdout.fileno(), data.encode("ascii"))
            self.kitty_logo = False

    def run(self, scr):
        curses.curs_set(0)
        scr.keypad(True)
        setup_colors()
        self.send_logo_to_kitty()
        tmux_tab(True)
        try:
            self.main_loop(scr)
        finally:
            tmux_tab(False)
            self.forget_logo_in_kitty()

    def main_loop(self, scr):
        while True:
            self.draw(scr)
            farm = self.tab == TABS.index("POPARIUM") and self.popo
            key = None
            while key is None:
                # Sleep until the next frame is due, or until a key: the farm
                # redraws everything, the sidebar Popo only redraws himself
                waits = [self.popo["ms"]] if farm else []
                if self.logo_at or self.ficha_popo:
                    waits.append(logo_frame(int(time.monotonic() * 1000))[1] + 5)
                scr.timeout(min(waits) if waits else -1)
                try:
                    key = scr.get_wch()
                except curses.error:
                    if farm:
                        break
                    if self.logo_at:
                        self.draw_logo(self.win)
                    if self.ficha_popo:
                        self.draw_ficha_popo(self.win)
                    # The frame window, not the screen: what is drawn through a
                    # derwin doesn't mark the screen's lines as changed
                    self.win.refresh()
                finally:
                    scr.timeout(-1)
            if key is None:
                continue  # next farm frame
            if key in ("q", "Q"):
                break
            calendar = self.tab == TABS.index("CALENDARIO")
            enter = key in ("\n", "\r", curses.KEY_ENTER)
            vertical = key in (curses.KEY_UP, "k", "K", curses.KEY_DOWN, "j", "J")
            up = key in (curses.KEY_UP, "k", "K")
            if self.inside and key == "\x1b":
                self.inside = False  # back to the menu
            elif not self.inside and enter:
                self.inside = True  # into the tab's content
            elif not self.inside and vertical:
                self.tab = max(0, min(len(TABS) - 1, self.tab + (-1 if up else 1)))
            elif self.cal_focus and (vertical or key in (curses.KEY_LEFT, curses.KEY_RIGHT, "h", "l")):
                step = {curses.KEY_LEFT: -1, "h": -1, curses.KEY_RIGHT: 1, "l": 1,
                        curses.KEY_UP: -7, "k": -7, "K": -7, curses.KEY_DOWN: 7, "j": 7, "J": 7}[key]
                self.move_day(days=step)
            elif self.cal_focus and key in ("[", "]", curses.KEY_PPAGE, curses.KEY_NPAGE):
                self.move_day(months=-1 if key in ("[", curses.KEY_PPAGE) else 1)
            elif self.cal_focus and key in ("t", "T"):
                self.cal_day = dt.date.today()
            elif self.cal_focus and enter:
                self.inside = False
            elif isinstance(key, str) and key.isdigit() and 1 <= int(key) <= len(TABS):
                self.tab, self.inside = int(key) - 1, False
            elif key in (curses.KEY_RIGHT, "\t", "l", "L"):
                self.tab, self.inside = (self.tab + 1) % len(TABS), False
            elif key in (curses.KEY_LEFT, curses.KEY_BTAB, "h", "H"):
                self.tab, self.inside = (self.tab - 1) % len(TABS), False
            elif vertical and self.tab == TABS.index("BITÁCORA"):
                count = len(self.store.entries(limit=JOURNAL_LIMIT))
                self.entry_selected = max(0, min(count - 1, self.entry_selected + (-1 if up else 1)))
            elif vertical:
                items = self.current_items()
                if not items:
                    self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
                elif up:
                    self.selected = max(0, self.selected - 1)
                else:
                    self.selected = min(len(items) - 1, self.selected + 1)
            elif enter and self.tab == TABS.index("BITÁCORA"):
                self.message = "En la bitácora: S repara un obstáculo, Supr borra · ESC vuelve al menú."
            elif enter:
                if self.current():
                    self.open_detail(self.win)
                else:
                    self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
            elif key == curses.KEY_DC:
                self.delete(self.win)
            elif key in ("u", "U"):
                self.undo_delete()
            elif key in ("v", "V"):
                self.open_history(self.win)
            elif key in ("n", "N"):
                self.new(self.win)
            elif key in ("e", "E"):
                self.edit(self.win)
            elif key in ("+", " "):
                self.choose_experience(self.win)
            elif key in ("d", "D"):
                self.log(self.win, "done")
            elif key in ("p", "P"):
                self.log(self.win, "progress")
            elif key in ("b", "B"):
                self.log(self.win, "obstacle")
            elif key in ("i", "I"):
                self.log(self.win, "insight")
            elif key in ("r", "R"):
                self.review(self.win)
            elif key in ("x", "X"):
                self.change_status(self.win)
            elif key in ("s", "S"):
                self.add_repair(self.win)
            elif key in ("a", "A"):
                self.archive = not self.archive
                self.selected = 0
                self.message = "Mostrando todos los acuerdos." if self.archive else "Mostrando acuerdos activos."
            elif key in ("m", "M"):
                out = self.store.export()
                self.message = "Markdown guardado: " + str(out)
            elif key == "?":
                self.help(self.win)


def main():
    parser = argparse.ArgumentParser(prog="popos", description=f"{APP} {VERSION} · {TAGLINE} — bitácora local de acuerdos y progreso, diseñada para tmux")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta de la base de datos SQLite")
    parser.add_argument("--export", action="store_true", help="Exportar Markdown y salir")
    parser.add_argument("--tmux-status", action="store_true",
                        help="Imprimir la cara de Popo para la barra de estado de tmux y salir")
    args = parser.parse_args()
    if args.tmux_status:
        print(tmux_status(args.db))
        return
    locale.setlocale(locale.LC_ALL, "")
    # Sin esto curses espera 1 s tras ESC antes de cancelar un campo
    os.environ.setdefault("ESCDELAY", "25")
    store = Store(args.db)
    try:
        if args.export:
            print(store.export())
        elif not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("la interfaz necesita una terminal interactiva (dentro de tmux funciona)")
        else:
            curses.wrapper(App(store).run)
    finally:
        store.close()


if __name__ == "__main__":
    main()
